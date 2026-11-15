"""SQLite storage. One file, zero ops — the right size for a single investor's daily tool.

Tables
  prices         EOD OHLCV per symbol (includes index symbols like ^NSEI)
  announcements  every exchange filing we have seen, with classification + score + enrichment
  cache          content-addressed cache (LLM responses, parsed PDFs, screener pages)
  llm_calls      cost ledger — every model call, tokens, ₹, cache hit or not
  feedback       swipe triage events (keep / bury) that train per-category priors
  alerts         fired alerts, so we never push the same thing twice
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices(
  symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY(symbol, date));
CREATE TABLE IF NOT EXISTS announcements(
  id TEXT PRIMARY KEY, symbol TEXT, ts TEXT, subject TEXT, body TEXT, url TEXT,
  source TEXT, category TEXT, subtype TEXT, score REAL, reason TEXT,
  summary TEXT, extra TEXT);
CREATE INDEX IF NOT EXISTS ix_ann_ts ON announcements(ts);
CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, value TEXT, created REAL);
CREATE TABLE IF NOT EXISTS llm_calls(
  ts REAL, task TEXT, model TEXT, in_tok INTEGER, out_tok INTEGER,
  cost_usd REAL, cached INTEGER);
CREATE TABLE IF NOT EXISTS feedback(ts REAL, symbol TEXT, category TEXT, action TEXT);
CREATE TABLE IF NOT EXISTS alerts(
  id TEXT PRIMARY KEY, symbol TEXT, date TEXT, kind TEXT, payload TEXT, sent INTEGER);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ---------- cache ----------
def cache_get(key: str, max_age_s: float | None = None) -> Any | None:
    with connect() as con:
        row = con.execute("SELECT value, created FROM cache WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    if max_age_s is not None and time.time() - row["created"] > max_age_s:
        return None
    return json.loads(row["value"])


def cache_put(key: str, value: Any) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO cache(key, value, created) VALUES(?,?,?)",
            (key, json.dumps(value, default=str), time.time()),
        )


# ---------- prices ----------
def upsert_prices(rows: list[tuple]) -> int:
    with connect() as con:
        con.executemany(
            "INSERT OR REPLACE INTO prices(symbol,date,open,high,low,close,volume) "
            "VALUES(?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def price_series(symbol: str) -> list[sqlite3.Row]:
    with connect() as con:
        return con.execute(
            "SELECT date, open, high, low, close, volume FROM prices WHERE symbol=? ORDER BY date",
            (symbol,),
        ).fetchall()


# ---------- announcements ----------
ANN_COLS = ("id", "symbol", "ts", "subject", "body", "url", "source",
            "category", "subtype", "score", "reason", "summary", "extra")


def upsert_announcement(a: dict) -> None:
    a = {k: a.get(k) for k in ANN_COLS}
    if isinstance(a["extra"], (dict, list)):
        a["extra"] = json.dumps(a["extra"], default=str)
    with connect() as con:
        con.execute(
            f"INSERT OR REPLACE INTO announcements({','.join(ANN_COLS)}) "
            f"VALUES({','.join('?' * len(ANN_COLS))})",
            tuple(a.values()),
        )


def announcements(since_iso: str | None = None, symbol: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM announcements WHERE 1=1", []
    if since_iso:
        q += " AND ts >= ?"; args.append(since_iso)
    if symbol:
        q += " AND symbol = ?"; args.append(symbol)
    with connect() as con:
        rows = con.execute(q + " ORDER BY ts DESC", args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["extra"] = json.loads(d["extra"]) if d["extra"] else {}
        out.append(d)
    return out


def known_announcement_ids() -> set[str]:
    with connect() as con:
        return {r[0] for r in con.execute("SELECT id FROM announcements")}


# ---------- cost ledger ----------
def log_llm(task: str, model: str, in_tok: int, out_tok: int, cost: float, cached: bool) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO llm_calls VALUES(?,?,?,?,?,?,?)",
            (time.time(), task, model, in_tok, out_tok, cost, int(cached)),
        )


def cost_summary() -> dict:
    with connect() as con:
        rows = con.execute(
            "SELECT task, model, COUNT(*) n, SUM(in_tok) i, SUM(out_tok) o, "
            "SUM(cost_usd) c, SUM(cached) hits FROM llm_calls GROUP BY task, model"
        ).fetchall()
    by_task = [dict(r) for r in rows]
    total = sum((r["c"] or 0) for r in by_task)
    calls = sum(r["n"] for r in by_task)
    hits = sum((r["hits"] or 0) for r in by_task)
    return {
        "total_usd": round(total, 5),
        "total_inr": round(total * config.USD_INR, 2),
        "calls": calls,
        "cache_hit_rate": round(hits / calls, 3) if calls else 0.0,
        "by_task": by_task,
    }


# ---------- feedback / alerts ----------
def add_feedback(symbol: str, category: str, action: str) -> None:
    with connect() as con:
        con.execute("INSERT INTO feedback VALUES(?,?,?,?)", (time.time(), symbol, category, action))


def feedback_counts() -> dict[str, dict[str, int]]:
    with connect() as con:
        rows = con.execute(
            "SELECT category, action, COUNT(*) n FROM feedback GROUP BY category, action"
        ).fetchall()
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["category"], {})[r["action"]] = r["n"]
    return out


def record_alert(alert_id: str, symbol: str, date: str, kind: str, payload: dict) -> bool:
    """Returns True if this alert is new (i.e. should be pushed)."""
    with connect() as con:
        if con.execute("SELECT 1 FROM alerts WHERE id=?", (alert_id,)).fetchone():
            return False
        con.execute(
            "INSERT INTO alerts VALUES(?,?,?,?,?,0)",
            (alert_id, symbol, date, kind, json.dumps(payload, default=str)),
        )
    return True
