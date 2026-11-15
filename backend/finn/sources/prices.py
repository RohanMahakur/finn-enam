"""End-of-day price & volume via yfinance (.NS suffix), plus index series for the
market model. Stored in SQLite so the signal engine never touches the network."""
from __future__ import annotations

import logging

from .. import config, db

log = logging.getLogger(__name__)


def yf_symbol(sym: str) -> str:
    return sym if sym.startswith("^") or sym.endswith((".NS", ".BO")) else f"{sym}.NS"


def index_symbols() -> list[str]:
    idx = {config.portfolio()["market_index"]}
    idx |= {h["index"] for h in config.holdings() if h.get("index")}
    return sorted(idx)


def ingest(symbols: list[str] | None = None, period: str = "2y") -> dict:
    import yfinance as yf

    symbols = symbols or (config.symbols() + index_symbols())
    tickers = [yf_symbol(s) for s in symbols]
    df = yf.download(tickers, period=period, interval="1d", auto_adjust=True,
                     group_by="ticker", progress=False, threads=True)
    report = {}
    for sym, t in zip(symbols, tickers):
        try:
            sub = df[t] if len(tickers) > 1 else df
            sub = sub.dropna(subset=["Close"])
        except KeyError:
            report[sym] = 0
            continue
        rows = [(sym, d.date().isoformat(), float(r.Open), float(r.High), float(r.Low),
                 float(r.Close), float(r.Volume or 0)) for d, r in sub.iterrows()]
        report[sym] = db.upsert_prices(rows)
    missing = [s for s, n in report.items() if n == 0]
    if missing:
        log.warning("no price data for %s", missing)
    return report
