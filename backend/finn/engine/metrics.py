"""Deterministic fundamentals: everything that is arithmetic is done here, in code, from the
company's reported numbers. Models never compute ratios — they only read and reason.

Each section returns {"tiles": [...], "series": {...}, "flags": [...]} where a flag is a
plain-English observation with a tone (good / watch / bad). These flags are the "numbers"
half of narrative-vs-numbers.
"""
from __future__ import annotations

import math

from ..sources.screener import row


def _clean(xs):
    return [x for x in xs if x is not None]


def cagr(series: list[float | None], years: int) -> float | None:
    s = [x for x in series if x is not None]
    if len(s) <= years:
        return None
    a, b = s[-1 - years], s[-1]
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return round(100 * ((b / a) ** (1 / years) - 1), 1)


def _annual(tbl: dict, *labels):
    """Annual columns only (drop TTM / half-year), ascending."""
    vals = row(tbl, *labels)
    keep = [(p, v) for p, v in zip(tbl["periods"], vals) if p.startswith("Mar")]
    return [p for p, _ in keep], [v for _, v in keep]


def _ttm(tbl: dict, *labels):
    vals = row(tbl, *labels)
    for p, v in zip(tbl["periods"], vals):
        if p.upper() == "TTM":
            return v
    return None


def flag(text: str, tone: str) -> dict:
    return {"text": text, "tone": tone}


