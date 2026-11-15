"""Pull side: on-demand research grounded ONLY in primary documents (annual report +
concall transcripts) and the company's reported numbers.

Pipeline (any NSE symbol with a screener.in page):
  1. screener.in → reported tables + links to primary docs (transcripts on BSE/IR, AR PDFs)
  2. metrics.compute → every ratio/trend in code (no model)
  3. corpus = last 4 transcripts + latest AR, page-level, BM25-indexed (no embeddings needed)
  4. Promise Ledger:
       a. per transcript, keep only guidance-bearing paragraphs (keyword prefilter, ~70% fewer
          tokens), mid-tier model extracts forward-looking claims with page refs
       b. strong model judges each matured claim against the actual quarterly numbers
          (computed in code) + what management said later (retrieved passages)
       c. say-do score computed in code
  5. Business snapshot + narrative-vs-numbers + bull/bear: strong model, given the computed
     flags and retrieved passages, must cite [doc p.N] for every line. A validator drops any
     line whose citation doesn't exist in the corpus — that's how "no outside knowledge" is
     enforced rather than merely requested.
"""
from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from rank_bm25 import BM25Okapi

from .. import db
from ..llm import router
from ..sources import pdftext, screener
from . import metrics

log = logging.getLogger(__name__)

GUIDANCE_RX = re.compile(
    r"guid|expect|target|outlook|aspir|aim|plan to|going forward|next (year|quarter|few)|FY ?\d{2}|"
    r"double.digit|mid.teens|high.single|margin|capex|capacity|we will|we should|should be able|"
    r"trajectory|run.?rate|by (the )?end of|in the range|\d+\s?(%|percent|bps)", re.I)
TOKEN_RX = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------- corpus
class Corpus:
    def __init__(self, docs: list[dict]):
        self.docs = docs  # {id, label, kind, url, pages: [str]}
        self.chunks = []  # (doc_id, page_no, text)
        for d in docs:
            for i, p in enumerate(d["pages"]):
                for para in self._split(p):
                    self.chunks.append((d["id"], i + 1, para))
        self.bm25 = BM25Okapi([TOKEN_RX.findall(c[2].lower()) for c in self.chunks]) if self.chunks else None

    @staticmethod
    def _split(page: str, size: int = 900) -> list[str]:
        page = re.sub(r"[ \t]+", " ", page)
        out, buf = [], ""
        for para in re.split(r"\n\s*\n|\n(?=[A-Z][a-z]+ [A-Z][a-z]+:)", page):
            if len(buf) + len(para) > size and buf:
                out.append(buf.strip()); buf = ""
            buf += para + "\n"
        if buf.strip():
            out.append(buf.strip())
        return out

    def search(self, query: str, k: int = 8, kinds: tuple[str, ...] | None = None) -> list[tuple]:
        if not self.bm25:
            return []
        scores = self.bm25.get_scores(TOKEN_RX.findall(query.lower()))
        idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in idx:
            d_id = self.chunks[i][0]
            if kinds and self.doc(d_id)["kind"] not in kinds:
                continue
            out.append(self.chunks[i])
            if len(out) >= k:
                break
        return out

    def doc(self, d_id: str) -> dict:
        return next(d for d in self.docs if d["id"] == d_id)

    def valid_cite(self, cite: str) -> bool:
        m = re.match(r"\s*([A-Z]+\d*)\s*p\.?\s*(\d+)", cite)
        if not m:
            return False
        try:
            d = self.doc(m.group(1))
        except StopIteration:
            return False
        return 1 <= int(m.group(2)) <= len(d["pages"])

    @staticmethod
    def fmt(chunks: list[tuple], limit: int = 9000) -> str:
        s, out = 0, []
        for d_id, p, text in chunks:
            block = f"[{d_id} p.{p}]\n{text}\n"
            if s + len(block) > limit:
                break
            out.append(block); s += len(block)
        return "\n".join(out)


