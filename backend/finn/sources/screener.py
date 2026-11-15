"""screener.in company page → standardised financial tables + primary-document links.

We use screener only as (a) a tidy copy of the company's *reported* numbers and (b) an index
of primary documents (annual reports, concall transcripts hosted on BSE / company IR).
Its Pros/Cons/"AI summary" content is secondary commentary and is deliberately ignored.

Parsing is keyed on row labels, not positions, and section lookup falls back from the
element id to the heading text, so small layout changes don't break us.
"""
from __future__ import annotations

import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from .. import config, db

log = logging.getLogger(__name__)
BASE = "https://www.screener.in/company"
SECTIONS = {
    "quarters": "Quarterly Results", "profit-loss": "Profit & Loss", "balance-sheet": "Balance Sheet",
    "cash-flow": "Cash Flows", "ratios": "Ratios", "shareholding": "Shareholding Pattern",
}


def _num(s: str) -> float | None:
    s = s.replace(",", "").replace("%", "").replace("₹", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _label(s: str) -> str:
    return re.sub(r"\s*\+\s*$", "", s.replace("\xa0", " ")).strip()


def _section(soup: BeautifulSoup, sid: str, heading: str):
    sec = soup.find("section", id=sid)
    if sec is None:
        h = soup.find(lambda t: t.name in ("h2", "h3") and heading.lower() in t.get_text(" ").lower())
        sec = h.find_parent("section") if h else None
    return sec


def _table(sec) -> dict:
    if sec is None:
        return {"periods": [], "rows": {}}
    tbl = sec.find("table")
    if tbl is None:
        return {"periods": [], "rows": {}}
    head = [th.get_text(" ", strip=True) for th in tbl.find("thead").find_all("th")][1:] if tbl.find("thead") else []
    rows = {}
    for tr in tbl.find("tbody").find_all("tr") if tbl.find("tbody") else []:
        tds = tr.find_all("td")
        if not tds:
            continue
        lab = _label(tds[0].get_text(" ", strip=True))
        if not lab or lab.lower().startswith("raw pdf"):
            continue
        rows[lab] = [_num(td.get_text(" ", strip=True)) for td in tds[1:]]
    return {"periods": head, "rows": rows}


def _docs(soup: BeautifulSoup) -> dict:
    sec = _section(soup, "documents", "Documents")
    out = {"annual_reports": [], "concalls": []}
    if sec is None:
        return out
    ar_box = sec.find(class_=re.compile("annual-reports")) or sec
    for a in ar_box.select("a[href]"):
        txt = a.get_text(" ", strip=True)
        m = re.search(r"(?:Financial Year|FY)\s*(\d{4})", txt)
        if m:
            out["annual_reports"].append({"year": int(m.group(1)), "url": a["href"], "label": txt})
    cc_box = sec.find(class_=re.compile("concalls"))
    if cc_box is not None:
        for li in cc_box.find_all("li"):
            date_el = li.find(class_=re.compile("ink-600|nowrap")) or li
            m = re.search(r"([A-Z][a-z]{2})\s+(\d{4})", date_el.get_text(" ", strip=True))
            item = {"period": f"{m.group(1)} {m.group(2)}" if m else None}
            for a in li.find_all("a", href=True):
                t = a.get_text(" ", strip=True).lower()
                if "transcript" in t:
                    item["transcript"] = a["href"]
                elif t == "ppt":
                    item["ppt"] = a["href"]
            if item.get("transcript"):
                out["concalls"].append(item)
    out["annual_reports"].sort(key=lambda d: d["year"], reverse=True)
    return out


def _top(soup: BeautifulSoup) -> dict:
    out = {}
    for li in soup.select("#top-ratios li"):
        n, v = li.find(class_="name"), li.find(class_="number")
        if n and v:
            out[n.get_text(strip=True)] = _num(v.get_text(strip=True))
    return out


def company(symbol: str, consolidated: bool = True, max_age_s: float = 12 * 3600) -> dict:
    """Fetch + parse. Falls back to standalone if consolidated isn't published."""
    symbol = symbol.upper().strip()
    key = f"screener:{symbol}:{consolidated}"
    if (hit := db.cache_get(key, max_age_s)) is not None:
        return hit
    url = f"{BASE}/{symbol}/{'consolidated/' if consolidated else ''}"
    r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=30)
    if r.status_code == 404:
        raise LookupError(f"{symbol}: no screener.in page — is it an NSE symbol?")
    r.raise_for_status()
    time.sleep(1.5)  # polite
    soup = BeautifulSoup(r.text, "lxml")
    data = {
        "symbol": symbol,
        "name": (soup.find("h1").get_text(strip=True) if soup.find("h1") else symbol),
        "url": url,
        "consolidated": consolidated,
        "about": (soup.select_one(".company-profile .about p") or soup.select_one(".about p") or soup.new_tag("p")).get_text(" ", strip=True),
        "top": _top(soup),
        "tables": {sid: _table(_section(soup, sid, h)) for sid, h in SECTIONS.items()},
        "documents": _docs(soup),
    }
    q = data["tables"]["quarters"]
    if consolidated and not any(v for row in q["rows"].values() for v in row if v):
        return company(symbol, consolidated=False, max_age_s=max_age_s)
    data["is_bank"] = any(k in q["rows"] for k in ("Financing Profit", "Revenue")) and "Sales" not in q["rows"]
    db.cache_put(key, data)
    return data


def row(table: dict, *labels: str) -> list[float | None]:
    for lab in labels:
        if lab in table["rows"]:
            return table["rows"][lab]
    return [None] * len(table["periods"])


def quarterly_headlines(data: dict) -> list[dict]:
    """Headline numbers from screener's quarterly table, newest first (₹ crore).
    Screener's 'Operating Profit' = Sales − Expenses, i.e. EBITDA excluding other income."""
    q = data["tables"]["quarters"]
    rev = row(q, "Sales", "Revenue")
    ebitda = row(q, "Operating Profit", "Financing Profit")
    pbt, pat = row(q, "Profit before tax"), row(q, "Net Profit")
    out = [{"period": p, "revenue": rev[i], "ebitda": ebitda[i], "pbt": pbt[i], "pat": pat[i],
            "source": "screener.in quarterly table (as reported)"} for i, p in enumerate(q["periods"])]
    return list(reversed(out))
