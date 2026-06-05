"""
ai.py — Monthly Touch OS · Powered by Map Ranking
AI Router: Gemini Direct (primary) → Groq (optional) → OpenAI (optional)
Dependencies: httpx only  (pip install httpx)

Environment variables required:
    GEMINI_API_KEY
    GROQ_API_KEY
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
    # ── PRIMARY (Gemini Direct) ─────────────────────────────────────────
    "gemini-direct": {
        "provider": "gemini",
        "model": "gemini-2.5-pro",
    },
    # ── FAST / LOW COST (Groq) ──────────────────────────────────────────
    "llama-fast": {
        "provider": "groq",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
    },
    "deepseek-fast": {
        "provider": "groq",
        "model": "deepseek-r1-distill-llama-70b",
    },
    # ── PREMIUM (OpenAI) ────────────────────────────────────────────────
    "gpt-premium": {
        "provider": "openai",
        "model": "gpt-5",
    },
}

# Defaults per feature
DEFAULT_MODEL = "gemini-direct"  # meeting brief + recap
TRANSCRIPT_MODEL = "gemini-direct"

# ─────────────────────────────────────────────
# Provider Endpoints & Config
# ─────────────────────────────────────────────

PROVIDER_CONFIG: Dict[str, Dict[str, Any]] = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key_env": "GROQ_API_KEY",
        "headers_extra": {},
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "api_key_env": "OPENAI_API_KEY",
        "headers_extra": {},
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
        "api_key_env": "GEMINI_API_KEY",
        "headers_extra": {},
    },
}

# Failover chain: when a provider fails, escalate to next
FAILOVER_CHAIN: Dict[str, Dict[str, Any]] = {
    "groq":       {"next_provider": None, "fallback_model_key": None},
    "openai":     {"next_provider": None,          "fallback_model_key": None},  # terminal
    "gemini":     {"next_provider": None, "fallback_model_key": None},
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

    headers: Dict[str, str] = {"Content-Type": "application/json", **cfg["headers_extra"]}
    payload: Dict[str, Any]
    params: Dict[str, Any] = {}

    if provider == "gemini":
        system_text = ""
        user_text = ""
        for m in messages:
            if (m.get("role") or "") == "system":
                system_text = str(m.get("content") or "")
            elif (m.get("role") or "") == "user":
                user_text = str(m.get("content") or "")
        url = f"{cfg['url'].rstrip('/')}/{model}:generateContent"
        params = {"key": api_key}
        if system_text:
            payload = {
                "system_instruction": {"parts": [{"text": system_text}]},
                "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            }
        else:
            payload = {"contents": [{"role": "user", "parts": [{"text": user_text}]}]}
    else:
        headers = {"Authorization": f"Bearer {api_key}", **headers}
        payload = {"model": model, "messages": messages}
        url = cfg["url"]
    last_exc: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            logger.info(
                "[AI] attempt=%d provider=%s model=%s session=%s",
                attempt, provider, model, session_id or "—",
            )
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, params=params, json=payload)

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
            if provider == "gemini":
                candidates = data.get("candidates") or []
                parts = ((candidates[0] or {}).get("content") or {}).get("parts") if candidates else None
                content = (parts[0] or {}).get("text") if parts else None
                if not content:
                    raise AIProviderError("Gemini returned no content")
                return content if isinstance(content, str) else str(content)
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


JSON_REPAIR_SYSTEM = "You fix JSON. Return a single valid JSON object only. No markdown, no commentary."


async def _extract_or_repair_json(
    raw: str,
    model_key: str,
    session_id: Optional[str],
) -> Dict[str, Any]:
    data = _extract_json(raw)
    if data:
        return data
    fix_text = (
        "Convert the following into a single valid JSON object. "
        "Keep the same keys/structure as intended. Output JSON only.\n\n"
        f"{raw[:12000]}"
    )
    fixed = await run_chat(JSON_REPAIR_SYSTEM, fix_text, model_key, (session_id or "ai") + "-repair")
    return _extract_json(fixed)


# ─────────────────────────────────────────────
# Meeting Brief
# ─────────────────────────────────────────────

BRIEF_SYSTEM = """You are a Senior Client Success Director at a digital marketing agency.
You prepare Monthly Touch Meeting briefs that are strategic, retention-focused, and emotionally intelligent.
You ALWAYS return a single valid JSON object (no markdown fences, no commentary).
You write in a confident, warm, consultative voice.

