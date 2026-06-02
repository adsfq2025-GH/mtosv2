from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import HTTPException

from db import db, decrypt_secret
from integrations_meta import demo_kpi_snapshot


def _tenant_scope(tenant_id: str) -> dict:
    return {"$or": [{"tenant_id": tenant_id}, {"tenant_id": {"$exists": False}}]}


async def _get_integration_doc(tenant_id: str, platform: str) -> Optional[dict]:
    return await db.integrations.find_one({"$and": [{"platform": platform}, _tenant_scope(tenant_id)]})


async def get_credentials(tenant_id: str, platform: str) -> Dict[str, str]:
    doc = await _get_integration_doc(tenant_id, platform)
    if not doc:
        return {}
    enc = doc.get("credentials_encrypted") or {}
    meta = doc.get("metadata") or {}
    dec = {k: decrypt_secret(v) for k, v in enc.items()} if enc else {}
    return {**meta, **dec}


async def get_client_binding(tenant_id: str, client_id: str, platform: str) -> Optional[dict]:
    return await db.client_bindings.find_one(
        {"$and": [{"client_id": client_id, "platform": platform, "enabled": True}, _tenant_scope(tenant_id)]}
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _last_30_days_range() -> Tuple[date, date]:
    end = _utc_now().date()
    start = end - timedelta(days=30)
    return start, end


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
            if data.get("message"):
                return str(data.get("message"))
            if data.get("err"):
                return str(data.get("err"))
            if data.get("error"):
                return str(data.get("error"))
        return str(data)[:300]
    except Exception:
        return (resp.text or "")[:300]


async def fetch_clickup_monthly(creds: Dict[str, str], binding: dict) -> Dict[str, Any]:
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

    start_d, _ = _last_30_days_range()
    date_updated_gt = str(int(start_d.replace(tzinfo=timezone.utc).timestamp() * 1000))
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

    data = resp.json() or {}
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


async def fetch_gohighlevel_monthly(creds: Dict[str, str], binding: dict) -> Dict[str, Any]:
    api_key = _strip_bearer((creds or {}).get("api_key", ""))
    location_id = (
        (binding.get("external_ids") or {}).get("location_id")
        or (binding.get("config") or {}).get("location_id")
        or (creds or {}).get("location_id")
    )
    if not api_key or not location_id:
        return {}

    start_d, end_d = _last_30_days_range()
    url = "https://services.leadconnectorhq.com/opportunities/search"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Version": "2023-02-21",
    }

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
        return resp.json() or {}

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
    cid = (creds or {}).get("oauth_client_id")
    secret = (creds or {}).get("oauth_client_secret")
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


def _normalize_customer_id(v: Any) -> str:
    s = str(v or "").strip()
    return s.replace("-", "").replace(" ", "")


async def fetch_google_ads_monthly(creds: Dict[str, str], binding: dict) -> Dict[str, Any]:
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

    access_token = await _google_ads_access_token(creds)
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