def compute(data: dict) -> dict:
    t = data["tables"]
    pl, bs, cf, ra, q = t["profit-loss"], t["balance-sheet"], t["cash-flow"], t["ratios"], t["quarters"]
    bank = data.get("is_bank", False)
    out: dict = {"is_bank": bank, "basis": "consolidated" if data.get("consolidated") else "standalone"}

    # ---------- financial snapshot
    top = data.get("top", {})
    yrs, rev = _annual(pl, "Sales", "Revenue")
    _, op = _annual(pl, "Operating Profit", "Financing Profit")
    _, pat = _annual(pl, "Net Profit")
    _, oi = _annual(pl, "Other Income")
    _, pbt = _annual(pl, "Profit before tax")
    opm = [round(100 * o / r, 1) if o is not None and r else None for o, r in zip(op, rev)]
    out["snapshot"] = {"tiles": [
        {"k": "Revenue (TTM)", "v": _ttm(pl, "Sales", "Revenue") or (rev[-1] if rev else None), "unit": "₹ cr"},
        {"k": "EBITDA margin", "v": opm[-1] if opm else None, "unit": "%"},
        {"k": "PAT (TTM)", "v": _ttm(pl, "Net Profit") or (pat[-1] if pat else None), "unit": "₹ cr"},
        {"k": "ROCE", "v": top.get("ROCE"), "unit": "%"},
        {"k": "ROE", "v": top.get("ROE"), "unit": "%"},
        {"k": "Market cap", "v": top.get("Market Cap"), "unit": "₹ cr"},
        {"k": "P/E", "v": top.get("Stock P/E"), "unit": "×"},
    ]}

    # ---------- trajectory
    fl = []
    r3, r5, p3, p5 = cagr(rev, 3), cagr(rev, 5), cagr(pat, 3), cagr(pat, 5)
    if r3 is not None and r5 is not None:
        fl.append(flag(f"Revenue CAGR {r3}% (3y) vs {r5}% (5y) — growth is "
                       f"{'accelerating' if r3 > r5 + 1 else 'slowing' if r3 < r5 - 1 else 'steady'}",
                       "good" if r3 >= r5 - 1 else "watch"))
    if p3 is not None and r3 is not None:
        fl.append(flag(f"Profit CAGR {p3}% (3y) {'outpacing' if p3 > r3 else 'lagging'} revenue — "
                       f"{'operating leverage' if p3 > r3 else 'margins absorbing the growth'}",
                       "good" if p3 >= r3 else "watch"))
    om = _clean(opm)
    if len(om) >= 4:
        d = round(100 * (om[-1] - sum(om[-4:-1]) / 3))
        fl.append(flag(f"EBITDA margin {om[-1]}% vs {round(sum(om[-4:-1]) / 3, 1)}% 3-yr avg "
                       f"({'+' if d >= 0 else ''}{d} bps) — {'expanding' if d > 50 else 'compressing' if d < -50 else 'stable'}",
                       "good" if d > 50 else "bad" if d < -150 else "watch" if d < -50 else "good"))
    if pbt and oi and pbt[-1] and oi[-1] is not None and pbt[-1] > 0 and oi[-1] / pbt[-1] > 0.25:
        fl.append(flag(f"Other income is {round(100 * oi[-1] / pbt[-1])}% of PBT — core earnings are thinner than PAT suggests", "watch"))
    # quarterly YoY
    qrev, qop, qpat = row(q, "Sales", "Revenue"), row(q, "Operating Profit", "Financing Profit"), row(q, "Net Profit")
    qyoy = [(round(100 * (qrev[i] / qrev[i - 4] - 1), 1) if i >= 4 and qrev[i] and qrev[i - 4] else None)
            for i in range(len(qrev))]
    out["trajectory"] = {
        "tiles": [{"k": "Revenue CAGR 3y", "v": r3, "unit": "%"}, {"k": "Revenue CAGR 5y", "v": r5, "unit": "%"},
                  {"k": "PAT CAGR 3y", "v": p3, "unit": "%"}, {"k": "PAT CAGR 5y", "v": p5, "unit": "%"}],
        "series": {"years": yrs, "revenue": rev, "pat": pat, "opm": opm,
                   "quarters": q["periods"], "q_revenue": qrev, "q_pat": qpat,
                   "q_opm": [round(100 * o / r, 1) if o is not None and r else None for o, r in zip(qop, qrev)],
                   "q_rev_yoy": qyoy},
        "flags": fl,
    }

    # ---------- balance sheet
    bsy = bs["periods"]
    borrow, eq, res = row(bs, "Borrowings", "Borrowing"), row(bs, "Equity Capital"), row(bs, "Reserves")
    equity = [(e or 0) + (r or 0) if (e is not None or r is not None) else None for e, r in zip(eq, res)]
    de = [round(b / e, 2) if b is not None and e else None for b, e in zip(borrow, equity)]
    ccc, dd, invd, dp = row(ra, "Cash Conversion Cycle"), row(ra, "Debtor Days"), row(ra, "Inventory Days"), row(ra, "Days Payable")
    wcd = row(ra, "Working Capital Days")
    fl = []
    if not bank and _clean(de):
        d_last = _clean(de)[-1]
        fl.append(flag(f"Debt/equity {d_last}× — {'net-cash-like' if d_last < 0.1 else 'comfortable' if d_last < 0.5 else 'elevated' if d_last < 1.5 else 'high'}",
                       "good" if d_last < 0.5 else "watch" if d_last < 1.5 else "bad"))
        cd = _clean(de)
        if len(cd) >= 4 and cd[-1] - cd[-4] > 0.25:
            fl.append(flag(f"Leverage rising: D/E {cd[-4]}× → {cd[-1]}× over 3 years", "watch"))
    if bank:
        fl.append(flag("Lender: D/E and working-capital cycle are not meaningful — judge on asset quality and NIMs", "watch"))
    c = _clean(ccc) or _clean(wcd)
    if len(c) >= 4:
        delta = round(c[-1] - c[-4])
        fl.append(flag(f"{'Cash conversion cycle' if _clean(ccc) else 'Working-capital days'} {round(c[-1])} days "
                       f"({'+' if delta >= 0 else ''}{delta} vs 3 yrs ago) — "
                       f"{'lengthening, cash is getting stuck' if delta > 10 else 'tightening' if delta < -10 else 'stable'}",
                       "bad" if delta > 25 else "watch" if delta > 10 else "good"))
    out["balance_sheet"] = {
        "tiles": [{"k": "Borrowings", "v": _clean(borrow)[-1] if _clean(borrow) else None, "unit": "₹ cr"},
                  {"k": "Net worth", "v": _clean(equity)[-1] if _clean(equity) else None, "unit": "₹ cr"},
                  {"k": "Debt / equity", "v": _clean(de)[-1] if _clean(de) and not bank else None, "unit": "×"},
                  {"k": "Cash conv. cycle", "v": c[-1] if c else None, "unit": "days"}],
        "series": {"periods": bsy, "borrowings": borrow, "equity": equity, "de": de,
                   "ratio_periods": ra["periods"], "debtor_days": dd, "inventory_days": invd,
                   "payable_days": dp, "ccc": ccc or wcd},
        "flags": fl,
    }

    # ---------- cash quality
    cyrs, cfo = _annual(cf, "Cash from Operating Activity")
    _, cfi = _annual(cf, "Cash from Investing Activity")
    _, fcf_row = _annual(cf, "Free Cash Flow")
    fcf = fcf_row if _clean(fcf_row) else [(a + b) if a is not None and b is not None else None for a, b in zip(cfo, cfi)]
    pat_by_year = dict(zip(yrs, pat))
    conv = [round(c_ / pat_by_year[y], 2) if c_ is not None and pat_by_year.get(y) else None for y, c_ in zip(cyrs, cfo)]
    fl = []
    k = min(5, len(_clean(cfo)))
    if k >= 3:
        sc = sum(_clean(cfo)[-k:])
        sp = sum(x for y, x in pat_by_year.items() if y in cyrs[-k:] and x is not None)
        if sp > 0:
            ratio = round(sc / sp, 2)
            fl.append(flag(f"Over {k} years, operating cash was {ratio}× reported profit — "
                           f"{'profits are turning into cash' if ratio >= 0.9 else 'some profit is not showing up as cash' if ratio >= 0.6 else 'profits are NOT turning into cash'}",
                           "good" if ratio >= 0.9 else "watch" if ratio >= 0.6 else "bad"))
    neg = sum(1 for x in _clean(fcf)[-5:] if x < 0)
    if neg >= 2 and not bank:
        fl.append(flag(f"Free cash flow negative in {neg} of last 5 years — growth is being funded, not self-financed", "watch"))
    out["cash_quality"] = {
        "tiles": [{"k": "CFO (last FY)", "v": _clean(cfo)[-1] if _clean(cfo) else None, "unit": "₹ cr"},
                  {"k": "FCF (last FY)", "v": _clean(fcf)[-1] if _clean(fcf) else None, "unit": "₹ cr"},
                  {"k": "CFO / PAT", "v": _clean(conv)[-1] if _clean(conv) else None, "unit": "×"}],
        "series": {"years": cyrs, "cfo": cfo, "fcf": fcf, "pat": [pat_by_year.get(y) for y in cyrs], "conversion": conv},
        "flags": fl,
        "note": "FCF = screener's Free Cash Flow row, else CFO + CFI (a conservative proxy)." if not _clean(fcf_row) else "",
    }
    return out


def fmt(v, unit=""):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if unit == "₹ cr":
        return f"₹{v:,.0f} cr"
    return f"{v:g}{unit}"
