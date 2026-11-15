"""Out-of-app push. Telegram (bot token + chat id) and/or ntfy.sh (topic) — both free,
both reach a phone lock screen within seconds of the after-close job finishing.

Interrupts are expensive, so only alerts with severity ≥ FINN_PUSH_MIN (default 70) leave the
app; everything else waits in the digest. Messages are one screen, plain text, with a link
back to the item.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)
APP_URL = os.getenv("FINN_APP_URL", "")
MIN_SEV = float(os.getenv("FINN_PUSH_MIN", "70"))


def render(a: dict) -> str:
    lines = [f"{a['symbol']} · {a['headline']}"]
    lines += [f"• {t['text']}" for t in a.get("triggers", [])[:3]]
    if a.get("kind") == "move":
        if a.get("explained_by"):
            lines.append(f"↳ likely: {a['explained_by'][0]['subject']}")
        else:
            lines.append("↳ no filing explains this")
    elif a.get("filing", {}).get("summary"):
        lines.append(a["filing"]["summary"])
    if APP_URL:
        lines.append(f"{APP_URL}/#/alert/{a['id']}")
    return "\n".join(lines)


def push(alerts: list[dict]) -> int:
    tok, chat, topic = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"), os.getenv("NTFY_TOPIC")
    sent = 0
    for a in alerts:
        if a.get("severity", 0) < MIN_SEV:
            continue
        msg = render(a)
        try:
            if tok and chat:
                requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                              json={"chat_id": chat, "text": msg, "disable_web_page_preview": True}, timeout=10)
            if topic:
                requests.post(f"https://ntfy.sh/{topic}", data=msg.encode(),
                              headers={"Title": f"FINN · {a['symbol']}", "Priority": "high" if a["severity"] >= 85 else "default"},
                              timeout=10)
            sent += 1
        except requests.RequestException as e:
            log.warning("push failed: %s", e)
    return sent
