from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from db import db, decrypt_secret
from integrations_meta import demo_kpi_snapshot


async def _get_integration_doc(platform: str) -> Optional[dict]:
    return await db.integrations.find_one({"platform": platform})


async def get_credentials(platform: str) -> Dict[str, str]:
    doc = await _get_integration_doc(platform)
    if not doc or not doc.get("credentials_encrypted"):
        return {}
    enc = doc.get("credentials_encrypted") or {}
    return {k: decrypt_secret(v) for k, v in enc.items()}


async def get_client_binding(client_id: str, platform: str) -> Optional[dict]:
    return await db.client_bindings.find_one({"client_id": client_id, "platform": platform, "enabled": True})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def fetch_clickup_monthly(creds: Dict[str, str], binding: dict) -> Dict[str, Any]:
    token = (creds or {}).get("api_token", "").strip()
    list_id = (binding.get("external_ids") or {}).get("list_id") or (binding.get("config") or {}).get("list_id")
    if not token or not list_id:
        return {}

    headers = {"Authorization": token}
    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    params = {"archived": "false", "include_closed": "true", "page": 0}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return {"error": f"clickup_http_{resp.status_code}"}

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
        "list_id": str(list_id),
    }


async def fetch_gohighlevel_monthly(creds: Dict[str, str], binding: dict) -> Dict[str, Any]:
    api_key = (creds or {}).get("api_key", "").strip()
    location_id = (binding.get("external_ids") or {}).get("location_id") or (binding.get("config") or {}).get("location_id")
    if not api_key or not location_id:
        return {}
    return {"location_id": str(location_id)}


async def build_kpi_snapshot(client_id: str, client_name: str = "") -> Dict[str, Any]:
    snapshot = demo_kpi_snapshot(client_name)

    clickup_creds = await get_credentials("clickup")
    clickup_binding = await get_client_binding(client_id, "clickup")
    if clickup_creds and clickup_binding:
        clickup_data = await fetch_clickup_monthly(clickup_creds, clickup_binding)
        if clickup_data:
            snapshot["clickup"] = {**(snapshot.get("clickup") or {}), **clickup_data}

    ghl_creds = await get_credentials("gohighlevel")
    ghl_binding = await get_client_binding(client_id, "gohighlevel")
    if ghl_creds and ghl_binding:
        ghl_data = await fetch_gohighlevel_monthly(ghl_creds, ghl_binding)
        if ghl_data:
            snapshot["gohighlevel"] = {**(snapshot.get("gohighlevel") or {}), **ghl_data}

    return snapshot

