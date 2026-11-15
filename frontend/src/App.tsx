import { useCallback, useEffect, useState } from "react";
import { isLiveMode, loadDigest, loadMeta, loadPortfolio, sendFeedback } from "./lib/data";
import { DEFAULT_TH } from "./lib/engine";
import { lastVisit, usePersisted } from "./lib/store";
import { Holdings } from "./screens/Holdings";
import { Research } from "./screens/Research";
import { Today } from "./screens/Today";
import { Tune } from "./screens/Tune";
import type { Filing, Holding, Meta, Thresholds } from "./types";

type Tab = "today" | "holdings" | "research" | "tune";
const seen = lastVisit();

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [filings, setFilings] = useState<Filing[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [tab, setTab] = useState<Tab>(() => (location.hash.replace("#/", "").split("/")[0] as Tab) || "today");
  const [sym, setSym] = useState<string | null>(() => location.hash.match(/#\/research\/(\w+)/)?.[1] ?? null);
  const [th, setTh] = usePersisted<Thresholds>("thresholds", DEFAULT_TH);
  const [fb, setFb] = usePersisted<Record<string, { keep?: number; bury?: number }>>("feedback", {});

  useEffect(() => {
    Promise.all([loadMeta(), loadPortfolio(), loadDigest(), isLiveMode()])
      .then(([m, p, d, l]) => { setMeta(m); setHoldings(p.holdings); setFilings(d.items); setLive(l); })
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    const h = tab === "research" && sym ? `#/research/${sym}` : `#/${tab}`;
    if (location.hash !== h) history.replaceState(null, "", h);
    window.scrollTo({ top: 0 });
  }, [tab, sym]);

  const dig = useCallback((s: string) => { setSym(s); setTab("research"); }, []);
  const onFeedback = useCallback((f: Filing, a: "keep" | "bury") => {
    setFb((p) => ({ ...p, [f.category]: { ...p[f.category], [a]: (p[f.category]?.[a] ?? 0) + 1 } }));
    sendFeedback(f.symbol, f.category, a);
  }, [setFb]);

  if (err) return <div className="boot">Couldn't load data: {err}<br /><small>Run <code>python -m finn demo</code> or <code>python -m finn export</code>.</small></div>;
  if (!meta) return <div className="boot"><div className="logo">FINN</div><div className="pulse" /></div>;

  return (
    <div className="app">
      <header className="top">
        <div className="logo" onClick={() => setTab("today")}>FINN<span>.</span></div>
        <div className="status">
          {meta.synthetic && <span className="pill warn" title="Fictional companies, generated numbers — run the real ingest for live data">synthetic demo</span>}
          <span className={`pill ${live ? "live" : ""}`}>{live ? "live" : "snapshot"}</span>
        </div>
      </header>
      {meta.synthetic && tab === "today" && (
        <div className="banner">Demo mode: fictional companies and generated data, run through the real engine. Point it at NSE with <code>python -m finn run</code>.</div>
      )}
      <main>
        {tab === "today" && <Today meta={meta} holdings={holdings} filings={filings} th={th} setTh={setTh} fb={fb} onFeedback={onFeedback} lastSeen={seen} dig={dig} />}
        {tab === "holdings" && <Holdings holdings={holdings} filings={filings} th={th} dig={dig} />}
        {tab === "research" && <Research meta={meta} symbol={sym} setSymbol={setSym} />}
        {tab === "tune" && <Tune meta={meta} th={th} setTh={setTh} holdings={holdings} filings={filings} fb={fb} resetFb={() => setFb({})} live={live} />}
      </main>
      <nav className="tabbar">
        {([["today", "Today", "◉"], ["holdings", "Portfolio", "◫"], ["research", "Research", "⌕"], ["tune", "Tune", "⚙"]] as [Tab, string, string][]).map(([k, l, i]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}><span className="ti">{i}</span>{l}</button>
        ))}
      </nav>
    </div>
  );
}
