from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from db import db, new_id, utcnow
import connectors
from models import Client, ClientIntegrationBinding


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _clickup_headers(token: str) -> Dict[str, str]:
    t = connectors._strip_bearer(token or "")
    return {"Authorization": t, "Accept": "application/json"}


async def _clickup_get(url: str, headers: Dict[str, str], params: Optional[dict] = None, timeout: int = 30) -> Tuple[int, Any, str]:
    last_err = ""
    for i in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 200:
                try:
                    return 200, resp.json() or {}, ""
                except Exception:
                    return 200, {}, ""
            last_err = connectors._safe_err_detail(resp)
        except Exception as e:
            last_err = str(e)
        await asyncio.sleep(0.6 * (2 ** i))
    return 0, {}, last_err or "ClickUp request failed"


async def _clickup_list_spaces(team_id: str, headers: Dict[str, str]) -> List[dict]:
    _, data, _ = await _clickup_get(f"https://api.clickup.com/api/v2/team/{team_id}/space", headers=headers)
    return (data or {}).get("spaces") or []


async def _clickup_list_lists_in_space(space_id: str, headers: Dict[str, str]) -> List[dict]:
    _, data, _ = await _clickup_get(f"https://api.clickup.com/api/v2/space/{space_id}/list", headers=headers)
    return (data or {}).get("lists") or []


async def _clickup_list_folders_in_space(space_id: str, headers: Dict[str, str]) -> List[dict]:
    _, data, _ = await _clickup_get(f"https://api.clickup.com/api/v2/space/{space_id}/folder", headers=headers)
    return (data or {}).get("folders") or []


async def _clickup_list_lists_in_folder(folder_id: str, headers: Dict[str, str]) -> List[dict]:
    _, data, _ = await _clickup_get(f"https://api.clickup.com/api/v2/folder/{folder_id}/list", headers=headers)
    return (data or {}).get("lists") or []


async def _clickup_get_list(list_id: str, headers: Dict[str, str]) -> Optional[dict]:
    status, data, _ = await _clickup_get(f"https://api.clickup.com/api/v2/list/{list_id}", headers=headers)
    return data if status == 200 else None


async def resolve_client_health_tracker_list_id(tenant_id: str, token: str, team_id: str) -> Dict[str, Any]:
    headers = _clickup_headers(token)
    integration = await db.integrations.find_one({"tenant_id": tenant_id, "platform": "clickup"})
    cached = str(((integration or {}).get("metadata") or {}).get("client_health_tracker_list_id") or "").strip()
    if cached:
        exists = await _clickup_get_list(cached, headers=headers)
        if exists and _norm(str(exists.get("name") or "")) == _norm("Client Health Tracker"):
            return {"ok": True, "list_id": cached, "list": exists, "source": "cached"}

    wanted = _norm("Client Health Tracker")
    spaces = await _clickup_list_spaces(team_id, headers=headers)
    for s in spaces:
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        direct_lists = await _clickup_list_lists_in_space(sid, headers=headers)
        for l in direct_lists:
            if _norm(str(l.get("name") or "")) == wanted:
                list_id = str(l.get("id") or "").strip()
                if list_id:
                    await db.integrations.update_one(
                        {"tenant_id": tenant_id, "platform": "clickup"},
                        {"$set": {"metadata.client_health_tracker_list_id": list_id, "updated_at": utcnow().isoformat()}},
                        upsert=True,
                    )
                    return {"ok": True, "list_id": list_id, "list": l, "source": "discovered"}
        folders = await _clickup_list_folders_in_space(sid, headers=headers)
        for f in folders:
            fid = str(f.get("id") or "").strip()
            if not fid:
                continue
            folder_lists = await _clickup_list_lists_in_folder(fid, headers=headers)
            for l in folder_lists:
                if _norm(str(l.get("name") or "")) == wanted:
                    list_id = str(l.get("id") or "").strip()
                    if list_id:
                        await db.integrations.update_one(
                            {"tenant_id": tenant_id, "platform": "clickup"},
                            {"$set": {"metadata.client_health_tracker_list_id": list_id, "updated_at": utcnow().isoformat()}},
                            upsert=True,
                        )
                        return {"ok": True, "list_id": list_id, "list": l, "source": "discovered"}
    return {"ok": False, "error": "clickup_list_not_found", "error_detail": "Could not find a ClickUp list named 'Client Health Tracker'."}