def build_corpus(data: dict, n_calls: int = 4, with_ar: bool = True) -> Corpus:
    docs = []
    calls = data["documents"]["concalls"][:n_calls]
    jobs = [(f"T{i+1}", f"Concall {c['period']}", "transcript", c["transcript"], 60) for i, c in enumerate(calls)]
    if with_ar and data["documents"]["annual_reports"]:
        ar = data["documents"]["annual_reports"][0]
        jobs.append((f"AR{str(ar['year'])[-2:]}", f"Annual Report FY{ar['year']}", "annual_report", ar["url"], 320))
    with ThreadPoolExecutor(4) as ex:
        pages = list(ex.map(lambda j: pdftext.fetch_pages(j[3], max_pages=j[4]), jobs))
    for (d_id, label, kind, url, _), pg in zip(jobs, pages):
        if pg.get("pages"):
            docs.append({"id": d_id, "label": label, "kind": kind, "url": url, "pages": pg["pages"],
                         "scanned": pg.get("scanned", False)})
    return Corpus(docs)


# ---------------------------------------------------------------- promise ledger
CLAIMS_SYS = """You extract management's forward-looking commitments from an Indian company's earnings-call
transcript excerpt. Only include explicit, checkable statements by management (not analysts' questions):
guidance on revenue/volume growth, margins, profit, capex, capacity, debt, launches, timelines.
Return JSON {"claims": [{"metric": "revenue_growth"|"margin"|"profit"|"capex"|"capacity"|"debt"|"other",
"claim": "<=25-word paraphrase", "quote": "<=25 words verbatim", "target": "the number/range or direction",
"horizon": "e.g. FY27, Q3FY27, next 2-3 years, near term", "page": <int from the [Tn p.N] tag>}]}.
Max 8 claims, most material first. If none, return {"claims": []}."""

JUDGE_SYS = """You audit management credibility for an investor. For each claim, decide using ONLY the
'Actual numbers' table and the 'Later statements' excerpts:
  kept     – delivered in full by the stated horizon
  partial  – directionally right but short of the stated number/timeline
  missed   – clearly not delivered, or quietly walked back/abandoned later
  pending  – horizon not reached yet
  unclear  – evidence insufficient
Return JSON {"verdicts": [{"id": <claim id>, "verdict": ..., "evidence": "<=30 words, cite numbers",
"cites": ["Tn p.N" or "NUMBERS"]}]}. Be strict and specific; do not use outside knowledge."""


def _guidance_text(corpus: Corpus, d_id: str) -> str:
    d = corpus.doc(d_id)
    keep = []
    for i, p in enumerate(d["pages"]):
        paras = [x for x in Corpus._split(p) if GUIDANCE_RX.search(x)]
        if paras:
            keep.append(f"[{d_id} p.{i+1}]\n" + "\n".join(paras))
    return "\n".join(keep)[:24000]


def _numbers_table(m: dict) -> str:
    s = m["trajectory"]["series"]
    rows = ["period | revenue ₹cr | rev YoY % | EBITDA margin % | PAT ₹cr"]
    for i, p in enumerate(s["quarters"]):
        rows.append(f"{p} | {s['q_revenue'][i]} | {s['q_rev_yoy'][i]} | {s['q_opm'][i]} | {s['q_pat'][i]}")
    rows.append("— annual —")
    for i, y in enumerate(s["years"]):
        rows.append(f"{y} | {s['revenue'][i]} | | {s['opm'][i]} | {s['pat'][i]}")
    return "\n".join(rows)


