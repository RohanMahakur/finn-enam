# Build log & how I worked with AI

The challenge asks to see *how* I work with coding agents, not just the result. This is an honest
account.

## How this was built

FINN was built with **Claude Code** (the agentic CLI) driving the work, with me steering
architecture and reviewing every design decision. The pattern that worked:

1. **Research first, in parallel.** Before writing a line of product code, I spun up parallel research agents to nail down the things you can't guess: NSE/BSE endpoint shapes and headers, the SEBI Reg-30 "brief profile" requirement, the current free-tier model prices, and what existing investor tools already do (so I could aim at open ground). The findings are in [RESEARCH.md](RESEARCH.md), with everything unverified flagged as such.
2. **Backend engine before UI.** The signal engine (Kalman tracker, market model, classifier, priority, metrics) was built and unit-tested against synthetic data first, so the "unusual" detectors were calibrated before any pixels existed.
3. **Screenshot-driven UI.** The front-end was built, then rendered at phone size (390×844) with a headless browser and reviewed visually — several layout and copy fixes came from actually looking at the renders, not from the code.
4. **Tests as the safety net.** 21 offline tests, including a full research run with the network and model stubbed, so the pipeline is verifiable without hitting NSE or spending a paisa.

## Decisions I made against the obvious default

- **Rules before models for classification.** The tempting move is "throw every filing at an LLM". Exchange subjects are formulaic, so regex is cheaper, faster, and *predictable* — which matters for alerts.
- **A market model, not just a % move.** The obvious "price moved X%" alert fires constantly on market-wide days. Stripping β × Nifty is what makes the alert mean something.
- **Enforced citations.** "Ground it in primary sources" is easy to say in a prompt and easy for a model to ignore. The validator that drops uncitable lines is the part that actually enforces it.
- **A never-down static snapshot.** A demo that doesn't run is the worst outcome (your words), and free tiers sleep. So the deployed app reads a snapshot and can't 404.

## A note on honesty about the data

This workspace couldn't reach NSE/BSE/screener/Yahoo (sandbox allowlist), so the live scrapers
are written from the current source of the maintained Python libraries and their saved sample
responses, and are **not yet tested against the live exchanges**. Rather than fake it, the repo
ships:
- a **synthetic demo** with fictional companies (and a "synthetic" banner in the UI) so nothing fabricated is ever attributed to a real listed company, and
- a `python -m finn doctor` command that checks every source and model key **from your network**, so the first thing you run tells you exactly what's reachable.

Running `python -m finn run` on a normal connection is the step that loads real data.

## The AI conversation exports

The Claude Code session(s) used to build this are linked in the covering email. They show the
research → engine → UI → test loop above, including the places where a first approach was wrong
(e.g. demo filings initially mis-aligned to trading sessions, so an after-close results filing
looked "unexplained" until the session-alignment fix) and got corrected.
