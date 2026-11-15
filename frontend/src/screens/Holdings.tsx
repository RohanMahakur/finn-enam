import { useState } from "react";
import { CAT_ICON, Sheet } from "../components/Bits";
import { Corridor, Decomp } from "../components/Corridor";
import { ago, pct, tone } from "../lib/fmt";
import type { Filing, Holding, Thresholds } from "../types";

// Sorted by how unusual today was *for that stock* (|stock-specific z|), not by % move or
// alphabet — the list itself is a filter.
export function Holdings({ holdings, filings, th, dig }: { holdings: Holding[]; filings: Filing[]; th: Thresholds; dig: (s: string) => void }) {
  const [open, setOpen] = useState<Holding | null>(null);
  const rows = [...holdings].sort((a, b) => Math.abs(b.days.at(-1)?.abnormal_z ?? 0) - Math.abs(a.days.at(-1)?.abnormal_z ?? 0));
  return (
    <div className="screen">
      <div className="sec-h"><h2>Portfolio</h2><span className="hint">most unusual today first</span></div>
      <div className="hold-list">
        {rows.map((h) => {
          const d = h.days.at(-1);
          const z = d?.abnormal_z ?? 0;
          return (
            <button key={h.symbol} className="hold" onClick={() => setOpen(h)}>
              <div className="h-l">
                <div className="sym">{h.symbol}</div>
                <div className="nm">{h.name}</div>
              </div>
              <div className="h-c"><Corridor days={h.days.slice(-45)} h={34} mini zLine={th.trajectory_z} /></div>
              <div className="h-r">
                <div className={`ret ${tone(d?.ret_pct)}`}>{pct(d?.ret_pct)}</div>
                <div className={`z ${Math.abs(z) >= th.abnormal_z ? "hot" : Math.abs(z) >= 1.5 ? "warm" : ""}`}>{z >= 0 ? "+" : ""}{z.toFixed(1)}σ</div>
              </div>
            </button>
          );
        })}
      </div>
      <p className="caption">σ = today's stock-specific move (after removing β × Nifty) relative to its own typical noise.</p>

      <Sheet open={!!open} onClose={() => setOpen(null)}>
        {open && (() => {
          const d = open.days.at(-1)!;
          const fs = filings.filter((f) => f.symbol === open.symbol).slice(0, 8);
          return (
            <div className="detail">
              <div className="d-eyebrow">{open.sector} · {open.size} cap</div>
              <h3>{open.name} <span className="dim">{open.symbol}</span></h3>
              <div className="stats">
                <div><span>Close</span><b>{d.close.toLocaleString("en-IN", { maximumFractionDigits: 1 })}</b></div>
                <div><span>Day</span><b className={tone(d.ret_pct)}>{pct(d.ret_pct)}</b></div>
                <div><span>Volume</span><b>{d.vol_mult?.toFixed(1) ?? "—"}×</b></div>
                <div><span>β</span><b>{d.beta?.toFixed(2) ?? "—"}</b></div>
              </div>
              <Corridor days={open.days.slice(-90)} h={170} zLine={th.trajectory_z} />
              <Decomp d={d} />
              <h4>Recent filings</h4>
              {fs.length === 0 && <p className="dim">None in the snapshot window.</p>}
              {fs.map((f) => (
                <div key={f.id} className="mini-filing">
                  <span className="ic">{CAT_ICON[f.category]}</span>
                  <span className="s">{f.summary ?? f.subject}</span>
                  <span className="t">{ago(f.ts)}</span>
                </div>
              ))}
              <button className="primary" onClick={() => dig(open.symbol)}>Research {open.symbol} →</button>
            </div>
          );
        })()}
      </Sheet>
    </div>
  );
}
