"""BSE announcements — the fallback when NSE's bot wall wins (e.g. from a cloud IP).

Plain requests works with Origin/Referer headers. Symbol→scrip code via BSE's own
smart-search, cached forever (codes don't change).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime

import requests

from .. import config, db

log = logging.getLogger(__name__)
API = "https://api.bseindia.com/BseIndiaAPI/api"
HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}


def scrip_code(symbol: str) -> str | None:
    key = f"bse:code:{symbol}"
    if (hit := db.cache_get(key)) is not None:
        return hit
    r = requests.get(f"{API}/PeerSmartSearch/w", params={"Type": "SS", "text": symbol},
                     headers=HEADERS, timeout=15)
    r.raise_for_status()
    # Response is an HTML-ish snippet; codes are 6-digit numbers next to the NSE symbol.
    txt = r.text
    m = re.search(rf"{re.escape(symbol)}.{{0,200}}?(\d{{6}})", txt, re.S) or re.search(r"(\d{6})", txt)
    code = m.group(1) if m else None
    db.cache_put(key, code)
    return code


def announcements(symbol: str, since: date, until: date | None = None) -> list[dict]:
    code = scrip_code(symbol)
    if not code:
        return []
    until = until or date.today()
    out, page = [], 1
    while page < 10:
        r = requests.get(f"{API}/AnnSubCategoryGetData/w", headers=HEADERS, timeout=20, params={
            "pageno": page, "strCat": -1, "subcategory": -1, "strPrevDate": since.strftime("%Y%m%d"),
            "strToDate": until.strftime("%Y%m%d"), "strSearch": "P", "strScrip": code, "strType": "C",
        })
        r.raise_for_status()
        data = r.json()
        rows = data.get("Table") or []
        out += [normalise(x, symbol) for x in rows]
        total = (data.get("Table1") or [{}])[0].get("ROWCNT", 0)
        if len(out) >= total or not rows:
            break
        page += 1
        time.sleep(0.5)
    return out


def normalise(r: dict, symbol: str) -> dict:
    ts = r.get("NEWS_DT") or r.get("DissemDT") or ""
    try:
        ts = datetime.fromisoformat(ts.split(".")[0]).isoformat()
    except ValueError:
        ts = datetime.now().isoformat(timespec="seconds")
    att = r.get("ATTACHMENTNAME")
    sub = r.get("NEWSSUB") or r.get("HEADLINE") or ""
    # NEWSSUB looks like "<COMPANY> - <scrip> - <subject>" — keep the subject part
    subject = sub.split(" - ")[-1].strip() if " - " in sub else sub
    return {
        "id": f"bse:{r.get('NEWSID')}",
        "symbol": symbol,
        "ts": ts,
        "subject": subject,
        "body": (r.get("HEADLINE") or "") + ("\n" + r["MORE"] if r.get("MORE") else ""),
        "url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else "",
        "source": "BSE",
        "extra": {"bse_category": r.get("CATEGORYNAME"), "bse_subcategory": r.get("SUBCATNAME")},
    }
