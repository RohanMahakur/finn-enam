import { useMemo, useState } from "react";
import { CAT_ICON, Empty, People, ResultsGrid, Sheet, Swipe } from "../components/Bits";
import { Corridor, Decomp } from "../components/Corridor";
import { Waterline } from "../components/Waterline";
import { buildAlerts, rescore } from "../lib/engine";
import { ago, dayLabel, pct, tone } from "../lib/fmt";
import { usePersisted } from "../lib/store";
import type { Alert, Filing, Holding, Meta, Thresholds } from "../types";

type FB = Record<string, { keep?: number; bury?: number }>;
type Props = {
  meta: Meta; holdings: Holding[]; filings: Filing[]; th: Thresholds; setTh: (t: Thresholds) => void;
  fb: FB; onFeedback: (f: Filing, a: "keep" | "bury") => void; lastSeen: string | null; dig: (s: string) => void;
};

const WINDOWS: { k: string; label: string; hours: number }[] = [
  { k: "session", label: "Since last session", hours: 0 }, { k: "last", label: "Since last look", hours: 0 },
  { k: "24", label: "24h", hours: 24 },
  { k: "72", label: "3 days", hours: 72 }, { k: "168", label: "Week", hours: 168 },
];

export function Today({ meta, holdings, filings, th, setTh, fb, onFeedback, lastSeen, dig }: Props) {
  const [win, setWin] = usePersisted("window", "session");
  const [buried, setBuried] = usePersisted<string[]>("buried", []);
  const [kept, setKept] = usePersisted<string[]>("kept", []);
  const [openBelow, setOpenBelow] = useState<string | null>(null);
  const [sheet, setSheet] = useState<{ alert?: Alert; filing?: Filing } | null>(null);
  const names = Object.fromEntries(meta.holdings.map((h) => [h.symbol, h.name]));

  // Anchor windows to the snapshot's clock (live API → now), so a static snapshot opened
  // days later still shows "the last 24h" of *its* data instead of an empty screen.
  const now = Math.min(Date.now(), new Date(meta.generated_at).getTime() || Date.now());
  // Markets run in sessions, not hours: on a Monday morning "the last 24h" is empty, but
  // "since the close before the last session" is exactly what you missed.
  const sessionStart = (() => {
    const d = holdings[0]?.days.at(-2)?.date;
    return d ? new Date(`${d}T15:30:00`).getTime() : now - 24 * 36e5;
  })();
  const sinceMs = win === "last" && lastSeen ? new Date(lastSeen).getTime()
    : win === "session" ? Math.min(sessionStart, now - 24 * 36e5)
    : now - (WINDOWS.find((w) => w.k === win)?.hours || 24) * 36e5;
  const inWin = filings.filter((f) => new Date(f.ts).getTime() >= sinceMs && !buried.includes(f.id));
  const scored = inWin.map((f) => ({ f, s: rescore(f, fb) })).sort((a, b) => b.s - a.s);
  const above = scored.filter((x) => x.s >= th.waterline);
  const below = scored.filter((x) => x.s < th.waterline);
  const belowGroups = useMemo(() => {
    const g: Record<string, Filing[]> = {};
    below.forEach(({ f }) => (g[f.category] ||= []).push(f));
    return Object.entries(g).sort((a, b) => b[1].length - a[1].length);
  }, [below]);

  const alerts = useMemo(() => buildAlerts(holdings, filings, th), [holdings, filings, th]);
  const [showAll, setShowAll] = useState(false);
  const urgent = alerts.filter((a) => a.severity >= 70);
  const top = showAll ? alerts.filter((a) => a.severity >= 55) : urgent;

  const brief = useMemo(() => briefLine(urgent, names), [urgent, names]);
  const speak = () => {
    try {
      const u = new SpeechSynthesisUtterance(brief.replace(/·/g, ",").replace(/₹/g, "rupees "));
      u.lang = "en-IN"; u.rate = 1.05;
      speechSynthesis.cancel(); speechSynthesis.speak(u);
    } catch { /* no TTS */ }
  };

  return (
    <div className="screen">
      <section className="brief">
        <div className="eyebrow">{new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
          {meta.last_price_date && <> · prices to {dayLabel(meta.last_price_date)}</>}</div>
        <h1>{brief}</h1>
        <button className="listen" onClick={speak} aria-label="Read the brief aloud">▶ Listen · 20s</button>
      </section>

      <div className="sec-h"><h2>Needs you</h2><span className="count">{urgent.length}</span></div>
      {top.length === 0 && <Empty title="Nothing crossed your lines.">Your thresholds are in Tune — the app only interrupts when you said it should.</Empty>}
      <div className="alerts">
        {top.map((a) => <AlertCard key={a.id} a={a} name={names[a.symbol]} onOpen={() => setSheet({ alert: a })} th={th} holdings={holdings} />)}
      </div>
      {alerts.filter((a) => a.severity >= 55).length > urgent.length && (
        <button className="link" onClick={() => setShowAll(!showAll)}>
          {showAll ? "Show only what needs you" : `+${alerts.filter((a) => a.severity >= 55 && a.severity < 70).length} lower-severity (market-driven moves, minor filings)`}
        </button>)}

      <div className="sec-h">
        <h2>Filings</h2>
        <div className="chips">
          {WINDOWS.map((w) => (
            <button key={w.k} className={`chip ${win === w.k ? "on" : ""}`} onClick={() => setWin(w.k)}
              title={w.k === "last" && lastSeen ? `since ${new Date(lastSeen).toLocaleString()}` : undefined}>
              {w.k === "last" && lastSeen ? `Since you looked · ${ago(lastSeen)}` : w.label}
            </button>
          ))}
        </div>
      </div>

      <div className="digest">
        {above.length === 0 && <Empty title="Nothing material in this window.">Lower the waterline to see routine filings.</Empty>}
        {above.map(({ f, s }) => (
          <Swipe key={f.id}
            onKeep={() => { setKept([...kept, f.id]); onFeedback(f, "keep"); }}
            onBury={() => { setBuried([...buried, f.id]); onFeedback(f, "bury"); }}>
            <FilingCard f={f} s={s} name={names[f.symbol]} kept={kept.includes(f.id)} onOpen={() => setSheet({ filing: f })} />
          </Swipe>
        ))}
      </div>

      <Waterline value={th.waterline} onChange={(v) => setTh({ ...th, waterline: v })} above={above.length} below={below.length} />

      <div className="underwater">
        {belowGroups.map(([cat, fs]) => (
          <div key={cat} className="uw-group">
            <button className="uw-head" onClick={() => setOpenBelow(openBelow === cat ? null : cat)}>
              <span className="ic">{CAT_ICON[cat]}</span> {meta.category_labels[cat] ?? cat}
              <span className="n">{fs.length}</span><span className="chev">{openBelow === cat ? "▾" : "▸"}</span>
            </button>
            {openBelow === cat && fs.map((f) => (
              <div key={f.id} className="uw-item" onClick={() => setSheet({ filing: f })}>
                <b>{f.symbol}</b> {f.subject} <span className="t">{ago(f.ts)}</span>
              </div>
            ))}
          </div>
        ))}
        {buried.length > 0 && (
          <button className="link" onClick={() => setBuried([])}>Restore {buried.length} buried</button>
        )}
      </div>

      <Sheet open={!!sheet} onClose={() => setSheet(null)}>
        {sheet?.alert && <AlertDetail a={sheet.alert} holdings={holdings} name={names[sheet.alert.symbol]} dig={dig} th={th} />}
        {sheet?.filing && <FilingDetail f={sheet.filing} name={names[sheet.filing.symbol]} dig={dig} />}
      </Sheet>
    </div>
  );
}

function briefLine(top: Alert[], names: Record<string, string>) {
  if (!top.length) return "Quiet day. Nothing in your portfolio crossed a line you care about.";
  const seenSym = new Set<string>();
  const uniq = top.filter((a) => (seenSym.has(a.symbol) ? false : (seenSym.add(a.symbol), true)));
  const bits = uniq.slice(0, 3).map((a) => {
    const n = names[a.symbol]?.split(" ")[0] ?? a.symbol;
    if (a.kind === "move" && a.day)
      return a.headline === "Unexplained move" ? `${n} ${a.day.ret_pct! < 0 ? "fell" : "rose"} ${Math.abs(a.day.ret_pct!).toFixed(1)}% with no filing`
        : `${n} ${pct(a.day.ret_pct)} on ${a.explainedBy?.[0]?.category === "results" ? "results" : a.explainedBy?.[0] ? "news" : "the market"}`;
    const f = a.filing!;
    if (f.category === "management_change")
      return f.subtype.startsWith("senior") ? `${n} changes ${f.extra.people?.[0]?.role?.match(/financial/i) ? "its CFO" : "top management"}` : `${n}: board change`;
    if (f.category === "credit_rating") return `${n} rating ${f.subtype}`;
    return `${n}: ${a.headline.toLowerCase()}`;
  });
  const n = uniq.length;
  return `${n} name${n > 1 ? "s" : ""} need${n > 1 ? "" : "s"} you. ${bits.join(". ")}${n > 3 ? `, and ${n - 3} more` : ""}.`;
}

function AlertCard({ a, name, onOpen, holdings, th }: { a: Alert; name?: string; onOpen: () => void; holdings: Holding[]; th: Thresholds }) {
  const h = holdings.find((x) => x.symbol === a.symbol);
  const cls = a.headline === "Unexplained move" ? "red" : a.kind === "move" ? "amber" : "blue";
  return (
    <button className={`alert ${cls}`} onClick={onOpen}>
      <div className="a-top">
        <span className="sym">{a.symbol}</span>
        <span className={`badge ${cls}`}>{a.headline}</span>
        <span className="sev" title="severity">{a.severity}</span>
      </div>
      <div className="a-body">
        <div className="a-text">
          {a.kind === "move" && a.day && <div className={`big ${tone(a.day.ret_pct)}`}>{pct(a.day.ret_pct)}</div>}
          {a.kind === "move" ? <ul>{a.triggers.slice(0, 2).map((t, i) => <li key={i}>{t.text}</li>)}</ul>
            : <div className="a-reason">{a.filing?.reason}</div>}
          {a.kind === "move" && (a.explainedBy?.length
            ? <div className="why">↳ {a.explainedBy[0].summary ?? a.explainedBy[0].subject}</div>
            : a.headline === "Unexplained move" ? <div className="why warn">↳ no filing explains this</div>
            : <div className="why">↳ moved with the market (Nifty {pct(a.day?.mkt_ret_pct)}, β {a.day?.beta?.toFixed(1)}). Not stock-specific</div>)}
          {a.kind === "filing" && a.filing?.summary && <div className="why">{a.filing.summary}</div>}
        </div>
        {h && a.kind === "move" && <div className="a-chart"><Corridor days={h.days.slice(-40)} h={56} mini zLine={th.trajectory_z} /></div>}
      </div>
      <div className="a-name">{name} · {dayLabel(a.date)}</div>
    </button>
  );
}

function FilingCard({ f, s, name, kept, onOpen }: { f: Filing; s: number; name?: string; kept: boolean; onOpen: () => void }) {
  return (
    <div className={`fcard ${kept ? "kept" : ""}`} onClick={onOpen}>
      <div className="f-top">
        <span className="ic">{CAT_ICON[f.category]}</span>
        <span className="sym">{f.symbol}</span>
        <span className="reason">{f.reason}</span>
        <span className="score" style={{ ["--s" as string]: s }}>{s}</span>
      </div>
      <div className="f-sub">{f.summary ?? f.subject}</div>
      {f.extra.results && <ResultsGrid r={f.extra.results} />}
      {f.extra.people && f.extra.people.some((p) => p.action === "appointed") && (
        <People people={f.extra.people.filter((p) => p.action === "appointed")} />
      )}
      <div className="f-meta">{name} · {ago(f.ts)} ago · {f.source}{kept && " · ✓ kept"}</div>
    </div>
  );
}

function AlertDetail({ a, holdings, name, dig, th }: { a: Alert; holdings: Holding[]; name?: string; dig: (s: string) => void; th: Thresholds }) {
  const h = holdings.find((x) => x.symbol === a.symbol);
  if (a.kind === "filing" && a.filing) return <FilingDetail f={a.filing} name={name} dig={dig} />;
  return (
    <div className="detail">
      <div className="d-eyebrow">{a.headline} · {dayLabel(a.date)}</div>
      <h3>{name} <span className="dim">{a.symbol}</span></h3>
      {h && <Corridor days={h.days.slice(-90)} h={170} zLine={th.trajectory_z} />}
      <p className="caption">Line: close. Shaded corridor: where a Kalman filter tracking the stock's level and drift expected it to close (±2σ). Dots: sessions it left the corridor.</p>
      {a.day && <Decomp d={a.day} />}
      <ul className="trig">{a.triggers.map((t, i) => <li key={i} className={t.kind}>{t.text}</li>)}</ul>
      <h4>{a.explainedBy?.length ? "Probably explained by" : "No filing on the day or the day before"}</h4>
      {a.explainedBy?.map((f) => <FilingCard key={f.id} f={f} s={f.score} name={name} kept={false} onOpen={() => {}} />)}
      {!a.explainedBy?.length && (a.headline === "Unexplained move"
        ? <p className="dim">Unexplained, stock-specific moves are ranked first. If a filing didn't cause it, something else did, and that's worth a call.</p>
        : <p className="dim">Most of this move is the market: β × Nifty explains it. Low priority unless you hold it for reasons the market is now questioning.</p>)}
      <button className="primary" onClick={() => dig(a.symbol)}>Dig into {a.symbol} →</button>
    </div>
  );
}

function FilingDetail({ f, name, dig }: { f: Filing; name?: string; dig: (s: string) => void }) {
  return (
    <div className="detail">
      <div className="d-eyebrow">{f.reason}</div>
      <h3>{name} <span className="dim">{f.symbol}</span></h3>
      <p className="subj">{f.subject}</p>
      {f.summary && <p className="summ">{f.summary}</p>}
      {f.extra.results && <ResultsGrid r={f.extra.results} />}
      {f.extra.people && <People people={f.extra.people} />}
      {f.extra.move && f.extra.move.ret_pct != null && (
        <p className="dim">Next session: {pct(f.extra.move.ret_pct)}{f.extra.move.abnormal_z != null && `, ${f.extra.move.abnormal_z.toFixed(1)}σ stock-specific`}</p>
      )}
      {f.body && f.body !== f.summary && <p className="body">{f.body}</p>}
      <div className="row">
        {f.url && <a className="ghost" href={f.url} target="_blank" rel="noreferrer">Open filing ↗</a>}
        <button className="primary" onClick={() => dig(f.symbol)}>Dig into {f.symbol} →</button>
      </div>
      <p className="tiny">Score {f.score} · classified by {f.extra.classified_by ?? "rules"} · {new Date(f.ts).toLocaleString("en-IN")}</p>
    </div>
  );
}
