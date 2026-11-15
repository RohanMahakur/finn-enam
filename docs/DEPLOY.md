# Deploy

Two ways to ship, both on free tiers. The static route is the safest demo; the full route adds
live research on any ticker.

## A. Static PWA (never goes down) — Vercel / Netlify / GitHub Pages

The app reads a JSON snapshot, so there's no backend to fall asleep.

```bash
cd backend && python -m finn run && python -m finn export   # writes frontend/public/data/*.json
cd ../frontend && npm run build                             # dist/ now includes the snapshot
```

- **Vercel:** root `frontend`, build `npm run build`, output `dist`.
- **Netlify:** base `frontend`, build `npm run build`, publish `frontend/dist`.
- **GitHub Pages:** push `frontend/dist` (set Vite `base` to the repo path if not at root).

The `.github/workflows/eod.yml` Action re-runs the pipeline each weekday at 16:20 IST and commits
a fresh snapshot, which triggers the host's auto-redeploy. Add `GEMINI_API_KEY` (and optionally
`ANTHROPIC_API_KEY`, push secrets) in the repo settings.

## B. Full app (API + PWA, one container) — Render free tier

Adds live research on any NSE symbol and the live-tuning `/api/run` endpoint.

```bash
# render.yaml is included — just connect the repo on Render, or:
docker build -t finn . && docker run -p 8000:8000 --env-file .env finn
```

Render reads `render.yaml`, builds the `Dockerfile` (which builds the PWA and serves both from
FastAPI), and health-checks `/api/health`. Set `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` in the
dashboard. If no real DB is present the container boots the synthetic demo, so the link is never
blank. Point the PWA at it with `VITE_API_URL`, or just open the container's own URL (it serves
the app).

> **Note on hosting + Indian data.** NSE/BSE may rate-limit or block datacenter IPs. If a cloud
> host can't reach NSE, FINN automatically falls back to BSE for filings; for prices, run
> `python -m finn run` on a normal connection (or a GitHub Action) and deploy the snapshot. Run
> `python -m finn doctor` from the target environment to see exactly what it can reach.

## Push notifications (optional, free)

- **ntfy.sh:** pick a hard-to-guess topic, set `NTFY_TOPIC`, install the ntfy app, subscribe. Zero signup.
- **Telegram:** make a bot via @BotFather, set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.

Only alerts at severity ≥ `FINN_PUSH_MIN` (default 70) are pushed; the rest wait in the digest.

## Submitting to a phone

Open the deployed URL on a phone and "Add to Home Screen" — it's a standalone PWA (manifest +
theme colour + safe-area insets). No App Store, no TestFlight needed.
