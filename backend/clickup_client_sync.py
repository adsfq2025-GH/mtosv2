from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import os
import re
import httpx

from db import new_id, utcnow
import connectors
from models import Client, ClientIntegrationBinding
from supabase_store import get_store


# region debug-point C0:clickup-sync-core
async def _dbg_emit(hypothesis_id: str, location: str, msg: str, data: Optional[dict] = None) -> None:
    try:
        url = (os.environ.get("DEBUG_SERVER_URL") or "").strip()
        if not url:
            return
        session_id = (os.environ.get("DEBUG_SESSION_ID") or "clickup-client-sync").strip() or "clickup-client-sync"
        async with httpx.AsyncClient(timeout=2) as c:
            await c.post(url, json={"sessionId": session_id, "runId": "pre", "hypothesisId": hypothesis_id, "location": location, "msg": msg, "data": data or {}, "ts": int(datetime.now(tz=timezone.utc).timestamp() * 1000)})
    except Exception:
        return
# endregion


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _clickup_headers(token: str) -> Dict[str, str]:
    t = connectors._strip_bearer(token or "")
    return {"Authorization": t, "Accept": "application/json"}


def _normalize_clickup_list_id(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    nums = re.findall(r"\d+", s)
    if not nums:
        return s
    return max(nums, key=len)


async def _save_clickup_integration_metadata(tenant_id: str, patch: dict[str, Any]) -> Optional[dict]:
    current = await connectors._get_integration_doc(tenant_id, "clickup") or {
        "tenant_id": tenant_id,
        "platform": "clickup",
        "label": "clickup",
        "status": "connected",
        "metadata": {},
    }
    next_doc = dict(current or {})
    next_doc["platform"] = "clickup"
    next_doc["label"] = str(next_doc.get("label") or "clickup")
    next_doc["status"] = str(next_doc.get("status") or "connected") or "connected"
    next_meta = dict(next_doc.get("metadata") or {})
    top_level_keys = {"label", "status", "last_synced_at", "last_error", "vault_secret_ref", "oauth_connection_ref"}
    for key, value in dict(patch or {}).items():
        if key in top_level_keys:
            next_doc[key] = value
        else:
            next_meta[key] = value
    next_doc["metadata"] = next_meta
    bridge = get_store()
    if bridge.is_enabled_for("integrations"):
        return await bridge.upsert_tenant_integration(tenant_id, next_doc)
    return next_doc


async def _write_sync_state(tenant_id: str, user_id: str, patch: dict[str, Any]) -> Optional[dict]:
    bridge = get_store()
    current = await bridge.get_clickup_client_sync_state(tenant_id, user_id) if bridge.is_enabled_for("clickup_sync") else None
    next_doc = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        **dict(current or {}),
        **dict(patch or {}),
    }
    if bridge.is_enabled_for("clickup_sync"):
        return await bridge.upsert_clickup_client_sync_state(tenant_id, user_id, next_doc)
    return next_doc


async def _write_sync_log(tenant_id: str, user_id: str, doc: dict[str, Any]) -> Optional[dict]:
    bridge = get_store()
    if bridge.is_enabled_for("clickup_sync"):
        return await bridge.create_clickup_client_sync_log(tenant_id, user_id, doc)
    return dict(doc or {})


async def _list_clients_for_tenant(tenant_id: str) -> List[dict]:
    bridge = get_store()
    if bridge.is_enabled_for("clients"):
        return await bridge.list_clients(tenant_id, limit=5000)
    return []


async def _list_clickup_bindings_for_tenant(tenant_id: str) -> List[dict]:
    bridge = get_store()
    if bridge.is_enabled_for("client_bindings"):
        return await bridge.list_tenant_client_bindings(tenant_id, platform="clickup_client_health_tracker", enabled=True, limit=5000)
    return []


async def _upsert_client_doc(tenant_id: str, doc: dict[str, Any]) -> Optional[dict]:
    bridge = get_store()
    if bridge.is_enabled_for("clients"):
        return await bridge.upsert_client(tenant_id, doc)
    return dict(doc or {})


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