async def fetch_client_health_tracker_tasks(token: str, list_id: str) -> Dict[str, Any]:
    headers = _clickup_headers(token)
    tasks: List[dict] = []
    page = 0
    while True:
        status, data, err = await _clickup_get(
            f"https://api.clickup.com/api/v2/list/{list_id}/task",
            headers=headers,
            params={"include_closed": "true", "subtasks": "true", "page": str(page)},
        )
        if status != 200:
            return {"ok": False, "error": "clickup_tasks_failed", "error_detail": err or "Failed to fetch tasks"}
        batch = (data or {}).get("tasks") or []
        if not batch:
            break
        tasks.extend(batch)
        page += 1
        if page >= 20:
            break
    return {"ok": True, "tasks": tasks}


def _custom_field_value(task: dict, field_name: str) -> Optional[str]:
    wanted = _norm(field_name)
    for cf in (task or {}).get("custom_fields") or []:
        if _norm(str(cf.get("name") or "")) != wanted:
            continue
        val = cf.get("value")
        if val is None:
            return None
        options = (((cf.get("type_config") or {}).get("options")) or []) if isinstance(cf.get("type_config"), dict) else []
        if options:
            for opt in options:
                if str(opt.get("id")) == str(val):
                    return str(opt.get("name") or "").strip() or None
        if isinstance(val, list):
            return ", ".join([str(x).strip() for x in val if str(x).strip()]) or None
        if isinstance(val, dict):
            for k in ("name", "label", "value", "email"):
                if val.get(k):
                    return str(val.get(k)).strip()
            return str(val)[:200]
        return str(val).strip() or None
    return None


def _match_account_manager(field_value: str, user_name: str, user_email: str) -> bool:
    v = _norm(field_value)
    if not v:
        return False
    name = _norm(user_name)
    email = _norm(user_email)
    first = _norm((user_name or "").split(" ", 1)[0])
    local = _norm((user_email or "").split("@", 1)[0])
    candidates = {name, email, first, local}
    parts = {_norm(p) for p in (field_value or "").replace(";", ",").split(",") if _norm(p)}
    return bool(parts & candidates) or v in candidates


def _task_is_closed(task: dict) -> bool:
    st = (task or {}).get("status") or {}
    status = _norm(str(st.get("status") or ""))
    return bool(st.get("type") == "closed") or status in ("closed", "complete", "completed", "done")


def _extract_client_from_task(task: dict) -> dict:
    company = str((task or {}).get("name") or "").strip()
    name = _custom_field_value(task, "Contact Name") or _custom_field_value(task, "Primary Contact") or company
    email = _custom_field_value(task, "Email")
    phone = _custom_field_value(task, "Phone")
    website = _custom_field_value(task, "Website") or _custom_field_value(task, "Domain")
    location = _custom_field_value(task, "Location") or None
    return {
        "name": name or company,
        "company": company or name,
        "email": email,
        "phone": phone,
        "website": website,
        "location": location,
    }


