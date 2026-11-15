"""Central configuration. Everything tunable lives here or in env vars — no magic numbers
scattered through the engine."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
DATA_DIR = Path(os.getenv("FINN_DATA_DIR", REPO / "data"))
DB_PATH = Path(os.getenv("FINN_DB", DATA_DIR / "finn.sqlite"))
EXPORT_DIR = Path(os.getenv("FINN_EXPORT_DIR", REPO / "frontend" / "public" / "data"))

# A real browser UA — NSE/BSE/screener reject default python-requests UAs.
USER_AGENT = os.getenv(
    "FINN_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
)


@dataclass
class Thresholds:
    """What counts as 'unusual'. The user owns these numbers; the UI edits them live."""

    price_move_pct: float = 4.0        # |daily return| >= X %
    volume_multiple: float = 2.0       # volume >= X × 20-day average
    abnormal_z: float = 2.5            # stock-specific (market-model residual) z-score
    trajectory_z: float = 3.0          # Kalman innovation z — "left its predicted path"
    alert_categories: list[str] = field(
        default_factory=lambda: [
            "results", "M&A", "management_change", "fund_raise",
            "litigation", "credit_rating", "pledging",
        ]
    )
    waterline: float = 40.0            # digest items scoring below this are collapsed


@dataclass
class ModelRoute:
    """Comma-separated provider:model fallback chains per tier. The router uses the first
    entry whose provider has an API key configured, so the app degrades gracefully from
    'all keys' → 'only a free Gemini key' → 'no keys' (rules + arithmetic only).
    Swap via env without touching code."""

    cheap: str = os.getenv("FINN_MODEL_CHEAP",
                           "gemini:gemini-3.1-flash-lite,groq:openai/gpt-oss-20b,anthropic:claude-haiku-5-5")
    mid: str = os.getenv("FINN_MODEL_MID",
                         "gemini:gemini-3-flash-preview,anthropic:claude-haiku-5-5,groq:openai/gpt-oss-120b")
    strong: str = os.getenv("FINN_MODEL_STRONG",
                            "anthropic:claude-sonnet-5-5,gemini:gemini-3.1-pro-preview,gemini:gemini-3-flash-preview")


# Which tier each task uses. The principle: rules > arithmetic > cheap model > strong model.
TASK_TIER = {
    "classify": "cheap",        # only for filings the regex classifier can't place
    "one_liner": "cheap",       # one-line summary of a mid-priority filing
    "extract_results": "cheap", # line items from a results PDF (code computes EBITDA/deltas)
    "extract_person": "cheap",  # name / role / profile paragraph from a Reg-30 filing
    "bio": "cheap",             # condense search snippets into a 2-line background
    "extract_claims": "mid",    # guidance claims from a concall transcript (long context)
    "business": "mid",          # segments & revenue mix from the annual report
    "judge_claims": "strong",   # promised vs delivered — needs reasoning across quarters
    "synthesis": "strong",      # narrative vs numbers, bull vs bear
    "ask": "mid",               # free-form grounded Q&A
}

# USD per 1M tokens (input, output). Edit when prices change; used for the in-app cost meter.
PRICES = {  # checked against provider pricing pages on 2026-11-15
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.1-pro-preview": (2.00, 12.0),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.0),
}
USD_INR = float(os.getenv("FINN_USD_INR", "88"))


@lru_cache
def portfolio() -> dict:
    with open(ROOT / "portfolio.yaml") as f:
        return yaml.safe_load(f)


def holdings() -> list[dict]:
    return portfolio()["portfolio"]


def symbols() -> list[str]:
    return [h["symbol"] for h in holdings()]


def holding(symbol: str) -> dict | None:
    return next((h for h in holdings() if h["symbol"] == symbol), None)


def thresholds() -> Thresholds:
    return Thresholds()


def routes() -> ModelRoute:
    return ModelRoute()
