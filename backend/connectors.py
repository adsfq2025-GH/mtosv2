from __future__ import annotations

import base64
import os
import re
from html import unescape
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import HTTPException

from db import decrypt_secret, encrypt_secret
from oauth_runtime import (
    decode_inline_oauth_connection_ref,
    get_google_oauth_runtime_doc,
)
from runtime_bridge import get_runtime_bridge


def _demo_kpi_enabled() -> bool:
    return str(os.environ.get("ENABLE_DEMO_KPI_SNAPSHOT", "") or "").strip().lower() in ("1", "true", "yes", "on")


def _tenant_scope(tenant_id: str) -> dict:
    return {"tenant_id": tenant_id}


async def _get_integration_doc(tenant_id: str, platform: str) -> Optional[dict]:
    return await get_runtime_bridge().get_tenant_integration(tenant_id, platform)


async def get_credentials(tenant_id: str, platform: str) -> Dict[str, str]:
    doc = await _get_integration_doc(tenant_id, platform)
    if not doc:
        return {}
    enc = doc.get("credentials_encrypted") or {}
    meta = doc.get("metadata") or {}
    dec = {k: decrypt_secret(v) for k, v in enc.items()} if enc else {}
    return {**meta, **dec}


def _clickup_token_from_creds(creds: Dict[str, str]) -> str:
    return _strip_bearer((creds or {}).get("api_token") or (creds or {}).get("access_token") or "")


async def get_clickup_access_token(tenant_id: str) -> str:
    return _clickup_token_from_creds(await get_credentials(tenant_id, "clickup"))


