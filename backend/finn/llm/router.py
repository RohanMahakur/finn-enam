"""Cost-aware model router.

Principles (in order):
  1. Don't call a model if rules or arithmetic can answer.          (callers enforce)
  2. Never call twice for the same input.                            (content-hash cache)
  3. Use the cheapest tier that can do the job.                      (TASK_TIER)
  4. Degrade, don't die: missing key → next provider in the chain;
     no provider at all → raise NoLLM and let the caller fall back.
  5. Every call is metered so the app can show what a brief cost.

Providers are called over plain HTTP (OpenAI-compatible for Gemini/Groq/OpenRouter,
Messages API for Anthropic) — no SDK zoo, ~100 lines, easy to audit.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass

import httpx

from .. import config, db

log = logging.getLogger(__name__)


class NoLLM(RuntimeError):
    """No provider configured for this tier — callers must fall back to rules."""


PROVIDERS = {
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions"),
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/messages"),
}


@dataclass
class LLMResult:
    text: str
    model: str
    in_tok: int
    out_tok: int
    cost_usd: float
    cached: bool

    def json(self) -> dict | list:
        return parse_json(self.text)


def available(tier: str) -> str | None:
    chain = getattr(config.routes(), tier).split(",")
    for spec in chain:
        provider = spec.split(":", 1)[0].strip()
        if provider in PROVIDERS and os.getenv(PROVIDERS[provider][0]):
            return spec.strip()
    return None


def price(model: str, i: int, o: int) -> float:
    pi, po = config.PRICES.get(model, (0.0, 0.0))
    return (i * pi + o * po) / 1e6


def complete(task: str, system: str, user: str, *, json_mode: bool = False,
             max_tokens: int = 1200, temperature: float = 0.1) -> LLMResult:
    tier = config.TASK_TIER.get(task, "mid")
    spec = available(tier)
    if not spec:
        raise NoLLM(f"no provider key for tier '{tier}' (task {task})")
    provider, model = spec.split(":", 1)

    key = "llm:" + hashlib.sha256(f"{spec}|{system}|{user}|{json_mode}".encode()).hexdigest()
    if (hit := db.cache_get(key)) is not None:
        db.log_llm(task, model, hit["in"], hit["out"], 0.0, True)
        return LLMResult(hit["text"], model, hit["in"], hit["out"], 0.0, True)

    env, url = PROVIDERS[provider]
    api_key = os.environ[env]
    if provider == "anthropic":
        body = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                # cache the (long, repeated) system prompt — cache reads are ~10x cheaper
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    else:
        body = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {api_key}"}

    r = httpx.post(url, json=body, headers=headers, timeout=120)
    r.raise_for_status()
    data = r.json()
    if provider == "anthropic":
        text = "".join(b.get("text", "") for b in data.get("content", []))
        u = data.get("usage", {})
        i, o = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0)
    else:
        text = data["choices"][0]["message"]["content"] or ""
        u = data.get("usage", {})
        i, o = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)

    cost = price(model, i, o)
    db.cache_put(key, {"text": text, "in": i, "out": o})
    db.log_llm(task, model, i, o, cost, False)
    return LLMResult(text, model, i, o, cost, False)


def parse_json(text: str):
    """Models wrap JSON in prose/fences more often than they should. Be forgiving."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
        if m:
            return json.loads(m.group(1))
        raise


def status() -> dict:
    return {tier: available(tier) for tier in ("cheap", "mid", "strong")}
