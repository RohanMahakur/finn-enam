import type { CSSProperties } from "react";
import type { Day } from "../types";

// The Kalman "corridor": where the filter predicted the stock would close (band = ±2√S),
// and where it actually closed. Dots outside the band are the days it left its trajectory.
export function Corridor({ days, h = 140, mini = false, zLine = 3 }: { days: Day[]; h?: number; mini?: boolean; zLine?: number }) {
  const w = mini ? 120 : 340;
  const pts = days.filter((d) => d.close != null);
  if (pts.length < 3) return <svg width={w} height={h} />;
  const ys = pts.flatMap((d) => [d.close, d.band_lo ?? d.close, d.band_hi ?? d.close]);
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const pad = (hi - lo) * 0.08 || 1;
  const x = (i: number) => (i / (pts.length - 1)) * (w - (mini ? 2 : 8)) + (mini ? 1 : 4);
  const y = (v: number) => h - 4 - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * (h - 8);
  const band = pts.map((d, i) => (d.band_hi != null ? `${x(i)},${y(d.band_hi)}` : null)).filter(Boolean);
  const bandLo = pts.map((d, i) => (d.band_lo != null ? `${x(i)},${y(d.band_lo)}` : null)).filter(Boolean).reverse();
  const line = pts.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.close).toFixed(1)}`).join("");
  const breaks = pts.map((d, i) => ({ d, i })).filter(({ d }) => d.traj_z != null && Math.abs(d.traj_z) >= zLine);
  const last = pts[pts.length - 1];
  const up = (last.ret_pct ?? 0) >= 0;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} className="corridor" role="img"
      aria-label="Closing price against the Kalman-predicted corridor">
      <polygon points={[...band, ...bandLo].join(" ")} className="band" />
      <path d={line} className={`px ${up ? "up" : "down"}`} />
      {breaks.map(({ d, i }) => (
        <circle key={d.date} cx={x(i)} cy={y(d.close)} r={mini ? 2.2 : 3.4} className={(d.traj_z ?? 0) > 0 ? "brk up" : "brk down"} />
      ))}
      {!mini && <circle cx={x(pts.length - 1)} cy={y(last.close)} r={3} className="now" />}
    </svg>
  );
}

// Market vs stock-specific decomposition of the day's move.
export function Decomp({ d }: { d: Day }) {
  if (d.ret_pct == null) return null;
  const mkt = d.beta != null && d.mkt_ret_pct != null ? d.beta * d.mkt_ret_pct : null;
  const spec = d.abnormal_pct;
  const max = Math.max(4, Math.abs(d.ret_pct), Math.abs(mkt ?? 0), Math.abs(spec ?? 0));
  const bar = (v: number | null, cls: string, label: string) => (
    <div className="decomp-row">
      <span className="lbl">{label}</span>
      <div className="track">
        <div className="mid" />
        {v != null && (
          <div className={`fill ${cls} ${v >= 0 ? "pos" : "neg"}`}
            style={{ width: `${(Math.abs(v) / max) * 50}%`, [v >= 0 ? "left" : "right"]: "50%" } as CSSProperties} />
        )}
      </div>
      <span className={`num ${v != null && v < 0 ? "down" : "up"}`}>{v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`}</span>
    </div>
  );
  return (
    <div className="decomp">
      {bar(d.ret_pct, "total", "Move")}
      {bar(mkt, "mkt", `Market ×β${d.beta?.toFixed(1) ?? ""}`)}
      {bar(spec, "spec", "Stock-specific")}
    </div>
  );
}
