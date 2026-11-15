"""CLI.

  python -m finn doctor              # which sources/models are reachable from this machine?
  python -m finn run [--days 3]      # the daily job: prices → filings → alerts → push
  python -m finn research TICKER     # pull research pack for any NSE symbol
  python -m finn export [--research ASIANPAINT BEL]   # write the static snapshot for the app
  python -m finn demo                # synthetic, clearly-labelled demo data (no network)
"""
from __future__ import annotations

import argparse
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def doctor() -> None:
    from datetime import date, timedelta

    from .llm import router

    checks = {}
    try:
        from .sources import prices
        n = prices.ingest(["RELIANCE", "^NSEI"], period="1mo")
        checks["yfinance"] = f"ok ({n})"
    except Exception as e:
        checks["yfinance"] = f"FAIL {e}"
    try:
        from .sources.nse import NSE
        nse = NSE()
        a = nse.announcements("RELIANCE", date.today() - timedelta(days=10))
        checks["nse_announcements"] = f"ok ({len(a)} filings via {nse.base})"
        r = nse.results_comparison("RELIANCE")
        checks["nse_results"] = f"ok ({len(r)} quarters)"
    except Exception as e:
        checks["nse"] = f"FAIL {e} (BSE fallback will be used)"
    try:
        from .sources import bse
        checks["bse_announcements"] = f"ok ({len(bse.announcements('RELIANCE', date.today() - timedelta(days=10)))})"
    except Exception as e:
        checks["bse_announcements"] = f"FAIL {e}"
    try:
        from .sources import screener
        d = screener.company("TCS")
        checks["screener"] = (f"ok (quarters={len(d['tables']['quarters']['periods'])}, "
                              f"concalls={len(d['documents']['concalls'])}, ARs={len(d['documents']['annual_reports'])})")
    except Exception as e:
        checks["screener"] = f"FAIL {e}"
    checks["models"] = router.status()
    print(json.dumps(checks, indent=2, default=str))


def main() -> None:
    p = argparse.ArgumentParser(prog="finn")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    r = sub.add_parser("run"); r.add_argument("--days", type=int, default=3); r.add_argument("--no-prices", action="store_true")
    rs = sub.add_parser("research"); rs.add_argument("symbol"); rs.add_argument("--shallow", action="store_true")
    ex = sub.add_parser("export"); ex.add_argument("--research", nargs="*", default=None)
    sub.add_parser("demo")
    a = p.parse_args()

    if a.cmd == "doctor":
        doctor()
    elif a.cmd == "run":
        from . import pipeline
        print(json.dumps(pipeline.run(days_back=a.days, prices=not a.no_prices), indent=2, default=str))
    elif a.cmd == "research":
        from .engine.research import research
        print(json.dumps(research(a.symbol, deep=not a.shallow), indent=2, default=str)[:20000])
    elif a.cmd == "export":
        from . import config, export
        syms = a.research if a.research is not None else config.portfolio()["research_demo"]
        print(export.write_static(research_symbols=syms))
    elif a.cmd == "demo":
        from . import demo
        demo.build()


if __name__ == "__main__":
    main()