CRITICAL RULES:
- Wins and issues MUST be about the CLIENT'S marketing performance and business outcomes (SEO, rankings/visibility, traffic, leads, conversions, GBP, ads, pipeline, retention).
- NEVER mention internal tooling/ops/engineering items (data connection refreshes, integration errors, API keys/tokens, database issues, auth, CORS, "our system", "the app").
- If some KPI sources are missing or incomplete, DO NOT surface that as an 'issue'. Instead, choose real client-facing issues/risk areas based on available KPIs and common growth levers.
- DO NOT fabricate facts, numbers, rankings, competitors, or time periods. Only state things directly supported by the KPI SNAPSHOT or EXTRA CONTEXT.
- Every win/issue/campaign_recommendation MUST include explain.kpi_paths pointing to real keys inside the KPI SNAPSHOT (e.g., "google_business_profile.calls.value"). If you cannot cite KPI paths, do not include that item.
- Surface highest-priority items first: biggest business impact, biggest retention risk, biggest opportunity."""

BRIEF_USER_TEMPLATE = """Generate a Monthly Touch Meeting brief for this client.

CLIENT:
{client_json}

KPI SNAPSHOT:
{kpi_json}

EXTRA CONTEXT:
{extra}

Use kpi_snapshot._period.current and kpi_snapshot._period.comparison for time period clarity when available.

Return a JSON object with EXACTLY this shape:
{{
  "wins": [
    {{ "title": "...", "description": "client-friendly 1-2 sentences", "metric": "GBP Calls", "delta": "+28% MoM",
       "explain": {{
         "source_used": "GBP Calls",
         "data_sources_analyzed": ["google_business_profile", "google_ads", "gohighlevel", "clickup"],
         "time_period": {{ "current": "May 2026", "comparison": "Apr 2026" }},
         "kpi_paths": ["google_business_profile.calls.value", "google_business_profile.calls.delta_pct"],
         "observed_values": {{ "google_business_profile.calls.value": 23, "google_business_profile.calls.delta_pct": 28 }},
         "logic_used": "Compared current vs prior period",
         "calculation": "Calls increased from 18 to 23",
         "confidence": 0
       }}
    }}
  ],
  "wins_library": [
    {{ "title": "...", "description": "client-friendly 1-2 sentences", "metric": "GBP Calls", "delta": "+28% MoM" }}
  ],
  "issues": [
    {{ "title": "...", "description": "what's happening, transparent but not alarming",
       "action_plan": "what we're already doing + next step",
       "solutions": ["solution 1", "solution 2"],
       "severity": "low|medium|high",
       "explain": {{
         "source_used": "GBP Calls",
         "data_sources_analyzed": ["google_business_profile", "google_ads", "gohighlevel", "clickup"],
         "time_period": {{ "current": "May 2026", "comparison": "Apr 2026" }},
         "kpi_paths": ["google_business_profile.calls.value", "google_business_profile.calls.delta_pct"],
         "observed_values": {{ "google_business_profile.calls.value": 18, "google_business_profile.calls.delta_pct": -22 }},
         "logic_used": "Compared current vs prior period",
         "calculation": "Calls decreased from 23 to 18",
         "confidence": 0
       }}
     }}
  ],
  "issues_library": [
    {{ "title": "...", "description": "what's happening, transparent but not alarming",
       "action_plan": "what we're already doing + next step", "severity": "low|medium|high" }}
  ],
  "campaign_recommendations": [
    {{
      "platform": "seo|google_ads|meta_ads|google_business_profile|other",
      "campaign": "campaign name or null",
      "priority": "high|medium|low",
      "recommendations": ["recommendation 1", "recommendation 2"],
      "explain": {{
        "source_used": "Google Ads CPL",
        "data_sources_analyzed": ["google_ads", "google_business_profile", "gohighlevel", "clickup"],
        "time_period": {{ "current": "May 2026", "comparison": "Apr 2026" }},
        "kpi_paths": ["google_ads.cpl.value", "google_ads.cpl.previous"],
        "observed_values": {{ "google_ads.cpl.value": 92, "google_ads.cpl.previous": 68 }},
        "logic_used": "Mapped KPI deltas to highest-leverage fixes",
        "calculation": "CPL rose from $68 to $92 while conversions stayed flat; prioritize landing page + keyword pruning",
        "confidence": 0
      }}
    }}
  ],
  "talking_points": [
    {{ "topic": "...", "angle": "how to frame it strategically in 1 sentence" }}
  ],
  "talking_points_library": [
    {{ "topic": "...", "angle": "how to frame it strategically in 1 sentence" }}
  ],
  "suggested_questions": [
    "open-ended engagement question 1",
    "..."
  ],
  "prep_checklist": [
    "prep item 1",
    "..."
  ],
  "ace_up_the_sleeve": [
    {{ "scenario": "client pushes back on price", "response": "what to say in 2-4 sentences", "follow_up_question": "one question" }}
  ],
  "testimonial_opportunity": "1-2 sentences naming whether this client is ready for testimonial ask and how to ask naturally — or 'Not yet, focus on results first'",
  "strategic_recommendations": [
    "specific upsell/cross-sell/CRO/AI/operations recommendation 1",
    "..."
  ],
  "health_signal": "1 sentence summary of overall account health and trend"
}}