async def sync_assigned_clients_for_user(tenant_id: str, user_id: str, user_name: str, user_email: str) -> Dict[str, Any]:
    started_at = utcnow().isoformat()
    run_id = new_id()
    state_key = {"tenant_id": tenant_id, "user_id": user_id}

    try:
        creds = await connectors.get_credentials(tenant_id, "clickup")
        token = connectors._strip_bearer(str((creds or {}).get("api_token") or ""))
        team_id = str((creds or {}).get("team_id") or "").strip()
        if not token:
            raise ValueError("ClickUp is not connected (missing api_token).")
        if not team_id:
            teams_res = await connectors.list_clickup_workspaces(tenant_id)
            teams = teams_res.get("teams") or []
            team_id = str((teams[0] or {}).get("id") or "").strip() if teams else ""
        if not team_id:
            raise ValueError("Missing ClickUp team_id. Set it in Integrations → ClickUp.")

        list_res = await resolve_client_health_tracker_list_id(tenant_id, token=token, team_id=team_id)
        if not list_res.get("ok"):
            raise ValueError(list_res.get("error_detail") or "Client Health Tracker list not found")
        list_id = str(list_res.get("list_id") or "").strip()

        tasks_res = await fetch_client_health_tracker_tasks(token=token, list_id=list_id)
        if not tasks_res.get("ok"):
            raise ValueError(tasks_res.get("error_detail") or "Failed to load ClickUp tasks")

        tasks = tasks_res.get("tasks") or []
        assigned_tasks: List[dict] = []
        for t in tasks:
            am = _custom_field_value(t, "Account Manager") or ""
            if _match_account_manager(am, user_name=user_name, user_email=user_email):
                assigned_tasks.append(t)

        created = 0
        updated = 0
        paused = 0
        task_ids_seen = set()

        for t in assigned_tasks:
            task_id = str(t.get("id") or "").strip()
            if not task_id:
                continue
            task_ids_seen.add(task_id)
            closed = _task_is_closed(t)
            extracted = _extract_client_from_task(t)
            company = str(extracted.get("company") or "").strip()
            if not company:
                continue

            binding_doc = await db.client_bindings.find_one(
                {"tenant_id": tenant_id, "platform": "clickup_client_health_tracker", "external_ids.task_id": task_id}
            )
            client_doc = None
            if binding_doc:
                client_id = str(binding_doc.get("client_id") or "").strip()
                client_doc = await db.clients.find_one({"_id": client_id, "tenant_id": tenant_id})
            if not client_doc and extracted.get("website"):
                client_doc = await db.clients.find_one({"tenant_id": tenant_id, "website": {"$regex": f"^{extracted.get('website')}$", "$options": "i"}})
            if not client_doc:
                client_doc = await db.clients.find_one({"tenant_id": tenant_id, "company": {"$regex": f"^{company}$", "$options": "i"}})

            base_crm = (client_doc.get("crm_data") or {}) if client_doc else {}
            patch = {
                "name": extracted.get("name"),
                "company": company,
                "email": extracted.get("email") or None,
                "phone": extracted.get("phone") or None,
                "website": extracted.get("website") or None,
                "location": extracted.get("location") or None,
                "account_manager_id": user_id,
                "account_manager_name": user_name,
                "status": "paused" if closed else "active",
                "updated_at": utcnow().isoformat(),
                "crm_data": {
                    **base_crm,
                    "clickup_client_health_tracker": {
                        "task_id": task_id,
                        "list_id": list_id,
                        "url": str(t.get("url") or ""),
                        "status": (t.get("status") or {}).get("status"),
                    },
                },
            }

            if client_doc:
                await db.clients.update_one({"_id": client_doc.get("_id"), "tenant_id": tenant_id}, {"$set": patch})
                updated += 1
                client_id = str(client_doc.get("_id"))
            else:
                c = Client(
                    tenant_id=tenant_id,
                    name=patch["name"],
                    company=patch["company"],
                    email=patch["email"],
                    phone=patch["phone"],
                    website=patch["website"],
                    location=patch["location"],
                    account_manager_id=user_id,
                    account_manager_name=user_name,
                    status=patch["status"],
                    crm_data=patch["crm_data"],
                )
                await db.clients.insert_one(c.to_mongo())
                created += 1
                client_id = c.id

            if not binding_doc:
                b = ClientIntegrationBinding(
                    tenant_id=tenant_id,
                    client_id=client_id,
                    platform="clickup_client_health_tracker",
                    enabled=True,
                    external_ids={"task_id": task_id, "list_id": list_id, "team_id": team_id},
                    config={},
                    updated_at=utcnow().isoformat(),
                )
                await db.client_bindings.insert_one(b.to_mongo())

            if closed:
                paused += 1

        stale = await db.client_bindings.find(
            {"tenant_id": tenant_id, "platform": "clickup_client_health_tracker", "enabled": True}
        ).to_list(5000)
        for b in stale:
            task_id = str(((b.get("external_ids") or {}).get("task_id")) or "").strip()
            if not task_id:
                continue
            if task_id in task_ids_seen:
                continue
            client_id = str(b.get("client_id") or "").strip()
            if not client_id:
                continue
            cdoc = await db.clients.find_one({"_id": client_id, "tenant_id": tenant_id})
            if not cdoc:
                continue
            if str(cdoc.get("account_manager_id") or "") != str(user_id):
                continue
            await db.clients.update_one(
                {"_id": client_id, "tenant_id": tenant_id},
                {"$set": {"account_manager_id": None, "account_manager_name": None, "status": "paused", "updated_at": utcnow().isoformat()}},
            )

        finished_at = utcnow().isoformat()
        out = {
            "ok": True,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "list_id": list_id,
            "created": created,
            "updated": updated,
            "paused": paused,
            "assigned_found": len(assigned_tasks),
        }
        await db.clickup_client_sync_logs.insert_one({"_id": run_id, "tenant_id": tenant_id, "user_id": user_id, **out})
        await db.clickup_client_sync_state.update_one(
            state_key,
            {"$set": {"tenant_id": tenant_id, "user_id": user_id, "last_success_at": finished_at, "last_error": None, "last_run_id": run_id, "updated_at": finished_at}},
            upsert=True,
        )
        return out
    except Exception as e:
        finished_at = utcnow().isoformat()
        err = str(e)
        out = {"ok": False, "run_id": run_id, "started_at": started_at, "finished_at": finished_at, "error": err}
        await db.clickup_client_sync_logs.insert_one({"_id": run_id, "tenant_id": tenant_id, "user_id": user_id, **out})
        await db.clickup_client_sync_state.update_one(
            state_key,
            {"$set": {"tenant_id": tenant_id, "user_id": user_id, "last_error": err, "last_run_id": run_id, "updated_at": finished_at}},
            upsert=True,
        )
        return out