def _clean_oauth_str(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    for _ in range(3):
        s2 = s.strip()
        if len(s2) >= 2 and (
            (s2[0] == "`" and s2[-1] == "`")
            or (s2[0] == '"' and s2[-1] == '"')
            or (s2[0] == "'" and s2[-1] == "'")
        ):
            s = s2[1:-1].strip()
            continue
        s = s2
        break
    s = s.replace("`", "").strip()
    return s


async def get_google_refresh_token(tenant_id: str, user_id: str, platform: str) -> str:
    runtime_doc = await get_google_oauth_runtime_doc(tenant_id, user_id, platform)
    return decode_inline_oauth_connection_ref((runtime_doc or {}).get("oauth_connection_ref"))


async def get_client_binding(tenant_id: str, client_id: str, platform: str) -> Optional[dict]:
    bridge_doc = await get_runtime_bridge().get_client_binding(tenant_id, client_id, platform)
    if bridge_doc:
        return bridge_doc
    return None


async def _save_client_binding(tenant_id: str, client_id: str, doc: dict) -> Optional[dict]:
    if get_runtime_bridge().is_enabled_for("client_bindings"):
        return await get_runtime_bridge().upsert_client_binding(tenant_id, client_id, doc)
    return dict(doc or {})


async def _update_client_binding_external_ids(tenant_id: str, client_id: str, platform: str, patch: dict[str, Any]) -> Optional[dict]:
    existing = await get_client_binding(tenant_id, client_id, platform)
    if not existing:
        return None
    next_doc = dict(existing or {})
    next_doc["platform"] = str(platform or "").strip().lower()
    next_doc["enabled"] = bool(next_doc.get("enabled", True))
    next_external_ids = dict(next_doc.get("external_ids") or {})
    next_external_ids.update(dict(patch or {}))
    next_doc["external_ids"] = next_external_ids
    next_doc["updated_at"] = _utc_now().isoformat()
    return await _save_client_binding(tenant_id, client_id, next_doc)


def _ghl_location_tokens_map(doc: Optional[dict]) -> dict[str, str]:
    metadata = dict((doc or {}).get("metadata") or {})
    return dict(metadata.get("location_tokens_encrypted") or {})


async def list_gohighlevel_location_token_ids(tenant_id: str) -> list[str]:
    integration_doc = await _get_integration_doc(tenant_id, "gohighlevel")
    bridge_ids = sorted({str(location_id or "").strip() for location_id in _ghl_location_tokens_map(integration_doc).keys() if str(location_id or "").strip()})
    if bridge_ids:
        return bridge_ids
    return []


async def upsert_gohighlevel_location_token(tenant_id: str, location_id: str, token: str) -> bool:
    lid = str(location_id or "").strip()
    tok = str(token or "").strip()
    if not lid or not tok:
        return False
    integration_doc = await _get_integration_doc(tenant_id, "gohighlevel") or {
        "tenant_id": tenant_id,
        "platform": "gohighlevel",
        "label": "gohighlevel",
        "status": "connected",
        "metadata": {},
    }
    metadata = dict((integration_doc or {}).get("metadata") or {})
    location_tokens = _ghl_location_tokens_map(integration_doc)
    location_tokens[lid] = encrypt_secret(tok)
    metadata["location_tokens_encrypted"] = location_tokens
    integration_doc["metadata"] = metadata
    integration_doc["status"] = str(integration_doc.get("status") or "connected").strip() or "connected"
    bridge_doc = None
    if get_runtime_bridge().is_enabled_for("integrations"):
        bridge_doc = await get_runtime_bridge().upsert_tenant_integration(tenant_id, integration_doc)
    return bool(bridge_doc)


async def delete_gohighlevel_location_token(tenant_id: str, location_id: str) -> bool:
    lid = str(location_id or "").strip()
    if not lid:
        return False
    integration_doc = await _get_integration_doc(tenant_id, "gohighlevel")
    updated_bridge = False
    if integration_doc:
        metadata = dict((integration_doc or {}).get("metadata") or {})
        location_tokens = _ghl_location_tokens_map(integration_doc)
        if lid in location_tokens:
            location_tokens.pop(lid, None)
            metadata["location_tokens_encrypted"] = location_tokens
            integration_doc["metadata"] = metadata
            updated_doc = await get_runtime_bridge().upsert_tenant_integration(tenant_id, integration_doc)
            updated_bridge = updated_doc is not None
    return updated_bridge


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _last_30_days_range() -> Tuple[date, date]:
    end = _utc_now().date()
    start = end - timedelta(days=30)
    return start, end


def _period_meta(
    cur_start: Optional[date] = None,
    cur_end: Optional[date] = None,
    prev_start: Optional[date] = None,
    prev_end: Optional[date] = None,
) -> Dict[str, Any]:
    cur_start = cur_start or _last_30_days_range()[0]
    cur_end = cur_end or _last_30_days_range()[1]
    delta_days = max((cur_end - cur_start).days, 1)
    prev_end = prev_end or (cur_start - timedelta(days=1))
    prev_start = prev_start or (prev_end - timedelta(days=delta_days))

    def month_label(d: date) -> str:
        return d.strftime("%b %Y")

    return {
        "current": {"start": cur_start.isoformat(), "end": cur_end.isoformat(), "label": month_label(cur_end)},
        "comparison": {"start": prev_start.isoformat(), "end": prev_end.isoformat(), "label": month_label(prev_end)},
        "kind": f"days_{delta_days}_vs_prior_{delta_days}",
    }


def _fmt_mmddyyyy(d: date) -> str:
    return d.strftime("%m-%d-%Y")


def _strip_bearer(token: str) -> str:
    t = (token or "").strip()
    if t.lower().startswith("bearer "):
        return t[7:].strip()
    return t


def _safe_err_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json() or {}
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("status") or err.get("code")
                details = err.get("details")
                if isinstance(details, list) and details:
                    first = details[0]
                    if isinstance(first, dict):
                        msg = msg or first.get("message") or first.get("reason")
                if msg:
                    return str(msg)
            if data.get("message"):
                return str(data.get("message"))
            if data.get("err"):
                return str(data.get("err"))
            if data.get("error"):
                return str(data.get("error"))
        return str(data)[:300]
    except Exception:
        text = str(resp.text or "").strip()
        low = text.lower()
        if "<html" in low or "<!doctype" in low:
            m = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()
                if title:
                    return f"html_error_page: {title[:220]}"
            m = re.search(r"<h1[^>]*>(.*?)</h1>", text, flags=re.I | re.S)
            if m:
                h1 = re.sub(r"\s+", " ", m.group(1)).strip()
                if h1:
                    return f"html_error_page: {h1[:220]}"
            return f"html_error_page_http_{resp.status_code}"
        return text[:300]


async def fetch_clickup_monthly(creds: Dict[str, str], binding: dict, start_d: Optional[date] = None, end_d: Optional[date] = None) -> Dict[str, Any]:
    token = _strip_bearer((creds or {}).get("api_token", ""))
    team_id = (
        (binding.get("external_ids") or {}).get("team_id")
        or (binding.get("config") or {}).get("team_id")
        or (creds or {}).get("team_id")
    )
    folder_id = (binding.get("external_ids") or {}).get("folder_id") or (binding.get("config") or {}).get("folder_id")
    if not token or not folder_id:
        return {}

    headers = {"Authorization": token, "Accept": "application/json"}
    if not team_id:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get("https://api.clickup.com/api/v2/team", headers=headers)
        if r.status_code == 200:
            teams = (r.json() or {}).get("teams") or []
            team_id = (teams[0] or {}).get("id") if teams else None
        if not team_id:
            return {"error": "clickup_missing_team_id", "error_detail": "Missing ClickUp workspace/team_id. Set it in Integrations → ClickUp."}

    start_d = start_d or _last_30_days_range()[0]
    start_dt = (
        start_d
        if isinstance(start_d, datetime)
        else datetime(int(start_d.year), int(start_d.month), int(start_d.day), tzinfo=timezone.utc)
    )
    if isinstance(start_dt, datetime) and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    date_updated_gt = str(int(start_dt.timestamp() * 1000))
    url = f"https://api.clickup.com/api/v2/team/{team_id}/task"
    params = [
        ("include_closed", "true"),
        ("subtasks", "true"),
        ("date_updated_gt", date_updated_gt),
        ("project_ids[]", str(folder_id)),
        ("page", "0"),
    ]

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return {"error": f"clickup_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}

    try:
        data = resp.json() or {}
    except Exception:
        return {"error": "clickup_bad_json", "error_detail": (resp.text or "")[:300]}
    tasks = data.get("tasks") or []
    now = _utc_now()

    open_tasks = 0
    overdue_tasks = 0
    completed_recent = 0

    for t in tasks:
        status = ((t.get("status") or {}).get("status") or "").lower()
        is_closed = bool((t.get("status") or {}).get("type") == "closed") or status in ("closed", "complete", "completed", "done")
        due_ms = t.get("due_date")
        closed_ms = t.get("date_closed")

        if not is_closed:
            open_tasks += 1
            if due_ms:
                try:
                    due_dt = datetime.fromtimestamp(int(due_ms) / 1000, tz=timezone.utc)
                    if due_dt < now:
                        overdue_tasks += 1
                except Exception:
                    pass

        if is_closed and closed_ms:
            try:
                closed_dt = datetime.fromtimestamp(int(closed_ms) / 1000, tz=timezone.utc)
                if (now - closed_dt).days <= 30:
                    completed_recent += 1
            except Exception:
                pass

    return {
        "open_tasks": open_tasks,
        "overdue_tasks": overdue_tasks,
        "completed_last_30_days": completed_recent,
        "team_id": str(team_id),
        "folder_id": str(folder_id),
    }


async def fetch_gohighlevel_monthly(tenant_id: str, binding: dict, start_d: Optional[date] = None, end_d: Optional[date] = None) -> Dict[str, Any]:
    location_id = (
        (binding.get("external_ids") or {}).get("location_id")
        or (binding.get("config") or {}).get("location_id")
    )
    api_key = await _gohighlevel_token_for_location(tenant_id, str(location_id or ""))
    if not api_key or not location_id:
        return {}

    if not start_d or not end_d:
        start_d, end_d = _last_30_days_range()
    url = "https://services.leadconnectorhq.com/opportunities/search"
    headers = _ghl_headers(api_key, location_id=str(location_id))

    async def fetch_status(status: str) -> dict:
        params = {
            "location_id": str(location_id),
            "status": status,
            "date": _fmt_mmddyyyy(start_d),
            "endDate": _fmt_mmddyyyy(end_d),
            "limit": 20,
            "page": 1,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            return {"error": f"gohighlevel_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
        try:
            return resp.json() or {}
        except Exception:
            return {"error": "gohighlevel_bad_json", "error_detail": (resp.text or "")[:300]}

    open_res, won_res, lost_res = await fetch_status("open"), await fetch_status("won"), await fetch_status("lost")
    if any(isinstance(r, dict) and r.get("error") for r in (open_res, won_res, lost_res)):
        return {
            "location_id": str(location_id),
            "error": open_res.get("error") or won_res.get("error") or lost_res.get("error"),
            "error_detail": open_res.get("error_detail") or won_res.get("error_detail") or lost_res.get("error_detail"),
        }

    def get_total(res: dict) -> int:
        meta = res.get("meta") or {}
        if isinstance(meta.get("total"), int):
            return meta["total"]
        opps = res.get("opportunities") or []
        return len(opps)

    def sum_won_value(res: dict) -> float:
        opps = res.get("opportunities") or []
        total = 0.0
        for o in opps:
            try:
                total += float(o.get("monetaryValue") or 0)
            except Exception:
                pass
        return total

    return {
        "location_id": str(location_id),
        "opportunities_open": get_total(open_res),
        "opportunities_won": get_total(won_res),
        "opportunities_lost": get_total(lost_res),
        "won_value": sum_won_value(won_res),
        "period_start": start_d.isoformat(),
        "period_end": end_d.isoformat(),
    }


async def _google_ads_access_token(creds: Dict[str, str]) -> str:
    rt = (creds or {}).get("refresh_token")
    cid = _clean_oauth_str((creds or {}).get("oauth_client_id") or os.environ.get("GOOGLE_OAUTH_CLIENT_ID"))
    secret = _clean_oauth_str((creds or {}).get("oauth_client_secret") or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"))
    if not rt or not cid or not secret:
        raise ValueError("Missing Google OAuth credentials")
    payload = {
        "client_id": cid,
        "client_secret": secret,
        "refresh_token": rt,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data=payload)
    if resp.status_code != 200:
        raise ValueError(f"oauth_http_{resp.status_code}: {_safe_err_detail(resp)}")
    data = resp.json() or {}
    token = data.get("access_token")
    if not token:
        raise ValueError("missing_access_token")
    return str(token)


async def _google_ads_access_token_for_tenant(tenant_id: str, creds: Dict[str, str]) -> str:
    merged = dict(creds or {})
    cid = _clean_oauth_str((merged or {}).get("oauth_client_id") or os.environ.get("GOOGLE_OAUTH_CLIENT_ID"))
    secret = _clean_oauth_str((merged or {}).get("oauth_client_secret") or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"))
    if not cid or not secret:
        oauth = await get_credentials(tenant_id, "google_oauth")
        if not cid:
            cid = _clean_oauth_str((oauth or {}).get("client_id"))
            if cid:
                merged["oauth_client_id"] = cid
        if not secret:
            secret = _clean_oauth_str((oauth or {}).get("client_secret"))
            if secret:
                merged["oauth_client_secret"] = secret
    return await _google_ads_access_token(merged)


def _normalize_customer_id(v: Any) -> str:
    s = str(v or "").strip()
    return s.replace("-", "").replace(" ", "")


async def fetch_google_ads_monthly(tenant_id: str, creds: Dict[str, str], binding: dict, start_d: Optional[date] = None, end_d: Optional[date] = None) -> Dict[str, Any]:
    developer_token = (creds or {}).get("developer_token")
    if not developer_token:
        return {}
    customer_id = (
        (binding.get("external_ids") or {}).get("customer_id")
        or (binding.get("config") or {}).get("customer_id")
        or (creds or {}).get("customer_id")
    )
    customer_id = _normalize_customer_id(customer_id)
    if not customer_id:
        return {"error": "google_ads_missing_customer_id", "error_detail": "Missing Google Ads customer_id for this client."}

    access_token = await _google_ads_access_token_for_tenant(tenant_id, creds)
    if not start_d or not end_d:
        start_d, end_d = _last_30_days_range()
    q = (
        "SELECT metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions "
        f"FROM customer WHERE segments.date BETWEEN '{start_d.isoformat()}' AND '{end_d.isoformat()}'"
    )
    url = f"https://googleads.googleapis.com/v16/customers/{customer_id}/googleAds:searchStream"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": str(developer_token),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    login_customer_id = (creds or {}).get("login_customer_id") or (creds or {}).get("manager_customer_id")
    if login_customer_id:
        headers["login-customer-id"] = _normalize_customer_id(login_customer_id)

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json={"query": q})
    if resp.status_code != 200:
        return {"error": f"google_ads_http_{resp.status_code}", "error_detail": _safe_err_detail(resp), "customer_id": customer_id}

    rows = resp.json() or []
    impressions = 0
    clicks = 0
    cost_micros = 0
    conversions = 0.0
    for block in rows:
        for r in (block.get("results") or []):
            metrics = r.get("metrics") or {}
            try:
                impressions += int(metrics.get("impressions") or 0)
            except Exception:
                pass
            try:
                clicks += int(metrics.get("clicks") or 0)
            except Exception:
                pass
            try:
                cost_micros += int(metrics.get("costMicros") or metrics.get("cost_micros") or 0)
            except Exception:
                pass
            try:
                conversions += float(metrics.get("conversions") or 0)
            except Exception:
                pass

    spend = float(cost_micros) / 1_000_000.0
    cpc = (spend / clicks) if clicks else 0.0
    cpl = (spend / conversions) if conversions else 0.0
    return {
        "customer_id": customer_id,
        "period_start": start_d.isoformat(),
        "period_end": end_d.isoformat(),
        "impressions": impressions,
        "clicks": clicks,
        "spend": round(spend, 2),
        "conversions": round(conversions, 2),
        "avg_cpc": round(cpc, 2),
        "cpl": round(cpl, 2),
    }


async def build_kpi_snapshot(
    tenant_id: str,
    client_id: str,
    client_name: str = "",
    user_id: Optional[str] = None,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    compare_start: Optional[date] = None,
    compare_end: Optional[date] = None,
) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}
    if _demo_kpi_enabled():
        from integrations_meta import demo_kpi_snapshot

        snapshot = demo_kpi_snapshot(client_name)
    if not period_start or not period_end:
        period_start, period_end = _last_30_days_range()
    snapshot["_period"] = _period_meta(cur_start=period_start, cur_end=period_end, prev_start=compare_start, prev_end=compare_end)
    snapshot["_availability"] = {}
    def _is_err_payload(v: Any) -> bool:
        return isinstance(v, dict) and bool(v.get("error"))

    clickup_creds = await get_credentials(tenant_id, "clickup")
    clickup_binding = await get_client_binding(tenant_id, client_id, "clickup")
    if _clickup_token_from_creds(clickup_creds):
        folder_id = ((clickup_binding or {}).get("external_ids") or {}).get("folder_id") or ((clickup_binding or {}).get("config") or {}).get("folder_id")
        if clickup_binding and folder_id:
            try:
                clickup_data = await fetch_clickup_monthly(clickup_creds, clickup_binding, start_d=period_start, end_d=period_end)
                if _is_err_payload(clickup_data):
                    snapshot["_availability"]["clickup"] = {"ok": False, "error": clickup_data.get("error"), "error_detail": clickup_data.get("error_detail")}
                elif clickup_data:
                    snapshot["clickup"] = {**(snapshot.get("clickup") or {}), **clickup_data}
                    snapshot["_availability"]["clickup"] = {"ok": True}
                else:
                    snapshot["_availability"]["clickup"] = {"ok": False, "error": "clickup_no_data"}
            except Exception as exc:
                snapshot["_availability"]["clickup"] = {"ok": False, "error": "clickup_error", "error_detail": str(exc)[:300]}
        else:
            snapshot["_availability"]["clickup"] = {"ok": False, "error": "clickup_missing_client_mapping", "error_detail": "Missing ClickUp Folder ID mapping for this client."}
    else:
        snapshot["_availability"]["clickup"] = {"ok": False, "error": "not_connected"}

    ghl_binding = await get_client_binding(tenant_id, client_id, "gohighlevel")
    ghl_api_key = await _gohighlevel_base_api_key(tenant_id)
    if ghl_api_key:
        try:
            ghl_data = await fetch_gohighlevel_monthly(tenant_id, ghl_binding or {"external_ids": {}, "config": {}}, start_d=period_start, end_d=period_end)
            if _is_err_payload(ghl_data):
                snapshot["gohighlevel"] = {**(snapshot.get("gohighlevel") or {}), **ghl_data}
                snapshot["_availability"]["gohighlevel"] = {"ok": False, "error": ghl_data.get("error"), "error_detail": ghl_data.get("error_detail")}
            elif ghl_data:
                snapshot["gohighlevel"] = {**(snapshot.get("gohighlevel") or {}), **ghl_data}
                snapshot["_availability"]["gohighlevel"] = {"ok": True}
            else:
                snapshot["_availability"]["gohighlevel"] = {"ok": False, "error": "gohighlevel_missing_location_id", "error_detail": "Missing GoHighLevel location_id (set it in the client mapping or integration settings)."}
        except Exception as exc:
            snapshot["_availability"]["gohighlevel"] = {"ok": False, "error": "gohighlevel_error", "error_detail": str(exc)[:300]}
    else:
        snapshot["_availability"]["gohighlevel"] = {"ok": False, "error": "not_connected"}

    gads_creds = await get_credentials(tenant_id, "google_ads")
    gads_binding = await get_client_binding(tenant_id, client_id, "google_ads")
    if any(str(v or "").strip() for v in (gads_creds or {}).values()) or user_id:
        if not str((gads_creds or {}).get("developer_token") or "").strip():
            snapshot["_availability"]["google_ads"] = {"ok": False, "error": "google_ads_incomplete_setup", "error_detail": "Missing Google Ads developer_token in Integrations → Google Ads."}
        elif not user_id:
            snapshot["_availability"]["google_ads"] = {"ok": False, "error": "google_ads_missing_user", "error_detail": "Missing user context to run Google Ads sync."}
        else:
            rt = await get_google_refresh_token(tenant_id, user_id, "google_ads")
            if not rt:
                snapshot["_availability"]["google_ads"] = {"ok": False, "error": "google_ads_missing_google_connection", "error_detail": "Connect Google for Google Ads first."}
            else:
                merged = {**gads_creds, "refresh_token": rt}
                try:
                    gads_data = await fetch_google_ads_monthly(tenant_id, merged, gads_binding or {"external_ids": {}, "config": {}}, start_d=period_start, end_d=period_end)
                    if gads_data:
                        snapshot["google_ads"] = {**(snapshot.get("google_ads") or {}), **gads_data}
                        snapshot["_availability"]["google_ads"] = {"ok": True}
                except Exception as exc:
                    snapshot["_availability"]["google_ads"] = {"ok": False, "error": "google_ads_error", "error_detail": str(exc)[:300]}
    else:
        snapshot["_availability"]["google_ads"] = {"ok": False, "error": "not_connected"}

    return snapshot


async def test_clickup(tenant_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "clickup")
    token = _clickup_token_from_creds(creds)
    if not token:
        return {"ok": False, "error": "missing_clickup_token"}
    headers = {"Authorization": token, "Accept": "application/json"}
    url = "https://api.clickup.com/api/v2/user"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        return {"ok": False, "error": f"clickup_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    return {"ok": True, "user": (data.get("user") or {}).get("username") or (data.get("user") or {}).get("email")}


async def test_gohighlevel(tenant_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "gohighlevel")
    api_key = _strip_bearer((creds or {}).get("api_key", ""))
    company_id = (creds or {}).get("company_id")
    location_id = (creds or {}).get("location_id")
    if not api_key:
        return {"ok": False, "error": "missing_api_key"}
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}", "Version": "2023-02-21"}
    if company_id:
        url = "https://services.leadconnectorhq.com/locations/search"
        params = {"companyId": str(company_id), "limit": 1, "skip": 0}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            return {"ok": False, "error": f"gohighlevel_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
        data = resp.json() or {}
        locs = data.get("locations") or []
        return {"ok": True, "locations_found": len(locs)}

    if not location_id:
        return {"ok": False, "error": "missing_company_id_or_location_id"}

    start_d, end_d = _last_30_days_range()
    url = "https://services.leadconnectorhq.com/opportunities/search"
    params = {"location_id": str(location_id), "status": "all", "date": _fmt_mmddyyyy(start_d), "endDate": _fmt_mmddyyyy(end_d), "limit": 1, "page": 1}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return {"ok": False, "error": f"gohighlevel_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    meta = data.get("meta") or {}
    return {"ok": True, "total": meta.get("total")}


async def list_google_ads_customers(tenant_id: str, user_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "google_ads")
    developer_token = (creds or {}).get("developer_token")
    if not developer_token:
        return {"ok": False, "error": "missing_developer_token"}
    refresh_token = await get_google_refresh_token(tenant_id, user_id, "google_ads")
    if not refresh_token:
        return {"ok": False, "error": "missing_google_connection", "error_detail": "Connect Google for Google Ads first."}
    creds = {**creds, "refresh_token": refresh_token}
    try:
        access_token = await _google_ads_access_token_for_tenant(tenant_id, creds)
    except Exception as exc:
        return {"ok": False, "error": "oauth_error", "error_detail": str(exc)[:300]}
    headers = {"Authorization": f"Bearer {access_token}", "developer-token": str(developer_token), "Accept": "application/json"}
    login_customer_id = (creds or {}).get("login_customer_id") or (creds or {}).get("manager_customer_id")
    if login_customer_id:
        headers["login-customer-id"] = _normalize_customer_id(login_customer_id)
    url = "https://googleads.googleapis.com/v16/customers:listAccessibleCustomers"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        return {"ok": False, "error": f"google_ads_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    names = data.get("resourceNames") or []
    out = []
    for rn in names:
        if isinstance(rn, str) and rn.startswith("customers/"):
            out.append({"id": rn.split("/", 1)[1]})
    return {"ok": True, "customers": out}


async def test_google_ads(tenant_id: str) -> Dict[str, Any]:
    return {"ok": False, "error": "missing_user_id"}


async def test_google_ads_for_user(tenant_id: str, user_id: str) -> Dict[str, Any]:
    res = await list_google_ads_customers(tenant_id, user_id)
    if not res.get("ok"):
        return res
    return {"ok": True, "customers_found": len(res.get("customers") or [])}


async def test_google_meet(tenant_id: str) -> Dict[str, Any]:
    return {"ok": False, "error": "missing_user_id"}


async def test_google_meet_for_user(tenant_id: str, user_id: str) -> Dict[str, Any]:
    rt = await get_google_refresh_token(tenant_id, user_id, "google_meet")
    if not rt:
        return {"ok": False, "error": "missing_google_connection", "error_detail": "Connect Google for Google Meet first."}
    creds = {"refresh_token": rt}
    try:
        await _google_ads_access_token_for_tenant(tenant_id, creds)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": "oauth_error", "error_detail": str(exc)[:300]}


def _meet_code_from_url(url: str) -> Optional[str]:
    s = (url or "").strip()
    if not s:
        return None
    if "meet.google.com" not in s:
        return None
    try:
        parts = s.split("/")
        for p in parts[::-1]:
            p = p.strip()
            if p and "-" in p and len(p) >= 10 and "." not in p:
                return p.split("?")[0]
    except Exception:
        return None
    return None


async def list_google_meet_conference_records(tenant_id: str, user_id: str, meet_code: str) -> Dict[str, Any]:
    rt = await get_google_refresh_token(tenant_id, user_id, "google_meet")
    if not rt:
        return {"ok": False, "error": "missing_google_connection", "error_detail": "Connect Google for Google Meet first."}
    creds = {"refresh_token": rt}
    try:
        access_token = await _google_ads_access_token_for_tenant(tenant_id, creds)
    except Exception as exc:
        return {"ok": False, "error": "oauth_error", "error_detail": str(exc)[:300]}
    url = f"https://meet.googleapis.com/v2/spaces/{meet_code}/conferenceRecords"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        return {"ok": False, "error": f"google_meet_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    return {"ok": True, "conference_records": data.get("conferenceRecords") or []}


async def _get_google_meet_transcripts(tenant_id: str, user_id: str, conference_record_name: str) -> Dict[str, Any]:
    rt = await get_google_refresh_token(tenant_id, user_id, "google_meet")
    if not rt:
        return {"ok": False, "error": "missing_google_connection", "error_detail": "Connect Google for Google Meet first."}
    creds = {"refresh_token": rt}
    try:
        access_token = await _google_ads_access_token_for_tenant(tenant_id, creds)
    except Exception as exc:
        return {"ok": False, "error": "oauth_error", "error_detail": str(exc)[:300]}
    url = f"https://meet.googleapis.com/v2/{conference_record_name}/transcripts"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        return {"ok": False, "error": f"google_meet_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    return {"ok": True, "transcripts": data.get("transcripts") or []}


async def _google_docs_document(tenant_id: str, user_id: str, document_id: str) -> Dict[str, Any]:
    rt = await get_google_refresh_token(tenant_id, user_id, "google_meet")
    if not rt:
        raise ValueError("missing_google_connection")
    creds = {"refresh_token": rt}
    try:
        access_token = await _google_ads_access_token_for_tenant(tenant_id, creds)
    except Exception as exc:
        raise ValueError(str(exc))
    url = f"https://docs.googleapis.com/v1/documents/{document_id}"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        raise ValueError(f"google_docs_http_{resp.status_code}: {_safe_err_detail(resp)}")
    return resp.json() or {}


def _extract_docs_text(doc: Dict[str, Any]) -> str:
    out: List[str] = []
    body = (doc or {}).get("body") or {}
    for c in (body.get("content") or []):
        p = c.get("paragraph")
        if not p:
            continue
        buf: List[str] = []
        for el in (p.get("elements") or []):
            tr = (el.get("textRun") or {}).get("content")
            if tr:
                buf.append(tr)
        line = "".join(buf).strip()
        if line:
            out.append(line)
    return "\n".join(out).strip()


async def sync_google_meet_transcript_to_meeting(tenant_id: str, user_id: str, meeting: dict) -> Dict[str, Any]:
    meet_code = _meet_code_from_url((meeting or {}).get("google_meet_url") or "")
    if not meet_code:
        return {"ok": False, "error": "missing_meet_url"}

    recs = await list_google_meet_conference_records(tenant_id, user_id, meet_code)
    if not recs.get("ok"):
        return recs
    records = recs.get("conference_records") or []
    if not records:
        return {"ok": False, "error": "no_conference_records"}

    record = records[0]
    record_name = record.get("name")
    if not record_name:
        return {"ok": False, "error": "invalid_conference_record"}

    trs = await _get_google_meet_transcripts(tenant_id, user_id, record_name)
    if not trs.get("ok"):
        return trs
    transcripts = trs.get("transcripts") or []
    if not transcripts:
        return {"ok": False, "error": "no_transcripts"}

    transcript = transcripts[0]
    docs_dest = (transcript.get("docsDestination") or {})
    document_id = docs_dest.get("document") or ""
    if isinstance(document_id, str) and document_id.startswith("documents/"):
        document_id = document_id.split("/", 1)[1]
    if not document_id:
        return {"ok": False, "error": "missing_document_id"}

    gdoc = await _google_docs_document(tenant_id, user_id, str(document_id))
    text = _extract_docs_text(gdoc)
    if not text:
        return {"ok": False, "error": "empty_transcript"}
    return {
        "ok": True,
        "meet_code": meet_code,
        "conference_record": record_name,
        "transcript": text,
        "document_id": str(document_id),
    }


async def list_clickup_workspaces(tenant_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "clickup")
    token = _clickup_token_from_creds(creds)
    if not token:
        return {"ok": False, "error": "missing_clickup_token"}
    headers = {"Authorization": token, "Accept": "application/json"}
    url = "https://api.clickup.com/api/v2/team"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        return {"ok": False, "error": f"clickup_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    teams = data.get("teams") or []
    return {"ok": True, "workspaces": [{"id": str(t.get("id")), "name": t.get("name")} for t in teams if t.get("id")]}


async def list_clickup_folders(tenant_id: str, team_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "clickup")
    token = _clickup_token_from_creds(creds)
    if not token:
        return {"ok": False, "error": "missing_clickup_token"}
    if not team_id:
        return {"ok": False, "error": "missing_team_id"}
    headers = {"Authorization": token, "Accept": "application/json"}

    async def get_json(url: str):
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=headers, params={"archived": "false"})
        if r.status_code != 200:
            raise HTTPException(400, f"ClickUp error {r.status_code}: {_safe_err_detail(r)}")
        return r.json() or {}

    spaces = (await get_json(f"https://api.clickup.com/api/v2/team/{team_id}/space")).get("spaces") or []
    folders = []
    for s in spaces:
        sid = s.get("id")
        sname = s.get("name")
        if not sid:
            continue
        space_folders = (await get_json(f"https://api.clickup.com/api/v2/space/{sid}/folder")).get("folders") or []
        for f in space_folders:
            fid = f.get("id")
            if fid:
                folders.append({"id": str(fid), "name": f.get("name"), "space": sname})

    uniq = {}
    for f in folders:
        uniq[f["id"]] = f
    out = list(uniq.values())
    out.sort(key=lambda x: (x.get("space") or "", x.get("name") or ""))
    return {"ok": True, "folders": out}


async def list_clickup_lists(tenant_id: str, team_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "clickup")
    token = _clickup_token_from_creds(creds)
    if not token:
        return {"ok": False, "error": "missing_clickup_token"}
    if not team_id:
        return {"ok": False, "error": "missing_team_id"}
    headers = {"Authorization": token, "Accept": "application/json"}

    async def get_json(url: str):
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=headers, params={"archived": "false"})
        if r.status_code != 200:
            raise HTTPException(400, f"ClickUp error {r.status_code}: {_safe_err_detail(r)}")
        return r.json() or {}

    spaces = (await get_json(f"https://api.clickup.com/api/v2/team/{team_id}/space")).get("spaces") or []

    lists: List[dict] = []
    for s in spaces:
        sid = s.get("id")
        sname = s.get("name")
        if not sid:
            continue
        direct_lists = (await get_json(f"https://api.clickup.com/api/v2/space/{sid}/list")).get("lists") or []
        for l in direct_lists:
            if l.get("id"):
                lists.append({"id": str(l.get("id")), "name": l.get("name"), "space": sname})
        folders = (await get_json(f"https://api.clickup.com/api/v2/space/{sid}/folder")).get("folders") or []
        for f in folders:
            fid = f.get("id")
            fname = f.get("name")
            if not fid:
                continue
            folder_lists = (await get_json(f"https://api.clickup.com/api/v2/folder/{fid}/list")).get("lists") or []
            for l in folder_lists:
                if l.get("id"):
                    lists.append({"id": str(l.get("id")), "name": l.get("name"), "space": sname, "folder": fname})

    uniq = {}
    for l in lists:
        uniq[l["id"]] = l
    out = list(uniq.values())
    out.sort(key=lambda x: (x.get("space") or "", x.get("folder") or "", x.get("name") or ""))
    return {"ok": True, "lists": out}


def _norm_clickup_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


async def _clickup_client_book_list_id(tenant_id: str, client_id: str) -> str:
    creds = await get_credentials(tenant_id, "clickup")
    token = _clickup_token_from_creds(creds)
    if not token:
        return ""
    binding = await get_client_binding(tenant_id, client_id, "clickup")
    if not binding:
        return ""
    external_ids = (binding.get("external_ids") or {}) if binding else {}
    config = (binding.get("config") or {}) if binding else {}
    folder_id = external_ids.get("folder_id") or config.get("folder_id")
    if not folder_id:
        return ""

    cached = str(external_ids.get("client_book_list_id") or "").strip()
    if cached:
        return cached

    headers = {"Authorization": token, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.clickup.com/api/v2/folder/{folder_id}/list",
            headers=headers,
            params={"archived": "false"},
        )
    if resp.status_code == 200:
        lists = (resp.json() or {}).get("lists") or []
        for l in lists:
            name = _norm_clickup_name(l.get("name") or "")
            if name in ("client book", "clients book", "client's book", "clients' book") and l.get("id"):
                list_id = str(l.get("id"))
                await _update_client_binding_external_ids(tenant_id, client_id, "clickup", {"client_book_list_id": list_id})
                return list_id

    async with httpx.AsyncClient(timeout=30) as client:
        resp2 = await client.post(
            f"https://api.clickup.com/api/v2/folder/{folder_id}/list",
            headers={"Authorization": token, "Content-Type": "application/json", "Accept": "application/json"},
            json={"name": "Client Book"},
        )
    if resp2.status_code in (200, 201):
        list_id = str((resp2.json() or {}).get("id") or (resp2.json() or {}).get("list", {}).get("id") or "")
        if list_id:
            await _update_client_binding_external_ids(tenant_id, client_id, "clickup", {"client_book_list_id": list_id})
            return list_id
    return ""


async def _clickup_department_tickets_list_id(tenant_id: str, client_id: str) -> str:
    creds = await get_credentials(tenant_id, "clickup")
    token = _clickup_token_from_creds(creds)
    if not token:
        return ""
    binding = await get_client_binding(tenant_id, client_id, "clickup")
    if not binding:
        return ""
    external_ids = (binding.get("external_ids") or {}) if binding else {}
    config = (binding.get("config") or {}) if binding else {}
    folder_id = external_ids.get("folder_id") or config.get("folder_id")
    if not folder_id:
        return ""

    cached = str(external_ids.get("department_tickets_list_id") or "").strip()
    if cached:
        return cached

    headers = {"Authorization": token, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.clickup.com/api/v2/folder/{folder_id}/list",
            headers=headers,
            params={"archived": "false"},
        )
    if resp.status_code == 200:
        lists = (resp.json() or {}).get("lists") or []
        for l in lists:
            name = _norm_clickup_name(l.get("name") or "")
            if name in ("department tickets", "dept tickets", "tickets") and l.get("id"):
                list_id = str(l.get("id"))
                await _update_client_binding_external_ids(tenant_id, client_id, "clickup", {"department_tickets_list_id": list_id})
                return list_id

    async with httpx.AsyncClient(timeout=30) as client:
        resp2 = await client.post(
            f"https://api.clickup.com/api/v2/folder/{folder_id}/list",
            headers={"Authorization": token, "Content-Type": "application/json", "Accept": "application/json"},
            json={"name": "Department Tickets"},
        )
    if resp2.status_code in (200, 201):
        list_id = str((resp2.json() or {}).get("id") or (resp2.json() or {}).get("list", {}).get("id") or "")
        if list_id:
            await _update_client_binding_external_ids(tenant_id, client_id, "clickup", {"department_tickets_list_id": list_id})
            return list_id
    return ""


async def _clickup_upsert_task(token: str, list_id: str, task_id: str, name: str, description: str) -> Dict[str, Any]:
    headers = {"Authorization": token, "Content-Type": "application/json", "Accept": "application/json"}
    payload: Dict[str, Any] = {"name": str(name or "").strip(), "description": str(description or "").strip()}
    async with httpx.AsyncClient(timeout=30) as client:
        if task_id:
            resp = await client.put(f"https://api.clickup.com/api/v2/task/{task_id}", headers=headers, json=payload)
        else:
            resp = await client.post(f"https://api.clickup.com/api/v2/list/{list_id}/task", headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        return {"ok": False, "error": f"clickup_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    return {"ok": True, "task_id": str(data.get("id") or task_id or ""), "url": data.get("url")}


def _fmt_bullets(items):
    out = []
    for it in items or []:
        if isinstance(it, dict):
            title = str(it.get("title") or "").strip()
            desc = str(it.get("description") or "").strip()
            if title and desc:
                out.append(f"- {title}: {desc}")
            elif title:
                out.append(f"- {title}")
        else:
            s = str(it or "").strip()
            if s:
                out.append(f"- {s}")
    return "\n".join(out).strip()


async def publish_clickup_meeting_brief(tenant_id: str, meeting: dict, client: dict) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "clickup")
    token = _clickup_token_from_creds(creds)
    if not token:
        return {"ok": False, "error": "missing_clickup_token"}
    client_id = str((meeting or {}).get("client_id") or "").strip()
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}
    list_id = await _clickup_client_book_list_id(tenant_id, client_id)
    if not list_id:
        return {"ok": False, "error": "missing_client_book_list_id"}

    title = str((meeting or {}).get("title") or "").strip() or "Monthly Touch"
    name = f"{title} — Brief"
    desc = (
        f"Client: {str((client or {}).get('company') or '')}".strip()
        + "\n"
        + f"Contact: {str((client or {}).get('name') or '')}".strip()
        + "\n\nWins:\n"
        + (_fmt_bullets((meeting or {}).get("wins") or []) or "—")
        + "\n\nIssues:\n"
        + (_fmt_bullets((meeting or {}).get("issues") or []) or "—")
        + "\n\nTalking points:\n"
        + (
            _fmt_bullets(
                [
                    f"{tp.get('topic')}: {tp.get('angle')}" if isinstance(tp, dict) else tp
                    for tp in ((meeting or {}).get("talking_points") or [])
                ]
            )
            or "—"
        )
        + "\n\nSuggested questions:\n"
        + (_fmt_bullets((meeting or {}).get("suggested_questions") or []) or "—")
        + "\n\nRecommendations:\n"
        + (_fmt_bullets((meeting or {}).get("strategic_recommendations") or []) or "—")
    )

    existing_task_id = str(((meeting or {}).get("clickup_client_book") or {}).get("brief_task_id") or "").strip()
    return await _clickup_upsert_task(token, list_id, existing_task_id, name, desc)


async def publish_clickup_meeting_summary(tenant_id: str, meeting: dict, client: dict, actions: list, tickets: list) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "clickup")
    token = _clickup_token_from_creds(creds)
    if not token:
        return {"ok": False, "error": "missing_clickup_token"}
    client_id = str((meeting or {}).get("client_id") or "").strip()
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}
    list_id = await _clickup_client_book_list_id(tenant_id, client_id)
    if not list_id:
        return {"ok": False, "error": "missing_client_book_list_id"}

    title = str((meeting or {}).get("title") or "").strip() or "Monthly Touch"
    name = f"{title} — Meeting Summary"
    recap = str((meeting or {}).get("recap_email") or "").strip()
    sent = str((meeting or {}).get("sentiment") or "").strip()
    sent_sum = str((meeting or {}).get("sentiment_summary") or "").strip()
    desc = (
        f"Client: {str((client or {}).get('company') or '')}".strip()
        + "\n"
        + f"Contact: {str((client or {}).get('name') or '')}".strip()
        + (f"\n\nSENTIMENT: {sent}\n{sent_sum}".strip() if (sent or sent_sum) else "")
        + "\n\nRecap email:\n"
        + (recap or "—")
        + "\n\nAction items:\n"
        + (_fmt_bullets([{"title": a.get("title"), "description": a.get("description")} for a in (actions or []) if isinstance(a, dict)]) or "—")
        + "\n\nDepartment tickets:\n"
        + (
            _fmt_bullets(
                [
                    {
                        "title": f"[{t.get('department')}] {t.get('title')}",
                        "description": t.get("description"),
                    }
                    for t in (tickets or [])
                    if isinstance(t, dict)
                ]
            )
            or "—"
        )
    )

    existing_task_id = str(((meeting or {}).get("clickup_client_book") or {}).get("summary_task_id") or "").strip()
    return await _clickup_upsert_task(token, list_id, existing_task_id, name, desc)


async def publish_clickup_department_tickets(tenant_id: str, meeting: dict, tickets: list) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "clickup")
    token = _clickup_token_from_creds(creds)
    if not token:
        return {"ok": False, "error": "missing_clickup_token"}
    client_id = str((meeting or {}).get("client_id") or "").strip()
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}
    list_id = await _clickup_department_tickets_list_id(tenant_id, client_id)
    if not list_id:
        return {"ok": False, "error": "missing_department_tickets_list_id"}

    published = []
    for t in tickets or []:
        if not isinstance(t, dict):
            continue
        ticket_id = str(t.get("_id") or t.get("id") or "").strip()
        dept = str(t.get("department") or "Other").strip()
        title = str(t.get("title") or "Ticket").strip()
        name = f"[{dept}] {title}"
        desc = str(t.get("description") or "").strip()
        existing_task_id = str(t.get("external_id") or "").strip()
        res = await _clickup_upsert_task(token, list_id, existing_task_id, name, desc)
        if res.get("ok"):
            published.append({"ticket_id": ticket_id, "task_id": res.get("task_id"), "url": res.get("url")})
    return {"ok": True, "published": published}


async def send_gmail_plain_email(tenant_id: str, user_id: str, to_email: str, subject: str, plain: str) -> Dict[str, Any]:
    to_addr = str(to_email or "").strip()
    if not to_addr:
        return {"ok": False, "error": "missing_to"}
    refresh_token = await get_google_refresh_token(tenant_id, user_id, "gmail")
    if not refresh_token:
        return {"ok": False, "error": "missing_google_connection", "error_detail": "Connect Google for Gmail first."}
    access_token = await _google_ads_access_token({"refresh_token": refresh_token})

    subj = str(subject or "").strip() or "Monthly Touch Recap"
    body = str(plain or "").strip()
    raw_msg = (
        f"To: {to_addr}\r\n"
        f"Subject: {subj}\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n"
        "\r\n"
        f"{body}"
    )
    encoded = base64.urlsafe_b64encode(raw_msg.encode("utf-8")).decode("utf-8").rstrip("=")
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", headers=headers, json={"raw": encoded})
    if resp.status_code not in (200, 201):
        return {"ok": False, "error": f"gmail_send_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    return {"ok": True}


async def list_gohighlevel_locations(tenant_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "gohighlevel")
    api_key = _strip_bearer((creds or {}).get("api_key", ""))
    company_id = (creds or {}).get("company_id")
    if not api_key:
        return {"ok": False, "error": "missing_api_key"}
    if not company_id:
        return {"ok": False, "error": "missing_company_id"}
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}", "Version": "2023-02-21"}
    url = "https://services.leadconnectorhq.com/locations/search"
    params = {"companyId": str(company_id), "limit": 200, "skip": 0}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return {"ok": False, "error": f"gohighlevel_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    locs = data.get("locations") or []
    out = [{"id": str(l.get("id")), "name": l.get("name"), "email": l.get("email"), "phone": l.get("phone")} for l in locs if l.get("id")]
    return {"ok": True, "locations": out}


def _ghl_headers(api_key: str, location_id: Optional[str] = None) -> Dict[str, str]:
    h = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Version": "2023-02-21",
    }
    if location_id:
        h["locationId"] = str(location_id)
    return h


async def _gohighlevel_base_api_key(tenant_id: str) -> str:
    creds = await get_credentials(tenant_id, "gohighlevel")
    return _strip_bearer((creds or {}).get("api_key", ""))


async def get_gohighlevel_location_token(tenant_id: str, location_id: str) -> str:
    lid = str(location_id or "").strip()
    if not lid:
        return ""
    integration_doc = await _get_integration_doc(tenant_id, "gohighlevel")
    encrypted = _ghl_location_tokens_map(integration_doc).get(lid) if integration_doc else None
    if encrypted:
        return _strip_bearer(decrypt_secret(encrypted))
    return ""


async def _gohighlevel_token_for_location(tenant_id: str, location_id: str) -> str:
    tok = await get_gohighlevel_location_token(tenant_id, location_id)
    if tok:
        return tok
    return await _gohighlevel_base_api_key(tenant_id)


async def list_gohighlevel_contacts(tenant_id: str, location_id: str, query: str = "", limit: int = 100) -> Dict[str, Any]:
    api_key = await _gohighlevel_token_for_location(tenant_id, location_id)
    if not api_key:
        return {"ok": False, "error": "missing_api_key"}
    if not location_id:
        return {"ok": False, "error": "missing_location_id"}
    headers = _ghl_headers(api_key, location_id=location_id)

    wanted = int(limit or 100)
    if wanted < 1:
        wanted = 1
    if wanted > 5000:
        wanted = 5000

    page_limit = 100
    out: List[Dict[str, Any]] = []

    async def _add_contacts(raw_contacts: Any) -> None:
        nonlocal out
        if isinstance(raw_contacts, dict):
            raw_contacts = [raw_contacts]
        for c in raw_contacts or []:
            if len(out) >= wanted:
                return
            cid = c.get("id") or c.get("_id")
            if not cid:
                continue
            name = c.get("name") or " ".join([str(c.get("firstName") or "").strip(), str(c.get("lastName") or "").strip()]).strip()
            company = c.get("companyName") or c.get("company") or ""
            out.append(
                {
                    "id": str(cid),
                    "name": str(name or "").strip(),
                    "company": str(company or "").strip(),
                    "email": str(c.get("email") or "").strip(),
                    "phone": str(c.get("phone") or "").strip(),
                }
            )

    async with httpx.AsyncClient(timeout=30) as client:
        used_fallback = False
        for page in range(1, 101):
            body = {"locationId": str(location_id), "page": page, "pageLimit": page_limit}
            if query:
                body["searchTerm"] = str(query)
            resp = await client.post("https://services.leadconnectorhq.com/contacts/search", headers=headers, json=body)
            if resp.status_code in (400, 404, 422) or "property limit should not exist" in (resp.text or "").lower():
                used_fallback = True
                break
            if resp.status_code != 200:
                if resp.status_code in (401, 403) and not await get_gohighlevel_location_token(tenant_id, location_id):
                    return {"ok": False, "error": "missing_location_token", "error_detail": "This location requires a GoHighLevel Location Private Integration Token. Ask your tenant admin to add it in Integrations → GoHighLevel."}
                return {"ok": False, "error": f"gohighlevel_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
            data = resp.json() or {}
            raw = data.get("contacts") or data.get("results") or data.get("contact") or []
            await _add_contacts(raw)
            if len(out) >= wanted:
                break
            if not raw or (isinstance(raw, list) and len(raw) < page_limit):
                break

        if used_fallback and len(out) < wanted:
            for skip in range(0, wanted, page_limit):
                params: Dict[str, Any] = {"locationId": str(location_id), "limit": int(page_limit), "skip": int(skip)}
                if query:
                    params["query"] = str(query)
                resp = await client.get("https://services.leadconnectorhq.com/contacts/", headers=headers, params=params)
                if resp.status_code != 200:
                    if resp.status_code in (401, 403) and not await get_gohighlevel_location_token(tenant_id, location_id):
                        return {"ok": False, "error": "missing_location_token", "error_detail": "This location requires a GoHighLevel Location Private Integration Token. Ask your tenant admin to add it in Integrations → GoHighLevel."}
                    return {"ok": False, "error": f"gohighlevel_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
                data = resp.json() or {}
                raw = data.get("contacts") or data.get("results") or data.get("contact") or []
                await _add_contacts(raw)
                if len(out) >= wanted:
                    break
                if not raw or (isinstance(raw, list) and len(raw) < page_limit):
                    break

    if query:
        q = query.strip().lower()
        out = [x for x in out if q in (x.get("name") or "").lower() or q in (x.get("company") or "").lower() or q in (x.get("email") or "").lower()]

    return {"ok": True, "contacts": out[:wanted]}


async def fetch_gohighlevel_contact_detail(tenant_id: str, location_id: str, contact_id: str) -> Dict[str, Any]:
    api_key = await _gohighlevel_token_for_location(tenant_id, location_id)
    if not api_key:
        return {"ok": False, "error": "missing_api_key"}
    cid = str(contact_id or "").strip()
    if not cid:
        return {"ok": False, "error": "missing_contact_id"}
    headers = _ghl_headers(api_key, location_id=location_id)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"https://services.leadconnectorhq.com/contacts/{cid}", headers=headers)
    if resp.status_code != 200:
        if resp.status_code in (401, 403) and not await get_gohighlevel_location_token(tenant_id, location_id):
            return {"ok": False, "error": "missing_location_token", "error_detail": "This location requires a GoHighLevel Location Private Integration Token. Ask your tenant admin to add it in Integrations → GoHighLevel."}
        return {"ok": False, "error": f"gohighlevel_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    try:
        data = resp.json() or {}
    except Exception:
        return {"ok": False, "error": "gohighlevel_bad_json", "error_detail": (resp.text or "")[:300]}
    contact = data.get("contact") or data
    return {"ok": True, "contact": contact}


def _extract_services_products_from_ghl_contact(contact: Dict[str, Any]) -> Dict[str, Any]:
    tags = contact.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags = [str(t).strip() for t in tags if str(t).strip()]

    services = []
    products = []
    for t in tags:
        tl = t.lower().strip()
        if tl.startswith("service:"):
            services.append(t.split(":", 1)[1].strip())
        if tl.startswith("product:"):
            products.append(t.split(":", 1)[1].strip())
        if tl.startswith("deliverable:"):
            services.append(t.split(":", 1)[1].strip())

    custom_fields = contact.get("customFields") or []
    if isinstance(custom_fields, dict):
        custom_fields = [custom_fields]

    crm_data = {
        "tags": tags,
        "customFields": custom_fields,
        "source": contact.get("source"),
        "dateAdded": contact.get("dateAdded") or contact.get("date_added"),
        "timezone": contact.get("timezone"),
        "businessId": contact.get("businessId") or contact.get("business_id"),
        "attributions": contact.get("attributions") or [],
    }
    return {
        "services": sorted({s for s in services if s}),
        "assigned_products": sorted({p for p in products if p}),
        "crm_data": crm_data,
    }


def _extract_domain(v: str) -> str:
    s = str(v or "").strip().lower()
    s = s.replace("https://", "").replace("http://", "")
    s = s.split("/", 1)[0]
    return s.strip()


async def _gbp_list_accounts(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    url = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params={"pageSize": 100})
    if resp.status_code != 200:
        return {"ok": False, "error": f"gbp_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    return {"ok": True, "accounts": (resp.json() or {}).get("accounts") or []}


async def _gbp_list_locations(access_token: str, account_name: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    url = f"https://mybusinessbusinessinformation.googleapis.com/v1/{str(account_name).strip()}/locations"
    params = {"readMask": "name,title,websiteUri,phoneNumbers,storefrontAddress"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return {"ok": False, "error": f"gbp_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    return {"ok": True, "locations": (resp.json() or {}).get("locations") or []}


async def _gbp_get_location(access_token: str, location_name: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    url = f"https://mybusinessbusinessinformation.googleapis.com/v1/{str(location_name).strip()}"
    read_mask = ",".join(
        [
            "name",
            "title",
            "websiteUri",
            "phoneNumbers",
            "storefrontAddress",
            "serviceArea",
            "primaryCategory",
            "additionalCategories",
            "regularHours",
            "specialHours",
            "profileDescription",
        ]
    )
    params = {"readMask": read_mask}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return {"ok": False, "error": f"gbp_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    return {"ok": True, "location": resp.json() or {}}


async def _gbp_list_reviews(access_token: str, location_name: str, page_size: int = 50) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    url = f"https://mybusinessreviews.googleapis.com/v1/{str(location_name).strip()}/reviews"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params={"pageSize": max(1, min(int(page_size or 50), 200))})
    if resp.status_code != 200:
        return {"ok": False, "error": f"gbp_reviews_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    return {"ok": True, "reviews": data.get("reviews") or []}


def _gbp_extract_service_areas(location: dict) -> List[str]:
    sa = location.get("serviceArea") if isinstance(location, dict) else None
    if not isinstance(sa, dict):
        return []
    places = sa.get("places")
    out = []
    if isinstance(places, dict):
        regs = places.get("placeInfos") or []
        if isinstance(regs, list):
            for p in regs:
                if not isinstance(p, dict):
                    continue
                nm = str(p.get("placeName") or "").strip()
                if nm:
                    out.append(nm)
    return sorted({x for x in out if x})


def _gbp_extract_categories(location: dict) -> List[str]:
    out = []
    if not isinstance(location, dict):
        return []
    pc = location.get("primaryCategory")
    if isinstance(pc, dict):
        n = str(pc.get("displayName") or "").strip()
        if n:
            out.append(n)
    ac = location.get("additionalCategories") or []
    if isinstance(ac, list):
        for c in ac:
            if not isinstance(c, dict):
                continue
            n = str(c.get("displayName") or "").strip()
            if n:
                out.append(n)
    return sorted({x for x in out if x})


async def fetch_gbp_profile_for_client(tenant_id: str, user_id: str, client_id: str) -> Dict[str, Any]:
    binding = await get_client_binding(tenant_id, str(client_id), "google_business_profile")
    if not binding:
        return {"ok": False, "error": "gbp_not_connected"}
    ext = binding.get("external_ids") or {}
    account_name = str(ext.get("account_name") or "").strip()
    location_name = str(ext.get("location_name") or "").strip()
    if not account_name or not location_name:
        return {"ok": False, "error": "gbp_missing_binding"}

    rt = await get_google_refresh_token(tenant_id, user_id, "google_business_profile")
    if not rt:
        return {"ok": False, "error": "gbp_missing_oauth"}
    try:
        access_token = await _google_ads_access_token_for_tenant(tenant_id, {"refresh_token": rt})
    except Exception as exc:
        return {"ok": False, "error": "gbp_oauth_error", "error_detail": str(exc)[:300]}

    loc_res = await _gbp_get_location(access_token, location_name=location_name)
    if not loc_res.get("ok"):
        return loc_res
    location = loc_res.get("location") or {}

    rev_res = await _gbp_list_reviews(access_token, location_name=location_name, page_size=50)
    reviews = rev_res.get("reviews") if rev_res.get("ok") else []
    rating_vals = []
    for r in reviews or []:
        if not isinstance(r, dict):
            continue
        rv = r.get("starRating")
        if isinstance(rv, str):
            m = re.search(r"(\d)", rv)
            if m:
                rating_vals.append(int(m.group(1)))
        elif isinstance(rv, int):
            rating_vals.append(int(rv))

    avg_rating = round(sum(rating_vals) / float(len(rating_vals)), 2) if rating_vals else None

    return {
        "ok": True,
        "account_name": account_name,
        "location_name": location_name,
        "business_name": str(location.get("title") or "").strip(),
        "website": str(location.get("websiteUri") or "").strip(),
        "storefront_address": location.get("storefrontAddress") or {},
        "service_areas": _gbp_extract_service_areas(location),
        "categories": _gbp_extract_categories(location),
        "reviews_count": len(reviews or []) if isinstance(reviews, list) else 0,
        "avg_rating": avg_rating,
        "raw_location": location,
        "raw_reviews": reviews or [],
    }


async def find_best_gbp_location_for_client(tenant_id: str, user_id: str, company: str, website: str, phone: str) -> Dict[str, Any]:
    rt = await get_google_refresh_token(tenant_id, user_id, "google_business_profile")
    if not rt:
        return {"ok": False, "error": "missing_google_connection"}
    try:
        access_token = await _google_ads_access_token_for_tenant(tenant_id, {"refresh_token": rt})
    except Exception as exc:
        return {"ok": False, "error": "oauth_error", "error_detail": str(exc)[:300]}

    acc_res = await _gbp_list_accounts(access_token)
    if not acc_res.get("ok"):
        return acc_res
    accounts = acc_res.get("accounts") or []

    want_domain = _extract_domain(website)
    want_phone = re.sub(r"\D+", "", str(phone or ""))
    want_name = (company or "").strip().lower()

    best = None
    best_score = -1
    for a in accounts:
        acct_name = a.get("name")
        if not acct_name:
            continue
        loc_res = await _gbp_list_locations(access_token, acct_name)
        if not loc_res.get("ok"):
            continue
        for loc in loc_res.get("locations") or []:
            score = 0
            title = str(loc.get("title") or "").strip()
            loc_domain = _extract_domain(loc.get("websiteUri") or "")
            phones = loc.get("phoneNumbers") or {}
            prim = str((phones.get("primaryPhone") if isinstance(phones, dict) else "") or "").strip()
            loc_phone = re.sub(r"\D+", "", prim)
            if want_domain and loc_domain and want_domain == loc_domain:
                score += 3
            if want_phone and loc_phone and want_phone[-7:] == loc_phone[-7:]:
                score += 2
            if want_name and title and want_name in title.lower():
                score += 2
            if score > best_score:
                best_score = score
                best = {"account_name": acct_name, "location": loc, "match_score": score}

    if not best:
        return {"ok": True, "match": None}
    return {"ok": True, "match": best}


async def list_gbp_locations_for_user(tenant_id: str, user_id: str) -> Dict[str, Any]:
    rt = await get_google_refresh_token(tenant_id, user_id, "google_business_profile")
    if not rt:
        return {"ok": False, "error": "missing_google_connection", "error_detail": "Connect Google for Google Business Profile first."}
    try:
        access_token = await _google_ads_access_token_for_tenant(tenant_id, {"refresh_token": rt})
    except Exception as exc:
        return {"ok": False, "error": "oauth_error", "error_detail": str(exc)[:300]}

    acc_res = await _gbp_list_accounts(access_token)
    if not acc_res.get("ok"):
        return acc_res
    accounts = acc_res.get("accounts") or []

    out = []
    for a in accounts:
        acct_name = a.get("name")
        if not acct_name:
            continue
        loc_res = await _gbp_list_locations(access_token, acct_name)
        if not loc_res.get("ok"):
            continue
        for loc in loc_res.get("locations") or []:
            loc_name = str(loc.get("name") or "").strip()
            title = str(loc.get("title") or "").strip()
            website = str(loc.get("websiteUri") or "").strip()
            phones = loc.get("phoneNumbers") or {}
            phone = str((phones.get("primaryPhone") if isinstance(phones, dict) else "") or "").strip()
            out.append(
                {
                    "account_name": str(acct_name),
                    "location_name": loc_name,
                    "title": title,
                    "website": website,
                    "phone": phone,
                    "storefront_address": loc.get("storefrontAddress") or {},
                }
            )

    return {"ok": True, "locations": out}


async def list_gohighlevel_conversations(tenant_id: str, location_id: str, contact_id: str, limit: int = 50) -> Dict[str, Any]:
    api_key = await _gohighlevel_token_for_location(tenant_id, location_id)
    if not api_key:
        return {"ok": False, "error": "missing_api_key"}
    if not location_id:
        return {"ok": False, "error": "missing_location_id"}
    if not contact_id:
        return {"ok": False, "error": "missing_contact_id"}
    headers = _ghl_headers(api_key, location_id=location_id)
    params = {"locationId": str(location_id), "contactId": str(contact_id), "limit": int(limit or 50), "sort": "desc", "sortBy": "last_message_date", "status": "all"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get("https://services.leadconnectorhq.com/conversations/search", headers=headers, params=params)
    if resp.status_code != 200:
        if resp.status_code in (401, 403) and not await get_gohighlevel_location_token(tenant_id, location_id):
            return {"ok": False, "error": "missing_location_token", "error_detail": "This location requires a GoHighLevel Location Private Integration Token. Ask your tenant admin to add it in Integrations → GoHighLevel."}
        return {"ok": False, "error": f"gohighlevel_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
    data = resp.json() or {}
    convs = data.get("conversations") or []
    out = []
    for c in convs:
        cid = c.get("id")
        if cid:
            out.append({"id": str(cid), "lastMessageType": c.get("lastMessageType"), "lastMessageBody": c.get("lastMessageBody")})
    return {"ok": True, "conversations": out}


async def list_gohighlevel_messages(tenant_id: str, location_id: str, conversation_id: str, limit: int = 100) -> Dict[str, Any]:
    api_key = await _gohighlevel_token_for_location(tenant_id, location_id)
    if not api_key:
        return {"ok": False, "error": "missing_api_key"}
    if not location_id:
        return {"ok": False, "error": "missing_location_id"}
    if not conversation_id:
        return {"ok": False, "error": "missing_conversation_id"}
    headers = _ghl_headers(api_key, location_id=location_id)
    all_msgs = []
    last_message_id: Optional[str] = None
    for _ in range(20):
        params: Dict[str, Any] = {"limit": int(limit or 100)}
        if last_message_id:
            params["lastMessageId"] = last_message_id
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://services.leadconnectorhq.com/conversations/{conversation_id}/messages",
                headers=headers,
                params=params,
            )
        if resp.status_code != 200:
            if resp.status_code in (401, 403) and not await get_gohighlevel_location_token(tenant_id, location_id):
                return {"ok": False, "error": "missing_location_token", "error_detail": "This location requires a GoHighLevel Location Private Integration Token. Ask your tenant admin to add it in Integrations → GoHighLevel."}
            return {"ok": False, "error": f"gohighlevel_http_{resp.status_code}", "error_detail": _safe_err_detail(resp)}
        data = resp.json() or {}
        wrapper = data.get("messages") or {}
        msgs = wrapper.get("messages") if isinstance(wrapper, dict) else None
        if not isinstance(msgs, list):
            msgs = []
        all_msgs.extend(msgs)
        next_page = bool(wrapper.get("nextPage")) if isinstance(wrapper, dict) else False
        last_message_id = str(wrapper.get("lastMessageId") or "") if isinstance(wrapper, dict) else ""
        if not next_page or not last_message_id:
            break
    out = []
    for m in all_msgs:
        body = m.get("body")
        if isinstance(body, str):
            body = unescape(body)
            body = re.sub(r"\s+", " ", body).strip()
        out.append(
            {
                "id": str(m.get("id") or ""),
                "messageType": m.get("messageType"),
                "direction": m.get("direction"),
                "dateAdded": m.get("dateAdded"),
                "body": body or "",
                "from": m.get("from"),
                "to": m.get("to"),
                "attachments": m.get("attachments") or [],
            }
        )
    return {"ok": True, "messages": out}


async def list_gmail_messages_for_contact(tenant_id: str, user_id: str, email: str, max_messages: int = 50) -> Dict[str, Any]:
    em = (email or "").strip()
    if not em:
        return {"ok": True, "messages": []}
    refresh_token = await get_google_refresh_token(tenant_id, user_id, "gmail")
    if not refresh_token:
        return {"ok": False, "error": "missing_google_connection", "error_detail": "Connect Google for Gmail first."}
    try:
        access_token = await _google_ads_access_token_for_tenant(tenant_id, {"refresh_token": refresh_token})
    except Exception as exc:
        return {"ok": False, "error": "oauth_error", "error_detail": str(exc)[:300]}

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    q = f"(from:{em} OR to:{em})"
    async with httpx.AsyncClient(timeout=30) as client:
        r1 = await client.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", headers=headers, params={"q": q, "maxResults": int(max_messages or 50)})
    if r1.status_code != 200:
        return {"ok": False, "error": f"gmail_http_{r1.status_code}", "error_detail": _safe_err_detail(r1)}
    ids = (r1.json() or {}).get("messages") or []
    out = []
    for item in ids[: int(max_messages or 50)]:
        mid = (item or {}).get("id")
        if not mid:
            continue
        async with httpx.AsyncClient(timeout=30) as client:
            r2 = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                headers=headers,
                params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]},
            )
        if r2.status_code != 200:
            continue
        m = r2.json() or {}
        headers_meta = {h.get("name"): h.get("value") for h in ((m.get("payload") or {}).get("headers") or []) if isinstance(h, dict) and h.get("name")}
        out.append(
            {
                "id": str(mid),
                "date": headers_meta.get("Date") or "",
                "from": headers_meta.get("From") or "",
                "to": headers_meta.get("To") or "",
                "subject": headers_meta.get("Subject") or "",
                "snippet": (m.get("snippet") or ""),
            }
        )
    return {"ok": True, "messages": out}