wins: as many as strongly supported by the KPI snapshot (typically 3-12) · issues: all important issues (typically 1-8) · talking_points: 4-10 items
wins and issues must be ordered highest-impact first (lead volume / revenue / retention risk).
issues: every issue MUST include a non-empty solutions array (1-3 items).
campaign_recommendations: recommendations per campaign/deliverable, tied to KPI snapshot (typically 2-8 items). No generic fluff.
wins/issues/recommendations MUST be factual. Never guess. If you can’t cite KPI paths for an insight, omit it.
wins_library: 8-15 items · issues_library: 6-12 items · talking_points_library: 10-18 items
suggested_questions: 4-6 items (mix experience / emotional / outcome / future)
strategic_recommendations: 3-5 items
prep_checklist: 8-14 items
ace_up_the_sleeve: 5-10 items
"""


def _resolve_kpi_path(root: Any, path: str) -> Any:
    cur: Any = root
    for part in (path or "").split("."):
        if not part:
            return None
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur.get(part)
            continue
        if isinstance(cur, list):
            try:
                idx = int(part)
            except Exception:
                return None
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
            continue
        return None
    return cur


def _normalize_explain_evidence(item: Dict[str, Any], kpi_snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    explain = item.get("explain") if isinstance(item.get("explain"), dict) else {}

    kpi_paths = explain.get("kpi_paths") or explain.get("kpiPaths") or []
    if isinstance(kpi_paths, str):
        kpi_paths = [kpi_paths]
    if not isinstance(kpi_paths, list):
        kpi_paths = []

    source_used = str(explain.get("source_used") or explain.get("sourceUsed") or "").strip()
    if not kpi_paths and source_used:
        aliases = {
            "GBP Calls": ["google_business_profile.calls.value", "google_business_profile.calls.delta_pct"],
            "GBP Directions": ["google_business_profile.direction_requests.value", "google_business_profile.direction_requests.delta_pct"],
            "GBP Direction Requests": ["google_business_profile.direction_requests.value", "google_business_profile.direction_requests.delta_pct"],
            "Google Ads Spend": ["google_ads.spend.value", "google_ads.spend.delta_pct"],
            "Google Ads Leads": ["google_ads.leads.value", "google_ads.leads.delta_pct"],
            "Google Ads CPL": ["google_ads.cpl.value", "google_ads.cpl.previous"],
            "Meta Ads Leads": ["meta_ads.leads.value", "meta_ads.leads.delta_pct"],
            "Meta Ads CPL": ["meta_ads.cpl.value", "meta_ads.cpl.previous"],
            "GSC Clicks": ["google_search_console.clicks.value", "google_search_console.clicks.delta_pct"],
            "GSC Impressions": ["google_search_console.impressions.value", "google_search_console.impressions.delta_pct"],
            "GA Sessions": ["google_analytics.sessions.value", "google_analytics.sessions.delta_pct"],
            "GA Conversions": ["google_analytics.conversions.value", "google_analytics.conversions.delta_pct"],
            "Map Check-ins Avg Grid Rank": ["map_checkins.avg_grid_rank.value", "map_checkins.avg_grid_rank.previous"],
        }
        kpi_paths = aliases.get(source_used, [])

    observed_values: Dict[str, Any] = {}
    for p in [str(x).strip() for x in kpi_paths if str(x).strip()]:
        v = _resolve_kpi_path(kpi_snapshot, p)
        if v is not None:
            observed_values[p] = v

    if not observed_values:
        return None

    explain["kpi_paths"] = list(observed_values.keys())
    explain["observed_values"] = observed_values
    item["explain"] = explain
    return item


def _validate_factual_items(items: Any, kpi_snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        fixed = _normalize_explain_evidence(it, kpi_snapshot)
        if fixed is None:
            continue
        out.append(fixed)
    return out


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
    raw = await run_chat(BRIEF_SYSTEM, user_text, model_key, session_id)
    data = await _extract_or_repair_json(raw, model_key, session_id)

    issues = data.get("issues") or []
    if isinstance(issues, list):
        for iss in issues:
            if not isinstance(iss, dict):
                continue
            sols = iss.get("solutions")
            if sols is None:
                iss["solutions"] = []
            elif isinstance(sols, str):
                iss["solutions"] = [sols]
            elif not isinstance(sols, list):
                iss["solutions"] = []

    campaign_recommendations = data.get("campaign_recommendations") or []
    if isinstance(campaign_recommendations, dict):
        campaign_recommendations = [campaign_recommendations]
    if not isinstance(campaign_recommendations, list):
        campaign_recommendations = []

    wins = _validate_factual_items(data.get("wins") or [], kpi_snapshot)
    wins_library = _validate_factual_items(data.get("wins_library") or (data.get("wins") or []), kpi_snapshot)

    issues = _validate_factual_items(issues, kpi_snapshot)
    for iss in issues:
        sols = iss.get("solutions")
        if sols is None:
            iss["solutions"] = []
        elif isinstance(sols, str):
            iss["solutions"] = [sols]
        elif not isinstance(sols, list):
            iss["solutions"] = []

    campaign_recommendations = _validate_factual_items(campaign_recommendations, kpi_snapshot)

    issues_library = _validate_factual_items(data.get("issues_library") or issues, kpi_snapshot)

    return {
        "wins":                      wins,
        "wins_library":              wins_library,
        "issues":                    issues,
        "issues_library":            issues_library,
        "talking_points":            data.get("talking_points") or [],
        "talking_points_library":    data.get("talking_points_library") or [],
        "suggested_questions":       data.get("suggested_questions") or [],
        "prep_checklist":            data.get("prep_checklist") or [],
        "ace_up_the_sleeve":         data.get("ace_up_the_sleeve") or [],
        "testimonial_opportunity":   data.get("testimonial_opportunity") or "",
        "strategic_recommendations": data.get("strategic_recommendations") or [],
        "campaign_recommendations":  campaign_recommendations,
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

SPECIAL INSTRUCTIONS:
{instructions}

TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"

Return a JSON object with EXACTLY this shape:
{{
  "summary": "3-5 sentence executive summary of the meeting",
  "sentiment": "positive|neutral|negative",
  "sentiment_summary": "1-2 sentences explaining client sentiment with evidence",
  "client_profile": {{
    "personality": "1-3 sentences",
    "decision_making_style": "1-2 sentences",
    "business_goals": [ "goal 1", "..." ],
    "growth_goals": [ "goal 1", "..." ],
    "trust_issues": [ "signal 1", "..." ],
    "frustrations": [ "frustration 1", "..." ],
    "hidden_risks": [ "risk 1", "..." ],
    "relationship_opportunities": [ "opportunity 1", "..." ],
    "operational_bottlenecks": [ "bottleneck 1", "..." ]
  }},
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
    instructions: str = "",
) -> Dict[str, Any]:
    user_text = TRANSCRIPT_USER_TEMPLATE.format(
        client_name=client_name or "Client",
        company=company or "",
        am_name=am_name or "Account Manager",
        instructions=(instructions or "").strip() or "Follow the shape exactly. Be specific and evidence-based.",
        transcript=transcript[:18_000],
    )
    raw = await run_chat(TRANSCRIPT_SYSTEM, user_text, model_key, session_id)
    data = await _extract_or_repair_json(raw, model_key, session_id)
    return {
        "summary":                 data.get("summary", ""),
        "sentiment":               data.get("sentiment", "neutral"),
        "sentiment_summary":       data.get("sentiment_summary", ""),
        "client_profile":          data.get("client_profile") or {},
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
    raw = await run_chat(RECAP_SYSTEM, user_text, model_key, session_id)
    data = await _extract_or_repair_json(raw, model_key, session_id)
    if not data:
        return {"subject": f"Recap — {title}", "html": f"<pre>{raw}</pre>", "plain": raw}
    return {
        "subject": data.get("subject", f"Recap — {title}"),
        "html":    data.get("html", ""),
        "plain":   data.get("plain", ""),
    }


WORKFLOW_SYSTEM = """You are an expert account management operations engine.
You convert meeting transcripts into a structured post-meeting workflow.
You ALWAYS return a single valid JSON object only (no markdown, no commentary)."""

WORKFLOW_USER_TEMPLATE = """Generate post-meeting workflow outputs.

