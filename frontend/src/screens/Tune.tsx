import { useEffect, useMemo, useState } from "react";
import { DEFAULT_TH, buildAlerts, priorMult } from "../lib/engine";
import { loadCosts } from "../lib/data";
import type { Filing, Holding, Meta, Thresholds } from "../types";

type FB = Record<string, { keep?: number; bury?: number }>;

export function Tune({ meta, th, setTh, holdings, filings, fb, resetFb, live }: {
  meta: Meta; th: Thresholds; setTh: (t: Thresholds) => void; holdings: Holding[]; filings: Filing[];
  fb: FB; resetFb: () => void; live: boolean;
}) {
  const fired = useMemo(() => buildAlerts(holdings, filings, th).filter((a) => a.kind === "move").length, [holdings, filings, th]);
  const [costs, setCosts] = useState<Awaited<ReturnType<typeof loadCosts>> | null>(null);
  useEffect(() => { loadCosts().then(setCosts).catch(() => {}); }, []);

  const slider = (k: keyof Thresholds, label: string, min: number, max: number, step: number, unit: string, help: string) => (
    <label className="slider">
      <div className="s-top"><span>{label}</span><b>{th[k] as number}{unit}</b></div>
      <input type="range" min={min} max={max} step={step} value={th[k] as number}
        onChange={(e) => setTh({ ...th, [k]: Number(e.target.value) })} />
      <div className="s-help">{help}</div>
    </label>
  );
  const cats = Object.keys(meta.category_labels).filter((c) => c !== "unclassified");
  const learned = cats.map((c) => ({ c, m: priorMult(c, fb), n: (fb[c]?.keep ?? 0) + (fb[c]?.bury ?? 0) })).filter((x) => x.n > 0);

  return (
    <div className="screen">
      <div className="sec-h"><h2>What's unusual to you</h2></div>
      <div className="live-count"><b>{fired}</b> move alert{fired === 1 ? "" : "s"} would have fired in the last 5 sessions with these lines.</div>
      {slider("price_move_pct", "Price move", 1, 10, 0.5, "%", "Raw daily move, either direction.")}
      {slider("volume_multiple", "Volume spike", 1.2, 5, 0.1, "×", "Volume vs its own 20-session average.")}
      {slider("abnormal_z", "Stock-specific move", 1.5, 5, 0.1, "σ", "Move left after removing β × Nifty, in units of the stock's own noise. Kills market-wide false alarms.")}
      {slider("trajectory_z", "Left its corridor", 2, 5, 0.1, "σ", "Kalman-filter innovation: how far the close landed from where its trend predicted.")}

      <div className="sec-h"><h2>Filing types that may interrupt you</h2></div>
      <div className="chips wrap">
        {cats.map((c) => {
          const on = th.alert_categories.includes(c);
          return <button key={c} className={`chip ${on ? "on" : ""}`}
            onClick={() => setTh({ ...th, alert_categories: on ? th.alert_categories.filter((x) => x !== c) : [...th.alert_categories, c] })}>
            {meta.category_labels[c]}</button>;
        })}
      </div>
      <p className="caption">Interrupts follow these explicit rules only. What FINN learns from your swipes re-ranks the digest, never the alerts. Interrupts should be predictable.</p>

      <div className="sec-h"><h2>What FINN has learned</h2>{learned.length > 0 && <button className="link" onClick={resetFb}>reset</button>}</div>
      {learned.length === 0 ? <p className="caption">Swipe digest cards right (keep) or left (bury). Each category's weight moves slowly from 1.0 (Beta(2,2) prior), so three swipes can't bury a whole category.</p>
        : <div className="learned">{learned.map(({ c, m, n }) => (
          <div key={c} className="lrow"><span>{meta.category_labels[c]}</span>
            <div className="ltrack"><div className="lfill" style={{ width: `${((m - 0.6) / 0.8) * 100}%` }} /><div className="lmid" /></div>
            <b>×{m.toFixed(2)}</b><span className="tiny">{n}</span></div>))}</div>}

      <div className="sec-h"><h2>What this costs</h2></div>
      <div className="cost">
        <div className="tile"><span>Model spend to date</span><b>{costs ? `₹${costs.total_inr.toFixed(2)}` : "—"}</b></div>
        <div className="tile"><span>Model calls</span><b>{costs?.calls ?? 0}</b></div>
        <div className="tile"><span>Cache hit rate</span><b>{costs ? `${Math.round(costs.cache_hit_rate * 100)}%` : "—"}</b></div>
      </div>
      <p className="caption">Routing: regex rules → NSE's own parsed numbers → <b>{meta.models.cheap}</b> for bulk extraction → <b>{meta.models.mid}</b> for transcripts → <b>{meta.models.strong}</b> only to judge promises and write the case.</p>

      <div className="sec-h"><h2>Data</h2></div>
      <p className="caption">{live ? "Live backend" : "Static snapshot"} · generated {new Date(meta.generated_at).toLocaleString("en-IN")} ·
        prices to {meta.last_price_date ?? "—"}{meta.synthetic && " · SYNTHETIC demo data (fictional companies)"}</p>
      <button className="ghost" onClick={() => setTh({ ...DEFAULT_TH })}>Reset thresholds</button>
    </div>
  );
}