async def sync_assigned_clients_for_all_users(tenant_id: str) -> Dict[str, Any]:
    memberships = await db.tenant_memberships.find({"tenant_id": tenant_id, "status": "active", "role": {"$ne": "viewer"}}).to_list(5000)
    user_ids = [str(m.get("user_id") or "") for m in memberships if str(m.get("user_id") or "").strip()]
    if not user_ids:
        return {"ok": True, "tenant_id": tenant_id, "runs": []}
    users = await db.users.find({"_id": {"$in": user_ids}, "active": True}).to_list(5000)
    runs = []
    for u in users:
        if str(u.get("role") or "") != "manager":
            continue
        runs.append(await sync_assigned_clients_for_user(tenant_id=tenant_id, user_id=str(u.get("_id")), user_name=str(u.get("name") or ""), user_email=str(u.get("email") or "")))
    return {"ok": True, "tenant_id": tenant_id, "runs": runs}


async def sync_all_tenants() -> Dict[str, Any]:
    tenants = await db.tenants.find({"status": "active"}).to_list(5000)
    results = []
    for t in tenants:
        tid = str(t.get("_id") or "").strip()
        if not tid:
            continue
        results.append(await sync_assigned_clients_for_all_users(tenant_id=tid))
    return {"ok": True, "tenants": results, "ran_at": utcnow().isoformat()}
