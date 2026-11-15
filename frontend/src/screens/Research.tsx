import { useEffect, useRef, useState } from "react";
import { Empty, ResultsGrid } from "../components/Bits";
import { ask, loadResearch } from "../lib/data";
import { tileVal } from "../lib/fmt";
import type { Claim, Meta, Research as R, Section } from "../types";

const VERDICT: Record<Claim["verdict"], { label: string; cls: string }> = {
  kept: { label: "Kept", cls: "good" }, partial: { label: "Partly", cls: "watch" }, missed: { label: "Missed", cls: "bad" },
  pending: { label: "Pending", cls: "dim" }, unclear: { label: "Unclear", cls: "dim" },
};

export function Research({ meta, symbol, setSymbol }: { meta: Meta; symbol: string | null; setSymbol: (s: string) => void }) {
  const [q, setQ] = useState(symbol ?? "");
  const [data, setData] = useState<R | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!symbol) return;
    setQ(symbol); setBusy(true); setErr(null); setData(null);
    loadResearch(symbol).then(setData).catch((e) => setErr(String(e.message ?? e))).finally(() => setBusy(false));
  }, [symbol]);

  const suggestions = [...new Set([...meta.research_demo, ...meta.holdings.map((h) => h.symbol)])].slice(0, 10);
  return (
    <div className="screen">
      <form className="search" onSubmit={(e) => { e.preventDefault(); if (q.trim()) setSymbol(q.trim().toUpperCase()); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Any NSE ticker — e.g. ASIANPAINT" autoCapitalize="characters" />
        <button className="primary">Dig</button>
      </form>
      <div className="chips wrap">{suggestions.map((s) => <button key={s} className={`chip ${s === symbol ? "on" : ""}`} onClick={() => setSymbol(s)}>{s}</button>)}</div>

      {!symbol && <Empty title="Pull research, grounded in what management actually filed.">
        Annual reports and the last four concall transcripts only: no broker notes, no news. Every line cites its page; lines a model can't cite are dropped.</Empty>}
      {busy && <div className="loading"><div className="pulse" />Reading transcripts and the annual report… first run per company takes ~1 min, then it's cached.</div>}
      {err && <Empty title="Couldn't research that.">{err}</Empty>}
      {data && <Report r={data} />}
    </div>
  );
}

function Tiles({ s }: { s: Section }) {
  return <div className="tiles">{s.tiles.map((t) => <div key={t.k} className="tile"><span>{t.k}</span><b>{tileVal(t.v, t.unit)}</b></div>)}</div>;
}
function Flags({ s }: { s: Section }) {
  return <ul className="flags">{s.flags?.map((f, i) => <li key={i} className={f.tone}>{f.text}</li>)}</ul>;
}
const Cite = ({ c }: { c?: string }) => (c ? <span className="cite">{c}</span> : null);

function Bars({ labels, values, fmt = (v: number) => (Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${Math.round(v)}`) }: { labels: string[]; values: (number | null)[]; fmt?: (v: number) => string }) {
  const vs = values.slice(-6), ls = labels.slice(-6);
  const max = Math.max(...vs.map((v) => Math.abs(v ?? 0)), 1);
  return (
    <div className="bars">
      {vs.map((v, i) => (
        <div key={i} className="bar-col">
          <div className="bar-v">{v == null ? "" : fmt(v)}</div>
          <div className={`bar ${v != null && v < 0 ? "neg" : ""}`} style={{ height: `${(Math.abs(v ?? 0) / max) * 56}px` }} />
          <div className="bar-l">{String(ls[i]).replace("Mar ", "'").replace(/^(\w{3}) 20/, "$1 '")}</div>
        </div>
      ))}
    </div>
  );
}

function Report({ r }: { r: R }) {
  const m = r.metrics, L = r.ledger, S = r.synthesis;
  const [tab, setTab] = useState<"ledger" | "case" | "numbers" | "ask">("ledger");
  const ser = m.trajectory.series as Record<string, (number | null)[]>;
  const cq = m.cash_quality.series as Record<string, (number | null)[]>;
  const bs = m.balance_sheet.series as Record<string, (number | null)[]>;
  return (
    <div className="report">
      <header className="r-head">
        <div className="d-eyebrow">{m.basis} · {m.is_bank ? "lender" : "operating company"}{r.cached ? " · cached" : ""}{r.cost_usd ? ` · this report cost $${r.cost_usd.toFixed(3)}` : ""}</div>
        <h2>{r.name}</h2>
        {S?.business?.one_liner && <p className="lede">{S.business.one_liner}</p>}
        {S?.watch_next && <p className="watch">Watch next: {S.watch_next}</p>}
      </header>

      <div className="tabs">
        {(["ledger", "case", "numbers", "ask"] as const).map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
            {{ ledger: "Promises", case: "Bull · Bear", numbers: "Numbers", ask: "Ask" }[t]}
          </button>
        ))}
      </div>

      {tab === "ledger" && (
        <section>
          {L?.status === "ok" ? (
            <>
              <div className="saydo">
                <div className="dial" style={{ ["--p" as string]: L.score ?? 0 }}><b>{L.score ?? "—"}</b><span>say–do</span></div>
                <div>
                  <p className="sd-line">Of the guidance management gave on the last four calls that has come due, they delivered
                    <b> {L.counts?.kept ?? 0}</b> in full, <b>{L.counts?.partial ?? 0}</b> in part and missed <b>{L.counts?.missed ?? 0}</b>.
                    {(L.counts?.pending ?? 0) > 0 && ` ${L.counts?.pending} still pending.`}</p>
                  <p className="tiny">Research shows markets react more to guidance from managements with accurate track records. Use this to discount the next promise.</p>
                </div>
              </div>
              <ol className="ledger">
                {L.claims.map((c) => (
                  <li key={c.id} className={VERDICT[c.verdict].cls}>
                    <div className="l-top"><span className="call">{c.call}</span><span className={`verdict ${VERDICT[c.verdict].cls}`}>{VERDICT[c.verdict].label}</span></div>
                    <div className="promise">“{c.claim}”{c.horizon && <span className="hz"> · by {c.horizon}</span>}</div>
                    {c.evidence && <div className="evidence">{c.evidence} {c.cites?.map((x) => <Cite key={x} c={x} />)}</div>}
                    <div className="tiny">said on <Cite c={`${c.doc} p.${c.page}`} /></div>
                  </li>
                ))}
              </ol>
            </>
          ) : <Empty title={L?.status === "needs_model_key" ? "Add a model key to build the ledger." : "No transcripts found to audit."}>
              The ledger reads the last four concall transcripts, extracts each forward-looking commitment, then checks it against reported numbers and what was said later.</Empty>}
          {S?.narrative_vs_numbers && S.narrative_vs_numbers.length > 0 && (
            <>
              <h4>Narrative vs numbers</h4>
              <div className="nvn">
                {S.narrative_vs_numbers.map((n, i) => (
                  <div key={i} className={`nvn-row ${n.verdict === "diverge" ? "bad" : n.verdict === "agree" ? "good" : "dim"}`}>
                    <div><span className="lbl">They say</span>{n.says}</div>
                    <div><span className="lbl">Numbers</span>{n.numbers}</div>
                    <div className="v">{n.verdict} <Cite c={n.cite} /></div>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      {tab === "case" && (
        <section>
          {S?.status === "ok" ? (
            <>
              <div className="case">
                <div className="bull"><h4>Bull</h4>{S.bull?.map((b, i) => <p key={i}>{b.point} <Cite c={b.cite} /></p>)}</div>
                <div className="bear"><h4>Bear</h4>{S.bear?.map((b, i) => <p key={i}>{b.point} <Cite c={b.cite} /></p>)}</div>
              </div>
              {S.guidance && S.guidance.length > 0 && <><h4>Current guidance</h4>
                <ul className="guid">{S.guidance.map((g, i) => <li key={i}><b>{g.metric}</b> {g.what} <Cite c={g.cite} /></li>)}</ul></>}
              {S.business && S.business.segments.length > 0 && <><h4>Business</h4>
                <ul className="segs">{S.business.segments.map((g, i) => <li key={i}><span className="share">{g.share ?? "—"}</span><b>{g.name}</b> {g.note} <Cite c={g.cite} /></li>)}</ul></>}
              {(S.dropped_uncited ?? 0) > 0 && <p className="tiny">{S.dropped_uncited} model statements were dropped because their citation didn't check out.</p>}
            </>
          ) : <Empty title="Add a model key for the written case.">The numbers tab works without any model.</Empty>}
        </section>
      )}

      {tab === "numbers" && (
        <section>
          {r.headline_quarter && <><h4>Latest quarter · {r.headline_quarter.period}</h4><ResultsGrid r={r.headline_quarter} /></>}
          <h4>Snapshot</h4><Tiles s={m.snapshot} />
          <h4>Trajectory</h4><Tiles s={m.trajectory} />
          <div className="chart-pair">
            <div><span className="cl">Revenue ₹cr</span><Bars labels={ser.years as unknown as string[]} values={ser.revenue} /></div>
            <div><span className="cl">EBITDA margin %</span><Bars labels={ser.years as unknown as string[]} values={ser.opm} fmt={(v) => v.toFixed(1)} /></div>
          </div>
          <Flags s={m.trajectory} />
          <h4>Balance sheet</h4><Tiles s={m.balance_sheet} />
          <div className="chart-pair">
            <div><span className="cl">Borrowings ₹cr</span><Bars labels={bs.periods as unknown as string[]} values={bs.borrowings} /></div>
            <div><span className="cl">Cash conversion cycle (days)</span><Bars labels={bs.ratio_periods as unknown as string[]} values={bs.ccc} /></div>
          </div>
          <Flags s={m.balance_sheet} />
          <h4>Cash quality</h4><Tiles s={m.cash_quality} />
          <div className="chart-pair">
            <div><span className="cl">Operating cash ₹cr</span><Bars labels={cq.years as unknown as string[]} values={cq.cfo} /></div>
            <div><span className="cl">Free cash flow ₹cr</span><Bars labels={cq.years as unknown as string[]} values={cq.fcf} /></div>
          </div>
          <Flags s={m.cash_quality} />
          {m.cash_quality.note && <p className="tiny">{m.cash_quality.note}</p>}
          <p className="tiny">All ratios computed in code from reported financials. No model touched these numbers.</p>
        </section>
      )}

      {tab === "ask" && <Ask symbol={r.symbol} />}

      {r.sources && (
        <footer className="sources">
          <h4>Sources (primary only)</h4>
          {r.sources.map((s) => (
            <div key={s.id} className="srow"><span className="cite">{s.id}</span>
              {s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.label}</a> : <span>{s.label}</span>}
              <span className="tiny"> · {s.pages} pp</span></div>
          ))}
        </footer>
      )}
    </div>
  );
}

function Ask({ symbol }: { symbol: string }) {
  const [q, setQ] = useState("");
  const [log, setLog] = useState<{ q: string; a: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const rec = useRef<{ start: () => void; stop: () => void } | null>(null);
  const [listening, setListening] = useState(false);
  const go = async (question: string) => {
    if (!question.trim()) return;
    setBusy(true);
    try {
      const r = await ask(symbol, question);
      setLog((l) => [...l, { q: question, a: r.answer ?? (r.passages?.map((p) => `[${p.cite}] ${p.text}`).join("\n\n") || "No answer.") }]);
    } catch (e) {
      setLog((l) => [...l, { q: question, a: String((e as Error).message) }]);
    }
    setBusy(false); setQ("");
  };
  const mic = () => {
    // Voice in: browser speech recognition where available (Chrome/Android/Safari).
    const W = window as unknown as Record<string, new () => { lang: string; onresult: (e: { results: { 0: { 0: { transcript: string } } } }) => void; onend: () => void; start: () => void; stop: () => void }>;
    const SR = W.SpeechRecognition || W.webkitSpeechRecognition;
    if (!SR) return alert("Voice input isn't supported in this browser.");
    if (listening) { rec.current?.stop(); return; }
    const r = new SR(); r.lang = "en-IN";
    r.onresult = (e) => { const t = e.results[0][0].transcript; setQ(t); go(t); };
    r.onend = () => setListening(false);
    rec.current = r; setListening(true); r.start();
  };
  return (
    <section className="ask">
      {log.length === 0 && <div className="chips wrap">{["What did they guide for margins next year?", "Why did working capital rise?", "What are the key risks management flagged?"].map((s) => (
        <button key={s} className="chip" onClick={() => go(s)}>{s}</button>))}</div>}
      {log.map((x, i) => <div key={i} className="qa"><div className="q">{x.q}</div><div className="a">{x.a}</div></div>)}
      {busy && <div className="loading"><div className="pulse" />Searching transcripts…</div>}
      <form onSubmit={(e) => { e.preventDefault(); go(q); }} className="search">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask about ${symbol}…`} />
        <button type="button" className={`mic ${listening ? "on" : ""}`} onClick={mic} aria-label="Voice">●</button>
        <button className="primary">Ask</button>
      </form>
    </section>
  );
}