CLIENT: {client_name} ({company})
MEETING TITLE: {title}

TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"

Return JSON:
{{
  "meeting_summary": "5-10 sentence summary",
  "client_recap_email": {{
    "subject": "...",
    "plain": "client-facing recap email, plain text"
  }},
  "follow_up_action_items": [
    {{ "title": "...", "description": "...", "owner_type": "agency|client", "due_date": "YYYY-MM-DD or null", "priority": "low|medium|high" }}
  ],
  "department_tickets": [
    {{ "department": "SEO|Ads|Web|Design|GBP|Support|Other", "title": "...", "description": "...", "priority": "low|medium|high" }}
  ],
  "internal_recommendations": [ "internal note 1", "..." ],
  "escalation_requests": [ "escalation 1", "..." ],
  "client_voice_moments": [ "exact quote or key feedback 1", "..." ]
}}
"""


async def generate_meeting_workflow(
    client_name: str,
    company: str,
    title: str,
    transcript: str,
    model_key: str = DEFAULT_MODEL,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = WORKFLOW_USER_TEMPLATE.format(
        client_name=client_name or "Client",
        company=company or "",
        title=title or "Monthly Touch",
        transcript=(transcript or "")[:18_000],
    )
    raw = await run_chat(WORKFLOW_SYSTEM, user_text, model_key, session_id)
    data = await _extract_or_repair_json(raw, model_key, session_id)
    return {
        "meeting_summary": data.get("meeting_summary", ""),
        "client_recap_email": data.get("client_recap_email") or {},
        "follow_up_action_items": data.get("follow_up_action_items") or [],
        "department_tickets": data.get("department_tickets") or [],
        "internal_recommendations": data.get("internal_recommendations") or [],
        "escalation_requests": data.get("escalation_requests") or [],
        "client_voice_moments": data.get("client_voice_moments") or [],
        "_raw": raw if not data else None,
    }


QA_SYSTEM = """You are a QA coach for account managers.
Score the meeting process quality and effectiveness.
You ALWAYS return a single valid JSON object only."""

QA_USER_TEMPLATE = """Score this Monthly Touch Meeting.

