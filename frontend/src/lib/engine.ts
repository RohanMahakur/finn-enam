// Client-side mirror of the backend's alert rules (finn/engine/tracker.py::triggers and
// finn/pipeline.py::build_alerts). Running them here means the Tune screen is *live*:
// drag a threshold and watch alerts appear/disappear — "I decide what unusual means".
import type { Alert, Day, Filing, Holding, Thresholds, Trigger } from "../types";

const f1 = (x: number) => (x >= 0 ? "+" : "") + x.toFixed(1);

export function triggers(d: Day, th: Thresholds): Trigger[] {
  const out: Trigger[] = [];
  if (d.ret_pct != null && Math.abs(d.ret_pct) >= th.price_move_pct)
    out.push({ kind: "price", text: `${f1(d.ret_pct)}% on the day (your line ±${th.price_move_pct}%)` });
  if (d.vol_mult != null && d.vol_mult >= th.volume_multiple)
    out.push({ kind: "volume", text: `volume ${d.vol_mult.toFixed(1)}× its 20-day average (your line ${th.volume_multiple}×)` });
  if (d.abnormal_z != null && d.abnormal_pct != null && Math.abs(d.abnormal_z) >= th.abnormal_z)
    out.push({
      kind: "abnormal",
      text: `${f1(d.abnormal_pct)}% stock-specific after stripping Nifty ${d.mkt_ret_pct != null ? f1(d.mkt_ret_pct) + "%" : ""} (β ${d.beta?.toFixed(2)})`,
    });
  if (d.traj_z != null && Math.abs(d.traj_z) >= th.trajectory_z)
    out.push({ kind: "trajectory", text: `closed ${d.traj_z > 0 ? "above" : "below"} its predicted corridor (${f1(d.traj_z)}σ)` });
  return out;
}

const addDays = (iso: string, n: number) => {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};

export function buildAlerts(holdings: Holding[], filings: Filing[], th: Thresholds, sessions = 5): Alert[] {
  const out: Alert[] = [];
  for (const h of holdings) {
    for (const d of h.days.slice(-sessions)) {
      const trig = triggers(d, th);
      if (!trig.length) continue;
      const lo = addDays(d.date, -1);
      const explained = filings
        .filter((f) => f.symbol === h.symbol && f.category !== "unclassified" && f.ts.slice(0, 10) >= lo && f.ts.slice(0, 10) <= d.date)
        .sort((a, b) => b.score - a.score)
        .slice(0, 2);
      const specific = d.abnormal_z != null && Math.abs(d.abnormal_z) >= th.abnormal_z;
      const sev = Math.min(100, 40 + 8 * trig.length + (specific && !explained.length ? 20 : 0) + Math.min(12, 2 * Math.abs(d.abnormal_z ?? 0)));
      out.push({
        id: `move:${h.symbol}:${d.date}`, kind: "move", symbol: h.symbol, date: d.date, severity: Math.round(sev),
        headline: specific && !explained.length ? "Unexplained move" : explained.length ? "Explained move" : "Market-driven move",
        triggers: trig, day: d, explainedBy: explained,
      });
    }
  }
  const latest = holdings[0]?.days.at(-1)?.date ?? new Date().toISOString().slice(0, 10);
  const since = addDays(latest, -(sessions + 2));
  for (const f of filings) {
    if (th.alert_categories.includes(f.category) && f.score >= 55 && f.ts.slice(0, 10) >= since)
      out.push({
        id: `filing:${f.id}`, kind: "filing", symbol: f.symbol, date: f.ts.slice(0, 10), severity: Math.round(f.score),
        headline: f.reason.split(" · ")[0], triggers: [{ kind: "category", text: f.reason }], filing: f,
      });
  }
  // One card per symbol-day: if a move is explained by a filing that also alerts, fold the filing in.
  const folded = new Set(out.filter((a) => a.kind === "move").flatMap((a) => (a.explainedBy ?? []).map((f) => `filing:${f.id}`)));
  return out.filter((a) => !folded.has(a.id)).sort((a, b) => b.severity - a.severity || b.date.localeCompare(a.date));
}

// Learned per-category prior (Beta(2,2) on "kept"), same formula as backend priority.py
export function priorMult(cat: string, fb: Record<string, { keep?: number; bury?: number }>) {
  const k = fb[cat]?.keep ?? 0, b = fb[cat]?.bury ?? 0;
  return 0.6 + 0.8 * ((k + 2) / (k + b + 4));
}

export function rescore(f: Filing, fb: Record<string, { keep?: number; bury?: number }>) {
  // backend score already includes server-side feedback; apply local deltas on top
  return Math.min(100, Math.round(f.score * priorMult(f.category, fb)));
}

export const DEFAULT_TH: Thresholds = {
  price_move_pct: 4, volume_multiple: 2, abnormal_z: 2.5, trajectory_z: 3,
  alert_categories: ["results", "M&A", "management_change", "fund_raise", "litigation", "credit_rating", "pledging"],
  waterline: 40,
};