async def _clickup_get_team(team_id: str, headers: Dict[str, str]) -> Optional[dict]:
    status, data, _ = await _clickup_get(f"https://api.clickup.com/api/v2/team/{team_id}", headers=headers)
    return data if status == 200 else None


def _resolve_clickup_user_ids(value: str, user_map: Dict[str, Dict[str, str]]) -> str:
    s = str(value or "").strip()
    if not s or not user_map:
        return s
    ids = [x for x in re.findall(r"\d+", s) if x]
    if not ids:
        return s
    out: List[str] = []
    seen = set()
    for uid in ids:
        u = user_map.get(str(uid)) or {}
        name = str(u.get("name") or u.get("username") or "").strip()
        email = str(u.get("email") or "").strip()
        label = name or email or ""
        if not label:
            continue
        key = _norm(label)
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return ", ".join(out) or s


def _task_assignees_value(task: dict, user_map: Dict[str, Dict[str, str]]) -> str:
    assignees = (task or {}).get("assignees") or []
    if not isinstance(assignees, list) or not assignees:
        return ""
    out: List[str] = []
    seen = set()
    for a in assignees:
        if not isinstance(a, dict):
            continue
        uid = str(a.get("id") or "").strip()
        username = str(a.get("username") or "").strip()
        email = str(a.get("email") or "").strip()
        label = username or email
        if not label and uid and user_map.get(uid):
            u = user_map[uid]
            label = str(u.get("name") or u.get("username") or u.get("email") or "").strip()
        key = _norm(label)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(label)
    return ", ".join(out)


def _task_account_manager_value(task: dict, user_map: Dict[str, Dict[str, str]]) -> str:
    v0 = _custom_field_value(task, "Account Manager") or ""
    if v0:
        return _resolve_clickup_user_ids(v0, user_map) if user_map else v0
    return _task_assignees_value(task, user_map)


async def resolve_client_health_tracker_list_id(tenant_id: str, token: str, team_id: str) -> Dict[str, Any]:
    headers = _clickup_headers(token)
    forced_raw = str(os.environ.get("CLICKUP_CLIENT_HEALTH_TRACKER_LIST_ID") or "").strip()
    forced = _normalize_clickup_list_id(forced_raw)
    if forced_raw and not forced:
        return {"ok": False, "error": "clickup_list_forced_invalid", "error_detail": f"CLICKUP_CLIENT_HEALTH_TRACKER_LIST_ID is invalid: {forced_raw}"}
    if forced:
        exists = await _clickup_get_list(forced, headers=headers)
        if exists:
            await _save_clickup_integration_metadata(tenant_id, {"client_health_tracker_list_id": forced})
            return {"ok": True, "list_id": forced, "list": exists, "source": "env"}
        return {"ok": False, "error": "clickup_list_forced_not_accessible", "error_detail": f"CLICKUP_CLIENT_HEALTH_TRACKER_LIST_ID not accessible: {forced_raw}"}
    integration = await connectors._get_integration_doc(tenant_id, "clickup")
    cached_raw = str(((integration or {}).get("metadata") or {}).get("client_health_tracker_list_id") or "").strip()
    cached = _normalize_clickup_list_id(cached_raw)
    if cached_raw and not cached:
        return {"ok": False, "error": "clickup_list_configured_invalid", "error_detail": f"Configured Client Health Tracker List ID is invalid: {cached_raw}"}
    if cached:
        exists = await _clickup_get_list(cached, headers=headers)
        if exists:
            if cached_raw != cached:
                await _save_clickup_integration_metadata(tenant_id, {"client_health_tracker_list_id": cached})
            return {"ok": True, "list_id": cached, "list": exists, "source": "configured"}
        if cached_raw:
            return {"ok": False, "error": "clickup_list_configured_not_accessible", "error_detail": f"Configured Client Health Tracker List ID not accessible: {cached_raw}"}

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
                    await _save_clickup_integration_metadata(tenant_id, {"client_health_tracker_list_id": list_id})
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
                        await _save_clickup_integration_metadata(tenant_id, {"client_health_tracker_list_id": list_id})
                        return {"ok": True, "list_id": list_id, "list": l, "source": "discovered"}
    return {"ok": False, "error": "clickup_list_not_found", "error_detail": "Could not find a ClickUp list named 'Client Health Tracker'."}