ACCOUNT MANAGER: {am_name}
CLIENT: {client_name} ({company})
MEETING TITLE: {title}

CHECKLIST:
{checklist_json}

TRANSCRIPT:
\"\"\"
{transcript}
\"\"\"

Return JSON:
{{
  "total_score": 0,
  "dimensions": {{
    "meeting_quality": 0,
    "client_engagement": 0,
    "process_compliance": 0,
    "follow_up_clarity": 0,
    "communication_effectiveness": 0,
    "upsell_identification": 0
  }},
  "feedback": "short coaching feedback, 4-8 sentences"
}}
"""


async def score_meeting_qa(
    am_name: str,
    client_name: str,
    company: str,
    title: str,
    transcript: str,
    checklist: Dict[str, Any],
    model_key: str = DEFAULT_MODEL,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    user_text = QA_USER_TEMPLATE.format(
        am_name=am_name or "Account Manager",
        client_name=client_name or "Client",
        company=company or "",
        title=title or "Monthly Touch",
        transcript=(transcript or "")[:18_000],
        checklist_json=json.dumps(checklist or {}, default=str),
    )
    raw = await run_chat(QA_SYSTEM, user_text, model_key, session_id)
    data = await _extract_or_repair_json(raw, model_key, session_id)
    return {
        "total_score": int(data.get("total_score") or 0),
        "dimensions": data.get("dimensions") or {},
        "feedback": data.get("feedback") or "",
        "_raw": raw if not data else None,
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
