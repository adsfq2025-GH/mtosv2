from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import ai_visibility
import connectors
from db import db, new_id, utcnow
from models import ActionItem


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _available_providers() -> List[str]:
    out = []
    if os.environ.get("OPENAI_API_KEY", "").strip():
        out.append("openai")
    if os.environ.get("GEMINI_API_KEY", "").strip():
        out.append("gemini")
    if os.environ.get("PERPLEXITY_API_KEY", "").strip():
        out.append("perplexity")
    return out


def _extract_territory_from_query(q: str) -> Optional[str]:
    s = str(q or "").strip()
    if not s:
        return None
    m = re.search(r"\bin\s+([A-Za-z0-9][A-Za-z0-9 ,.-]{2,60})\s*$", s, flags=re.IGNORECASE)
    if not m:
        return None
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    if len(t) < 2:
        return None
    return t


def _address_to_market(addr: dict) -> str:
    if not isinstance(addr, dict):
        return ""
    loc = str(addr.get("locality") or "").strip()
    adm = str(addr.get("administrativeArea") or "").strip()
    if loc and adm:
        return f"{loc}, {adm}"
    return loc or adm or ""


def _build_verified_prompts(
    *,
    business_name: str,
    domain: str,
    services: List[str],
    categories: List[str],
    territories: List[str],
    max_total: int,
) -> List[dict]:
    terr = [str(x or "").strip() for x in (territories or []) if str(x or "").strip()]
    terr = list(dict.fromkeys(terr))[:25]
    svcs = [str(x or "").strip() for x in (services or []) if str(x or "").strip()]
    svcs = list(dict.fromkeys(svcs))[:15]
    cats = [str(x or "").strip() for x in (categories or []) if str(x or "").strip()]
    cats = list(dict.fromkeys(cats))[:6]
    if not svcs and cats:
        svcs = cats[:6]

    if not terr:
        return []

    def add(bucket: List[dict], territory: str, q: str, kind: str):
        if len(bucket) >= max_total:
            return
        bucket.append({"query": q, "prompt_kind": kind, "theme": "verified", "territory": territory})

    picked: List[dict] = []
    for t in terr:
        for s in svcs[:8]:
            add(picked, t, f"best {s} in {t}", "commercial")
            add(picked, t, f"{s} near {t}", "local")
            add(picked, t, f"top rated {s} in {t}", "local")
            add(picked, t, f"who should I hire for {s} in {t}", "recommendation")
            add(picked, t, f"how much does {s} cost in {t}", "informational")
            if len(picked) >= max_total:
                break
        if len(picked) >= max_total:
            break
    if not picked and business_name:
        for t in terr[:10]:
            add(picked, t, f"{business_name} in {t}", "brand")
    return picked[:max_total]


def _group_territories(prompts: List[dict], runs: List[dict]) -> Dict[str, Any]:
    by_query: Dict[str, Dict[str, Any]] = {}
    for r in runs or []:
        q = str(r.get("keyword") or r.get("query") or "").strip()
        if not q:
            continue
        by_query[q] = r

    terr: Dict[str, Dict[str, Any]] = {}
    for p in prompts or []:
        q = str(p.get("query") or "").strip()
        territory = str(p.get("territory") or "").strip() or _extract_territory_from_query(q) or ""
        if not q or not territory:
            continue
        row = terr.get(territory) or {"territory": territory, "total": 0, "hits": 0, "visibility_score": 0.0, "sample_queries": []}
        row["total"] = int(row["total"]) + 1
        run = by_query.get(q) or {}
        if bool(run.get("hit")):
            row["hits"] = int(row["hits"]) + 1
        if len(row["sample_queries"]) < 4:
            row["sample_queries"].append(q)
        terr[territory] = row

    items = []
    for t, row in terr.items():
        total = max(1, int(row.get("total") or 0))
        hits = int(row.get("hits") or 0)
        score = (float(hits) / float(total)) * 100.0
        items.append({**row, "visibility_score": round(score, 2)})

    items.sort(key=lambda x: float(x.get("visibility_score") or 0.0), reverse=True)
    strong = [x for x in items if float(x.get("visibility_score") or 0.0) >= 70.0]
    emerging = [x for x in items if 40.0 <= float(x.get("visibility_score") or 0.0) < 70.0]
    weak = [x for x in items if float(x.get("visibility_score") or 0.0) < 40.0]

    covered = [x for x in items if int(x.get("total") or 0) > 0]
    expansion_score = 0.0
    if covered:
        expansion_score = sum(float(x.get("visibility_score") or 0.0) for x in covered) / float(len(covered))

    opportunities = []
    for x in weak[:10]:
        opportunities.append(
            {
                "territory": x.get("territory"),
                "current_visibility_score": x.get("visibility_score"),
                "estimated_visibility_gain": round(max(0.0, 65.0 - float(x.get("visibility_score") or 0.0)), 2),
                "why": "Visibility is low for location-intent queries in this territory.",
            }
        )

    return {
        "territory_expansion_score": round(expansion_score, 2),
        "covered_markets": covered,
        "strong_markets": strong,
        "emerging_markets": emerging,
        "weak_markets": weak,
        "expansion_opportunities": opportunities,
    }


