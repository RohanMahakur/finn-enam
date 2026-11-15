"""HTTP API + static frontend in one process (one free-tier deploy, one URL to share).

Run:  uvicorn finn.api:app --reload
"""
from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, export, pipeline
from .engine import research as rs
from .llm import router

app = FastAPI(title="FINN", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "models": router.status(), "db": str(config.DB_PATH), "time": datetime.now().isoformat()}


@app.get("/api/meta")
def meta():
    return export.meta()


@app.get("/api/digest")
def digest(hours: float = Query(24 * 7, le=24 * 60)):
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    return export.digest(since)


@app.get("/api/portfolio")
def portfolio():
    return export.portfolio()


@app.get("/api/thresholds")
def thresholds():
    return asdict(config.thresholds())


@app.get("/api/research/{symbol}")
def research(symbol: str, deep: bool = True):
    try:
        return rs.research(symbol, deep=deep)
    except LookupError as e:
        raise HTTPException(404, str(e))


class AskIn(BaseModel):
    symbol: str
    question: str


@app.post("/api/ask")
def ask(body: AskIn):
    return rs.ask(body.symbol, body.question)


class FeedbackIn(BaseModel):
    symbol: str
    category: str
    action: str  # keep | bury


@app.post("/api/feedback")
def feedback(body: FeedbackIn):
    if body.action not in ("keep", "bury"):
        raise HTTPException(400, "action must be keep|bury")
    db.add_feedback(body.symbol, body.category, body.action)
    return {"ok": True, "counts": db.feedback_counts()}


@app.get("/api/costs")
def costs():
    return db.cost_summary()


@app.post("/api/run")
def run(x_finn_token: str = Header("")):
    if not os.getenv("FINN_RUN_TOKEN") or x_finn_token != os.getenv("FINN_RUN_TOKEN"):
        raise HTTPException(403, "set FINN_RUN_TOKEN and send it as X-Finn-Token")
    return pipeline.run()


# ---- serve the built frontend (frontend/dist) from the same origin, if present
DIST = Path(os.getenv("FINN_DIST", config.REPO / "frontend" / "dist"))
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
    if (DIST / "data").exists():
        app.mount("/data", StaticFiles(directory=DIST / "data"), name="data")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
