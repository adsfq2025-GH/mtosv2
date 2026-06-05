from __future__ import annotations

import os
import re
import json
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
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


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        t = str(tag or "").lower()
        if t in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        t = str(tag or "").lower()
        if t in ("script", "style", "noscript") and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        s = re.sub(r"\s+", " ", str(data or "").strip())
        if s:
            self._parts.append(s)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


async def fetch_website_text(url: str) -> Dict[str, Any]:
    u = str(url or "").strip()
    if not u:
        return {"ok": False, "url": "", "title": "", "text": "", "error": "missing_url"}
    if "://" not in u:
        u = f"https://{u}"
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            resp = await client.get(u, headers={"User-Agent": "mtos-ai-visibility/1.0"})
        if resp.status_code >= 400:
            return {"ok": False, "url": u, "title": "", "text": "", "error": f"http_{resp.status_code}"}
        html = str(resp.text or "")
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
        parser = _TextExtractor()
        parser.feed(html[:250000])
        text = parser.text()
        if len(text) > 9000:
            text = text[:9000]
        return {"ok": True, "url": u, "title": title, "text": text}
    except Exception as e:
        return {"ok": False, "url": u, "title": "", "text": "", "error": str(e)[:200]}


PROMPT_INTELLIGENCE_SYSTEM = """You are an AI Visibility prompt intelligence engine.
You produce theme discovery and prompt sets for scanning AI search visibility for a specific local business.
Return a single STRICT JSON object only.

Rules:
- No manual input is available. You must infer everything from WEBSITE, GBP DATA, and SERVICES.
- Prompts should be realistic consumer queries.
- Include a mix of: commercial, local, informational, comparison, recommendation, service, location prompts.
- Keep prompts concise (6-14 words) and include location where relevant.
- Output themes dynamically for this specific business (service themes, trust, pricing, reviews, location, industry, competitor).
- Do not include markdown or extra keys."""


PROMPT_INTELLIGENCE_USER = """BUSINESS:
name={name}
company={company}
services={services}

GBP DATA (may be partial):
{gbp_json}

WEBSITE:
url={website_url}
title={website_title}
text_excerpt={website_text}

Return JSON shape:
{{
  "market": "City, State or primary service area (best-effort)",
  "themes": [
    {{
      "name": "Theme name",
      "type": "service | trust | pricing | reviews | location | industry | competitor",
      "prompts": [
        {{
          "kind": "commercial | local | informational | comparison | recommendation | service | location",
          "query": "consumer query"
        }}
      ]
    }}
  ]
}}
"""


async def generate_prompt_intelligence(client: Dict[str, Any]) -> Dict[str, Any]:
    website = await fetch_website_text(str(client.get("website") or ""))
    user = PROMPT_INTELLIGENCE_USER.format(
        name=str(client.get("name") or ""),
        company=str(client.get("company") or ""),
        services=", ".join([str(s or "").strip() for s in (client.get("services") or []) if str(s or "").strip()]),
        gbp_json=json.dumps(client.get("gbp_data") or {}, default=str),
        website_url=str(website.get("url") or ""),
        website_title=str(website.get("title") or ""),
        website_text=str(website.get("text") or ""),
    )
    raw = await ai.run_chat(system=PROMPT_INTELLIGENCE_SYSTEM, user_text=user, model_key="gemini-direct")
    parsed = ai._extract_json(raw) or {}
    themes = parsed.get("themes") or []
    if isinstance(themes, dict):
        themes = [themes]
    if not isinstance(themes, list):
        themes = []
    out_themes = []
    prompts_total = 0
    for t in themes[:20]:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        ttype = str(t.get("type") or "").strip()
        ps = t.get("prompts") or []
        if isinstance(ps, dict):
            ps = [ps]
        if not isinstance(ps, list):
            ps = []
        cleaned = []
        for p in ps[:20]:
            if not isinstance(p, dict):
                continue
            q = str(p.get("query") or "").strip()
            kind = str(p.get("kind") or "").strip()
            if not q:
                continue
            cleaned.append({"kind": kind or "commercial", "query": q})
        if not name or not cleaned:
            continue
        prompts_total += len(cleaned)
        out_themes.append({"name": name, "type": ttype or "service", "prompts": cleaned})
    market = str(parsed.get("market") or "").strip()
    return {
        "market": market,
        "themes": out_themes,
        "prompts_total": prompts_total,
        "website": website,
        "_raw": raw if not parsed else None,
    }


def competitor_discovery_from_runs(runs: List[Dict[str, Any]], brand: str, domain: str) -> Dict[str, Any]:
    brand_norm = _norm(brand)
    domain_norm = _norm(domain)
    counts: Dict[str, Dict[str, Any]] = {}
    client_mentions = 0
    total_mentions = 0
    for r in runs or []:
        parsed = (r.get("parsed") or {}) if isinstance(r, dict) else {}
        results = parsed.get("results") or []
        if not isinstance(results, list):
            continue
        for it in results[:10]:
            if not isinstance(it, dict):
                continue
            nm = str(it.get("name") or "").strip()
            dm = str(it.get("domain") or "").strip()
            if not nm and not dm:
                continue
            total_mentions += 1
            nkey = _norm(dm or nm)
            if brand_norm and brand_norm in _norm(nm):
                client_mentions += 1
                continue
            if domain_norm and domain_norm and domain_norm in _norm(dm):
                client_mentions += 1
                continue
            if not nkey:
                continue
            row = counts.get(nkey) or {"name": nm, "domain": dm, "mentions": 0}
            row["mentions"] = int(row.get("mentions") or 0) + 1
            if nm and not row.get("name"):
                row["name"] = nm
            if dm and not row.get("domain"):
                row["domain"] = dm
            counts[nkey] = row

    comps = sorted(counts.values(), key=lambda x: int(x.get("mentions") or 0), reverse=True)
    top = comps[:12]
    share = []
    denom = max(1, total_mentions + client_mentions)
    client_sov = float(client_mentions) / float(denom)
    share.append({"name": brand or "Client", "domain": domain or "", "share": round(client_sov, 4), "mentions": client_mentions, "is_client": True})
    for c in top[:8]:
        share.append({"name": c.get("name") or "", "domain": c.get("domain") or "", "share": round(float(c.get("mentions") or 0) / float(denom), 4), "mentions": int(c.get("mentions") or 0), "is_client": False})

    ranked = sorted(share, key=lambda x: float(x.get("share") or 0.0), reverse=True)
    market_rank = None
    for idx, row in enumerate(ranked, start=1):
        if row.get("is_client"):
            market_rank = idx
            break

    return {"competitors": top, "share_of_voice": share, "market_rank": market_rank}


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