async def fetch_client_health_tracker_tasks(token: str, list_id: str) -> Dict[str, Any]:
    headers = _clickup_headers(token)
    tasks: List[dict] = []
    page = 0
    max_pages = int(os.environ.get("CLICKUP_CLIENT_HEALTH_TRACKER_MAX_PAGES", "200") or "200")
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
        last_page = (data or {}).get("last_page")
        if last_page is True:
            break
        page += 1
        if isinstance(last_page, int) and page > last_page:
            break
        if page >= max_pages:
            return {"ok": False, "error": "clickup_tasks_paging_cap", "error_detail": f"Exceeded max pages ({max_pages})"}
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
            opt_map = {str(opt.get("id")): str(opt.get("name") or "").strip() for opt in options}
            if isinstance(val, list):
                names: List[str] = []
                for x in val:
                    k = str((x.get("id") if isinstance(x, dict) else x))
                    if opt_map.get(k):
                        names.append(opt_map[k])
                out: List[str] = []
                seen = set()
                for n in names:
                    key = _norm(n)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    out.append(n)
                return ", ".join(out) or None
            k = str(val)
            if opt_map.get(k):
                return opt_map[k] or None
        if isinstance(val, list):
            out: List[str] = []
            for x in val:
                if isinstance(x, dict):
                    for k in ("name", "label", "value", "email"):
                        if x.get(k):
                            out.append(str(x.get(k)).strip())
                            break
                    continue
                s = str(x).strip()
                if s:
                    out.append(s)
            return ", ".join([s for s in dict.fromkeys(out) if s]) or None
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
    last = _norm((user_name or "").rsplit(" ", 1)[-1])
    local = _norm((user_email or "").split("@", 1)[0])
    candidates = {c for c in (name, email, first, last, local) if c}
    parts = {_norm(p) for p in re.split(r"[;,/|]+", field_value or "") if _norm(p)}
    if parts & candidates:
        return True
    if v in candidates:
        return True
    if first and (v == first or v.startswith(f"{first} ")):
        return True
    return False


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
        await _dbg_emit("H2", "clickup_client_sync:sync_assigned_clients_for_user", "run:begin", {"tenant_id": tenant_id, "user_id": user_id, "user_name": user_name, "user_email": user_email})
        await _write_sync_state(
            tenant_id,
            user_id,
            {"running": True, "started_at": started_at, "last_run_id": run_id, "updated_at": started_at},
        )
        creds = await connectors.get_credentials(tenant_id, "clickup")
        token = connectors._clickup_token_from_creds(creds)
        team_id = str((creds or {}).get("team_id") or "").strip()
        await _dbg_emit("H4", "clickup_client_sync:sync_assigned_clients_for_user", "creds:loaded", {"has_token": bool(token), "team_id": team_id})
        if not token:
            raise ValueError("ClickUp is not connected (missing personal token or OAuth access token).")
        if not team_id:
            teams_res = await connectors.list_clickup_workspaces(tenant_id)
            teams = teams_res.get("workspaces") or teams_res.get("teams") or []
            team_id = str((teams[0] or {}).get("id") or "").strip() if teams else ""
        if not team_id:
            raise ValueError("Missing ClickUp team_id. Set it in Integrations → ClickUp.")

        list_res = await resolve_client_health_tracker_list_id(tenant_id, token=token, team_id=team_id)
        if not list_res.get("ok"):
            raise ValueError(list_res.get("error_detail") or "Client Health Tracker list not found")
        list_id = str(list_res.get("list_id") or "").strip()
        await _dbg_emit("H3", "clickup_client_sync:sync_assigned_clients_for_user", "list:resolved", {"list_res": list_res})

        tasks_res = await fetch_client_health_tracker_tasks(token=token, list_id=list_id)
        if not tasks_res.get("ok"):
            raise ValueError(tasks_res.get("error_detail") or "Failed to load ClickUp tasks")

        tasks = tasks_res.get("tasks") or []
        headers = _clickup_headers(token)
        team = await _clickup_get_team(team_id, headers=headers)
        user_map: Dict[str, Dict[str, str]] = {}
        for m in (((team or {}).get("team") or {}).get("members") or []):
            u = (m or {}).get("user") or {}
            uid = str(u.get("id") or "").strip()
            if not uid:
                continue
            user_map[uid] = {
                "id": uid,
                "username": str(u.get("username") or "").strip(),
                "email": str(u.get("email") or "").strip(),
                "name": str(u.get("username") or "").strip(),
            }
        await _dbg_emit("H2", "clickup_client_sync:sync_assigned_clients_for_user", "team:loaded", {"members": len(user_map)})
        sample_ams: List[str] = []
        sample_custom_fields: List[str] = []
        for t in tasks[:20]:
            for cf in (t or {}).get("custom_fields") or []:
                n = str((cf or {}).get("name") or "").strip()
                if n:
                    sample_custom_fields.append(n[:120])
            v = _task_account_manager_value(t, user_map)
            if v:
                sample_ams.append(str(v)[:120])
        await _dbg_emit("H2", "clickup_client_sync:sync_assigned_clients_for_user", "tasks:fetched", {"total": len(tasks), "sample_account_manager_values": sample_ams[:10]})
        assigned_tasks: List[dict] = []
        for t in tasks:
            am = _task_account_manager_value(t, user_map)
            if _match_account_manager(am, user_name=user_name, user_email=user_email):
                assigned_tasks.append(t)
        await _dbg_emit("H2", "clickup_client_sync:sync_assigned_clients_for_user", "tasks:assigned_filtered", {"assigned": len(assigned_tasks), "total": len(tasks)})

        created = 0
        updated = 0
        paused = 0
        task_ids_seen = set()
        tenant_clients = await _list_clients_for_tenant(tenant_id)
        tenant_clients_by_id = {
            str((doc or {}).get("_id") or ""): dict(doc or {})
            for doc in tenant_clients
            if str((doc or {}).get("_id") or "").strip()
        }
        tenant_clients_by_company = {
            _norm(str((doc or {}).get("company") or "")): dict(doc or {})
            for doc in tenant_clients
            if _norm(str((doc or {}).get("company") or ""))
        }
        tenant_clients_by_website = {
            _norm(str((doc or {}).get("website") or "")): dict(doc or {})
            for doc in tenant_clients
            if _norm(str((doc or {}).get("website") or ""))
        }
        binding_by_task_id = {}
        for binding in await _list_clickup_bindings_for_tenant(tenant_id):
            task_id = str((((binding or {}).get("external_ids") or {}).get("task_id")) or "").strip()
            if task_id:
                binding_by_task_id[task_id] = dict(binding or {})

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

            binding_doc = binding_by_task_id.get(task_id)
            client_doc = None
            if binding_doc:
                client_id = str(binding_doc.get("client_id") or "").strip()
                client_doc = tenant_clients_by_id.get(client_id)
            if not client_doc and extracted.get("website"):
                client_doc = tenant_clients_by_website.get(_norm(str(extracted.get("website") or "")))
            if not client_doc:
                client_doc = tenant_clients_by_company.get(_norm(company))

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
                next_client = {**dict(client_doc or {}), **patch}
                stored_client = await _upsert_client_doc(tenant_id, next_client)
                updated += 1
                client_id = str(((stored_client or next_client) or {}).get("_id") or "")
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
                stored_client = await _upsert_client_doc(tenant_id, c.to_mongo())
                created += 1
                client_id = str(((stored_client or c.to_mongo()) or {}).get("_id") or c.id)
            if client_id:
                next_client_doc = dict(stored_client or next_client if client_doc else stored_client or c.to_mongo())
                tenant_clients_by_id[client_id] = next_client_doc
                tenant_clients_by_company[_norm(company)] = next_client_doc
                if _norm(str(extracted.get("website") or "")):
                    tenant_clients_by_website[_norm(str(extracted.get("website") or ""))] = next_client_doc

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
                binding_doc = await connectors._save_client_binding(tenant_id, client_id, b.to_mongo())
                if binding_doc:
                    binding_by_task_id[task_id] = binding_doc

            if closed:
                paused += 1

        stale = list(binding_by_task_id.values())
        for b in stale:
            task_id = str(((b.get("external_ids") or {}).get("task_id")) or "").strip()
            if not task_id:
                continue
            if task_id in task_ids_seen:
                continue
            client_id = str(b.get("client_id") or "").strip()
            if not client_id:
                continue
            cdoc = tenant_clients_by_id.get(client_id)
            if not cdoc:
                continue
            if str(cdoc.get("account_manager_id") or "") != str(user_id):
                continue
            next_client = {
                **dict(cdoc or {}),
                "account_manager_id": None,
                "account_manager_name": None,
                "status": "paused",
                "updated_at": utcnow().isoformat(),
            }
            stored_client = await _upsert_client_doc(tenant_id, next_client)
            tenant_clients_by_id[client_id] = dict(stored_client or next_client)

        finished_at = utcnow().isoformat()
        out = {
            "ok": True,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "list_id": list_id,
            "list_source": str(list_res.get("source") or ""),
            "created": created,
            "updated": updated,
            "paused": paused,
            "assigned_found": len(assigned_tasks),
            "debug_sample_account_managers": sample_ams[:10],
            "debug_sample_custom_field_names": [s for s in dict.fromkeys(sample_custom_fields) if s][:25],
        }
        await _write_sync_log(tenant_id, user_id, out)
        await _write_sync_state(
            tenant_id,
            user_id,
            {
                "running": False,
                "started_at": started_at,
                "finished_at": finished_at,
                "last_success_at": finished_at,
                "last_error": None,
                "last_run_id": run_id,
                "updated_at": finished_at,
            },
        )
        await _dbg_emit("H2", "clickup_client_sync:sync_assigned_clients_for_user", "run:ok", out)
        return out
    except Exception as e:
        finished_at = utcnow().isoformat()
        err = str(e)
        out = {"ok": False, "run_id": run_id, "started_at": started_at, "finished_at": finished_at, "error": err}
        await _dbg_emit("H2", "clickup_client_sync:sync_assigned_clients_for_user", "run:err", out)
        await _write_sync_log(tenant_id, user_id, out)
        await _write_sync_state(
            tenant_id,
            user_id,
            {
                "running": False,
                "started_at": started_at,
                "finished_at": finished_at,
                "last_error": err,
                "last_run_id": run_id,
                "updated_at": finished_at,
            },
        )
        return out


