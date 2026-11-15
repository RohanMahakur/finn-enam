"""Per-category enrichment — the "how should this item be presented" judgement.

  results            → headline card: Revenue / EBITDA / PBT / PAT, QoQ and YoY.
                       Source order: NSE's own XBRL-parsed comparison (free, exact)
                       → cheap-model extraction of line items from the PDF (code computes
                       EBITDA and deltas; the model never does arithmetic)
                       → screener's quarterly table.
  management_change  → who is coming / going. The filing itself must carry a "brief profile"
                       for appointments (SEBI LODR Reg 30), so that's source #1. Web search
                       snippets (LinkedIn & company pages) top it up — never scraped.
  everything else    → a one-liner only if the item is above the waterline. NSE's own
                       attachment text is often already a good one-liner (free); the model is
                       used only when it isn't.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from .. import config
from ..llm import router
from ..sources import pdftext

log = logging.getLogger(__name__)
METRICS = ("revenue", "ebitda", "pbt", "pat")


# ---------------------------------------------------------------- results
def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round(100 * (a - b) / abs(b), 1)


def compare(series: list[dict]) -> dict | None:
    """series newest-first, each {period_end|period, revenue, ebitda, pbt, pat}."""
    if not series:
        return None
    cur = series[0]
    prev = series[1] if len(series) > 1 else None
    yago = series[4] if len(series) > 4 else None
    out = {"period": cur.get("period_end") or cur.get("period"), "source": cur.get("source"), "rows": []}
    for m in METRICS:
        c = cur.get(m)
        out["rows"].append({
            "metric": m, "value": None if c is None else round(c, 1),
            "qoq": _pct(c, prev.get(m) if prev else None),
            "yoy": _pct(c, yago.get(m) if yago else None),
        })
    rev = cur.get("revenue")
    if rev and cur.get("ebitda") is not None:
        out["ebitda_margin"] = round(100 * cur["ebitda"] / rev, 1)
        if yago and yago.get("revenue") and yago.get("ebitda") is not None:
            out["margin_change_bps_yoy"] = round(100 * (out["ebitda_margin"] - 100 * yago["ebitda"] / yago["revenue"]))
    return out


EXTRACT_RESULTS_SYS = """You read Indian listed-company quarterly results filings (SEBI format).
Extract line items in ₹ crore (convert from lakhs/millions if the filing says so) for three columns:
"current" (quarter just ended), "previous" (immediately preceding quarter), "year_ago" (same quarter last year).
Prefer CONSOLIDATED figures if both standalone and consolidated are present.
Return JSON: {"unit_seen": str, "basis": "consolidated"|"standalone", "current": {...}, "previous": {...},
"year_ago": {...}} where each column has keys revenue_from_operations, other_income, finance_costs,
depreciation, exceptional_items, profit_before_tax, profit_after_tax (numbers or null).
Copy numbers exactly; never compute or estimate. Use null when a value is absent."""


def results_from_pdf(url: str) -> list[dict] | None:
    doc = pdftext.fetch_pages(url, max_pages=12)
    pages = [p for p in doc.get("pages", []) if re.search(r"revenue from operations|profit before tax", p, re.I)]
    if not pages:
        return None
    try:
        res = router.complete("extract_results", EXTRACT_RESULTS_SYS, "\n\n---PAGE---\n".join(pages[:3])[:14000],
                              json_mode=True, max_tokens=900).json()
    except router.NoLLM:
        return None
    except Exception as e:
        log.warning("results extraction failed: %s", e)
        return None

    def col(c: dict | None) -> dict:
        c = c or {}
        g = lambda k: c.get(k) if isinstance(c.get(k), (int, float)) else None  # noqa: E731
        pbt = g("profit_before_tax")
        ebitda = None
        if pbt is not None:  # operating EBITDA: PBT + finance + D&A − other income − exceptional
            ebitda = pbt + (g("finance_costs") or 0) + (g("depreciation") or 0) - (g("other_income") or 0) - (g("exceptional_items") or 0)
        return {"revenue": g("revenue_from_operations"), "ebitda": ebitda, "pbt": pbt, "pat": g("profit_after_tax"),
                "source": f"results filing PDF ({res.get('basis', '?')}), line items extracted by model, maths by code"}

    cur, prev, ya = col(res.get("current")), col(res.get("previous")), col(res.get("year_ago"))
    # sanity: PAT should not exceed PBT by a lot unless there's a tax credit; revenue must exist
    if cur["revenue"] is None:
        return None
    return [cur, prev, {}, {}, ya]  # positions 0/1/4 are what compare() reads


def results_card(symbol: str, ann: dict, nse=None) -> dict | None:
    if nse is not None:
        try:
            from ..sources.nse import headline_from_rescmp
            series = headline_from_rescmp(nse.results_comparison(symbol))
            if series:
                return compare(series)
        except Exception as e:
            log.info("NSE results-comparision unavailable for %s: %s", symbol, e)
    if ann.get("url", "").lower().endswith(".pdf"):
        series = results_from_pdf(ann["url"])
        if series:
            return compare(series)
    try:
        from ..sources import screener
        return compare(screener.quarterly_headlines(screener.company(symbol)))
    except Exception as e:
        log.info("screener fallback failed for %s: %s", symbol, e)
    return None


# ---------------------------------------------------------------- people
PERSON_SYS = """From an Indian stock-exchange filing about a change in directors / key managerial personnel,
list each person whose position changes. Return JSON {"people": [{"name": str, "role": str,
"action": "appointed"|"resigned"|"retired"|"redesignated"|"ceased", "effective": str|null,
"reason": str|null, "profile": str|null}]}. "profile" = the brief profile given in the filing,
condensed to <= 45 words, using only facts stated in the filing. Do not add outside knowledge."""

BIO_SYS = """Write a 2-sentence professional background for the named person using ONLY the numbered
search snippets provided. Prefer: current/previous employers and roles, years of experience,
education. If snippets look like a different person, say "Background not confidently found."
End with the snippet numbers you used, like [1][3]. Never invent facts."""

NAME_RX = re.compile(r"(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Shri|Smt\.?)\s+([A-Z][a-zA-Z.]+(?:\s+[A-Z][a-zA-Z.]+){0,3})")


def _web_snippets(query: str, n: int = 5) -> list[dict]:
    try:
        from ddgs import DDGS
        with DDGS() as d:
            return [{"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")}
                    for r in d.text(query, max_results=n)]
    except Exception as e:
        log.info("web search unavailable: %s", e)
        return []


def people_card(symbol: str, ann: dict) -> dict:
    h = config.holding(symbol) or {}
    company = h.get("name", symbol)
    text = ann.get("body") or ""
    if ann.get("url", "").lower().endswith(".pdf"):
        doc = pdftext.fetch_pages(ann["url"], max_pages=6)
        text = (text + "\n" + "\n".join(doc.get("pages", [])))[:12000]
    people = []
    try:
        people = router.complete("extract_person", PERSON_SYS, f"Company: {company}\n\n{text}",
                                 json_mode=True, max_tokens=700).json().get("people", [])
    except router.NoLLM:
        names = list(dict.fromkeys(NAME_RX.findall(text)))[:2]
        role = re.search(r"(Chief \w+ Officer|Managing Director|Company Secretary|Independent Director|Director)", text)
        act = "resigned" if re.search(r"resign|cessation", text, re.I) else "appointed"
        people = [{"name": n, "role": role.group(1) if role else None, "action": act, "profile": None} for n in names]
    except Exception as e:
        log.warning("person extraction failed: %s", e)

    for p in people[:3]:
        if not p.get("name") or p.get("action") not in ("appointed", "redesignated"):
            continue
        snippets = _web_snippets(f'"{p["name"]}" {p.get("role") or ""} {company} linkedin')
        p["sources"] = snippets[:4]
        if snippets:
            try:
                numbered = "\n".join(f"[{i+1}] {s['title']} — {s['snippet']} ({s['url']})" for i, s in enumerate(snippets))
                p["background"] = router.complete("bio", BIO_SYS, f"Person: {p['name']} ({p.get('role')}, {company})\n{numbered}",
                                                  max_tokens=160).text.strip()
            except router.NoLLM:
                li = next((s for s in snippets if "linkedin.com/in" in (s["url"] or "")), snippets[0])
                p["background"] = li["snippet"]
            except Exception:
                pass
    return {"people": people}


# ---------------------------------------------------------------- one-liner
ONE_SYS = """Summarise this stock-exchange filing in ONE line of at most 22 words for a busy investor:
what happened and the single number/date that matters. No preamble, no adjectives."""


def one_liner(ann: dict) -> str | None:
    body = (ann.get("body") or "").strip()
    if 20 <= len(body) <= 240:
        return body  # NSE's own attachment text is often already the one-liner — free.
    src = body
    if not src and ann.get("url", "").lower().endswith(".pdf"):
        src = "\n".join(pdftext.fetch_pages(ann["url"], max_pages=2).get("pages", []))
    if not src:
        return None
    try:
        return router.complete("one_liner", ONE_SYS, f"Subject: {ann.get('subject')}\n{src[:5000]}", max_tokens=60).text.strip()
    except router.NoLLM:
        first = re.split(r"(?<=[.;])\s", src.strip())[0]
        return first[:220]
    except Exception:
        return None


def age_hours(ts: str) -> float:
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
    except ValueError:
        return 0.0


def today() -> str:
    return date.today().isoformat()
