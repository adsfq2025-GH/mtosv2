"""AI service — wraps emergentintegrations LLM for brief / transcript / recap generation."""
import json
import os
import re
from typing import Any, Dict, List, Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage

EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]

# Supported models exposed in the UI
MODEL_REGISTRY = {
    "claude-sonnet-4-6": ("anthropic", "claude-sonnet-4-6"),
    "gpt-5.2": ("openai", "gpt-5.2"),
    "gemini-3.1-pro-preview": ("gemini", "gemini-3.1-pro-preview"),
}

DEFAULT_MODEL = "claude-sonnet-4-6"


def _provider_model(model_key: str):
    return MODEL_REGISTRY.get(model_key, MODEL_REGISTRY[DEFAULT_MODEL])


async def _run_chat(system: str, user_text: str, model_key: str, session_id: str) -> str:
    provider, model = _provider_model(model_key)
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=system,
    ).with_model(provider, model)
    response = await chat.send_message(UserMessage(text=user_text))
    return response if isinstance(response, str) else str(response)


def _extract_json(text: str) -> Dict[str, Any]:
    """Try hard to pull a JSON object out of a model response."""
    if not text:
        return {}
    # try fenced code blocks first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        candidate = m.group(1)
    else:
        # find first '{' and matching last '}'
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        # remove trailing commas and try again
        cleaned = re.sub(r",(\s*[}\]])", r"\1", candidate)
        try:
            return json.loads(cleaned)
        except Exception:
            return {}


# ---------- Meeting Brief ----------
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
  ],   // EXACTLY 3
  "issues": [
    {{ "title": "...", "description": "what's happening, transparent but not alarming",
       "action_plan": "what we're already doing + next step", "severity": "low|medium|high" }}
  ],   // EXACTLY 2
  "talking_points": [
    {{ "topic": "...", "angle": "how to frame it strategically in 1 sentence" }}
  ],   // 4-6 items
  "suggested_questions": [
    "open-ended engagement question 1",
    "..."
  ],   // 4-6 items; mix experience / emotional / outcome / future
  "testimonial_opportunity": "1-2 sentences naming whether this client is ready for testimonial ask and how to ask naturally — or 'Not yet, focus on results first' ",
  "strategic_recommendations": [
    "specific upsell/cross-sell/CRO/AI/operations recommendation 1",
    "..."
  ],   // 3-5 items
  "health_signal": "1 sentence summary of overall account health and trend"
}}
"""


async def generate_meeting_brief(
    client: Dict[str, Any],
    kpi_snapshot: Dict[str, Any],
    extra_context: Optional[str],
    model_key: str,
    session_id: str,
) -> Dict[str, Any]:
    user_text = BRIEF_USER_TEMPLATE.format(
        client_json=json.dumps(client, default=str),
        kpi_json=json.dumps(kpi_snapshot, default=str, indent=2),
        extra=extra_context or "(none)",
    )
    raw = await _run_chat(BRIEF_SYSTEM, user_text, model_key, session_id)
    data = _extract_json(raw)
    # safety defaults
    return {
        "wins": (data.get("wins") or [])[:3],
        "issues": (data.get("issues") or [])[:2],
        "talking_points": data.get("talking_points") or [],
        "suggested_questions": data.get("suggested_questions") or [],
        "testimonial_opportunity": data.get("testimonial_opportunity") or "",
        "strategic_recommendations": data.get("strategic_recommendations") or [],
        "health_signal": data.get("health_signal") or "",
        "_raw": raw if not data else None,
    }


# ---------- Transcript Analysis ----------
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
  "key_moments": [ "important moment 1", "..." ],   // 3-6 items
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
  "health_score_suggestion": 0-100
}}
"""


async def analyze_transcript(
    client_name: str, company: str, am_name: str, transcript: str, model_key: str, session_id: str
) -> Dict[str, Any]:
    user_text = TRANSCRIPT_USER_TEMPLATE.format(
        client_name=client_name or "Client",
        company=company or "",
        am_name=am_name or "Account Manager",
        transcript=transcript[:18000],
    )
    raw = await _run_chat(TRANSCRIPT_SYSTEM, user_text, model_key, session_id)
    data = _extract_json(raw)
    return {
        "summary": data.get("summary", ""),
        "sentiment": data.get("sentiment", "neutral"),
        "sentiment_summary": data.get("sentiment_summary", ""),
        "key_moments": data.get("key_moments", []),
        "action_items": data.get("action_items", []),
        "content_opportunities": data.get("content_opportunities", []),
        "churn_risk_signals": data.get("churn_risk_signals", []),
        "upsell_signals": data.get("upsell_signals", []),
        "health_score_suggestion": data.get("health_score_suggestion"),
        "_raw": raw if not data else None,
    }


# ---------- Recap ----------
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
    wins: List[Dict],
    issues: List[Dict],
    actions: List[Dict],
    model_key: str,
    session_id: str,
) -> Dict[str, Any]:
    user_text = RECAP_USER_TEMPLATE.format(
        client_name=client_name,
        company=company,
        title=title,
        wins=json.dumps(wins, default=str),
        issues=json.dumps(issues, default=str),
        actions=json.dumps(actions, default=str),
    )
    raw = await _run_chat(RECAP_SYSTEM, user_text, model_key, session_id)
    data = _extract_json(raw)
    if not data:
        return {"subject": f"Recap — {title}", "html": f"<pre>{raw}</pre>", "plain": raw}
    return {"subject": data.get("subject", f"Recap — {title}"), "html": data.get("html", ""), "plain": data.get("plain", "")}
