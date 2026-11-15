"""Engine tests — run offline: `pytest -q` from backend/."""
import json
import os
import tempfile

import numpy as np
import pytest

os.environ["FINN_DB"] = os.path.join(tempfile.mkdtemp(), "test.sqlite")
for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(k, None)

from finn import config  # noqa: E402
from finn.engine import classify as clf  # noqa: E402
from finn.engine import priority, tracker  # noqa: E402
from finn.engine.enrich import compare  # noqa: E402
from finn.sources.nse import headline_from_rescmp  # noqa: E402

BOILER = "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent"


@pytest.mark.parametrize("subject,body,cat,sub", [
    (BOILER, "Resignation of Mr. A as Chief Financial Officer", "management_change", "senior_exit"),
    (BOILER, "Appointment of Mr. B as Company Secretary and Compliance Officer", "management_change", "junior_entry"),
    (BOILER, "Resignation of Ms. C, Independent Director", "management_change", "independent_exit"),
    ("Outcome of Board Meeting", "Approved unaudited financial results for quarter ended Sep 30 and interim dividend", "results", "filing"),
    ("Board Meeting Intimation", "to consider results on Nov 12", "results", "intimation"),
    ("Credit Rating", "ICRA downgraded the rating to A+ (Negative)", "credit_rating", "downgrade"),
    ("Credit Rating", "CRISIL reaffirmed AA+/Stable", "credit_rating", "reaffirm"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of meeting with XYZ Fund", "investor_meetings", ""),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript of earnings conference call", "earnings_call", "transcript"),
    ("Disclosure under SEBI Takeover Regulations", "Substantial acquisition of shares", "insider_trading", "insider"),
    ("Disclosure of encumbrance of shares", "Promoter created pledge", "pledging", ""),
    ("Copy of Newspaper Publication", "", "unclassified", ""),
    ("Updates", "Company bags order worth Rs 500 crore", "press_release", "order_win"),
    ("Acquisition", "Acquisition of 100% stake in X Pvt Ltd", "M&A", ""),
])
def test_classifier(subject, body, cat, sub):
    c = clf.classify(subject, body, allow_llm=False)
    assert (c.category, c.subtype) == (cat, sub)


def test_priority_orders_judgement():
    s = lambda c, st="": priority.score(c, st)[0]  # noqa: E731
    assert s("management_change", "senior_exit") > s("management_change", "junior_entry")
    assert s("credit_rating", "downgrade") > s("credit_rating", "reaffirm")
    assert s("results", "filing") > s("results", "intimation") > s("unclassified")
    # market reaction boosts, learned prior dampens slowly
    moved, why = priority.score("press_release", "", move={"abnormal_z": -4.0, "ret_pct": -7.0})
    assert moved > s("press_release") and "stock-specific" in why
    buried = priority.score("dividend", "", feedback={"dividend": {"bury": 3}})[0]
    assert s("dividend") * 0.7 < buried < s("dividend")


def _walk(n=300, seed=3, shock=None):
    rng = np.random.default_rng(seed)
    m = np.cumprod(1 + rng.normal(0, 0.008, n)) * 20000
    r = 1.0 * np.diff(np.log(np.r_[m[0], m])) + rng.normal(0, 0.012, n)
    if shock:
        r[-1] += shock
    s = np.exp(np.cumsum(r)) * 1000
    v = rng.lognormal(13, 0.3, n)
    dates = [f"D{i:04d}" for i in range(n)]
    return [{"date": d, "close": c, "volume": x} for d, c, x in zip(dates, s, v)], dict(zip(dates, m))


def test_tracker_calibrated_and_detects_shock():
    rows, mkt = _walk()
    days = tracker.analyse(rows, mkt)
    zs = [d.abnormal_z for d in days if d.abnormal_z is not None]
    tz = [d.traj_z for d in days if d.traj_z is not None]
    assert 0.8 < np.std(zs) < 1.3 and 0.8 < np.std(tz) < 1.3
    rows, mkt = _walk(shock=-0.08)
    d = tracker.analyse(rows, mkt)[-1]
    kinds = {t["kind"] for t in tracker.triggers(d, config.thresholds())}
    assert {"price", "abnormal", "trajectory"} <= kinds
    assert d.band_lo < d.pred < d.band_hi


def test_market_move_is_not_stock_specific():
    rows, mkt = _walk()
    # make the last day a -5% market day that the stock simply follows (beta≈1)
    last = rows[-1]["date"]
    mkt[last] = mkt[rows[-2]["date"]] * 0.95
    rows[-1]["close"] = rows[-2]["close"] * 0.951
    d = tracker.analyse(rows, mkt)[-1]
    assert d.ret_pct < -4 and abs(d.abnormal_z) < 2


