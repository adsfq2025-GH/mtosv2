from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

import ai


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def infer_brand_and_domain(
    client: Dict[str, Any],
    brand_override: Optional[str],
    domain_override: Optional[str],
) -> Tuple[str, str]:
    brand = str(brand_override or "").strip()
    if not brand:
        brand = str(client.get("company") or "").strip() or str(client.get("name") or "").strip()

    domain = str(domain_override or "").strip()
    if not domain:
        website = str(client.get("website") or "").strip()
        if website:
            p = urlparse(website if "://" in website else f"https://{website}")
            host = (p.netloc or "").strip().lower()
            host = host[4:] if host.startswith("www.") else host
            domain = host

    return brand, domain


def score_visibility(response_text: str, brand: str, domain: str) -> Dict[str, Any]:
    text = str(response_text or "")
    tnorm = _norm(text)
    brand_norm = _norm(brand)
    domain_norm = _norm(domain)
    hit_brand = bool(brand_norm and brand_norm in tnorm)
    hit_domain = bool(domain_norm and domain_norm in tnorm)
    return {"hit": bool(hit_brand or hit_domain), "hit_brand": hit_brand, "hit_domain": hit_domain}


def build_prompt(keyword: str, market: str, brand: str, domain: str) -> str:
    mk = str(market or "").strip()
    k = str(keyword or "").strip()
    b = str(brand or "").strip()
    d = str(domain or "").strip()
    market_part = f"in {mk}" if mk else ""
    match_part = f"brand={b}" + (f", domain={d}" if d else "")
    return (
        "Return STRICT JSON only.\n"
        f"Task: For the query {k!r} {market_part}, list the top 10 businesses/services that a consumer would choose.\n"
        "JSON shape: {\"query\": string, \"market\": string, \"results\": [{\"name\": string, \"domain\": string, \"why\": string}]}\n"
        f"IMPORTANT: One of the brands we are checking for is: {match_part}. Include a domain when you can.\n"
        "Do not include markdown. Do not include extra keys."
    )


async def _call_openai_compatible(
    *,
    url: str,
    api_key: str,
    model: str,
    prompt: str,
) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise JSON generator. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        raise ai.AIProviderError(f"Provider http {resp.status_code}: {resp.text[:400]}")
    data = resp.json() or {}
    content = (((data.get("choices") or [None])[0] or {}).get("message") or {}).get("content")
    return str(content or "").strip()


async def scan_keyword(
    *,
    provider: str,
    keyword: str,
    market: str,
    brand: str,
    domain: str,
) -> Dict[str, Any]:
    prompt = build_prompt(keyword=keyword, market=market, brand=brand, domain=domain)
    provider = str(provider or "").strip().lower()

    if provider == "gemini":
        text = await ai.run_chat(system="You are a precise JSON generator. Output JSON only.", user_text=prompt, model_key="gemini-direct")
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ai.AIProviderError("Missing OPENAI_API_KEY")
        model = os.environ.get("AI_VISIBILITY_OPENAI_MODEL", "gpt-4o-mini").strip()
        text = await _call_openai_compatible(url="https://api.openai.com/v1/chat/completions", api_key=api_key, model=model, prompt=prompt)
    elif provider == "perplexity":
        api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
        if not api_key:
            raise ai.AIProviderError("Missing PERPLEXITY_API_KEY")
        model = os.environ.get("AI_VISIBILITY_PERPLEXITY_MODEL", "sonar-pro").strip()
        text = await _call_openai_compatible(url="https://api.perplexity.ai/chat/completions", api_key=api_key, model=model, prompt=prompt)
    else:
        raise ai.AIProviderError(f"Unknown provider: {provider}")

    parsed = ai._extract_json(text) or {}
    score = score_visibility(text, brand=brand, domain=domain)
    return {"prompt": prompt, "response_text": text, "parsed": parsed, **score}