def promise_ledger(corpus: Corpus, m: dict) -> dict:
    transcripts = sorted([d for d in corpus.docs if d["kind"] == "transcript"], key=lambda d: d["id"], reverse=True)
    if not transcripts:
        return {"status": "no_transcripts", "claims": []}
    claims: list[dict] = []
    # oldest call first so ids read chronologically; each call's claims are judged against later evidence
    for d in transcripts:
        text = _guidance_text(corpus, d["id"])
        if not text:
            continue
        try:
            got = router.complete("extract_claims", CLAIMS_SYS, f"Call: {d['label']}\n\n{text}",
                                  json_mode=True, max_tokens=1400).json().get("claims", [])
        except router.NoLLM:
            return {"status": "needs_model_key", "claims": []}
        except Exception as e:
            log.warning("claim extraction failed for %s: %s", d["id"], e)
            continue
        for c in got:
            c.update({"id": f"{d['id']}-{len(claims)+1}", "call": d["label"], "doc": d["id"]})
            claims.append(c)
    if not claims:
        return {"status": "no_claims", "claims": []}

    numbers = _numbers_table(m)
    ctx = []
    for c in claims:
        later = [t["id"] for t in transcripts if t["id"] < c["doc"]]  # T1 is the newest
        hits = corpus.search(f"{c['claim']} {c.get('target', '')}", k=3) if later else []
        hits = [h for h in hits if h[0] in later]
        ctx.append(f"CLAIM {c['id']} ({c['call']}): {c['claim']} | target: {c.get('target')} | horizon: {c.get('horizon')}\n"
                   + (Corpus.fmt(hits, 1800) if hits else "(no later statements found)"))
    try:
        res = router.complete("judge_claims", JUDGE_SYS,
                              f"Actual numbers (from reported financials):\n{numbers}\n\n" + "\n\n".join(ctx)[:30000],
                              json_mode=True, max_tokens=2200).json()
        verdicts = {v["id"]: v for v in res.get("verdicts", [])}
    except router.NoLLM:
        verdicts = {}
    except Exception as e:
        log.warning("judging failed: %s", e)
        verdicts = {}
    for c in claims:
        v = verdicts.get(c["id"], {})
        c["verdict"] = v.get("verdict", "unclear")
        c["evidence"] = v.get("evidence")
        c["cites"] = [x for x in v.get("cites", []) if x == "NUMBERS" or corpus.valid_cite(x)]
        c["source_ok"] = corpus.valid_cite(f"{c['doc']} p.{c.get('page', 0)}")
    kept = sum(c["verdict"] == "kept" for c in claims)
    part = sum(c["verdict"] == "partial" for c in claims)
    miss = sum(c["verdict"] == "missed" for c in claims)
    judged = kept + part + miss
    return {"status": "ok", "claims": claims,
            "score": round(100 * (kept + 0.5 * part) / judged) if judged else None,
            "counts": {"kept": kept, "partial": part, "missed": miss,
                       "pending": sum(c["verdict"] == "pending" for c in claims),
                       "unclear": sum(c["verdict"] == "unclear" for c in claims)}}


# ---------------------------------------------------------------- synthesis
SYNTH_SYS = """You are a buy-side analyst writing for a portfolio manager who has 60 seconds.
Use ONLY the computed flags and the source excerpts provided. Every bullet must end with a citation
like [T2 p.4] or [AR26 p.88] or [NUMBERS]. No outside knowledge, no broker views, no hype words.
Return JSON:
{"business": {"one_liner": str, "segments": [{"name": str, "share": str|null, "note": str, "cite": str}]},
 "guidance": [{"metric": str, "what": "<=20 words", "cite": str}],
 "narrative_vs_numbers": [{"says": "<=18 words", "numbers": "<=18 words", "verdict": "agree"|"diverge"|"too early", "cite": str}],
 "bull": [{"point": "<=22 words", "cite": str}], "bear": [{"point": "<=22 words", "cite": str}],
 "watch_next": "<=25 words: the one thing to check next quarter"}
Max 4 items per list."""


def _valid(items: list[dict], corpus: Corpus, key: str = "cite") -> list[dict]:
    out = []
    for it in items or []:
        cites = re.findall(r"[A-Z]+\d*\s*p\.?\s*\d+|NUMBERS", str(it.get(key, "")))
        if cites and all(c == "NUMBERS" or corpus.valid_cite(c) for c in cites):
            out.append(it)
    return out


