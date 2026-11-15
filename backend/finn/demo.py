"""Synthetic demo dataset — FICTIONAL companies, generated numbers.

Why fictional: the app must be demoable without network access, but fabricated filings
attributed to real listed companies would be misleading. So the demo uses invented names
(Konkan Cables, Deccan Bank, …) and the UI shows a 'synthetic data' banner whenever
meta.synthetic is true. Real data: `python -m finn run && python -m finn export`.

The demo still runs the REAL engine end-to-end: classifier, scorer, Kalman tracker, market
model, alert fusion and fundamentals maths all operate on this data.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import numpy as np

from . import config

HOLDINGS = [
    {"symbol": "KONKAN", "name": "Konkan Cables", "sector": "Cables & Wires", "size": "mid", "beta": 1.1},
    {"symbol": "DECCANBK", "name": "Deccan Bank", "sector": "Banks", "size": "large", "beta": 1.0},
    {"symbol": "SAHYADRI", "name": "Sahyadri Electronics", "sector": "EMS", "size": "small", "beta": 1.4},
    {"symbol": "VAYU", "name": "Vayu Aerospace", "sector": "Defence", "size": "mid", "beta": 1.6},
    {"symbol": "MERIDIAN", "name": "Meridian Infotech", "sector": "IT Services", "size": "large", "beta": 0.8},
    {"symbol": "NILGIRI", "name": "Nilgiri Foods", "sector": "FMCG", "size": "large", "beta": 0.6},
    {"symbol": "TAPTI", "name": "Tapti Chemicals", "sector": "Chemicals", "size": "small", "beta": 1.2},
    {"symbol": "ARAVALI", "name": "Aravali Cement", "sector": "Cement", "size": "mid", "beta": 1.1},
    {"symbol": "INDUSFIN", "name": "Indus Finserv", "sector": "NBFC", "size": "mid", "beta": 1.3},
    {"symbol": "KAVERI", "name": "Kaveri Power", "sector": "Utilities", "size": "large", "beta": 0.7},
    {"symbol": "GANGES", "name": "Ganges Motors", "sector": "Auto", "size": "large", "beta": 1.0},
    {"symbol": "LOTUS", "name": "Lotus Retail", "sector": "Retail", "size": "mid", "beta": 1.2},
    {"symbol": "BRAHMA", "name": "Brahma Telecom", "sector": "Telecom", "size": "large", "beta": 0.9},
    {"symbol": "PALASH", "name": "Palash Paints", "sector": "Paints", "size": "mid", "beta": 0.9},
    {"symbol": "SUTLEJ", "name": "Sutlej Pharma", "sector": "Pharma", "size": "mid", "beta": 0.7},
    {"symbol": "THAR", "name": "Thar Renewables", "sector": "Renewables", "size": "small", "beta": 1.5},
]
N = 320


def _sessions(n: int) -> list[str]:
    d, out = datetime.now().date(), []
    if datetime.now().hour < 16:
        d -= timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def _prices(rng) -> tuple[list[str], dict]:
    dates = _sessions(N)
    m = rng.normal(0.0004, 0.009, N)
    m[-3] = -0.028  # a market-wide sell-off 2 sessions ago
    market = 24000 * np.exp(np.cumsum(m))
    out = {"^NSEI": (market, rng.lognormal(19, 0.15, N))}
    events = {  # symbol: (session offset from end, idiosyncratic shock, volume multiple)
        "SAHYADRI": (-1, -0.092, 3.4),   # unexplained: no filing
        "KONKAN": (-1, +0.058, 2.6),     # explained by results
        "TAPTI": (-1, +0.004, 2.9),      # volume-only, pledge filing
        "ARAVALI": (-2, -0.045, 2.1),    # rating downgrade
        "THAR": (-4, +0.07, 2.4),        # older, explained by order win
    }
    for h in HOLDINGS:
        idio = rng.normal(0, 0.012 + 0.006 * (h["size"] == "small"), N)
        r = h["beta"] * m + idio
        vol = rng.lognormal(13 + rng.random(), 0.28, N)
        if h["symbol"] in events:
            off, shock, vm = events[h["symbol"]]
            r[off] = h["beta"] * m[off] + shock
            vol[off] = np.median(vol[off - 21:off]) * vm
        px = (200 + 3000 * rng.random()) * np.exp(np.cumsum(r))
        out[h["symbol"]] = (px, vol)
    return dates, out


def _filings(now: datetime, dates: list[str]) -> list[dict]:
    def at(hours_ago) -> str:
        if isinstance(hours_ago, str):  # tie to a trading session: 'S-1@18:30' = evening of last session
            off, hm = hours_ago[1:].split('@')
            return f"{dates[int(off)]}T{hm}:00"
        return (now - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    F = []

    def add(sym, h, subject, body="", **extra):
        F.append({"id": f"demo:{len(F)}", "symbol": sym, "ts": at(h), "subject": subject, "body": body,
                  "url": "", "source": "DEMO", "extra": {"synthetic": True, **extra}})
    add("KONKAN", "S-2@18:40", "Outcome of Board Meeting", "Board approved unaudited financial results (consolidated) for the quarter ended September 30, 2026 and declared interim dividend of Rs 7 per share.")
    add("KONKAN", "S-2@19:05", "Investor Presentation", "Investor presentation on Q2 FY27 results")
    add("DECCANBK", 30, "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent",
        "Resignation of Mr. Vikram Sethi as Chief Financial Officer, effective close of business on December 31, 2026, to pursue opportunities outside the bank.")
    add("DECCANBK", 29, "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent",
        "Appointment of Ms. Ananya Rao as Chief Financial Officer with effect from January 1, 2027.")
    add("ARAVALI", "S-3@17:30", "Credit Rating", "ICRA has downgraded the long-term rating of the company's bank facilities to [ICRA]A+ (Negative) from [ICRA]AA- (Stable).")
    add("INDUSFIN", 8, "Outcome of Board Meeting", "Board approved raising of funds up to Rs 2,000 crore by way of Qualified Institutions Placement (QIP).")
    add("NILGIRI", 52, "Acquisition", "Company to acquire 100% stake in Malabar Spices Pvt Ltd for an enterprise value of Rs 640 crore, funded through internal accruals.")
    add("TAPTI", "S-1@09:10", "Disclosure of encumbrance of shares", "Promoter group entity created pledge on 4.2% of equity shares; total promoter pledge rises to 18.6%.")
    add("THAR", "S-4@08:55", "Updates", "Company bags order worth Rs 1,180 crore for 450 MW solar EPC from a central PSU; executable over 18 months.")
    add("BRAHMA", 70, "Updates", "Receipt of demand order of Rs 312 crore from GST authorities for FY2019-20; company believes it has a strong case on merits and will appeal.")
    add("KAVERI", 60, "Outcome of Board Meeting", "Board approved capex of Rs 4,500 crore for a 660 MW brownfield capacity expansion at the Raichur unit; COD targeted FY30.")
    add("MERIDIAN", 40, "Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript of the earnings conference call held on November 6, 2026.")
    add("LOTUS", 34, "Record Date", "Record date for interim dividend of Rs 3.5 per share fixed as November 21, 2026.")
    add("GANGES", 12, "Board Meeting Intimation", "Meeting of the Board of Directors on November 19, 2026 to consider unaudited results for quarter ended September 30, 2026.")
    add("SUTLEJ", 90, "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent",
        "Appointment of Mr. Rohit Jain as Company Secretary and Compliance Officer.")
    add("PALASH", 44, "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent",
        "Resignation of Ms. Leela Menon, Independent Director, citing pre-occupation; she confirmed there are no other material reasons.")
    routine = [
        ("Copy of Newspaper Publication", "Newspaper publication of financial results"),
        ("Trading Window", "Closure of trading window"),
        ("Certificate under SEBI (Depositories and Participants) Regulations, 2018", "Certificate under Reg 74(5)"),
        ("Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of meeting with institutional investors"),
        ("Allotment of Securities", "Allotment of equity shares under ESOP scheme 2021"),
        ("Shareholders meeting", "Notice of postal ballot and e-voting"),
        ("Loss of Share Certificates", "Intimation of loss of share certificates"),
        ("Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of analyst meet at investor conference"),
        ("Statement of Investor Complaints", "Statement of investor complaints for the quarter"),
        ("Business Responsibility and Sustainability Report", "BRSR for FY 2025-26"),
    ]
    syms = [h["symbol"] for h in HOLDINGS]
    rng = np.random.default_rng(7)
    for i in range(32):
        s, b = routine[i % len(routine)]
        add(syms[rng.integers(len(syms))], float(rng.uniform(1, 160)), s, b)
    return F


def _enrich(f: dict) -> None:
    """Hand-written synthetic enrichment (what the LLM/NSE steps would attach)."""
    s, e = f["symbol"], f["extra"]
    if s == "KONKAN" and f["category"] == "results" and f["subtype"] == "filing":
        from .engine.enrich import compare
        e["results"] = compare([
            {"period_end": "2026-09-30", "revenue": 6120.4, "ebitda": 856.9, "pbt": 744.1, "pat": 556.3, "source": "SYNTHETIC"},
            {"period_end": "2026-06-30", "revenue": 5480.2, "ebitda": 712.4, "pbt": 615.0, "pat": 459.8},
            {}, {},
            {"period_end": "2025-09-30", "revenue": 4985.7, "ebitda": 618.2, "pbt": 528.9, "pat": 394.0},
        ])
        f["summary"] = "Q2 revenue +22.8% YoY with EBITDA margin up ~160 bps to 14.0%; interim dividend ₹7."
    if s == "DECCANBK" and "Appointment" in f["body"]:
        e["people"] = [{"name": "Ananya Rao", "role": "Chief Financial Officer", "action": "appointed",
                        "effective": "2027-01-01",
                        "profile": "Chartered accountant with 22 years in banking finance; currently Deputy CFO (fictional).",
                        "background": "Fictional demo person: Deputy CFO at Deccan Bank since 2021; earlier treasury and "
                                      "ALM roles at a large private bank. CA, IIM-A. [1][2]",
                        "sources": [{"title": "Ananya Rao — LinkedIn (demo placeholder)", "url": "", "snippet": "Deputy CFO"}]}]
    if s == "DECCANBK" and "Resignation" in f["body"]:
        e["people"] = [{"name": "Vikram Sethi", "role": "Chief Financial Officer", "action": "resigned",
                        "effective": "2026-12-31", "reason": "to pursue opportunities outside the bank"}]
        f["summary"] = "CFO Vikram Sethi resigns effective 31 Dec; Deputy CFO Ananya Rao steps up 1 Jan — orderly internal succession."
    if not f.get("summary") and f["score"] >= 40:
        f["summary"] = f["body"][:200]


def _research_konkan() -> dict:
    """Synthetic screener-shaped tables → REAL metrics.compute."""
    from .engine import metrics
    years = [f"Mar {y}" for y in range(2019, 2027)] + ["TTM"]
    sales = [7900, 8830, 8790, 12200, 14100, 18040, 21000, 23640, 25330]
    opm = [0.12, 0.13, 0.135, 0.12, 0.125, 0.132, 0.136, 0.131, 0.135]
    op = [round(s * o) for s, o in zip(sales, opm)]
    oi = [90, 110, 160, 180, 210, 280, 330, 360, 380]
    dep = [160, 170, 180, 200, 210, 230, 260, 300, 310]
    intr = [40, 45, 40, 35, 30, 45, 60, 85, 90]
    pbt = [o + i - d - n for o, i, d, n in zip(op, oi, dep, intr)]
    pat = [round(p * 0.75) for p in pbt]
    qp = ["Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]
    qs = [4980, 5230, 6930, 4870, 4986, 5560, 7120, 5480, 6120]
    qo = [600, 680, 990, 610, 618, 700, 940, 712, 857]
    qpbt = [520, 560, 860, 500, 529, 600, 840, 615, 744]
    data = {
        "symbol": "KONKAN", "name": "Konkan Cables (SYNTHETIC)", "url": "", "consolidated": True, "is_bank": False,
        "top": {"Market Cap": 98000, "Stock P/E": 46.2, "ROCE": 29.4, "ROE": 22.1},
        "tables": {
            "profit-loss": {"periods": years, "rows": {"Sales": sales, "Operating Profit": op, "Other Income": oi,
                                                        "Depreciation": dep, "Interest": intr, "Profit before tax": pbt, "Net Profit": pat}},
            "quarters": {"periods": qp, "rows": {"Sales": qs, "Operating Profit": qo, "Profit before tax": qpbt,
                                                  "Net Profit": [round(x * 0.75) for x in qpbt]}},
            "balance-sheet": {"periods": years[:-1] + ["Sep 2026"], "rows": {
                "Equity Capital": [75] * 9, "Reserves": [4300, 5100, 5900, 6900, 8000, 9500, 11300, 13200, 14100],
                "Borrowings": [420, 380, 300, 290, 260, 450, 680, 1020, 1240]}},
            "cash-flow": {"periods": years[:-1], "rows": {
                "Cash from Operating Activity": [620, 1180, 690, 410, 1520, 1630, 1150, 1240],
                "Cash from Investing Activity": [-400, -500, -520, -610, -900, -1400, -1800, -2100]}},
            "ratios": {"periods": years[:-1], "rows": {
                "Debtor Days": [48, 45, 44, 40, 38, 36, 41, 47], "Inventory Days": [110, 105, 112, 118, 108, 100, 112, 121],
                "Days Payable": [62, 60, 58, 55, 56, 54, 52, 50], "Cash Conversion Cycle": [96, 90, 98, 103, 90, 82, 101, 118]}},
        },
    }
    from .engine.enrich import compare
    from .sources.screener import quarterly_headlines
    m = metrics.compute(data)
    claims = [
        ("T4", "Concall Nov 2025", "revenue_growth", "FY26 revenue growth of 20%+ on cables volume", "20%+", "FY26", "partial",
         "FY26 revenue grew 12.6% (₹21,000→₹23,640 cr); volume commentary in T2 blames copper-price pass-through.", ["NUMBERS"]),
        ("T4", "Concall Nov 2025", "margin", "EBITDA margin to be sustained at 13–14%", "13–14%", "FY26", "kept",
         "FY26 EBITDA margin 13.1% — inside the band.", ["NUMBERS"]),
        ("T3", "Concall Feb 2026", "capex", "₹1,000 cr capex for new copper rod plant, commissioning by Q2 FY27", "₹1,000 cr; Q2 FY27", "Q2 FY27", "missed",
         "T1 says commissioning moved to Q4 FY27 after equipment delays; borrowings up ₹560 cr meanwhile.", ["T1 p.6", "NUMBERS"]),
        ("T3", "Concall Feb 2026", "other", "Working capital to normalise below 90 days", "<90 days", "FY26", "missed",
         "Cash conversion cycle lengthened to 118 days (from 101).", ["NUMBERS"]),
        ("T2", "Concall May 2026", "revenue_growth", "Mid-to-high teens growth in FY27", "15–19%", "FY27", "pending",
         "H1 FY27 revenue +17.8% YoY — on track so far.", ["NUMBERS"]),
        ("T1", "Concall Nov 2026", "margin", "Margins to expand 50–100 bps as wires mix improves", "+50–100 bps", "FY28", "pending",
         "Too early.", []),
    ]
    ledger_claims = [{"id": f"{d}-{i+1}", "doc": d, "call": c, "metric": met, "claim": cl, "target": tg, "horizon": hz,
                      "verdict": v, "evidence": ev, "cites": ct, "quote": "(synthetic)", "page": 5, "source_ok": True}
                     for i, (d, c, met, cl, tg, hz, v, ev, ct) in enumerate(claims)]
    return {
        "symbol": "KONKAN", "name": "Konkan Cables (SYNTHETIC)", "screener_url": "", "metrics": m, "synthetic": True,
        "headline_quarter": compare(quarterly_headlines(data)),
        "sources": [{"id": "T1", "label": "Concall Nov 2026 (synthetic)", "url": "", "pages": 22},
                    {"id": "T2", "label": "Concall May 2026 (synthetic)", "url": "", "pages": 19},
                    {"id": "T3", "label": "Concall Feb 2026 (synthetic)", "url": "", "pages": 21},
                    {"id": "T4", "label": "Concall Nov 2025 (synthetic)", "url": "", "pages": 20},
                    {"id": "AR26", "label": "Annual Report FY2026 (synthetic)", "url": "", "pages": 284}],
        "ledger": {"status": "ok", "claims": ledger_claims, "score": 33,
                   "counts": {"kept": 1, "partial": 1, "missed": 2, "pending": 2, "unclear": 0}},
        "synthesis": {
            "status": "ok",
            "business": {"one_liner": "Wires & cables maker (fictional) with a small but fast-growing consumer-electricals arm.",
                         "segments": [{"name": "Wires & cables", "share": "86%", "note": "Infra + real-estate driven; copper pass-through", "cite": "AR26 p.34"},
                                      {"name": "Consumer electricals", "share": "11%", "note": "Fans, lights; still loss-making", "cite": "AR26 p.36"},
                                      {"name": "EPC", "share": "3%", "note": "Being de-emphasised", "cite": "AR26 p.37"}]},
            "guidance": [{"metric": "Revenue", "what": "Mid-to-high-teens growth in FY27", "cite": "T2 p.4"},
                         {"metric": "Margin", "what": "+50–100 bps expansion by FY28 via wires mix", "cite": "T1 p.5"},
                         {"metric": "Capex", "what": "₹1,000 cr rod plant, now Q4 FY27", "cite": "T1 p.6"}],
            "narrative_vs_numbers": [
                {"says": "Working capital discipline is a priority", "numbers": "CCC up 17 days to 118 in FY26", "verdict": "diverge", "cite": "T3 p.8"},
                {"says": "Growth is volume-led, not price-led", "numbers": "Revenue +12.6% FY26 vs 20% guided", "verdict": "diverge", "cite": "T2 p.3"},
                {"says": "Margins resilient through copper volatility", "numbers": "EBITDA margin 13.1–13.6% for 3 yrs", "verdict": "agree", "cite": "T1 p.4"}],
            "bull": [{"point": "Margins have held 13–14% for three years despite commodity swings", "cite": "NUMBERS"},
                     {"point": "Q2 FY27 shows re-acceleration: revenue +22.8% YoY, margin +160 bps", "cite": "NUMBERS"},
                     {"point": "Balance sheet still light: D/E under 0.1× even after capex", "cite": "NUMBERS"}],
            "bear": [{"point": "Cash conversion slipping: CCC 118 days, inventory days at a 7-yr high", "cite": "NUMBERS"},
                     {"point": "Capex timeline already slipped two quarters; borrowings doubled in two years", "cite": "T1 p.6"},
                     {"point": "Management hit 1 of 4 matured promises — discount new guidance", "cite": "NUMBERS"}],
            "watch_next": "Q3 inventory days and whether the rod plant commissioning date holds at Q4 FY27.",
            "dropped_uncited": 0,
        },
        "cost_usd": 0.0,
    }


def build() -> None:
    os.environ.setdefault("FINN_DB", str(config.DATA_DIR / "demo.sqlite"))
    config.DB_PATH = config.Path(os.environ["FINN_DB"])
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    from . import db, export, pipeline
    from .engine import tracker

    rng = np.random.default_rng(42)
    dates, series = _prices(rng)
    for sym, (px, vol) in series.items():
        db.upsert_prices([(sym, d, float(p), float(p), float(p), float(p), float(v)) for d, p, v in zip(dates, px, vol)])
    db.cache_put("meta:synthetic", True)
    db.cache_put("meta:holdings", [{k: v for k, v in h.items() if k != "beta"} for h in HOLDINGS])
    db.cache_put("meta:research_demo", ["KONKAN"])

    market = {r["date"]: r["close"] for r in db.price_series("^NSEI")}
    sigs = {h["symbol"]: tracker.analyse(db.price_series(h["symbol"]), market) for h in HOLDINGS}
    filings = _filings(datetime.now(), dates)
    pipeline.process(filings, sigs, enrich_budget=0)  # real classifier + scorer
    for f in db.announcements():
        _enrich(f)
        db.upsert_announcement(f)
    db.cache_put("export:research:KONKAN", _research_konkan())
    out = export.write_static(research_symbols=["KONKAN"])
    alerts = pipeline.build_alerts(sigs)
    print(f"demo snapshot → {out}")
    for a in alerts[:8]:
        print(f"  {a['severity']:>3} {a['symbol']:<9} {a['headline']:<20} " + "; ".join(t["text"] for t in a["triggers"])[:110])