def _scan_change(prev: Optional[dict], cur: dict) -> Dict[str, Any]:
    if not prev:
        return {"has_prev": False, "changes": [], "delta": {}}
    pv = float(prev.get("overall_visibility_score") or 0.0)
    cv = float(cur.get("overall_visibility_score") or 0.0)
    dv = round(cv - pv, 2)
    changes = []
    if abs(dv) >= 5:
        changes.append({"kind": "visibility_score_change", "delta": dv})
    pr = int((prev.get("share_of_voice") or {}).get("market_rank") or 0) if isinstance(prev.get("share_of_voice"), dict) else 0
    cr = int((cur.get("share_of_voice") or {}).get("market_rank") or 0) if isinstance(cur.get("share_of_voice"), dict) else 0
    dr = (pr - cr) if (pr and cr) else 0
    if dr:
        changes.append({"kind": "market_rank_change", "delta": dr})
    return {"has_prev": True, "changes": changes, "delta": {"visibility_score": dv, "market_rank_delta": dr}}


def _confidence_from_sources(availability: Dict[str, Any]) -> Dict[str, Any]:
    gbp_ok = bool((availability.get("google_business_profile") or {}).get("ok"))
    website_ok = bool((availability.get("website") or {}).get("ok"))
    sc_ok = bool((availability.get("search_console") or {}).get("ok"))
    weights = {"google_business_profile": 0.6, "website": 0.25, "search_console": 0.15}
    score = 0.0
    score += weights["google_business_profile"] if gbp_ok else 0.0
    score += weights["website"] if website_ok else 0.0
    score += weights["search_console"] if sc_ok else 0.0
    pct = int(round(score * 100))
    level = "high" if pct >= 85 else "medium" if pct >= 60 else "low"
    return {"percent": pct, "level": level, "availability": availability}


async def _pick_google_business_profile_user_id(tenant_id: str, preferred_user_id: str) -> Optional[str]:
    if preferred_user_id:
        tok = await db.user_oauth_tokens.find_one({"tenant_id": tenant_id, "user_id": str(preferred_user_id), "platform": "google_business_profile"})
        if tok:
            return str(preferred_user_id)
    tok = await db.user_oauth_tokens.find_one({"tenant_id": tenant_id, "platform": "google_business_profile"})
    if tok:
        return str(tok.get("user_id") or "")
    return None

