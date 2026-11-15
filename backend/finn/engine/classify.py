"""Rules-first filing classifier.

Exchange subjects are formulaic ("Change in Directors/ Key Managerial Personnel/ ...",
"Analysts/Institutional Investor Meet/Con. Call Updates"), so ordered regexes over
subject + body classify ~90% of filings for free. Only genuinely ambiguous ones
("Updates", "General", empty subjects) go to the cheap model — and even then the
result is cached by content hash.

Besides the category we pull a *subtype* that matters for priority:
CFO resignation ≠ company-secretary appointment; rating downgrade ≠ reaffirmation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..llm import router

CATEGORIES = [
    "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
    "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
    "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified",
]

# Order matters: first match wins. (pattern, category)
RULES: list[tuple[str, str]] = [
    (r"pledg|encumbr|invocation of", "pledging"),
    (r"credit rating|rating (agency|action)|\bcrisil\b|\bicra\b|\bcare ratings\b|india ratings", "credit_rating"),
    (r"insolvency|bankruptcy|nclt|litigation|show.?cause|penalt|demand order|tax demand|"
     r"sebi order|regulatory action|search and seizure|enforcement directorate|arbitration award", "litigation"),
    (r"change in (director|key managerial|management|auditor|compliance)|appointment of|"
     r"resignation|cessation|re-?designation|chief (executive|financial|operating)|"
     r"\b(ceo|cfo|coo|cto)\b|managing director", "management_change"),
    (r"sebi \(prohibition of insider trading\)|insider trading|reg(ulation)? ?7\(2\)|"
     r"substantial acquisition|takeover regulations|reg(ulation)? ?29|reg(ulation)? ?31", "insider_trading"),
    (r"acquisition|amalgamation|merger|demerger|scheme of arrangement|joint venture|"
     r"\bjv\b|stake (sale|purchase)|investment in (wholly owned )?subsidiar|divest|slump sale", "M&A"),
    (r"buy.?back|qualified institutions? placement|\bqip\b|rights issue|preferential (issue|allotment)|"
     r"fund.?rais|commercial paper|non.?convertible debenture|\bncd\b|issue of (securities|bonds)", "fund_raise"),
    (r"bonus|sub-?division|stock split|split of", "bonus_split"),
    (r"financial results?|result updates|outcome of board meeting.*result|integrated filing.*financ|"
     r"quarterly results|audited results|unaudited|limited review", "results"),
    (r"board meeting intimation|intimation of board meeting|prior intimation", "results"),
    (r"investor presentation|earnings presentation|results presentation", "results"),
    (r"transcript|earnings call|con\.? ?call|conference call|audio recording|concall", "earnings_call"),
    (r"analyst|institutional investor|investor meet|investor conference|non.?deal roadshow|meeting with|"
     r"schedule of (the )?meet", "investor_meetings"),
    (r"dividend|record date", "dividend"),
    (r"capacity expansion|capex|capital expenditure|new (plant|facility|unit)|commercial production|"
     r"commissioning|greenfield|brownfield", "capex"),
    (r"postal ballot|e-?voting", "postal_ballot"),
    (r"annual general meeting|\bagm\b|extraordinary general|\begm\b|shareholders? meeting", "agm_egm"),
    (r"newspaper publication|trading window|depositories and participants|loss of share certificate|"
     r"duplicate share|esop|employee stock|allotment of (equity )?shares under|compliance certificate|"
     r"statement of (investor )?complaints|reg(ulation)? ?74\(5\)|business responsibility|\besg\b|"
     r"secretarial|scrutini[sz]er|closure of trading|change of (registered office|name of rta)", "unclassified"),
    (r"award of order|receipt of order|order (win|received|inflow)|bags|secures|launch|partnership|"
     r"press release|clarification|media release|collaborat|agreement", "press_release"),
]
_COMPILED = [(re.compile(p, re.I), c) for p, c in RULES]

SENIOR = re.compile(r"\b(ceo|cfo|coo|managing director|chief executive|chief financial|whole.?time director|"
                    r"executive director|chairman|chairperson|md)\b", re.I)
JUNIOR = re.compile(r"company secretary|compliance officer|share transfer agent|\brta\b|"
                    r"secretarial auditor|internal auditor|cost auditor|senior management personnel", re.I)


GENERIC = re.compile(r"^(updates?|general updates?|outcome of board meeting|announcement under regulation 30|"
                     r"analysts/institutional investor meet/con\. call updates|disclosure under regulation 30)", re.I)


@dataclass
class Classified:
    category: str
    subtype: str = ""
    method: str = "rules"   # rules | llm | default


BOILERPLATE = re.compile(r"change in directors?/ ?key managerial personnel/ ?auditor/ ?compliance officer/ ?"
                         r"share transfer agent", re.I)


def subtype_for(category: str, text: str) -> str:
    t = BOILERPLATE.sub(" ", text).lower()  # the NSE subject names every role — ignore it
    if category == "management_change":
        who = "senior" if SENIOR.search(t) and not JUNIOR.search(t) else ("junior" if JUNIOR.search(t) else "director")
        if "independent director" in t and who != "senior":
            who = "independent"
        if "auditor" in t and "statutory auditor" in t:
            who = "auditor"
        way = "exit" if re.search(r"resign|cessation|step(ping|s)? down|retire|demise", t) else "entry"
        return f"{who}_{way}"
    if category == "credit_rating":
        if re.search(r"downgrad|negative|watch with negative", t):
            return "downgrade"
        if re.search(r"upgrad|positive", t):
            return "upgrade"
        return "reaffirm"
    if category == "results":
        if re.search(r"intimation|to consider|will be held|prior intimation", t):
            return "intimation"
        if re.search(r"presentation", t):
            return "deck"
        return "filing"
    if category == "earnings_call":
        return "transcript" if "transcript" in t else ("recording" if re.search(r"audio|recording", t) else "notice")
    if category == "insider_trading":
        return "promoter" if "promoter" in t else "insider"
    if category == "press_release" and re.search(r"order|contract|bags|secures", t):
        return "order_win"
    return ""


def classify(subject: str, body: str = "", allow_llm: bool = True) -> Classified:
    text = f"{subject}\n{body}"
    # Subject is the strongest signal — unless it's one of NSE's catch-all subjects,
    # in which case the body decides.
    scopes = (body, text) if GENERIC.search(subject or "") and body else (subject, text)
    for scope in scopes:
        for rx, cat in _COMPILED:
            if rx.search(scope):
                return Classified(cat, subtype_for(cat, text))
    if allow_llm and (subject or body):
        try:
            res = router.complete(
                "classify",
                "You classify Indian stock-exchange filings. Reply with JSON {\"category\": one of "
                + ", ".join(CATEGORIES) + "}. Routine compliance paperwork is 'unclassified'.",
                f"Subject: {subject}\nText: {body[:1500]}",
                json_mode=True, max_tokens=40,
            ).json()
            cat = res.get("category", "unclassified")
            if cat in CATEGORIES:
                return Classified(cat, subtype_for(cat, text), "llm")
        except router.NoLLM:
            pass
        except Exception:  # bad JSON etc. — never let enrichment break ingest
            pass
    return Classified("unclassified", "", "default")
