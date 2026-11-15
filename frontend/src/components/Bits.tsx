import { useEffect, useRef, useState, type ReactNode } from "react";
import { METRIC_LABEL, pct, tone } from "../lib/fmt";
import type { Person, ResultsCard } from "../types";

export function ResultsGrid({ r }: { r: ResultsCard }) {
  return (
    <div className="results">
      <div className="rg-head"><span /> <span>₹ cr</span><span>QoQ</span><span>YoY</span></div>
      {r.rows.map((x) => (
        <div className="rg-row" key={x.metric}>
          <span className="m">{METRIC_LABEL[x.metric]}</span>
          <span className="v">{x.value == null ? "—" : Math.round(x.value).toLocaleString("en-IN")}</span>
          <span className={`d ${tone(x.qoq)}`}>{pct(x.qoq)}</span>
          <span className={`d ${tone(x.yoy)}`}>{pct(x.yoy)}</span>
        </div>
      ))}
      {r.ebitda_margin != null && (
        <div className="rg-foot">
          EBITDA margin {r.ebitda_margin}%
          {r.margin_change_bps_yoy != null && (
            <b className={tone(r.margin_change_bps_yoy)}> {r.margin_change_bps_yoy >= 0 ? "+" : ""}{r.margin_change_bps_yoy} bps YoY</b>
          )}
        </div>
      )}
      {r.source && <div className="src">{r.source}</div>}
    </div>
  );
}

export function People({ people }: { people: Person[] }) {
  return (
    <div className="people">
      {people.map((p) => (
        <div key={p.name} className={`person ${p.action === "appointed" ? "in" : "out"}`}>
          <div className="avatar">{p.name.split(" ").map((s) => s[0]).slice(0, 2).join("")}</div>
          <div>
            <div className="pn">{p.name} <span className="arrow">{p.action === "appointed" ? "→ in" : "← out"}</span></div>
            <div className="pr">{p.role}{p.effective ? ` · from ${p.effective}` : ""}</div>
            {p.background && <p className="bg">{p.background}</p>}
            {!p.background && p.profile && <p className="bg">{p.profile}</p>}
            {p.reason && <p className="bg dim">Reason given: {p.reason}</p>}
            {p.sources?.filter((s) => s.url).slice(0, 3).map((s, i) => (
              <a key={i} className="srcl" href={s.url} target="_blank" rel="noreferrer">[{i + 1}] {s.title}</a>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Sheet({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  if (!open) return null;
  return (
    <div className="sheet-wrap" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()} role="dialog">
        <div className="grab" onClick={onClose} />
        {children}
      </div>
    </div>
  );
}

// Swipe right = keep, left = bury. Pointer events so it works with touch and mouse.
export function Swipe({ onKeep, onBury, children }: { onKeep: () => void; onBury: () => void; children: ReactNode }) {
  const [dx, setDx] = useState(0);
  const start = useRef<{ x: number; y: number } | null>(null);
  const horiz = useRef(false);
  const [gone, setGone] = useState<"" | "l" | "r">("");
  const end = () => {
    if (dx > 90) { setGone("r"); setTimeout(onKeep, 180); }
    else if (dx < -90) { setGone("l"); setTimeout(onBury, 220); }
    setDx(0); start.current = null; horiz.current = false;
  };
  return (
    <div className={`swipe ${gone}`}>
      <div className="swipe-bg">
        <span className={`keep ${dx > 40 ? "on" : ""}`}>✓ keep</span>
        <span className={`bury ${dx < -40 ? "on" : ""}`}>bury ↓</span>
      </div>
      <div
        className="swipe-fg"
        style={{ transform: `translateX(${dx}px)`, transition: start.current ? "none" : "transform .2s" }}
        onPointerDown={(e) => { start.current = { x: e.clientX, y: e.clientY }; }}
        onPointerMove={(e) => {
          if (!start.current) return;
          const ddx = e.clientX - start.current.x, ddy = e.clientY - start.current.y;
          if (!horiz.current && Math.abs(ddx) > 12 && Math.abs(ddx) > Math.abs(ddy) * 1.4) {
            horiz.current = true;
            (e.target as Element).setPointerCapture?.(e.pointerId);
          }
          if (horiz.current) setDx(ddx);
        }}
        onPointerUp={end}
        onPointerCancel={() => { setDx(0); start.current = null; horiz.current = false; }}
        onClickCapture={(e) => { if (horiz.current || Math.abs(dx) > 5) e.stopPropagation(); }}
      >
        {children}
      </div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><b>{title}</b>{children && <p>{children}</p>}</div>;
}

export const CAT_ICON: Record<string, string> = {
  results: "▦", "M&A": "⧉", management_change: "◐", fund_raise: "₹", litigation: "⚖", insider_trading: "⇄",
  earnings_call: "☏", investor_meetings: "◎", credit_rating: "◆", dividend: "◈", bonus_split: "⊞", capex: "⚙",
  press_release: "✦", postal_ballot: "☐", agm_egm: "◫", pledging: "⛓", unclassified: "·",
};
