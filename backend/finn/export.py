"""Build the JSON the app reads. The same functions back the live API and the static
snapshot (frontend/public/data/*.json), so the deployed link works even when the backend
is asleep — the demo can never be 'down'."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from . import config, db, pipeline
from .engine import priority

log = logging.getLogger(__name__)


def meta() -> dict:
    synthetic = db.cache_get("meta:synthetic") or False
    with db.connect() as con:
        last_px = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
        last_ann = con.execute("SELECT MAX(ts) FROM announcements").fetchone()[0]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "synthetic": synthetic,
        "last_price_date": last_px,
        "last_filing_ts": last_ann,
        "holdings": db.cache_get("meta:holdings") or config.holdings(),
        "research_demo": db.cache_get("meta:research_demo") or config.portfolio()["research_demo"],
        "thresholds": config.thresholds().__dict__,
        "category_labels": priority.LABEL,
        "models": {t: getattr(config.routes(), t).split(",")[0] for t in ("cheap", "mid", "strong")},
    }


def digest(since_iso: str) -> dict:
    items = db.announcements(since_iso=since_iso)
    return {"since": since_iso, "items": items, "feedback": db.feedback_counts()}


def portfolio() -> dict:
    holds = db.cache_get("meta:holdings") or config.holdings()
    out = []
    for h in holds:
        sigs = pipeline.signals(h["symbol"]) if config.holding(h["symbol"]) else _signals_any(h)
        out.append({**h, "days": [d.as_dict() for d in sigs[-90:]]})
    return {"holdings": out, "market_index": config.portfolio()["market_index"]}


def _signals_any(h: dict):
    from .engine import tracker
    market = {r["date"]: r["close"] for r in db.price_series(config.portfolio()["market_index"])}
    sector = {r["date"]: r["close"] for r in db.price_series(h["index"])} if h.get("index") else None
    return tracker.analyse(db.price_series(h["symbol"]), market, sector)


def write_static(out_dir: Path | None = None, research_symbols: list[str] | None = None, days: int = 14) -> Path:
    out_dir = out_dir or config.EXPORT_DIR
    (out_dir / "research").mkdir(parents=True, exist_ok=True)
    since = (datetime.now() - timedelta(days=days)).isoformat()
    files = {"meta.json": meta(), "digest.json": digest(since), "portfolio.json": portfolio(),
             "costs.json": db.cost_summary()}
    for name, obj in files.items():
        (out_dir / name).write_text(json.dumps(obj, default=str, separators=(",", ":")))
    for sym in research_symbols or []:
        cached = db.cache_get(f"export:research:{sym}")
        if cached is None:
            try:
                from .engine.research import research
                cached = research(sym)
            except Exception as e:
                log.warning("research export failed for %s: %s", sym, e)
                continue
        (out_dir / "research" / f"{sym}.json").write_text(json.dumps(cached, default=str, separators=(",", ":")))
    log.info("static snapshot written to %s", out_dir)
    return out_dir
