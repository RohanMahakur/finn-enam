"""NSE: corporate announcements + parsed quarterly results.

NSE sits behind Akamai Bot Manager, which fingerprints the TLS handshake — plain
`requests` gets a 403 even on the homepage. We use curl_cffi with Chrome
impersonation, warm the cookie jar on an HTML page, then call /api/* with a Referer.
The base host is configurable because maintained libraries disagree on whether NSE
moved to nseindia.in; we try both.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

BASES = [b for b in os.getenv("FINN_NSE_BASES", "https://www.nseindia.com,https://www.nseindia.in").split(",") if b]
ARCHIVES = "https://nsearchives.nseindia.com/corporate/"


class NSE:
    def __init__(self) -> None:
        from curl_cffi import requests as creq  # yfinance already depends on curl_cffi

        self._creq = creq
        self.s = None
        self.base = None

    def _prime(self) -> None:
        last_err = None
        for base in BASES:
            s = self._creq.Session(impersonate="chrome")
            s.headers.update({"Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
                              "Referer": f"{base}/option-chain"})
            try:
                r = s.get(base, timeout=15)
                if r.status_code == 200:
                    s.get(f"{base}/option-chain", timeout=15)
                    self.s, self.base = s, base
                    return
                last_err = f"{base} -> HTTP {r.status_code}"
            except Exception as e:  # network / TLS
                last_err = f"{base} -> {e}"
        raise RuntimeError(f"NSE unreachable: {last_err}")

    def get(self, path: str, params: dict) -> object:
        for attempt in range(3):
            if self.s is None:
                self._prime()
            r = self.s.get(f"{self.base}/api/{path}", params=params, timeout=20)
            if r.status_code in (401, 403):
                self.s = None  # cookies expired → re-prime
                time.sleep(1 + attempt)
                continue
            r.raise_for_status()
            time.sleep(0.6)  # be polite: ~1 req/s
            return r.json()
        raise RuntimeError(f"NSE {path} kept returning 401/403")

    # ---- announcements ----
    def announcements(self, symbol: str, since: date, until: date | None = None) -> list[dict]:
        until = until or date.today()
        raw = self.get("corporate-announcements", {
            "index": "equities", "symbol": symbol,
            "from_date": since.strftime("%d-%m-%Y"), "to_date": until.strftime("%d-%m-%Y"),
        })
        rows = raw if isinstance(raw, list) else raw.get("data", [])
        return [normalise(r) for r in rows]

    # ---- results: NSE already parses the XBRL for us (Rs lakhs) ----
    def results_comparison(self, symbol: str) -> list[dict]:
        raw = self.get("results-comparision", {"symbol": symbol})  # sic — NSE's spelling
        return raw.get("resCmpData", []) if isinstance(raw, dict) else []


def normalise(r: dict) -> dict:
    ts = r.get("sort_date") or ""
    try:
        ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").isoformat()
    except ValueError:
        try:
            ts = datetime.strptime(r.get("an_dt", ""), "%d-%b-%Y %H:%M:%S").isoformat()
        except ValueError:
            ts = datetime.now().isoformat(timespec="seconds")
    url = r.get("attchmntFile") or ""
    return {
        "id": f"nse:{r.get('seq_id') or hash((r.get('symbol'), ts, r.get('desc')))}",
        "symbol": r.get("symbol"),
        "ts": ts,
        "subject": (r.get("desc") or "").strip(),
        "body": (r.get("attchmntText") or "").strip(),
        "url": url,
        "source": "NSE",
        "extra": {"industry": r.get("smIndustry"), "isin": r.get("sm_isin")},
    }


LAKH_TO_CR = 0.01


def headline_from_rescmp(rows: list[dict]) -> list[dict]:
    """Map NSE results-comparision rows → our headline schema (₹ crore).

    EBITDA is not a line item in the SEBI format, so we compute it the conventional way:
    PBT + finance costs + depreciation − other income  (i.e. operating EBITDA). We
    exclude exceptional items when NSE reports them separately.
    """
    out = []
    for r in rows:
        def f(k: str) -> float | None:
            v = r.get(k)
            try:
                return float(v) * LAKH_TO_CR if v not in (None, "", "-") else None
            except (TypeError, ValueError):
                return None

        rev, oi, fin, dep = f("re_net_sale"), f("re_oth_inc_new"), f("re_int_new"), f("re_depr_und_exp")
        pbt, pat, exc = f("re_pro_loss_bef_tax"), f("re_net_profit") or f("re_con_pro_loss"), f("re_excepn_items_new")
        ebitda = None
        if pbt is not None:
            ebitda = pbt + (fin or 0) + (dep or 0) - (oi or 0) - (exc or 0)
        try:
            end = datetime.strptime(r.get("re_to_dt", ""), "%d-%b-%Y").date().isoformat()
        except ValueError:
            end = r.get("re_to_dt")
        out.append({"period_end": end, "revenue": rev, "ebitda": ebitda, "pbt": pbt, "pat": pat,
                    "other_income": oi, "source": "NSE results-comparision (XBRL-derived)"})
    return sorted(out, key=lambda x: x["period_end"] or "", reverse=True)


def default_since(days: int = 7) -> date:
    return date.today() - timedelta(days=days)