async def sync_assigned_clients_for_all_users(tenant_id: str) -> Dict[str, Any]:
    bridge = get_store()
    users: List[dict] = []
    if bridge.is_enabled_for("profiles") and bridge.is_enabled_for("tenants"):
        profiles = await bridge.list_user_profiles(limit=5000)
        for profile in profiles:
            memberships = await bridge.list_user_memberships(str((profile or {}).get("_id") or ""), limit=50)
            if any(
                str((membership or {}).get("tenant_id") or "") == str(tenant_id)
                and str((membership or {}).get("status") or "") == "active"
                and str((membership or {}).get("role") or "") != "viewer"
                for membership in memberships
            ):
                users.append(profile)
    else:
        users = []
    runs = []
    for u in users:
        if str(u.get("role") or "") != "manager":
            continue
        runs.append(await sync_assigned_clients_for_user(tenant_id=tenant_id, user_id=str(u.get("_id")), user_name=str(u.get("name") or ""), user_email=str(u.get("email") or "")))
    return {"ok": True, "tenant_id": tenant_id, "runs": runs}


async def sync_all_tenants() -> Dict[str, Any]:
    bridge = get_store()
    if bridge.is_enabled_for("tenants"):
        tenants = await bridge.list_tenants(status="active", limit=5000)
    else:
        tenants = []
    results = []
    for t in tenants:
        tid = str(t.get("_id") or "").strip()
        if not tid:
            continue
        results.append(await sync_assigned_clients_for_all_users(tenant_id=tid))
    return {"ok": True, "tenants": results, "ran_at": utcnow().isoformat()}
