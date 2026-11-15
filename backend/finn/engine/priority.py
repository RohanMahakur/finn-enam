"""Attention score (0–100) for a filing, with a human-readable reason.

score = base(category, subtype) × learned_prior(category) + market_reaction_bonus

* base: a judgement table — the opinion of the product, written down where you can argue with it.
* learned prior: each swipe is a Bernoulli trial "did the investor keep this?". With a
  Beta(2,2) prior per category the multiplier is 0.6 + 0.8·E[p] ∈ [0.6, 1.4]; it starts
  at 1.0 and moves slowly, so three swipes can't bury a whole category.
  Learning only re-ranks the *digest*. Push alerts use explicit, visible rules
  (Google SRE: interrupts must be simple and predictable — no magic thresholds).
* market reaction: if the stock made a stock-specific move the same/next day, the filing
  is probably material regardless of its category.
"""
from __future__ import annotations

BASE: dict[str, float] = {
    "results": 80, "M&A": 75, "management_change": 65, "fund_raise": 65, "pledging": 70,
    "litigation": 60, "credit_rating": 50, "capex": 55, "insider_trading": 45, "bonus_split": 45,
    "press_release": 38, "earnings_call": 35, "dividend": 30, "agm_egm": 18, "postal_ballot": 15,
    "investor_meetings": 14, "unclassified": 5,
}

SUBTYPE: dict[tuple[str, str], float] = {
    ("management_change", "senior_exit"): 90, ("management_change", "senior_entry"): 82,
    ("management_change", "director_exit"): 55, ("management_change", "director_entry"): 45,
    ("management_change", "independent_exit"): 60,  # an independent director quitting can be a tell
    ("management_change", "independent_entry"): 30,
    ("management_change", "auditor_exit"): 85, ("management_change", "auditor_entry"): 30,
    ("management_change", "junior_exit"): 18, ("management_change", "junior_entry"): 12,
    ("credit_rating", "downgrade"): 82, ("credit_rating", "upgrade"): 55, ("credit_rating", "reaffirm"): 20,
    ("results", "intimation"): 28, ("results", "deck"): 50, ("results", "filing"): 85,
    ("earnings_call", "transcript"): 45, ("earnings_call", "recording"): 22, ("earnings_call", "notice"): 25,
    ("insider_trading", "promoter"): 55, ("press_release", "order_win"): 52,
}

LABEL = {
    "results": "Results", "M&A": "M&A", "management_change": "Management", "fund_raise": "Fund raise",
    "pledging": "Pledge", "litigation": "Legal/regulatory", "credit_rating": "Credit rating",
    "capex": "Capex", "insider_trading": "Insider/promoter", "bonus_split": "Bonus/split",
    "press_release": "Press release", "earnings_call": "Concall", "dividend": "Dividend",
    "agm_egm": "AGM/EGM", "postal_ballot": "Postal ballot", "investor_meetings": "Investor meet",
    "unclassified": "Routine",
}

SUBTYPE_LABEL = {
    "senior_exit": "CXO/MD exit", "senior_entry": "CXO/MD appointment", "auditor_exit": "auditor exit",
    "independent_exit": "independent director exit", "downgrade": "downgrade", "upgrade": "upgrade",
    "reaffirm": "reaffirmed", "intimation": "date intimation", "filing": "filed", "deck": "deck",
    "transcript": "transcript", "promoter": "promoter", "order_win": "order win",
    "junior_entry": "secretarial", "junior_exit": "secretarial",
}


def prior_multiplier(category: str, feedback: dict[str, dict[str, int]]) -> float:
    f = feedback.get(category, {})
    keep, bury = f.get("keep", 0), f.get("bury", 0)
    mean = (keep + 2) / (keep + bury + 4)
    return 0.6 + 0.8 * mean


def score(category: str, subtype: str, *, feedback: dict | None = None,
          move: dict | None = None) -> tuple[float, str]:
    base = SUBTYPE.get((category, subtype), BASE.get(category, 10))
    mult = prior_multiplier(category, feedback or {})
    s = base * mult
    why = [LABEL.get(category, category)]
    if subtype in SUBTYPE_LABEL:
        why[0] += f" · {SUBTYPE_LABEL[subtype]}"
    if abs(mult - 1) > 0.05:
        why.append(f"you {'keep' if mult > 1 else 'usually bury'} these (×{mult:.2f})")
    if move and move.get("abnormal_z") is not None and abs(move["abnormal_z"]) >= 2:
        bonus = min(20, 6 * abs(move["abnormal_z"]))
        s += bonus
        why.append(f"stock moved {move['ret_pct']:+.1f}% ({move['abnormal_z']:+.1f}σ stock-specific)")
    return round(min(100.0, s), 1), " · ".join(why)