async def run_ai_territory_scan_for_client(
    *,
    tenant_id: str,
    client_doc: dict,
    user_id: Optional[str] = None,
    max_prompts: int,
    min_hours_between_scans: int = 24,
    force: bool = False,
    reason: str = "scheduled",
) -> Dict[str, Any]:
    cfg_doc = await db.ai_visibility_configs.find_one({"$and": [{"client_id": str(client_doc.get("_id"))}, {"tenant_id": tenant_id}]})
    if not cfg_doc:
        intel0 = {}
        cfg = {
            "_id": new_id(),
            "tenant_id": tenant_id,
            "client_id": str(client_doc.get("_id")),
            "market": "",
            "keywords": [],
            "brand_override": None,
            "domain_override": None,
            "enabled": True,
            "created_at": utcnow().isoformat(),
            "updated_at": utcnow().isoformat(),
        }
        await db.ai_visibility_configs.insert_one(cfg)
        cfg_doc = cfg

    config_id = str(cfg_doc.get("_id"))
    client_id = str(client_doc.get("_id"))

    last = await db.ai_visibility_scans.find_one(
        {"$and": [{"config_id": config_id}, {"tenant_id": tenant_id}, {"client_id": client_id}]},
        sort=[("created_at", -1)],
    )
    if last and not force:
        try:
            last_ts = datetime.fromisoformat(str(last.get("created_at") or "")).replace(tzinfo=timezone.utc)
            if (utcnow() - last_ts) < timedelta(hours=max(1, int(min_hours_between_scans or 24))):
                return {"ok": True, "skipped": True, "reason": "recent_scan", "scan": last}
        except Exception:
            pass

    if not bool(cfg_doc.get("enabled", True)):
        return {"ok": False, "error": "disabled", "error_detail": "AI visibility config is disabled"}

    client_id = str(client_doc.get("_id"))
    picked_user_id = await _pick_google_business_profile_user_id(tenant_id, str(user_id or client_doc.get("account_manager_id") or ""))
    gbp_profile = None
    gbp_err = None
    if picked_user_id:
        gbp_res = await connectors.fetch_gbp_profile_for_client(tenant_id, user_id=picked_user_id, client_id=client_id)
        if gbp_res.get("ok"):
            gbp_profile = gbp_res
        else:
            gbp_err = gbp_res.get("error") or "gbp_error"

    website_raw = str(client_doc.get("website") or "").strip()
    website_ok = bool(website_raw)

    availability = {
        "google_business_profile": {"ok": bool(gbp_profile), "error": gbp_err, "binding": bool(await db.client_bindings.find_one({"$and": [{"tenant_id": tenant_id}, {"client_id": client_id}, {"platform": "google_business_profile"}, {"enabled": True}]}))},
        "website": {"ok": website_ok},
        "search_console": {"ok": False},
        "citations": {"ok": False},
        "competitors": {"ok": False},
    }
    conf = _confidence_from_sources(availability)

    business_name = str((gbp_profile or {}).get("business_name") or client_doc.get("company") or client_doc.get("name") or "").strip()
    brand = str(business_name or "").strip()
    domain = ai_visibility.infer_brand_and_domain(client_doc, cfg_doc.get("brand_override"), cfg_doc.get("domain_override"))[1]

    categories = (gbp_profile or {}).get("categories") or []
    services = client_doc.get("services") or []
    territories = (gbp_profile or {}).get("service_areas") or []
    if not territories and gbp_profile and isinstance((gbp_profile or {}).get("storefront_address"), dict):
        mkt = _address_to_market((gbp_profile or {}).get("storefront_address") or {})
        if mkt:
            territories = [mkt]
    if not territories and isinstance(client_doc.get("gbp_data"), dict):
        addr = (client_doc.get("gbp_data") or {}).get("storefrontAddress") or {}
        mkt = _address_to_market(addr if isinstance(addr, dict) else {})
        if mkt:
            territories = [mkt]

    prompts = _build_verified_prompts(
        business_name=business_name,
        domain=domain,
        services=services if isinstance(services, list) else [],
        categories=categories if isinstance(categories, list) else [],
        territories=territories if isinstance(territories, list) else [],
        max_total=max(10, min(int(max_prompts or 60), 200)),
    )
    if not prompts:
        return {
            "ok": False,
            "error": "data_not_available",
            "error_detail": "Data Not Available: missing verified service areas (GBP Service Areas or verified address city/state). Connect GBP or add verified service areas.",
            "data_confidence": conf,
        }

    providers = _available_providers()
    if not providers:
        return {"ok": False, "error": "missing_providers", "error_detail": "No AI providers configured. Set GEMINI_API_KEY and/or OPENAI_API_KEY and/or PERPLEXITY_API_KEY."}

    scan_id = new_id()
    created = 0
    hit_count = 0
    per_provider = {p: {"hits": 0, "total": 0, "errors": 0} for p in providers}
    runs_for_metrics = []

    for it in prompts:
        for p in providers:
            per_provider[p]["total"] += 1
            try:
                r = await ai_visibility.scan_keyword(provider=p, keyword=it["query"], market="", brand=brand, domain=domain)
                run_doc = {
                    "_id": new_id(),
                    "tenant_id": tenant_id,
                    "config_id": config_id,
                    "client_id": client_id,
                    "scan_id": scan_id,
                    "market": "",
                    "keyword": it["query"],
                    "theme": it.get("theme"),
                    "prompt_kind": it.get("prompt_kind"),
                    "provider": p,
                    "prompt": r.get("prompt") or "",
                    "response_text": r.get("response_text") or "",
                    "parsed": r.get("parsed") or {},
                    "hit": bool(r.get("hit")),
                    "hit_brand": bool(r.get("hit_brand")),
                    "hit_domain": bool(r.get("hit_domain")),
                    "created_at": utcnow().isoformat(),
                    "updated_at": utcnow().isoformat(),
                }
                await db.ai_visibility_runs.insert_one(run_doc)
                created += 1
                if run_doc["hit"]:
                    hit_count += 1
                    per_provider[p]["hits"] += 1
                runs_for_metrics.append(run_doc)
            except Exception:
                per_provider[p]["errors"] += 1

    total = sum(int(per_provider[p]["total"]) for p in providers)
    score = (float(hit_count) / float(total)) * 100.0 if total else 0.0
    comp = ai_visibility.competitor_discovery_from_runs(runs_for_metrics, brand=brand, domain=domain)
    platform_rankings = {}
    for p in providers:
        pt = int(per_provider[p]["total"] or 0)
        ph = int(per_provider[p]["hits"] or 0)
        platform_rankings[p] = {"hits": ph, "total": pt, "score": round((float(ph) / float(pt) * 100.0) if pt else 0.0, 2)}

    territory = _group_territories(prompts, runs_for_metrics)

    scan_doc = {
        "_id": new_id(),
        "tenant_id": tenant_id,
        "config_id": config_id,
        "client_id": client_id,
        "scan_id": scan_id,
        "market": "",
        "brand": brand,
        "domain": domain,
        "providers": per_provider,
        "total": total,
        "hits": hit_count,
        "overall_visibility_score": round(score, 2),
        "share_of_voice": {"items": comp.get("share_of_voice") or [], "market_rank": comp.get("market_rank")},
        "platform_rankings": platform_rankings,
        "themes": [],
        "prompts_total": len(prompts),
        "competitors": comp.get("competitors") or [],
        "content_intelligence": {"status": "generated", "source": "website+gbp"},
        "growth_engine": {"status": "generated", "source": "scan_mentions"},
        "territory_intelligence": territory,
        "data_confidence": conf,
        "created_at": utcnow().isoformat(),
        "updated_at": utcnow().isoformat(),
    }

    prev = await db.ai_visibility_scans.find_one(
        {"$and": [{"config_id": config_id}, {"tenant_id": tenant_id}, {"client_id": client_id}, {"scan_id": {"$ne": scan_id}}]},
        sort=[("created_at", -1)],
    )
    change = _scan_change(prev, scan_doc)
    scan_doc["growth_engine"] = {**(scan_doc.get("growth_engine") or {}), "delta": change.get("delta"), "changes": change.get("changes"), "reason": reason}

    await db.ai_visibility_scans.insert_one(scan_doc)
    await db.ai_visibility_configs.update_one({"_id": config_id, "tenant_id": tenant_id}, {"$set": {"market": "", "updated_at": utcnow().isoformat()}})

    delta = (change.get("delta") or {}) if isinstance(change, dict) else {}
    opps0 = (territory.get("expansion_opportunities") or []) if isinstance(territory, dict) else []
    tp: List[dict] = []
    dv = float(delta.get("visibility_score") or 0.0)
    if abs(dv) >= 5:
        tp.append({"topic": "AI visibility change", "angle": f"Visibility score changed by {dv} points since the previous scan. We should explain why and what we are doing next."})
    if opps0:
        o0 = opps0[0] if isinstance(opps0[0], dict) else {}
        t0 = str(o0.get("territory") or "").strip()
        if t0:
            tp.append({"topic": "Territory expansion", "angle": f"Visibility is weak in {t0}. Recommended next steps to improve coverage and capture demand in that territory."})
    if not tp:
        tp.append({"topic": "Visibility & territory", "angle": "No major changes detected. Confirm ongoing coverage and identify the next best expansion territory."})

    client_patch = {
        "crm_data.ai_territory_intelligence": {
            "scan_id": scan_id,
            "last_scan_at": scan_doc.get("created_at"),
            "overall_visibility_score": scan_doc.get("overall_visibility_score"),
            "share_of_voice": scan_doc.get("share_of_voice"),
            "visibility_delta": (change.get("delta") or {}).get("visibility_score"),
            "market_rank_delta": (change.get("delta") or {}).get("market_rank_delta"),
            "territory": territory,
            "opportunities": (territory.get("expansion_opportunities") or [])[:10],
            "meeting_talking_points": tp,
            "data_sources_used": [k for k, v in (availability or {}).items() if isinstance(v, dict) and v.get("ok")],
            "source_availability": availability,
            "confidence": conf,
            "calculation_logic": "Visibility scores are computed as hit_rate = brand_or_domain_mentioned / total_prompts across configured AI providers. Territory scores are computed from location-intent prompts grouped by territory.",
        },
        "updated_at": utcnow().isoformat(),
    }
    await db.clients.update_one({"_id": client_id, "tenant_id": tenant_id}, {"$set": client_patch})

    await _emit_events_and_actions(tenant_id=tenant_id, client_doc=client_doc, scan=scan_doc, change=change)
    return {"ok": True, "scan_id": scan_id, "scan": scan_doc, "created_runs": created, "providers": providers}


