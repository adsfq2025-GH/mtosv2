from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from db import db, decrypt_secret
from integrations_meta import demo_kpi_snapshot


async def _get_integration_doc(platform: str) -> Optional[dict]:
    return await db.integrations.find_one({"platform": platform})


async def get_credentials(platform: str) -> Dict[str, str]:
    doc = await _get_integration_doc(platform)
    if not doc:
        return {}
    enc = doc.get("credentials_encrypted") or {}
    meta = doc.get("metadata") or {}
    dec = {k: decrypt_secret(v) for k, v in enc.items()} if enc else {}
    return {**meta, **dec}


async def get_client_binding(client_id: str, platform: str) -> Optional[dict]:
    return await db.client_bindings.find_one({"client_id": client_id, "platform": platform, "enabled": True})


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


async def build_kpi_snapshot(client_id: str, client_name: str = "") -> Dict[str, Any]:
    snapshot = demo_kpi_snapshot(client_name)

    clickup_creds = await get_credentials("clickup")
    clickup_binding = await get_client_binding(client_id, "clickup")
    if (clickup_creds or {}).get("api_token"):
        folder_id = ((clickup_binding or {}).get("external_ids") or {}).get("folder_id") or ((clickup_binding or {}).get("config") or {}).get("folder_id")
        if clickup_binding and folder_id:
            clickup_data = await fetch_clickup_monthly(clickup_creds, clickup_binding)
            if clickup_data:
                snapshot["clickup"] = {**(snapshot.get("clickup") or {}), **clickup_data}
        else:
            snapshot["clickup"] = {**(snapshot.get("clickup") or {}), "error": "clickup_missing_client_mapping", "error_detail": "Missing ClickUp Folder ID mapping for this client."}

    ghl_creds = await get_credentials("gohighlevel")
    ghl_binding = await get_client_binding(client_id, "gohighlevel")
    if (ghl_creds or {}).get("api_key"):
        ghl_data = await fetch_gohighlevel_monthly(ghl_creds, ghl_binding or {"external_ids": {}, "config": {}})
        if ghl_data:
            snapshot["gohighlevel"] = {**(snapshot.get("gohighlevel") or {}), **ghl_data}
        else:
            snapshot["gohighlevel"] = {**(snapshot.get("gohighlevel") or {}), "error": "gohighlevel_missing_location_id", "error_detail": "Missing GoHighLevel location_id (set it in the client mapping or integration settings)."}

    return snapshot


async def test_clickup() -> Dict[str, Any]:
    creds = await get_credentials("clickup")
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


async def test_gohighlevel() -> Dict[str, Any]:
    creds = await get_credentials("gohighlevel")
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


async def list_clickup_workspaces() -> Dict[str, Any]:
    creds = await get_credentials("clickup")
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


async def list_clickup_folders(team_id: str) -> Dict[str, Any]:
    creds = await get_credentials("clickup")
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


async def list_clickup_lists(team_id: str) -> Dict[str, Any]:
    creds = await get_credentials("clickup")
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


async def list_gohighlevel_locations() -> Dict[str, Any]:
    creds = await get_credentials("gohighlevel")
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
