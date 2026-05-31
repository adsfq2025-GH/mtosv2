"""
ai.py — Monthly Touch OS · Powered by Map Ranking
AI Router: Groq (speed) → OpenRouter (flexibility) → OpenAI (premium)
Dependencies: httpx only  (pip install httpx)

Environment variables required:
    GROQ_API_KEY
    OPENROUTER_API_KEY
    OPENAI_API_KEY
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────


class AIProviderError(Exception):
    """Raised when all providers fail or configuration is invalid."""


# ─────────────────────────────────────────────
# Model Registry
# ─────────────────────────────────────────────

MODEL_REGISTRY: Dict[str, Dict[str, str]] = {
    # ── FAST / LOW COST (Groq) ──────────────────────────────────────────
    "llama-fast": {
        "provider": "groq",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
    },
    "deepseek-fast": {
        "provider": "groq",
        "model": "deepseek-r1-distill-llama-70b",
    },
    # ── FLEXIBLE (OpenRouter) ───────────────────────────────────────────
    "claude-sonnet": {
        "provider": "openrouter",
        "model": "anthropic/claude-sonnet-4",
    },
    "gemini-pro": {
        "provider": "openrouter",
        "model": "google/gemini-2.5-pro",
    },
    "deepseek-r1": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-r1",
    },
    # ── PREMIUM (OpenAI) ────────────────────────────────────────────────
    "gpt-premium": {
        "provider": "openai",
        "model": "gpt-5",
    },
}

# Defaults per feature
DEFAULT_MODEL    = "llama-fast"    # meeting brief + recap
TRANSCRIPT_MODEL = "deepseek-fast"

# ─────────────────────────────────────────────
# Provider Endpoints & Config
# ─────────────────────────────────────────────

PROVIDER_CONFIG: Dict[str, Dict[str, Any]] = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key_env": "GROQ_API_KEY",
        "headers_extra": {},
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key_env": "OPENROUTER_API_KEY",
        "headers_extra": {
            "HTTP-Referer": "https://monthlytouchos.com",
            "X-Title": "Monthly Touch OS",
        },
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "api_key_env": "OPENAI_API_KEY",
        "headers_extra": {},
    },
}

# Failover chain: when a provider fails, escalate to next
FAILOVER_CHAIN: Dict[str, Dict[str, Any]] = {
    "groq":       {"next_provider": "openrouter", "fallback_model_key": "claude-sonnet"},
    "openrouter": {"next_provider": "openai",     "fallback_model_key": "gpt-premium"},
    "openai":     {"next_provider": None,          "fallback_model_key": None},  # terminal
}

REQUEST_TIMEOUT = 90   # seconds
MAX_RETRIES     = 3


# ─────────────────────────────────────────────
# Core: single provider call (with retries)
# ─────────────────────────────────────────────


async def _call_provider(
    provider: str,
    model: str,
    messages: List[Dict[str, str]],
    session_id: Optional[str] = None,
) -> str:
    cfg = PROVIDER_CONFIG.get(provider)
    if cfg is None:
        raise AIProviderError(f"Unknown provider: {provider!r}")

    api_key = os.environ.get(cfg["api_key_env"], "").strip()
    if not api_key:
        raise AIProviderError(
            f"Missing API key for {provider!r}. Set {cfg['api_key_env']}."
        )

    headers: Dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **cfg["headers_extra"],
    }
    payload: Dict[str, Any] = {"model": model, "messages": messages}
    last_exc: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            logger.info(
                "[AI] attempt=%d provider=%s model=%s session=%s",
                attempt, provider, model, session_id or "—",
            )
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.post(cfg["url"], headers=headers, json=payload)

            elapsed = time.perf_counter() - t0
            logger.info(
                "[AI] provider=%s status=%d elapsed=%.2fs",
                provider, resp.status_code, elapsed,
            )

            if resp.status_code != 200:
                raise AIProviderError(
                    f"Provider {provider!r} → HTTP {resp.status_code}: {resp.text[:400]}"
                )

            data    = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content if isinstance(content, str) else str(content)

        except AIProviderError:
            raise  # propagate immediately; let failover handle it
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.warning(
                "[AI] attempt=%d provider=%s failed in %.2fs: %s",
                attempt, provider, elapsed, exc,
            )
            last_exc = exc
            if attempt < MAX_RETRIES:
                logger.info("[AI] retrying … (%d/%d)", attempt, MAX_RETRIES)

    raise AIProviderError(
        f"Provider {provider!r} exhausted {MAX_RETRIES} retries. Last: {last_exc}"
    )


# ─────────────────────────────────────────────
# Public: run_chat with automatic failover
# ─────────────────────────────────────────────


async def run_chat(
    system: str,
    user_text: str,
    model_key: str,
    session_id: Optional[str] = None,
) -> str:
    """
    Route a chat request through the provider chain.

    Failover order:
        Groq → OpenRouter (claude-sonnet) → OpenAI (gpt-premium) → AIProviderError
    """
    entry = MODEL_REGISTRY.get(model_key)
    if entry is None:
        raise AIProviderError(
            f"Unknown model_key: {model_key!r}. Available: {list(MODEL_REGISTRY)}"
        )

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_text},
    ]

    provider = entry["provider"]
    model    = entry["model"]

    while True:
        try:
            return await _call_provider(provider, model, messages, session_id)
        except AIProviderError as exc:
            logger.error("[AI] provider=%s failed: %s", provider, exc)

            step          = FAILOVER_CHAIN.get(provider, {})
            next_provider = step.get("next_provider")
            fallback_key  = step.get("fallback_model_key")

            if not next_provider or not fallback_key:
                raise AIProviderError(
                    f"All providers exhausted for model_key={model_key!r}. Last: {exc}"
                ) from exc

            logger.warning(
                "[AI] Failing over %s → %s (model_key=%s)",
                provider, next_provider, fallback_key,
            )
            provider = next_provider
            model    = MODEL_REGISTRY[fallback_key]["model"]


# ─────────────────────────────────────────────
# Utility: JSON extraction
# ─────────────────────────────────────────────


def _extract_json(text: str) -> Dict[str, Any]:
    """
    Extract a JSON object from a model response that may contain:
    - Markdown fences  (```json … ```)
    - Raw JSON text
    - Trailing commas  (cleaned before parsing)

    Returns {} on any failure.
    """
    if not text:
        return {}

    # 1. Strip markdown fences
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
    candidate = fence.group(1) if fence else text.strip()

    # 2. Isolate outermost { … }
    start = candidate.find("{")
    end   = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    candidate = candidate[start : end + 1]

    # 3. Remove trailing commas before } or ]
    candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)

    # 4. Parse
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.debug("[AI] _extract_json failed: %s | input=%.200s", exc, candidate)
        return {}


# ─────────────────────────────────────────────
# Meeting Brief
# ─────────────────────────────────────────────

BRIEF_SYSTEM = """You are a Senior Client Success Director at a digital marketing agency.
You prepare Monthly Touch Meeting briefs that are strategic, retention-focused, and emotionally intelligent.
You ALWAYS return a single valid JSON object (no markdown fences, no commentary).
You write in a confident, warm, consultative voice."""

BRIEF_USER_TEMPLATE = """Generate a Monthly Touch Meeting brief for this client.