def synthesis(corpus: Corpus, m: dict, ledger: dict, name: str) -> dict:
    flags = [f"- {f['text']}" for sec in ("trajectory", "balance_sheet", "cash_quality") for f in m[sec]["flags"]]
    led = [f"- {c['call']}: {c['claim']} → {c['verdict']}" for c in ledger.get("claims", [])][:12]
    seg = corpus.search("segment revenue business overview products customers geography share of revenue", k=6,
                        kinds=("annual_report",)) or corpus.search("segment revenue mix business", k=6)
    story = corpus.search("strategy growth outlook guidance margin demand capex expansion", k=8, kinds=("transcript",))
    risk = corpus.search("risk challenge pressure decline competition headwind slowdown pricing", k=5)
    user = (f"Company: {name}\n\nCOMPUTED FLAGS [NUMBERS]:\n" + "\n".join(flags)
            + "\n\nPROMISE LEDGER:\n" + "\n".join(led)
            + f"\n\nNUMBERS TABLE [NUMBERS]:\n{_numbers_table(m)[:2500]}"
            + "\n\nEXCERPTS:\n" + Corpus.fmt(seg + story + risk, 16000))
    try:
        r = router.complete("synthesis", SYNTH_SYS, user, json_mode=True, max_tokens=2000).json()
    except router.NoLLM:
        return {"status": "needs_model_key"}
    except Exception as e:
        log.warning("synthesis failed: %s", e)
        return {"status": "error"}
    biz = r.get("business", {}) or {}
    out = {"status": "ok",
           "business": {"one_liner": biz.get("one_liner"), "segments": _valid(biz.get("segments"), corpus)},
           "guidance": _valid(r.get("guidance"), corpus),
           "narrative_vs_numbers": _valid(r.get("narrative_vs_numbers"), corpus),
           "bull": _valid(r.get("bull"), corpus), "bear": _valid(r.get("bear"), corpus),
           "watch_next": r.get("watch_next")}
    dropped = sum(len(r.get(k) or []) for k in ("guidance", "narrative_vs_numbers", "bull", "bear")) - \
        sum(len(out[k]) for k in ("guidance", "narrative_vs_numbers", "bull", "bear"))
    out["dropped_uncited"] = dropped
    return out


ASK_SYS = """Answer the investor's question using ONLY the excerpts and computed numbers. Be concise
(<=120 words), lead with the answer, cite every sentence like [T1 p.3] or [NUMBERS]. If the sources
don't contain the answer, say exactly what is missing."""


def ask(symbol: str, question: str) -> dict:
    data = screener.company(symbol)
    m = metrics.compute(data)
    corpus = build_corpus(data)
    hits = corpus.search(question, k=8)
    try:
        r = router.complete("ask", ASK_SYS, f"Q: {question}\n\nNUMBERS:\n{_numbers_table(m)[:2000]}\n\nEXCERPTS:\n{Corpus.fmt(hits, 9000)}",
                            max_tokens=400)
    except router.NoLLM:
        return {"answer": None, "status": "needs_model_key",
                "passages": [{"cite": f"{d} p.{p}", "text": t[:400]} for d, p, t in hits[:4]]}
    cites = re.findall(r"\[([A-Z]+\d*\s*p\.?\s*\d+)\]", r.text)
    return {"answer": r.text, "status": "ok", "valid_cites": [c for c in cites if corpus.valid_cite(c)],
            "invalid_cites": [c for c in cites if not corpus.valid_cite(c)],
            "sources": _sources(corpus), "cost_usd": r.cost_usd}


def _sources(corpus: Corpus) -> list[dict]:
    return [{"id": d["id"], "label": d["label"], "url": d["url"], "pages": len(d["pages"]),
             "scanned": d.get("scanned")} for d in corpus.docs]


def research(symbol: str, deep: bool = True) -> dict:
    """Full research pack. Cached for 24h keyed on the document set, so re-opening is free."""
    symbol = symbol.upper().strip()
    data = screener.company(symbol)
    doc_key = hashlib.md5(str([c["transcript"] for c in data["documents"]["concalls"][:4]]).encode()).hexdigest()[:10]
    key = f"research:{symbol}:{doc_key}:{deep}"
    if (hit := db.cache_get(key, 24 * 3600)) is not None:
        hit["cached"] = True
        return hit
    before = db.cost_summary()["total_usd"]
    m = metrics.compute(data)
    out = {"symbol": symbol, "name": data["name"], "screener_url": data["url"], "metrics": m,
           "headline_quarter": None}
    from .enrich import compare
    out["headline_quarter"] = compare(screener.quarterly_headlines(data))
    if deep:
        corpus = build_corpus(data)
        out["sources"] = _sources(corpus)
        out["ledger"] = promise_ledger(corpus, m)
        out["synthesis"] = synthesis(corpus, m, out["ledger"], data["name"])
    out["cost_usd"] = round(db.cost_summary()["total_usd"] - before, 5)
    db.cache_put(key, out)
    return out
