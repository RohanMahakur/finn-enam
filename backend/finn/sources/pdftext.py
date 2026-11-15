"""Fetch a filing / report PDF and extract text page-by-page, cached by URL.

We keep pages separate so every claim downstream can cite [doc p.N].
Scanned filings (no text layer) are flagged rather than silently returning nothing.
"""
from __future__ import annotations

import hashlib
import io
import logging

import requests

from .. import config, db

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": config.USER_AGENT, "Referer": "https://www.bseindia.com/"}


def fetch_pages(url: str, max_pages: int | None = None) -> dict:
    """→ {"pages": [str, ...], "scanned": bool, "n_pages": int}"""
    key = "pdf:" + hashlib.sha256(f"{url}|{max_pages}".encode()).hexdigest()
    if (hit := db.cache_get(key)) is not None:
        return hit
    from pypdf import PdfReader

    urls = [url]
    if "AttachLive" in url:  # BSE moves older filings to AttachHis
        urls.append(url.replace("AttachLive", "AttachHis"))
    content = None
    for u in urls:
        try:
            r = requests.get(u, headers=HEADERS, timeout=60)
            if r.ok and r.content[:4] == b"%PDF":
                content = r.content
                break
        except requests.RequestException as e:
            log.warning("pdf fetch failed %s: %s", u, e)
    if content is None:
        return {"pages": [], "scanned": False, "n_pages": 0, "error": "fetch failed"}
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for i, p in enumerate(reader.pages):
        if max_pages and i >= max_pages:
            break
        try:
            pages.append((p.extract_text() or "").strip())
        except Exception:
            pages.append("")
    chars = sum(len(p) for p in pages)
    out = {"pages": pages, "n_pages": len(reader.pages), "scanned": chars < 200 * max(1, len(pages)) * 0.2}
    db.cache_put(key, out)
    return out
