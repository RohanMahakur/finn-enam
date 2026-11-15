export const pct = (x: number | null | undefined, d = 1) => (x == null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(d)}%`);
export const tone = (x: number | null | undefined) => (x == null ? "" : x > 0 ? "up" : x < 0 ? "down" : "");

export function cr(x: number | null | undefined) {
  if (x == null) return "—";
  const a = Math.abs(x);
  if (a >= 1e5) return `₹${(x / 1e5).toFixed(2)}L cr`;
  if (a >= 1000) return `₹${Math.round(x).toLocaleString("en-IN")} cr`;
  return `₹${x.toFixed(a < 10 ? 1 : 0)} cr`;
}

export function tileVal(v: number | null, unit: string) {
  if (v == null) return "—";
  if (unit === "₹ cr") return cr(v);
  if (unit === "%") return `${v.toFixed(1)}%`;
  if (unit === "×") return `${v.toFixed(2)}×`;
  if (unit === "days") return `${Math.round(v)} d`;
  return `${v}`;
}

export function ago(iso: string, now = Date.now()) {
  const h = (now - new Date(iso).getTime()) / 36e5;
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`;
  if (h < 24) return `${Math.round(h)}h`;
  return `${Math.round(h / 24)}d`;
}

export const dayLabel = (iso: string) =>
  new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });

export const METRIC_LABEL: Record<string, string> = { revenue: "Revenue", ebitda: "EBITDA", pbt: "PBT", pat: "PAT" };