CLIENT:
{client_json}

KPI SNAPSHOT (last 30 days):
{kpi_json}

EXTRA CONTEXT:
{extra}

Return a JSON object with EXACTLY this shape:
{{
  "wins": [
    {{ "title": "...", "description": "client-friendly 1-2 sentences", "metric": "GBP Calls", "delta": "+28% MoM" }}
  ],
  "issues": [
    {{ "title": "...", "description": "what's happening, transparent but not alarming",
       "action_plan": "what we're already doing + next step", "severity": "low|medium|high" }}
  ],
  "talking_points": [
    {{ "topic": "...", "angle": "how to frame it strategically in 1 sentence" }}
  ],
  "suggested_questions": [
    "open-ended engagement question 1",
    "..."
  ],
  "testimonial_opportunity": "1-2 sentences naming whether this client is ready for testimonial ask and how to ask naturally — or 'Not yet, focus on results first'",
  "strategic_recommendations": [
    "specific upsell/cross-sell/CRO/AI/operations recommendation 1",
    "..."
  ],
  "health_signal": "1 sentence summary of overall account health and trend"
}}

wins: EXACTLY 3 items · issues: EXACTLY 2 items · talking_points: 4-6 items
suggested_questions: 4-6 items (mix experience / emotional / outcome / future)
strategic_recommendations: 3-5 items
"""


async def generate_meeting_brief(
    client: Dict[str, Any],
    kpi_snapshot: Dict[str, Any],
    extra_context: Optional[str],
    model_key: str = DEFAULT_MODEL,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = BRIEF_USER_TEMPLATE.format(
        client_json=json.dumps(client, default=str),
        kpi_json=json.dumps(kpi_snapshot, default=str, indent=2),
        extra=extra_context or "(none)",
    )
    raw  = await run_chat(BRIEF_SYSTEM, user_text, model_key, session_id)
    data = _extract_json(raw)
    return {
        "wins":                      (data.get("wins") or [])[:3],
        "issues":                    (data.get("issues") or [])[:2],
        "talking_points":            data.get("talking_points") or [],
        "suggested_questions":       data.get("suggested_questions") or [],
        "testimonial_opportunity":   data.get("testimonial_opportunity") or "",
        "strategic_recommendations": data.get("strategic_recommendations") or [],
        "health_signal":             data.get("health_signal") or "",
        "_raw":                      raw if not data else None,
    }


# ─────────────────────────────────────────────
# Transcript Analysis
# ─────────────────────────────────────────────

TRANSCRIPT_SYSTEM = """You are an expert client success analyst.
You analyze Monthly Touch Meeting transcripts (often from Google Meet's Gemini notes).
You extract action items, identify testimonial / marketing-content opportunities, and detect client sentiment.
You ALWAYS return a single valid JSON object only (no markdown, no commentary)."""

TRANSCRIPT_USER_TEMPLATE = """Analyze this Monthly Touch Meeting transcript.

CLIENT: {client_name} ({company})
ACCOUNT MANAGER: {am_name}

TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"

Return a JSON object with EXACTLY this shape:
{{
  "summary": "3-5 sentence executive summary of the meeting",
  "sentiment": "positive|neutral|negative",
  "sentiment_summary": "1-2 sentences explaining client sentiment with evidence",
  "key_moments": [ "important moment 1", "..." ],
  "action_items": [
    {{ "title": "...", "description": "...", "owner_type": "agency|client",
       "due_date": "YYYY-MM-DD or null", "priority": "low|medium|high" }}
  ],
  "content_opportunities": [
    {{ "type": "testimonial_video|testimonial_written|quote|case_study_lead|clip",
       "content": "exact quote or moment description (client-said-it style)",
       "why_strong": "1 sentence on why this is good marketing content" }}
  ],
  "churn_risk_signals": [ "signal 1", "..." ],
  "upsell_signals": [ "signal 1", "..." ],
  "health_score_suggestion": 0
}}

key_moments: 3-6 items
"""


async def analyze_transcript(
    client_name: str,
    company: str,
    am_name: str,
    transcript: str,
    model_key: str = TRANSCRIPT_MODEL,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = TRANSCRIPT_USER_TEMPLATE.format(
        client_name=client_name or "Client",
        company=company or "",
        am_name=am_name or "Account Manager",
        transcript=transcript[:18_000],
    )
    raw  = await run_chat(TRANSCRIPT_SYSTEM, user_text, model_key, session_id)
    data = _extract_json(raw)
    return {
        "summary":                 data.get("summary", ""),
        "sentiment":               data.get("sentiment", "neutral"),
        "sentiment_summary":       data.get("sentiment_summary", ""),
        "key_moments":             data.get("key_moments", []),
        "action_items":            data.get("action_items", []),
        "content_opportunities":   data.get("content_opportunities", []),
        "churn_risk_signals":      data.get("churn_risk_signals", []),
        "upsell_signals":          data.get("upsell_signals", []),
        "health_score_suggestion": data.get("health_score_suggestion"),
        "_raw":                    raw if not data else None,
    }


# ─────────────────────────────────────────────
# Recap Generation
# ─────────────────────────────────────────────

RECAP_SYSTEM = """You are a senior account manager writing a polished Monthly Touch Meeting recap email.
Tone: warm, professional, confident, retention-focused. Use clear structure with short sections."""

RECAP_USER_TEMPLATE = """Write a Monthly Touch Meeting recap email to the client.

CLIENT: {client_name} at {company}
MEETING TITLE: {title}

WINS:
{wins}

ISSUES & WHAT WE'RE DOING:
{issues}

ACTION ITEMS:
{actions}

NEXT MEETING: TBD next month

Return a JSON object:
{{
  "subject": "...",
  "html": "<full html email body, well-formatted, professional, uses h2/h3/ul/li, no images>",
  "plain": "plain text version of the same recap"
}}
"""


async def generate_recap(
    client_name: str,
    company: str,
    title: str,
    wins: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
    actions: List[Dict[str, Any]],
    model_key: str = DEFAULT_MODEL,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = RECAP_USER_TEMPLATE.format(
        client_name=client_name,
        company=company,
        title=title,
        wins=json.dumps(wins, default=str),
        issues=json.dumps(issues, default=str),
        actions=json.dumps(actions, default=str),
    )
    raw  = await run_chat(RECAP_SYSTEM, user_text, model_key, session_id)
    data = _extract_json(raw)
    if not data:
        return {"subject": f"Recap — {title}", "html": f"<pre>{raw}</pre>", "plain": raw}
    return {
        "subject": data.get("subject", f"Recap — {title}"),
        "html":    data.get("html", ""),
        "plain":   data.get("plain", ""),
    }


# ─────────────────────────────────────────────
# Smoke-test  (python ai.py)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    async def _smoke() -> None:
        print("=== Monthly Touch OS · AI Router smoke test ===\n")

        msg = await run_chat(
            system="You are a helpful assistant.",
            user_text="Say hello from Monthly Touch OS in one sentence.",
            model_key="llama-fast",
        )
        print(f"[run_chat]  {msg}\n")

        sample = '```json\n{"name": "Alice", "score": 42,}\n```'
        print(f"[_extract_json]  {_extract_json(sample)}\n")

        brief = await generate_meeting_brief(
            client={"name": "Acme Plumbing", "city": "San Diego"},
            kpi_snapshot={"gbp_calls": 42, "gbp_views": 1800},
            extra_context="Client mentioned wanting more reviews.",
        )
        print(f"[generate_meeting_brief]  keys={list(brief)}\n")

    asyncio.run(_smoke())