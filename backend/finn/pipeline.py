"""Push side, end to end:

  prices ─► tracker (per-day signals) ─┐
                                       ├─► score filings (move-aware) ─► enrich above waterline ─► store
  NSE/BSE filings ─► classify ─────────┘
                                       └─► alerts = threshold triggers ⨝ filings (explained / unexplained)

Run daily after close (GitHub Action) and on demand from the API.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta

from . import config, db
from .engine import classify as clf
from .engine import enrich, priority, tracker

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- price signals
def _series_map(sym: str) -> dict[str, float]:
    return {r["date"]: r["close"] for r in db.price_series(sym)}


def signals(symbol: str) -> list[tracker.Day]:
    h = config.holding(symbol) or {}
    market = _series_map(config.portfolio()["market_index"])
    sector = _series_map(h["index"]) if h.get("index") else None
    rows = db.price_series(symbol)
    return tracker.analyse(rows, market, sector)


def all_signals() -> dict[str, list[tracker.Day]]:
    return {s: signals(s) for s in config.symbols()}


def move_on(days: list[tracker.Day], ts: str) -> dict | None:
    """Signals for the session the filing could have moved: same day if filed before the
    15:30 close, otherwise the next session (a 6pm results filing moves tomorrow's price)."""
    d, after_close = ts[:10], ts[11:16] >= "15:30"
    for day in days:
        if day.date > d or (day.date == d and not after_close):
            return day.as_dict()
    return None


# ---------------------------------------------------------------- filings
def fetch_filings(since: date) -> list[dict]:
    """NSE first (richer subjects + NSE-parsed results), BSE as fallback per symbol."""
    out, nse = [], None
    try:
        from .sources.nse import NSE
        nse = NSE()
    except Exception as e:
        log.warning("NSE client unavailable: %s", e)
    from .sources import bse
    for sym in config.symbols():
        got = []
        if nse is not None:
            try:
                got = nse.announcements(sym, since)
            except Exception as e:
                log.warning("NSE announcements failed for %s (%s) — trying BSE", sym, e)
                nse = None  # bot wall: don't keep hammering it
        if not got:
            try:
                got = bse.announcements(sym, since)
            except Exception as e:
                log.warning("BSE announcements failed for %s: %s", sym, e)
        out += got
    return out


def process(filings: list[dict], sigs: dict[str, list[tracker.Day]], nse=None,
            enrich_budget: int = 40) -> list[dict]:
    """Classify → score → enrich (only what clears the waterline, most important first)."""
    th = config.thresholds()
    fb = db.feedback_counts()
    known = db.known_announcement_ids()
    fresh = [f for f in filings if f["id"] not in known]
    for f in fresh:
        c = clf.classify(f["subject"], f.get("body", ""))
        f["category"], f["subtype"] = c.category, c.subtype
        f.setdefault("extra", {})["classified_by"] = c.method
        mv = move_on(sigs.get(f["symbol"], []), f["ts"])
        f["score"], f["reason"] = priority.score(c.category, c.subtype, feedback=fb, move=mv)
        if mv:
            f["extra"]["move"] = {k: mv.get(k) for k in ("date", "ret_pct", "abnormal_z", "vol_mult")}
    fresh.sort(key=lambda f: f["score"], reverse=True)
    for f in fresh:
        if enrich_budget > 0 and f["score"] >= th.waterline:
            try:
                if f["category"] == "results" and f["subtype"] == "filing":
                    f["extra"]["results"] = enrich.results_card(f["symbol"], f, nse)
                elif f["category"] == "management_change":
                    f["extra"]["people"] = enrich.people_card(f["symbol"], f)["people"]
                f["summary"] = enrich.one_liner(f)
            except Exception as e:  # enrichment must never block the digest
                log.warning("enrich failed for %s: %s", f["id"], e)
            enrich_budget -= 1
        db.upsert_announcement(f)
    return fresh


# ---------------------------------------------------------------- alerts
def build_alerts(sigs: dict[str, list[tracker.Day]], th=None, lookback_sessions: int = 5) -> list[dict]:
    """Fuse threshold triggers per symbol-day (one alert, many reasons) and join with filings
    within [day-1, day] to say whether the move is explained. Unexplained moves rank first:
    a big stock-specific move with no disclosure is the thing an investor most needs to know."""
    th = th or config.thresholds()
    alerts = []
    for sym, days in sigs.items():
        for d in days[-lookback_sessions:]:
            trig = tracker.triggers(d, th)
            if not trig:
                continue
            lo = (datetime.fromisoformat(d.date) - timedelta(days=1)).date().isoformat()
            hi = (datetime.fromisoformat(d.date) + timedelta(days=1)).date().isoformat()
            filings = [a for a in db.announcements(since_iso=lo, symbol=sym)
                       if a["ts"][:10] <= d.date and a["category"] != "unclassified"]
            explained = sorted(filings, key=lambda a: a["score"] or 0, reverse=True)[:2]
            stock_specific = d.abnormal_z is not None and abs(d.abnormal_z) >= th.abnormal_z
            sev = 40 + 8 * len(trig) + (20 if stock_specific and not explained else 0) \
                + min(12, 2 * abs(d.abnormal_z or 0))
            alerts.append({
                "id": hashlib.md5(f"move:{sym}:{d.date}".encode()).hexdigest()[:12],
                "kind": "move", "symbol": sym, "date": d.date, "severity": round(min(100, sev)),
                "headline": ("Unexplained move" if stock_specific and not explained else
                             "Explained move" if explained else "Market-driven move"),
                "triggers": trig, "day": d.as_dict(),
                "explained_by": [{"id": a["id"], "subject": a["subject"], "category": a["category"],
                                  "summary": a.get("summary")} for a in explained],
                "_window": hi,
            })
    # category alerts: material filings of a type the user opted into
    since = (date.today() - timedelta(days=lookback_sessions + 2)).isoformat()
    for a in db.announcements(since_iso=since):
        if a["category"] in th.alert_categories and (a["score"] or 0) >= 55:
            alerts.append({
                "id": hashlib.md5(f"filing:{a['id']}".encode()).hexdigest()[:12],
                "kind": "filing", "symbol": a["symbol"], "date": a["ts"][:10],
                "severity": round(a["score"]), "headline": priority.LABEL.get(a["category"], a["category"]),
                "triggers": [{"kind": "category", "text": a["reason"]}], "filing": a,
            })
    alerts.sort(key=lambda x: (x["severity"], x["date"]), reverse=True)
    return alerts


def run(days_back: int = 3, prices: bool = True) -> dict:
    """The daily job."""
    if prices:
        from .sources import prices as px
        px.ingest()
    sigs = all_signals()
    nse = None
    try:
        from .sources.nse import NSE
        nse = NSE()
    except Exception:
        pass
    fresh = process(fetch_filings(date.today() - timedelta(days=days_back)), sigs, nse)
    alerts = build_alerts(sigs)
    new = [a for a in alerts if db.record_alert(a["id"], a["symbol"], a["date"], a["kind"], {"h": a["headline"]})]
    from . import notify
    notify.push(new)
    return {"filings_new": len(fresh), "alerts": len(alerts), "alerts_new": len(new), "cost": db.cost_summary()}