async def build_kpi_snapshot(tenant_id: str, client_id: str, client_name: str = "") -> Dict[str, Any]:
    snapshot = demo_kpi_snapshot(client_name)

    clickup_creds = await get_credentials(tenant_id, "clickup")
    clickup_binding = await get_client_binding(tenant_id, client_id, "clickup")
    if (clickup_creds or {}).get("api_token"):
        folder_id = ((clickup_binding or {}).get("external_ids") or {}).get("folder_id") or ((clickup_binding or {}).get("config") or {}).get("folder_id")
        if clickup_binding and folder_id:
            clickup_data = await fetch_clickup_monthly(clickup_creds, clickup_binding)
            if clickup_data:
                snapshot["clickup"] = {**(snapshot.get("clickup") or {}), **clickup_data}
        else:
            snapshot["clickup"] = {**(snapshot.get("clickup") or {}), "error": "clickup_missing_client_mapping", "error_detail": "Missing ClickUp Folder ID mapping for this client."}

    ghl_creds = await get_credentials(tenant_id, "gohighlevel")
    ghl_binding = await get_client_binding(tenant_id, client_id, "gohighlevel")
    if (ghl_creds or {}).get("api_key"):
        ghl_data = await fetch_gohighlevel_monthly(ghl_creds, ghl_binding or {"external_ids": {}, "config": {}})
        if ghl_data:
            snapshot["gohighlevel"] = {**(snapshot.get("gohighlevel") or {}), **ghl_data}
        else:
            snapshot["gohighlevel"] = {**(snapshot.get("gohighlevel") or {}), "error": "gohighlevel_missing_location_id", "error_detail": "Missing GoHighLevel location_id (set it in the client mapping or integration settings)."}

    gads_creds = await get_credentials(tenant_id, "google_ads")
    gads_binding = await get_client_binding(tenant_id, client_id, "google_ads")
    if (gads_creds or {}).get("developer_token") and (gads_creds or {}).get("refresh_token"):
        try:
            gads_data = await fetch_google_ads_monthly(gads_creds, gads_binding or {"external_ids": {}, "config": {}})
            if gads_data:
                snapshot["google_ads"] = {**(snapshot.get("google_ads") or {}), **gads_data}
        except Exception as exc:
            snapshot["google_ads"] = {**(snapshot.get("google_ads") or {}), "error": "google_ads_error", "error_detail": str(exc)[:300]}

    return snapshot


async def test_clickup(tenant_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "clickup")
    token = _strip_bearer((creds or {}).get("api_token", ""))
    if not token:
        return {"ok": False, "error": "missing_api_token"}
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


async def list_google_ads_customers(tenant_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "google_ads")
    developer_token = (creds or {}).get("developer_token")
    if not developer_token:
        return {"ok": False, "error": "missing_developer_token"}
    try:
        access_token = await _google_ads_access_token(creds)
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
    res = await list_google_ads_customers(tenant_id)
    if not res.get("ok"):
        return res
    return {"ok": True, "customers_found": len(res.get("customers") or [])}


async def test_google_meet(tenant_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "google_meet")
    try:
        await _google_ads_access_token(creds)
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


async def list_google_meet_conference_records(tenant_id: str, meet_code: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "google_meet")
    try:
        access_token = await _google_ads_access_token(creds)
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


async def _get_google_meet_transcripts(tenant_id: str, conference_record_name: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "google_meet")
    try:
        access_token = await _google_ads_access_token(creds)
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


async def _google_docs_document(tenant_id: str, document_id: str) -> Dict[str, Any]:
    creds = await get_credentials(tenant_id, "google_meet")
    try:
        access_token = await _google_ads_access_token(creds)
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


async def sync_google_meet_transcript_to_meeting(tenant_id: str, meeting: dict) -> Dict[str, Any]:
    meet_code = _meet_code_from_url((meeting or {}).get("google_meet_url") or "")
    if not meet_code:
        return {"ok": False, "error": "missing_meet_url"}

    recs = await list_google_meet_conference_records(tenant_id, meet_code)
    if not recs.get("ok"):
        return recs
    records = recs.get("conference_records") or []
    if not records:
        return {"ok": False, "error": "no_conference_records"}

    record = records[0]
    record_name = record.get("name")
    if not record_name:
        return {"ok": False, "error": "invalid_conference_record"}

    trs = await _get_google_meet_transcripts(tenant_id, record_name)
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

    gdoc = await _google_docs_document(tenant_id, str(document_id))
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
    token = _strip_bearer((creds or {}).get("api_token", ""))
    if not token:
        return {"ok": False, "error": "missing_api_token"}
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
    token = _strip_bearer((creds or {}).get("api_token", ""))
    if not token:
        return {"ok": False, "error": "missing_api_token"}
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
    token = _strip_bearer((creds or {}).get("api_token", ""))
    if not token:
        return {"ok": False, "error": "missing_api_token"}
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