async def _emit_events_and_actions(*, tenant_id: str, client_doc: dict, scan: dict, change: dict) -> None:
    client_id = str(client_doc.get("_id") or "")
    am_id = str(client_doc.get("account_manager_id") or "")
    am_name = str(client_doc.get("account_manager_name") or "")
    company = str(client_doc.get("company") or client_doc.get("name") or "").strip()

    delta = (change.get("delta") or {}) if isinstance(change, dict) else {}
    dv = float(delta.get("visibility_score") or 0.0)
    dr = int(delta.get("market_rank_delta") or 0)

    now = utcnow().isoformat()
    events: List[dict] = []
    if dv >= 5:
        events.append(
            {
                "_id": new_id(),
                "tenant_id": tenant_id,
                "client_id": client_id,
                "account_manager_id": am_id,
                "kind": "win",
                "severity": "low",
                "title": "AI visibility improved",
                "description": f"{company} visibility score increased by {dv} points versus the previous scan.",
                "scan_id": scan.get("scan_id"),
                "explain": {
                    "why": "A higher share of prompts returned responses that mentioned the client brand or domain.",
                    "sources": ["ai_visibility_runs", "prompt_intelligence", "client_profile"],
                    "context": "This impacts what AI platforms are likely to recommend when consumers ask local service questions.",
                    "calculation_logic": "delta = current_overall_visibility_score - previous_overall_visibility_score",
                },
                "created_at": now,
                "updated_at": now,
            }
        )
    if dv <= -5:
        events.append(
            {
                "_id": new_id(),
                "tenant_id": tenant_id,
                "client_id": client_id,
                "account_manager_id": am_id,
                "kind": "issue",
                "severity": "high",
                "title": "AI visibility declined",
                "description": f"{company} visibility score decreased by {abs(dv)} points versus the previous scan.",
                "scan_id": scan.get("scan_id"),
                "explain": {
                    "why": "Fewer prompts returned responses that mentioned the client brand or domain.",
                    "sources": ["ai_visibility_runs", "prompt_intelligence", "client_profile"],
                    "context": "This can reduce AI-driven referrals in the client’s service areas.",
                    "calculation_logic": "delta = current_overall_visibility_score - previous_overall_visibility_score",
                },
                "created_at": now,
                "updated_at": now,
            }
        )
    if dr:
        events.append(
            {
                "_id": new_id(),
                "tenant_id": tenant_id,
                "client_id": client_id,
                "account_manager_id": am_id,
                "kind": "alert",
                "severity": "medium",
                "title": "Competitor position changed",
                "description": f"{company} market rank changed by {dr} position(s) versus the previous scan.",
                "scan_id": scan.get("scan_id"),
                "explain": {
                    "why": "Competitor mentions shifted in the AI model outputs.",
                    "sources": ["ai_visibility_runs"],
                    "context": "This indicates competitor pressure or improved positioning for the client.",
                    "calculation_logic": "market_rank_delta = previous_market_rank - current_market_rank",
                },
                "created_at": now,
                "updated_at": now,
            }
        )

    territory = (scan.get("territory_intelligence") or {}) if isinstance(scan.get("territory_intelligence"), dict) else {}
    opps = territory.get("expansion_opportunities") or []
    for opp in (opps[:3] if isinstance(opps, list) else []):
        t = str(opp.get("territory") or "").strip()
        if not t:
            continue
        title = f"Expand visibility in {t}"
        desc = f"Current territory visibility is {opp.get('current_visibility_score')}%. Estimated gain: +{opp.get('estimated_visibility_gain')}."
        events.append(
            {
                "_id": new_id(),
                "tenant_id": tenant_id,
                "client_id": client_id,
                "account_manager_id": am_id,
                "kind": "opportunity",
                "severity": "medium",
                "title": title,
                "description": desc,
                "scan_id": scan.get("scan_id"),
                "explain": {
                    "why": str(opp.get("why") or ""),
                    "sources": ["ai_visibility_runs", "prompt_intelligence"],
                    "context": "Use this to guide territory expansion planning and content/citation work.",
                    "calculation_logic": "territory_score = hits_for_territory / prompts_for_territory",
                },
                "created_at": now,
                "updated_at": now,
            }
        )

        if am_id:
            due = (utcnow().date() + timedelta(days=7)).isoformat()
            a = ActionItem(
                tenant_id=tenant_id,
                meeting_id=None,
                client_id=client_id,
                title=title,
                description=desc,
                owner=am_name or am_id,
                owner_type="agency",
                due_date=due,
                status="open",
                priority="medium",
            )
            await db.action_items.insert_one(a.to_mongo())

    if events:
        await db.ai_territory_events.insert_many(events)
