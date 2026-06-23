from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import httpx

import connectors
from db import utcnow
from supabase_store import get_store


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _norm_spaces(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_list_id(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    nums = re.findall(r"\d+", s)
    return max(nums, key=len) if nums else s


def _normalize_custom_field_id(raw: Any) -> str:
    s = str(raw or "").strip()
    if s.lower().startswith("cf_"):
        s = s[3:]
    return s.strip()


def _clickup_base_url() -> str:
    return str(os.environ.get("MTOS_CLICKUP_BASE_URL") or "https://api.clickup.com/api/v2").strip().rstrip("/")


def _clickup_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": connectors._strip_bearer(token or ""),
        "Accept": "application/json",
    }


def _clickup_dev_max_pages() -> int:
    return int(os.environ.get("MTOS_CLICKUP_MAX_PAGES") or os.environ.get("CLICKUP_CLIENT_HEALTH_TRACKER_MAX_PAGES") or "1")


def _clickup_dev_max_tasks() -> int:
    return int(os.environ.get("MTOS_CLICKUP_MAX_TASKS") or "5")


async def _clickup_get(path: str, headers: Dict[str, str], *, params: Optional[dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{_clickup_base_url()}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params or {})
    except Exception as exc:
        return {"ok": False, "error": "clickup_request_failed", "error_detail": str(exc)}
    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"clickup_http_{resp.status_code}",
            "error_detail": connectors._safe_err_detail(resp) or resp.text[:400] or "ClickUp request failed",
            "status_code": resp.status_code,
        }
    try:
        data = resp.json() or {}
    except Exception:
        data = {}
    return {"ok": True, "data": data, "status_code": resp.status_code}


async def _get_clickup_config(tenant_id: str) -> dict[str, Any]:
    creds = await connectors.get_credentials(tenant_id, "clickup")
    token = connectors._strip_bearer(str(os.environ.get("MTOS_CLICKUP_API_TOKEN") or "").strip()) or connectors._clickup_token_from_creds(creds)
    team_id = str(os.environ.get("MTOS_CLICKUP_TEAM_ID") or (creds or {}).get("team_id") or "").strip()
    list_id = _normalize_list_id(
        os.environ.get("MTOS_CLICKUP_LIST_ID")
        or os.environ.get("CLICKUP_CLIENT_HEALTH_TRACKER_LIST_ID")
        or (creds or {}).get("client_health_tracker_list_id")
    )
    am_custom_field_id = _normalize_custom_field_id(
        os.environ.get("MTOS_CLICKUP_AM_CUSTOM_FIELD_ID")
        or (creds or {}).get("account_manager_custom_field_id")
        or (creds or {}).get("am_custom_field_id")
    )
    return {
        "configured": bool(token and team_id and list_id),
        "base_url": _clickup_base_url(),
        "api_token_present": bool(token),
        "team_id": team_id,
        "list_id": list_id,
        "am_custom_field_id": am_custom_field_id,
        "token": token,
    }


def get_clickup_status_payload(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": bool(config.get("configured")),
        "base_url": config.get("base_url") or _clickup_base_url(),
        "team_id": config.get("team_id") or "",
        "list_id": config.get("list_id") or "",
        "am_custom_field_id": config.get("am_custom_field_id") or "",
    }


async def ping_clickup(tenant_id: str) -> dict[str, Any]:
    config = await _get_clickup_config(tenant_id)
    if not config.get("configured"):
        return {"ok": False, "configured": False, "detail": "ClickUp is not fully configured. Set token, team_id, and raw numeric list_id."}
    headers = _clickup_headers(str(config.get("token") or ""))
    result = await _clickup_get(
        f"list/{config['list_id']}/task",
        headers,
        params={"page": "0", "include_closed": "true"},
    )
    if not result.get("ok"):
        return {"ok": False, **get_clickup_status_payload(config), "detail": result.get("error_detail") or result.get("error") or "ClickUp ping failed"}
    data = result.get("data") or {}
    return {
        "ok": True,
        **get_clickup_status_payload(config),
        "task_count_sample": len((data or {}).get("tasks") or []),
    }


def _extract_option_label(cf: dict[str, Any], raw_value: Any) -> Optional[str]:
    type_config = cf.get("type_config") if isinstance(cf.get("type_config"), dict) else {}
    options = list((type_config or {}).get("options") or [])
    option_map = {}
    for option in options:
        option_id = str((option or {}).get("id") or "").strip()
        if option_id:
            option_map[option_id] = str((option or {}).get("name") or (option or {}).get("label") or "").strip()
    if isinstance(raw_value, list):
        labels = [option_map.get(str(item.get("id") if isinstance(item, dict) else item)) for item in raw_value]
        labels = [label for label in labels if label]
        return ", ".join(dict.fromkeys(labels)) if labels else None
    return option_map.get(str(raw_value))


def extract_account_manager_name(task: dict[str, Any], am_custom_field_id: str) -> Optional[str]:
    normalized_field_id = _normalize_custom_field_id(am_custom_field_id)
    for cf in (task or {}).get("custom_fields") or []:
        field_id = _normalize_custom_field_id((cf or {}).get("id"))
        if normalized_field_id and field_id != normalized_field_id:
            continue
        raw_value = (cf or {}).get("value")
        if raw_value in (None, "", []):
            if normalized_field_id:
                break
            continue
        option_label = _extract_option_label(cf, raw_value)
        if option_label:
            return option_label
        if isinstance(raw_value, str):
            value = _norm_spaces(raw_value)
            if value:
                return value
        if isinstance(raw_value, dict):
            for key in ("full_name", "name", "username", "label", "value", "email"):
                value = _norm_spaces(raw_value.get(key))
                if value:
                    return value
        if isinstance(raw_value, list):
            labels: list[str] = []
            for item in raw_value:
                if isinstance(item, dict):
                    for key in ("full_name", "name", "username", "label", "value", "email"):
                        value = _norm_spaces(item.get(key))
                        if value:
                            labels.append(value)
                            break
                else:
                    value = _norm_spaces(item)
                    if value:
                        labels.append(value)
            labels = [label for label in dict.fromkeys(labels) if label]
            if labels:
                return ", ".join(labels)
        if normalized_field_id:
            break
    assignees = list((task or {}).get("assignees") or [])
    if assignees:
        first = assignees[0] or {}
        for key in ("full_name", "username", "email"):
            value = _norm_spaces(first.get(key))
            if value:
                return value
    return None


def _normalize_client_name(value: Any) -> str:
    return _norm(value)


def _match_am_name(external_name: str, full_names: list[str]) -> tuple[Optional[str], Optional[str]]:
    normalized_external = _normalize_client_name(external_name)
    if not normalized_external:
        return None, "missing_account_manager"
    exact = [name for name in full_names if _normalize_client_name(name) == normalized_external]
    if len(exact) == 1:
        return exact[0], None
    ext_tokens = normalized_external.split()
    candidates: list[str] = []
    for full_name in full_names:
        candidate_tokens = _normalize_client_name(full_name).split()
        if len(candidate_tokens) < len(ext_tokens):
            continue
        matched = True
        for idx, token in enumerate(ext_tokens):
            if idx >= len(candidate_tokens) or not candidate_tokens[idx].startswith(token):
                matched = False
                break
        if matched:
            candidates.append(full_name)
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, "ambiguous_account_manager"
    return None, "account_manager_not_found"


def _suggest_user_name(external_name: str, full_names: list[str]) -> Optional[str]:
    normalized_external = _normalize_client_name(external_name)
    if not normalized_external:
        return None
    ext_tokens = normalized_external.split()
    candidates: list[str] = []
    for full_name in full_names:
        candidate_tokens = _normalize_client_name(full_name).split()
        if not candidate_tokens or not ext_tokens:
            continue
        if candidate_tokens[0].startswith(ext_tokens[0]) or ext_tokens[0].startswith(candidate_tokens[0]):
            candidates.append(full_name)
    candidates = list(dict.fromkeys(candidates))
    return candidates[0] if len(candidates) == 1 else None


async def _list_tenant_users(tenant_id: str) -> list[dict[str, Any]]:
    bridge = get_store()
    profiles = await bridge.list_user_profiles(limit=5000) if bridge.is_enabled_for("profiles") else []
    users: list[dict[str, Any]] = []
    for profile in profiles:
        memberships = await bridge.list_user_memberships(str((profile or {}).get("_id") or ""), limit=50)
        membership = next(
            (
                item for item in memberships
                if str((item or {}).get("tenant_id") or "") == str(tenant_id)
                and str((item or {}).get("status") or "") == "active"
                and str((item or {}).get("role") or "") != "viewer"
            ),
            None,
        )
        if not membership:
            continue
        users.append(
            {
                "id": str((profile or {}).get("_id") or ""),
                "auth_user_id": str((profile or {}).get("_id") or ""),
                "full_name": str((profile or {}).get("name") or "").strip(),
                "email": str((profile or {}).get("email") or "").strip().lower(),
                "role": str((membership or {}).get("role") or "").strip(),
            }
        )
    return users


async def _create_sync_run(tenant_id: str, actor_user_id: str, metadata_json: dict[str, Any]) -> Optional[dict[str, Any]]:
    bridge = get_store()
    target_tenant_id = await bridge.resolve_target_tenant_id(tenant_id)
    target_actor_id = await bridge.resolve_target_user_id(actor_user_id)
    if not target_tenant_id:
        return None
    result = await bridge._request(
        "POST",
        "ownership_sync_runs",
        payload={
            "tenant_id": target_tenant_id,
            "provider": "clickup",
            "source": "clickup_sync",
            "cadence_minutes": None,
            "started_at": utcnow().isoformat(),
            "status": "running",
            "metadata_json": metadata_json,
            "created_by": target_actor_id,
            "is_deleted": False,
        },
        headers=bridge._write_headers(prefer="return=representation"),
    )
    rows = result if isinstance(result, list) else [result]
    return (rows or [None])[0]


async def _finalize_sync_run(run_id: str, matched_clients: int, unmatched_clients: int, status: str, metadata_json: dict[str, Any]) -> None:
    bridge = get_store()
    await bridge._request(
        "PATCH",
        "ownership_sync_runs",
        params={"id": f"eq.{run_id}"},
        payload={
            "finished_at": utcnow().isoformat(),
            "matched_clients": matched_clients,
            "unmatched_clients": unmatched_clients,
            "status": status,
            "metadata_json": metadata_json,
        },
        headers=bridge._write_headers(prefer="return=representation"),
    )


async def _list_active_ownership_rows(tenant_id: str) -> list[dict[str, Any]]:
    bridge = get_store()
    target_tenant_id = await bridge.resolve_target_tenant_id(tenant_id)
    if not target_tenant_id:
        return []
    rows = await bridge._safe_select(
        "client_ownership",
        select="*",
        filters={"tenant_id": f"eq.{target_tenant_id}", "active": "eq.true", "is_deleted": "eq.false"},
        limit=5000,
    )
    return rows or []


async def _deactivate_ownership_row(row_id: str) -> None:
    bridge = get_store()
    await bridge._request(
        "PATCH",
        "client_ownership",
        params={"id": f"eq.{row_id}"},
        payload={"active": False, "synced_at": utcnow().isoformat()},
        headers=bridge._write_headers(prefer="return=representation"),
    )


async def _insert_ownership_row(tenant_id: str, client_id: str, user_id: str, actor_user_id: str, metadata_json: dict[str, Any]) -> None:
    bridge = get_store()
    target_tenant_id = await bridge.resolve_target_tenant_id(tenant_id)
    target_client_id = await bridge.resolve_target_client_id(tenant_id, client_id)
    target_user_id = await bridge.resolve_target_user_id(user_id)
    target_actor_id = await bridge.resolve_target_user_id(actor_user_id)
    if not target_tenant_id or not target_client_id:
        return
    await bridge._request(
        "POST",
        "client_ownership",
        payload={
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "user_id": target_user_id,
            "source": "clickup_sync",
            "synced_at": utcnow().isoformat(),
            "active": True,
            "metadata_json": metadata_json,
            "created_by": target_actor_id,
            "is_deleted": False,
        },
        headers=bridge._write_headers(prefer="return=representation"),
    )


async def _touch_exception(
    tenant_id: str,
    run_id: str,
    actor_user_id: str,
    client_name: str,
    external_account_manager: str,
    suggested_user_name: Optional[str],
    reason: str,
    metadata_json: dict[str, Any],
) -> None:
    bridge = get_store()
    target_tenant_id = await bridge.resolve_target_tenant_id(tenant_id)
    target_actor_id = await bridge.resolve_target_user_id(actor_user_id)
    if not target_tenant_id:
        return
    existing = await bridge._safe_select(
        "ownership_sync_exceptions",
        select="id",
        filters={
            "tenant_id": f"eq.{target_tenant_id}",
            "client_name": f"eq.{client_name}",
            "reason": f"eq.{reason}",
            "status": "eq.open",
            "is_deleted": "eq.false",
        },
        limit=10,
    )
    target_id = None
    for row in existing or []:
        target_id = str((row or {}).get("id") or "").strip() or target_id
        if target_id:
            break
    payload = {
        "tenant_id": target_tenant_id,
        "run_id": run_id,
        "client_name": client_name,
        "external_account_manager": external_account_manager or None,
        "suggested_user_name": suggested_user_name,
        "reason": reason,
        "status": "open",
        "last_seen_at": utcnow().isoformat(),
        "metadata_json": metadata_json,
        "created_by": target_actor_id,
        "is_deleted": False,
    }
    if target_id:
        await bridge._request(
            "PATCH",
            "ownership_sync_exceptions",
            params={"id": f"eq.{target_id}"},
            payload=payload,
            headers=bridge._write_headers(prefer="return=representation"),
        )
    else:
        await bridge._request(
            "POST",
            "ownership_sync_exceptions",
            payload=payload,
            headers=bridge._write_headers(prefer="return=representation"),
        )


async def _resolve_open_exceptions(tenant_id: str, actor_user_id: str, client_name: str) -> None:
    bridge = get_store()
    target_tenant_id = await bridge.resolve_target_tenant_id(tenant_id)
    target_actor_id = await bridge.resolve_target_user_id(actor_user_id)
    if not target_tenant_id:
        return
    rows = await bridge._safe_select(
        "ownership_sync_exceptions",
        select="id",
        filters={
            "tenant_id": f"eq.{target_tenant_id}",
            "client_name": f"eq.{client_name}",
            "status": "eq.open",
            "is_deleted": "eq.false",
        },
        limit=50,
    )
    for row in rows or []:
        row_id = str((row or {}).get("id") or "").strip()
        if not row_id:
            continue
        await bridge._request(
            "PATCH",
            "ownership_sync_exceptions",
            params={"id": f"eq.{row_id}"},
            payload={
                "status": "resolved",
                "resolved_at": utcnow().isoformat(),
                "resolved_by": target_actor_id,
            },
            headers=bridge._write_headers(prefer="return=representation"),
        )


async def _list_runs(tenant_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    bridge = get_store()
    target_tenant_id = await bridge.resolve_target_tenant_id(tenant_id)
    if not target_tenant_id:
        return []
    rows = await bridge._safe_select(
        "ownership_sync_runs",
        select="*",
        filters={"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
        order="started_at.desc",
        limit=limit,
    )
    return rows or []


async def list_open_exceptions(tenant_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    bridge = get_store()
    target_tenant_id = await bridge.resolve_target_tenant_id(tenant_id)
    if not target_tenant_id:
        return []
    rows = await bridge._safe_select(
        "ownership_sync_exceptions",
        select="id,run_id,client_name,external_account_manager,suggested_user_name,reason,status,last_seen_at,resolved_at,metadata_json",
        filters={"tenant_id": f"eq.{target_tenant_id}", "status": "eq.open", "is_deleted": "eq.false"},
        order="last_seen_at.desc",
        limit=limit,
    )
    return rows or []


async def get_ownership_summary(tenant_id: str) -> dict[str, Any]:
    runs = await _list_runs(tenant_id, limit=1)
    exceptions = await list_open_exceptions(tenant_id, limit=50)
    latest_run = (runs or [None])[0]
    return {
        "provider": "clickup",
        "last_run": latest_run,
        "open_exceptions_count": len(exceptions),
        "exceptions_preview": exceptions[:5],
    }


async def _fetch_clickup_tasks(config: dict[str, Any]) -> dict[str, Any]:
    headers = _clickup_headers(str(config.get("token") or ""))
    tasks: list[dict[str, Any]] = []
    max_pages = max(_clickup_dev_max_pages(), 1)
    max_tasks = max(_clickup_dev_max_tasks(), 1)
    for page in range(max_pages):
        result = await _clickup_get(
            f"list/{config['list_id']}/task",
            headers,
            params={"page": str(page), "include_closed": "true"},
        )
        if not result.get("ok"):
            return result
        batch = list(((result.get("data") or {}).get("tasks") or []))
        if not batch:
            break
        tasks.extend(batch)
        if len(tasks) >= max_tasks:
            tasks = tasks[:max_tasks]
            break
        if (result.get("data") or {}).get("last_page") is True:
            break
    return {"ok": True, "tasks": tasks}


async def run_clickup_ownership_sync(tenant_id: str, actor_user_id: str) -> dict[str, Any]:
    config = await _get_clickup_config(tenant_id)
    if not config.get("configured"):
        return {"ok": False, "detail": "ClickUp is not fully configured. Set token, team_id, raw numeric list_id, and optional AM custom field id."}
    run = await _create_sync_run(
        tenant_id,
        actor_user_id,
        {
            "team_id": config.get("team_id"),
            "list_id": config.get("list_id"),
            "am_custom_field_id": config.get("am_custom_field_id"),
            "base_url": config.get("base_url"),
            "dev_cap_pages": _clickup_dev_max_pages(),
            "dev_cap_tasks": _clickup_dev_max_tasks(),
        },
    )
    if not run:
        return {"ok": False, "detail": "Unable to create ownership sync run."}
    run_id = str((run or {}).get("id") or "").strip()
    try:
        tenant_users = await _list_tenant_users(tenant_id)
        full_names = [str(user.get("full_name") or "").strip() for user in tenant_users if str(user.get("full_name") or "").strip()]
        task_result = await _fetch_clickup_tasks(config)
        if not task_result.get("ok"):
            raise ValueError(task_result.get("error_detail") or task_result.get("error") or "Failed to fetch ClickUp tasks")
        tasks = list(task_result.get("tasks") or [])
        clients = await get_store().list_clients(tenant_id, limit=5000)
        active_ownership_rows = await _list_active_ownership_rows(tenant_id)
        ownership_by_client: dict[str, dict[str, Any]] = {}
        for row in active_ownership_rows:
            client_id = str((row or {}).get("client_id") or "").strip()
            if client_id:
                ownership_by_client[client_id] = dict(row or {})
        clients_by_external_ref = {
            str((client or {}).get("external_ref") or "").strip(): dict(client or {})
            for client in clients
            if str((client or {}).get("external_ref") or "").strip()
        }
        clients_by_name = {}
        for client in clients:
            for candidate in (client.get("company"), client.get("name")):
                key = _normalize_client_name(candidate)
                if key and key not in clients_by_name:
                    clients_by_name[key] = dict(client or {})

        matched_clients = 0
        unmatched_clients = 0
        created_ownership = 0
        updated_ownership = 0
        resolved_exceptions = 0
        sample_reasons: list[str] = []

        for task in tasks:
            task_id = str((task or {}).get("id") or "").strip()
            task_name = _norm_spaces((task or {}).get("name"))
            if not task_id or not task_name:
                continue
            client_doc = clients_by_external_ref.get(task_id) or clients_by_name.get(_normalize_client_name(task_name))
            external_am = extract_account_manager_name(task, str(config.get("am_custom_field_id") or "")) or ""
            if not client_doc:
                unmatched_clients += 1
                reason = "client_not_found"
                sample_reasons.append(reason)
                await _touch_exception(
                    tenant_id,
                    run_id,
                    actor_user_id,
                    task_name,
                    external_am,
                    _suggest_user_name(external_am, full_names),
                    reason,
                    {"task_id": task_id, "task_name": task_name},
                )
                continue
            matched_name, mismatch_reason = _match_am_name(external_am, full_names)
            if not matched_name:
                unmatched_clients += 1
                reason = mismatch_reason or "account_manager_not_found"
                sample_reasons.append(reason)
                await _touch_exception(
                    tenant_id,
                    run_id,
                    actor_user_id,
                    str((client_doc or {}).get("company") or (client_doc or {}).get("name") or task_name),
                    external_am,
                    _suggest_user_name(external_am, full_names),
                    reason,
                    {"task_id": task_id, "client_id": str((client_doc or {}).get("_id") or ""), "task_name": task_name},
                )
                continue
            matched_user = next((user for user in tenant_users if str(user.get("full_name") or "").strip() == matched_name), None)
            if not matched_user:
                unmatched_clients += 1
                reason = "tenant_user_not_found"
                sample_reasons.append(reason)
                await _touch_exception(
                    tenant_id,
                    run_id,
                    actor_user_id,
                    str((client_doc or {}).get("company") or (client_doc or {}).get("name") or task_name),
                    external_am,
                    matched_name,
                    reason,
                    {"task_id": task_id, "client_id": str((client_doc or {}).get("_id") or ""), "task_name": task_name},
                )
                continue

            client_id = str((client_doc or {}).get("_id") or "").strip()
            current_owner = ownership_by_client.get(client_id)
            now_iso = utcnow().isoformat()
            next_client = {
                **dict(client_doc or {}),
                "external_ref": task_id,
                "account_manager_id": str((matched_user or {}).get("id") or ""),
                "account_manager_name": str((matched_user or {}).get("full_name") or ""),
                "updated_at": now_iso,
            }
            await get_store().upsert_client(tenant_id, next_client)
            clients_by_external_ref[task_id] = next_client
            clients_by_name[_normalize_client_name(str(next_client.get("company") or next_client.get("name") or ""))] = next_client

            if current_owner and str((current_owner or {}).get("user_id") or "").strip() == await get_store().resolve_target_user_id(str((matched_user or {}).get("id") or "")):
                await get_store()._request(
                    "PATCH",
                    "client_ownership",
                    params={"id": f"eq.{str((current_owner or {}).get('id') or '').strip()}"},
                    payload={"synced_at": now_iso},
                    headers=get_store()._write_headers(prefer="return=representation"),
                )
                updated_ownership += 1
            else:
                if current_owner and str((current_owner or {}).get("id") or "").strip():
                    await _deactivate_ownership_row(str((current_owner or {}).get("id") or "").strip())
                await _insert_ownership_row(
                    tenant_id,
                    client_id,
                    str((matched_user or {}).get("id") or ""),
                    actor_user_id,
                    {"task_id": task_id, "task_name": task_name, "external_account_manager": external_am},
                )
                created_ownership += 1
            ownership_by_client[client_id] = {"user_id": str((matched_user or {}).get("id") or "")}
            matched_clients += 1
            await _resolve_open_exceptions(
                tenant_id,
                actor_user_id,
                str((client_doc or {}).get("company") or (client_doc or {}).get("name") or task_name),
            )
            resolved_exceptions += 1

        metadata_json = {
            "team_id": config.get("team_id"),
            "list_id": config.get("list_id"),
            "am_custom_field_id": config.get("am_custom_field_id"),
            "processed_tasks": len(tasks),
            "created_ownership": created_ownership,
            "updated_ownership": updated_ownership,
            "resolved_exceptions": resolved_exceptions,
            "reason_samples": list(dict.fromkeys(sample_reasons))[:10],
        }
        await _finalize_sync_run(run_id, matched_clients, unmatched_clients, "completed", metadata_json)
        return {
            "ok": True,
            "run_id": run_id,
            "status": "completed",
            "matched_clients": matched_clients,
            "unmatched_clients": unmatched_clients,
            "processed_tasks": len(tasks),
            "exceptions_limit": 50,
        }
    except Exception as exc:
        await _finalize_sync_run(run_id, 0, 0, "failed", {"error": str(exc)})
        return {"ok": False, "run_id": run_id, "detail": str(exc)}
