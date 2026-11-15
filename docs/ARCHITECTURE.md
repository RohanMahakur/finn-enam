# Architecture & key decisions

This is the "why", one decision at a time. The "what" is in the [README](../README.md); the
research behind it is in [RESEARCH.md](RESEARCH.md).

## The thesis: attention is the scarce resource

The brief says it plainly — aggregating information is easy, filtering it is the skill. So FINN
is built as a stack of filters, each with a control the investor can see and move:

- the **waterline** (one noise-floor dial for the digest),
- the **thresholds** (you define "unusual", with a live count of alerts they'd fire),
- the **say–do score** (how much to trust the next promise).

Nothing is a black box. Every alert and every score carries a one-line reason.

## Push side

### 1. "Unusual" has three lenses, not one

`engine/tracker.py` runs three independent detectors per stock-day, because "the price moved"
is the weakest possible signal:

1. **Raw thresholds** — `|return| ≥ X%`, `volume ≥ Y× 20-day average`. What the brief asks for, and what the user tunes.
2. **Market model (event study)** — fit `r_i = α + β·r_m + ε` over the prior 120 sessions; `ε/σ_ε` is the **stock-specific** z-score. This is the one that matters: it kills the false alarms where the whole market moved. A −4% day on a −3% Nifty is noise; a −4% day on a flat tape is a question.
3. **Kalman trajectory** — a local-linear-trend filter on log-price predicts tomorrow's close from today's level and drift; the innovation `z = (observed − predicted)/√S` says how far the stock left its own path. Process and measurement noise adapt to an EWMA of realised variance (λ=0.94). The ±2√S **corridor** is drawn in the UI.

> **Where this comes from.** The Kalman tracker is lifted, in spirit, from a ball-tracking project: there a constant-velocity Kalman filter with adaptive noise predicted a ball's path and coasted through occlusions. A stock price is a noisier, 1-D version of the same problem — predict the next step, measure the surprise. Adaptive noise is what stops the covariance exploding after a genuine jump. The tests assert the innovation z-scores are calibrated (σ ≈ 1 on normal days) so the σ thresholds mean the same thing on every stock.

### 2. The headline alert is "a move nobody has explained"

`pipeline.py::build_alerts` fuses the day's triggers into one card per stock-day (not one per
trigger — that's just noise), then joins it with filings in `[day−1, day]`. The ranking rule:

> a stock-specific move (`|abnormal_z| ≥ threshold`) with **no filing to explain it** is ranked above everything else.

Nobody else surfaces this (see RESEARCH.md). Most tools alert on a filing, or on a move, but
not on **a move with no filing** — which is precisely the "why did it drop 8%?" moment.

### 3. Classification is rules-first

`engine/classify.py` is ~25 ordered regexes over the filing subject and body. Exchange subjects
are formulaic (`Change in Directors/ Key Managerial Personnel/ Auditor/...`), so rules classify
~90% of filings for free and, crucially, *predictably*. A cheap model is the fallback only for
genuinely ambiguous subjects ("Updates", "General"). It also extracts a **subtype** that drives
priority: a CFO resignation is not a company-secretary appointment; a rating downgrade is not a
reaffirmation.

### 4. Priority is a judgement table you can argue with

`engine/priority.py`: `score = base(category, subtype) × learned_prior(category) + market_bonus`.
- `base` is an explicit opinion written down in one place.
- `learned_prior` is a per-category Beta(2,2) posterior on "did the user keep this?", mapped to ×[0.6, 1.4]. It starts at 1.0 and moves slowly — three swipes can't bury a whole category. **It only re-ranks the digest.** Alerts use fixed, visible rules (the Google SRE principle: interrupts must be predictable, not magic).
- `market_bonus` lifts any filing the stock actually reacted to.

## Pull side

### 5. Primary sources only, enforced not requested

`engine/research.py` builds a corpus from the last 4 concall transcripts + the latest annual
report (page-level, BM25-indexed — no embeddings needed for ~5 documents). The "no outside
knowledge" rule is **enforced**: every synthesis line must carry a citation like `[T2 p.4]`, and
`_valid()` drops any line whose citation doesn't resolve to a real page in the corpus. The app
reports how many lines were dropped. "Cite your sources" that the system actually checks.

### 6. The Promise Ledger is the differentiator

Three steps:
1. **Extract** (mid model) — forward-looking commitments from each transcript, after a keyword prefilter that drops ~70% of non-guidance text. Each claim keeps its metric, target, horizon and page.
2. **Judge** (strong model) — each matured claim against (a) the actual quarterly numbers, computed in code, and (b) what management said on later calls (retrieved by BM25). Verdict ∈ {kept, partial, missed, pending, unclear}.
3. **Score** (code) — say–do = kept + ½·partial over matured claims.

This is the brief's "numbers vs narrative — what was promised vs delivered", made into a
standing scorecard. The research note found no surveyed product that tracks guidance against
delivery over time.

### 7. Arithmetic is never the model's job

`engine/metrics.py` computes every ratio — CAGR, margins, D/E, cash-conversion cycle, CFO/PAT —
in code from reported numbers, and emits plain-English flags with a tone (good/watch/bad). It
knows banks are different (D/E and working capital aren't meaningful for a lender). The model
reads and reasons; it never multiplies.

## The model router (`llm/router.py`)

- **Tiered fallback chains.** Each tier is a comma-separated list of `provider:model`; the router uses the first whose API key exists. So the app degrades from "all keys" → "only a free Gemini key" → "no keys" (rules + arithmetic only) without a code change.
- **Content-hash cache.** Same input → never a second call. Research packs are cached 24h on the document set; re-opening a company is free.
- **Prompt caching.** Anthropic calls mark the (long, repeated) system prompt as cacheable — cache reads are ~10× cheaper.
- **Cost ledger.** Every call logs tokens and ₹; the Tune screen shows spend, call count and cache-hit rate.

## Data layer: never-down demo

`api.py` serves the API *and* the built PWA from one origin. But the PWA also reads a **static
JSON snapshot** (`export.py`), so the deployed link works even when the backend is asleep (free
tiers sleep). `lib/data.ts` probes `/api/health` once and transparently falls back to the
snapshot. The front-end re-implements the alert rules (`lib/engine.ts`) so the Tune sliders are
live without a round-trip.

## Sources & resilience (`sources/`)

- **NSE** needs `curl_cffi` with Chrome TLS impersonation + a cookie warm-up (Akamai bot wall). Base host is configurable (`nseindia.com` ⇄ `nseindia.in`) because maintained libraries disagree on which is current.
- **BSE** works with plain `requests` + Origin/Referer, so it's the fallback when NSE's wall wins (e.g. from a datacenter IP). Symbol→scrip-code is cached.
- **screener.in** is parsed by **row label, not position**, with section lookup falling back from element id to heading text — small layout changes don't break it. Its Pros/Cons/"AI summary" (secondary commentary) is deliberately ignored.
- Everything network-facing is cached in SQLite and degrades to a fallback or a clear error; enrichment failures never block the digest.

## What a grader should look at first
1. `engine/tracker.py` — the three-lens "unusual" detector and the Kalman corridor.
2. `engine/research.py` — the Promise Ledger and the citation validator.
3. `engine/priority.py` + `pipeline.py::build_alerts` — explained vs unexplained ranking.
4. `llm/router.py` — the cost discipline.
5. `tests/test_engine.py` — 21 offline tests, including a full stubbed research run.