def test_nse_results_mapping_and_compare():
    # RELIANCE Q3FY25 standalone sample from NseIndiaApi's samples (values in Rs lakhs)
    row = {"re_to_dt": "31-DEC-2024", "re_net_sale": "12826000", "re_oth_inc_new": "321400", "re_int_new": "237100",
           "re_depr_und_exp": "445900", "re_pro_loss_bef_tax": "1159700", "re_net_profit": "872100"}
    s = headline_from_rescmp([row])
    assert s[0]["revenue"] == pytest.approx(128260.0)
    assert s[0]["ebitda"] == pytest.approx(11597 + 2371 + 4459 - 3214)
    series = [{"revenue": 110, "ebitda": 22, "pbt": 15, "pat": 11}, {"revenue": 100, "ebitda": 20, "pbt": 14, "pat": 10},
              {}, {}, {"revenue": 88, "ebitda": 15, "pbt": 10, "pat": 8}]
    c = compare(series)
    rev = c["rows"][0]
    assert rev["qoq"] == 10.0 and rev["yoy"] == 25.0 and c["ebitda_margin"] == 20.0


SCREENER_HTML = """
<html><body><h1>Acme Ltd</h1><div class="company-profile"><div class="about"><p>Makes widgets.</p></div></div>
<ul id="top-ratios"><li><span class="name">Market Cap</span><span class="number">12,345</span></li>
<li><span class="name">ROCE</span><span class="number">18.5</span></li></ul>
<section id="quarters"><table class="data-table"><thead><tr><th></th>{qh}</tr></thead><tbody>
<tr><td>Sales&nbsp;+</td>{qs}</tr><tr><td>Operating Profit</td>{qo}</tr><tr><td>Profit before tax</td>{qp}</tr>
<tr><td>Net Profit&nbsp;+</td>{qn}</tr><tr><td>Raw PDF</td>{blank}</tr></tbody></table></section>
<section id="profit-loss"><table><thead><tr><th></th>{yh}</tr></thead><tbody>
<tr><td>Sales +</td>{ys}</tr><tr><td>Operating Profit</td>{yo}</tr><tr><td>Other Income +</td>{yi}</tr>
<tr><td>Profit before tax</td>{yp}</tr><tr><td>Net Profit +</td>{yn}</tr></tbody></table></section>
<section id="balance-sheet"><table><thead><tr><th></th>{bh}</tr></thead><tbody>
<tr><td>Equity Capital</td>{be}</tr><tr><td>Reserves</td>{br}</tr><tr><td>Borrowings +</td>{bb}</tr></tbody></table></section>
<section id="cash-flow"><table><thead><tr><th></th>{bh}</tr></thead><tbody>
<tr><td>Cash from Operating Activity +</td>{cf}</tr><tr><td>Cash from Investing Activity +</td>{ci}</tr></tbody></table></section>
<section id="ratios"><table><thead><tr><th></th>{bh}</tr></thead><tbody>
<tr><td>Cash Conversion Cycle</td>{cc}</tr></tbody></table></section>
<section id="documents"><div class="documents annual-reports"><ul class="list-links">
<li><a href="https://www.bseindia.com/xml-data/corpfiling/AttachHis/ar26.pdf">Financial Year 2026 from bse</a></li>
<li><a href="https://www.bseindia.com/xml-data/corpfiling/AttachHis/ar25.pdf">Financial Year 2025 from bse</a></li></ul></div>
<div class="documents concalls"><ul class="list-links">
<li><div class="ink-600">Nov 2026</div><a class="concall-link" href="https://x/t1.pdf">Transcript</a><a href="https://x/p1.pdf">PPT</a></li>
<li><div class="ink-600">Aug 2026</div><a class="concall-link" href="https://x/t2.pdf">Transcript</a></li>
</ul></div></section></body></html>"""


def _td(xs):
    return "".join(f"<td>{x:,}</td>" if x is not None else "<td></td>" for x in xs)


def screener_html():
    q = [f"{m} {y}" for y in (2024, 2025, 2026) for m in ("Mar", "Jun", "Sep", "Dec")][2:11]
    yrs = [f"Mar {y}" for y in range(2019, 2027)] + ["TTM"]
    bh = [f"Mar {y}" for y in range(2019, 2027)]
    return SCREENER_HTML.format(
        qh="".join(f"<th>{x}</th>" for x in q), qs=_td([100 + 5 * i for i in range(9)]), qo=_td([15 + i for i in range(9)]),
        qp=_td([10 + i for i in range(9)]), qn=_td([8 + i for i in range(9)]), blank="<td></td>" * 9,
        yh="".join(f"<th>{x}</th>" for x in yrs), ys=_td([300, 330, 360, 400, 450, 500, 560, 620, 640]),
        yo=_td([45, 50, 54, 58, 63, 72, 80, 84, 86]), yi=_td([5] * 9), yp=_td([35, 40, 44, 47, 51, 60, 66, 70, 72]),
        yn=_td([26, 30, 33, 35, 38, 45, 50, 53, 54]), bh="".join(f"<th>{x}</th>" for x in bh), be=_td([10] * 8),
        br=_td([100, 120, 140, 160, 180, 210, 240, 270]), bb=_td([50, 45, 40, 60, 80, 90, 120, 150]),
        cf=_td([20, 30, 28, 25, 40, 44, 35, 30]), ci=_td([-15, -20, -25, -30, -40, -50, -60, -70]),
        cc=_td([60, 62, 65, 61, 66, 70, 82, 95]))


