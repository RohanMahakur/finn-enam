**To:** assessment@enam.com
**Subject:** IIT Delhi – AI Engineer - 2027

---

Hi team,

Here is my submission for the FINN build challenge.

**Try it on a phone:** <DEPLOYED_URL> (add to home screen) · **Repo:** <GITHUB_URL> · **AI build history:** <CLAUDE_CODE_SHARE_LINK>

**What I built.** FINN around a single conviction from your brief: the scarce resource is the
investor's attention, so the product should be a stack of *filters*, each with a control the
investor can see and move. Three things I'd point you to first:

1. **Unexplained-move alerts.** Every portfolio stock is tracked three ways: raw thresholds, a market-model residual (the move left after stripping β × Nifty), and a Kalman "corridor" that predicts where the stock should close and flags when it leaves its path. An alert is then joined with the filings around it — and **a stock-specific move that no filing explains is ranked above everything else.** That "why did it drop 8% and nobody said anything?" moment is the one I'd most want surfaced, and none of the tools I surveyed does it.

2. **The Promise Ledger.** On the pull side, FINN reads the last four concall transcripts, extracts every forward-looking commitment, and scores each against the numbers management actually reported and what they said on later calls — kept / partial / missed / pending — into a single **say–do score**. It's your "promised vs delivered" turned into a standing scorecard, and it's grounded strictly in primary sources: every line cites a transcript page or `[NUMBERS]`, and lines a model can't cite are dropped automatically.

3. **Cost discipline as a design principle.** Rules classify ~90% of filings; NSE's own XBRL-parsed numbers and every ratio are computed in code; a cheap model handles bulk extraction; a strong model is used only to judge promises and write the bull/bear. Everything is content-hash cached. A full research pack costs about ₹10 and the app shows you the running total. With no API keys at all it still runs everything that's rules + arithmetic.

**Key trade-offs.**
- *Thin but working over broad but broken.* I went deep on two workflows — the unexplained-move alert and the Promise Ledger — rather than shipping every item on the menu.
- *Never-down demo.* The deployed link reads a static snapshot, so it works even when the free-tier backend is asleep; point it at the live API for research on any ticker. The repo also ships a clearly-labelled **synthetic demo** (fictional companies, real engine) so it's runnable offline in one command.
- *Primary sources only, enforced.* The pull side refuses broker notes and news by construction — the citation validator is the enforcement, not a prompt.

**Deliberately left out:** intraday data, price targets / buy-sell calls, logins, and a vector DB (BM25 over ~5 documents is enough and free). **Where I'd take it next:** portfolio-wide say–do so weak-track-record guidance is auto-discounted, and calibrating the alert-priority weights on two years of labelled next-day abnormal returns.

A personal note: the Kalman corridor is a direct descendant of a computer-vision project of mine
that tracked a table-tennis ball through occlusions with an adaptive-noise Kalman filter — a
stock price turned out to be a noisier 1-D version of the same "predict the next step, measure
the surprise" problem. It was the most fun part to build.

Thanks for a genuinely good problem to think about.

Best,
Rohan Mahakur
Electrical Engineering, IIT Delhi (2023–27)
<phone> · <email>

*Build notes and the full architecture write-up are in `docs/` in the repo.*
