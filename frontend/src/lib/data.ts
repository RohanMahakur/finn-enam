// Data layer. Two modes, same shapes:
//  • live   — VITE_API_URL set (or same-origin /api reachable): FastAPI backend
//  • static — the JSON snapshot in /data (written by `python -m finn export`), so the
//             deployed link works even if the backend is asleep.
import type { Filing, Holding, Meta, Research } from "../types";

const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
let live: boolean | null = null;

async function isLive(): Promise<boolean> {
  if (live !== null) return live;
  try {
    const r = await fetch(`${API}/api/health`, { signal: AbortSignal.timeout(2500) });
    live = r.ok && (r.headers.get("content-type") ?? "").includes("json");
  } catch {
    live = false;
  }
  return live;
}

async function get<T>(apiPath: string, staticPath: string): Promise<T> {
  if (await isLive()) {
    const r = await fetch(`${API}/api/${apiPath}`);
    if (r.ok) return r.json();
  }
  const r = await fetch(`${import.meta.env.BASE_URL}data/${staticPath}`);
  if (!r.ok) throw new Error(`missing ${staticPath}`);
  return r.json();
}

export const loadMeta = () => get<Meta>("meta", "meta.json");
export const loadDigest = () => get<{ items: Filing[] }>("digest?hours=336", "digest.json");
export const loadPortfolio = () => get<{ holdings: Holding[] }>("portfolio", "portfolio.json");
export const loadCosts = () => get<{ total_usd: number; total_inr: number; calls: number; cache_hit_rate: number; by_task: { task: string; model: string; n: number; c: number }[] }>("costs", "costs.json");

export async function loadResearch(symbol: string): Promise<Research> {
  const s = symbol.trim().toUpperCase();
  try {
    const r = await fetch(`${import.meta.env.BASE_URL}data/research/${s}.json`);
    if (r.ok && (r.headers.get("content-type") ?? "").includes("json")) return r.json();
  } catch { /* fall through */ }
  if (await isLive()) {
    const r = await fetch(`${API}/api/research/${encodeURIComponent(s)}`);
    if (r.ok) return r.json();
    throw new Error((await r.json().catch(() => ({}))).detail ?? `No data for ${s}`);
  }
  throw new Error(`${s} isn't in this snapshot. Live research on any NSE ticker needs the backend running.`);
}

export async function ask(symbol: string, question: string) {
  if (!(await isLive())) throw new Error("Ask needs the live backend (it reads the transcripts on demand).");
  const r = await fetch(`${API}/api/ask`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, question }),
  });
  return r.json() as Promise<{ answer: string | null; status: string; passages?: { cite: string; text: string }[] }>;
}

export async function sendFeedback(symbol: string, category: string, action: "keep" | "bury") {
  if (await isLive()) {
    fetch(`${API}/api/feedback`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, category, action }),
    }).catch(() => {});
  }
}

export const isLiveMode = isLive;