class FakeResp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        pass


def test_screener_parser(monkeypatch):
    from finn.sources import screener
    monkeypatch.setattr(screener.requests, "get", lambda *a, **k: FakeResp(screener_html()))
    monkeypatch.setattr(screener.time, "sleep", lambda s: None)
    d = screener.company("ACME", max_age_s=0)
    assert d["name"] == "Acme Ltd" and d["top"]["ROCE"] == 18.5
    assert d["tables"]["quarters"]["rows"]["Sales"][-1] == 140
    assert "Raw PDF" not in d["tables"]["quarters"]["rows"]
    assert [a["year"] for a in d["documents"]["annual_reports"]] == [2026, 2025]
    assert d["documents"]["concalls"][0] == {"period": "Nov 2026", "transcript": "https://x/t1.pdf", "ppt": "https://x/p1.pdf"}


def test_research_end_to_end_with_stub_model(monkeypatch):
    """Whole pull pipeline with stubbed network + model: ledger verdicts flow through,
    and a synthesis line citing a page that doesn't exist is dropped."""
    from finn.engine import research as rs
    from finn.llm import router
    from finn.sources import pdftext, screener
    monkeypatch.setattr(screener.requests, "get", lambda *a, **k: FakeResp(screener_html()))
    monkeypatch.setattr(screener.time, "sleep", lambda s: None)
    pages = {
        "https://x/t1.pdf": ["Opening remarks", "We expect margins to improve by 100 bps in FY27. Capex of 50 crore is on track."],
        "https://x/t2.pdf": ["We target revenue growth of 20% in FY26 and expect the new plant by Q2 FY27."],
        "https://www.bseindia.com/xml-data/corpfiling/AttachHis/ar26.pdf": ["Segment revenue: widgets 80%, gadgets 20%."] * 3,
    }
    monkeypatch.setattr(pdftext, "fetch_pages", lambda url, max_pages=None: {"pages": pages.get(url, []), "scanned": False})

    def fake_complete(task, system, user, **kw):
        if task == "extract_claims":
            doc = "T2" if "Aug 2026" in user else "T1"
            body = {"claims": [{"metric": "revenue_growth", "claim": "Revenue growth 20% in FY26", "target": "20%", "horizon": "FY26", "page": 1}]} \
                if doc == "T2" else {"claims": [{"metric": "margin", "claim": "Margins +100 bps in FY27", "target": "+100 bps", "horizon": "FY27", "page": 2}]}
        elif task == "judge_claims":
            body = {"verdicts": [{"id": "T2-1", "verdict": "missed", "evidence": "FY26 revenue grew 10.7%", "cites": ["NUMBERS", "T9 p.99"]},
                                 {"id": "T1-2", "verdict": "pending", "evidence": "too early", "cites": []}]}
        elif task == "synthesis":
            body = {"business": {"one_liner": "Widget maker", "segments": [{"name": "Widgets", "share": "80%", "note": "core", "cite": "AR26 p.1"}]},
                    "guidance": [], "narrative_vs_numbers": [],
                    "bull": [{"point": "ok", "cite": "NUMBERS"}], "bear": [{"point": "invented", "cite": "T1 p.40"}], "watch_next": "x"}
        else:
            body = {}
        return router.LLMResult(json.dumps(body), "stub", 10, 10, 0.0, False)

    monkeypatch.setattr(router, "complete", fake_complete)
    out = rs.research("ACME")
    led = out["ledger"]
    assert led["status"] == "ok" and led["counts"]["missed"] == 1 and led["counts"]["pending"] == 1
    t2 = next(c for c in led["claims"] if c["id"] == "T2-1")
    assert t2["cites"] == ["NUMBERS"]            # bogus "T9 p.99" stripped
    syn = out["synthesis"]
    assert len(syn["bull"]) == 1 and syn["bear"] == [] and syn["dropped_uncited"] == 1
    m = out["metrics"]
    assert any("Cash conversion cycle" in f["text"] for f in m["balance_sheet"]["flags"])
    assert out["headline_quarter"]["rows"][0]["value"] == 140


def test_no_model_degrades_gracefully(monkeypatch):
    from finn.engine import research as rs
    from finn.sources import pdftext, screener
    monkeypatch.setattr(screener.requests, "get", lambda *a, **k: FakeResp(screener_html()))
    monkeypatch.setattr(screener.time, "sleep", lambda s: None)
    monkeypatch.setattr(pdftext, "fetch_pages", lambda url, max_pages=None: {"pages": ["We expect 20% growth in FY27."], "scanned": False})
    out = rs.research("ACMEX", deep=True)  # different symbol → no cache hit; no API keys set
    assert out["ledger"]["status"] == "needs_model_key"
    assert out["synthesis"]["status"] == "needs_model_key"
    assert out["metrics"]["trajectory"]["tiles"][0]["v"] is not None
