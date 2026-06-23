from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from auth import RequestContext, can_manage_tenant
from supabase_native_repository import SupabaseNativeRepository, SupabaseRepositoryError


def _filters(**kwargs: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in kwargs.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = f"eq.{str(v).lower()}"
        else:
            out[k] = f"eq.{v}"
    return out


def _doc_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or "").strip()


def _client_doc_from_row(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row or {})
    if "id" in r:
        r["_id"] = _doc_id(r)
        r.pop("id", None)
    if "account_manager_user_id" in r:
        r["account_manager_id"] = r.get("account_manager_user_id")
        r.pop("account_manager_user_id", None)
    return r


def _client_row_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    d = dict(doc or {})
    if "_id" in d:
        d["id"] = str(d.get("_id") or "").strip()
        d.pop("_id", None)
    if "account_manager_id" in d:
        d["account_manager_user_id"] = d.get("account_manager_id")
        d.pop("account_manager_id", None)
    return d


def _meeting_doc_from_row(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row or {})
    if "id" in r:
        r["_id"] = _doc_id(r)
        r.pop("id", None)
    if "account_manager_user_id" in r:
        r["account_manager_id"] = r.get("account_manager_user_id")
        r.pop("account_manager_user_id", None)
    return r


def _meeting_row_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    d = dict(doc or {})
    if "_id" in d:
        d["id"] = str(d.get("_id") or "").strip()
        d.pop("_id", None)
    if "account_manager_id" in d:
        d["account_manager_user_id"] = d.get("account_manager_id")
        d.pop("account_manager_id", None)
    return d


def _action_item_doc_from_row(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row or {})
    if "id" in r:
        r["_id"] = _doc_id(r)
        r.pop("id", None)
    return r


def _action_item_row_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    d = dict(doc or {})
    if "_id" in d:
        d["id"] = str(d.get("_id") or "").strip()
        d.pop("_id", None)
    return d


def _repo_for_ctx(ctx: RequestContext) -> SupabaseNativeRepository:
    base = SupabaseNativeRepository()
    token = str(ctx.access_token or "").strip()
    if token and ctx.token_kind == "supabase":
        try:
            return base.for_user(token)
        except SupabaseRepositoryError:
            return base
    return base


def _service_repo() -> SupabaseNativeRepository:
    return SupabaseNativeRepository()


async def list_clients(ctx: RequestContext, *, limit: int = 1000) -> list[dict[str, Any]]:
    repo = _repo_for_ctx(ctx)
    rows = await repo.list(
        "clients",
        filters={**_filters(tenant_id=ctx.tenant_id, is_deleted=False), "limit": str(limit)},
        order="created_at.desc",
    )
    docs = [_client_doc_from_row(r) for r in (rows or [])]
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        docs = [d for d in docs if str(d.get("account_manager_id") or "") == str(ctx.user.id)]
    return docs


async def list_clients_for_tenant(tenant_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
    repo = _service_repo()
    rows = await repo.list(
        "clients",
        filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
        order="created_at.desc",
    )
    return [_client_doc_from_row(r) for r in (rows or [])]


async def get_client(ctx: RequestContext, client_id: str) -> Optional[dict[str, Any]]:
    repo = _repo_for_ctx(ctx)
    row = await repo.get_one(
        "clients",
        filters=_filters(tenant_id=ctx.tenant_id, id=str(client_id), is_deleted=False),
    )
    return _client_doc_from_row(row) if row else None


async def get_client_for_tenant(tenant_id: str, client_id: str) -> Optional[dict[str, Any]]:
    repo = _service_repo()
    row = await repo.get_one(
        "clients",
        filters=_filters(tenant_id=str(tenant_id), id=str(client_id), is_deleted=False),
    )
    return _client_doc_from_row(row) if row else None


async def upsert_client(ctx: RequestContext, doc: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_for_ctx(ctx)
    payload = _client_row_from_doc({**dict(doc or {}), "tenant_id": ctx.tenant_id, "is_deleted": False})
    row = await repo.upsert("clients", payload, on_conflict="id")
    return _client_doc_from_row(row or payload)


async def upsert_client_for_tenant(tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    repo = _service_repo()
    payload = _client_row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
    row = await repo.upsert("clients", payload, on_conflict="id")
    return _client_doc_from_row(row or payload)


async def soft_delete_client(ctx: RequestContext, client_id: str) -> None:
    repo = _repo_for_ctx(ctx)
    await repo.update(
        "clients",
        {"is_deleted": True},
        filters=_filters(tenant_id=ctx.tenant_id, id=str(client_id)),
    )


async def soft_delete_meetings_for_client(ctx: RequestContext, client_id: str) -> None:
    repo = _repo_for_ctx(ctx)
    await repo.update(
        "meetings",
        {"is_deleted": True},
        filters=_filters(tenant_id=ctx.tenant_id, client_id=str(client_id), is_deleted=False),
    )


async def list_meetings(ctx: RequestContext, *, client_id: Optional[str] = None, limit: int = 5000) -> list[dict[str, Any]]:
    repo = _repo_for_ctx(ctx)
    f = _filters(tenant_id=ctx.tenant_id, is_deleted=False)
    if client_id:
        f["client_id"] = f"eq.{client_id}"
    rows = await repo.list(
        "meetings",
        filters={**f, "limit": str(limit)},
        order="created_at.desc",
    )
    docs = [_meeting_doc_from_row(r) for r in (rows or [])]
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        docs = [d for d in docs if str(d.get("account_manager_id") or "") == str(ctx.user.id)]
    return docs


async def list_meetings_for_tenant(tenant_id: str, *, client_id: Optional[str] = None, limit: int = 5000) -> list[dict[str, Any]]:
    repo = _service_repo()
    f = _filters(tenant_id=str(tenant_id), is_deleted=False)
    if client_id:
        f["client_id"] = f"eq.{client_id}"
    rows = await repo.list(
        "meetings",
        filters={**f, "limit": str(limit)},
        order="created_at.desc",
    )
    return [_meeting_doc_from_row(r) for r in (rows or [])]


async def get_meeting(ctx: RequestContext, meeting_id: str) -> Optional[dict[str, Any]]:
    repo = _repo_for_ctx(ctx)
    row = await repo.get_one(
        "meetings",
        filters=_filters(tenant_id=ctx.tenant_id, id=str(meeting_id), is_deleted=False),
    )
    return _meeting_doc_from_row(row) if row else None


async def get_meeting_for_tenant(tenant_id: str, meeting_id: str) -> Optional[dict[str, Any]]:
    repo = _service_repo()
    row = await repo.get_one(
        "meetings",
        filters=_filters(tenant_id=str(tenant_id), id=str(meeting_id), is_deleted=False),
    )
    return _meeting_doc_from_row(row) if row else None


async def upsert_meeting(ctx: RequestContext, doc: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_for_ctx(ctx)
    payload = _meeting_row_from_doc({**dict(doc or {}), "tenant_id": ctx.tenant_id, "is_deleted": False})
    row = await repo.upsert("meetings", payload, on_conflict="id")
    return _meeting_doc_from_row(row or payload)


async def upsert_meeting_for_tenant(tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    repo = _service_repo()
    payload = _meeting_row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
    row = await repo.upsert("meetings", payload, on_conflict="id")
    return _meeting_doc_from_row(row or payload)


async def soft_delete_meeting(ctx: RequestContext, meeting_id: str) -> None:
    repo = _repo_for_ctx(ctx)
    await repo.update(
        "meetings",
        {"is_deleted": True},
        filters=_filters(tenant_id=ctx.tenant_id, id=str(meeting_id)),
    )


async def list_action_items(
    ctx: RequestContext,
    *,
    client_id: Optional[str] = None,
    meeting_id: Optional[str] = None,
    status: Optional[str] = None,
    owner_type: Optional[str] = None,
    due_before: Optional[str] = None,
    due_after: Optional[str] = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    repo = _repo_for_ctx(ctx)
    f = _filters(tenant_id=ctx.tenant_id, is_deleted=False)
    if client_id:
        f["client_id"] = f"eq.{client_id}"
    if meeting_id:
        f["meeting_id"] = f"eq.{meeting_id}"
    if status:
        f["status"] = f"eq.{status}"
    if owner_type:
        f["owner_type"] = f"eq.{owner_type}"
    if due_before:
        f["due_date"] = f"lte.{due_before}"
    if due_after:
        f["due_date"] = f"gte.{due_after}"
    rows = await repo.list(
        "action_items",
        filters={**f, "limit": str(limit)},
        order="created_at.desc",
    )
    return [_action_item_doc_from_row(r) for r in (rows or [])]


async def get_action_item(ctx: RequestContext, item_id: str) -> Optional[dict[str, Any]]:
    repo = _repo_for_ctx(ctx)
    row = await repo.get_one(
        "action_items",
        filters=_filters(tenant_id=ctx.tenant_id, id=str(item_id), is_deleted=False),
    )
    return _action_item_doc_from_row(row) if row else None


async def list_action_items_for_tenant(
    tenant_id: str,
    *,
    client_id: Optional[str] = None,
    meeting_id: Optional[str] = None,
    status: Optional[str] = None,
    owner_type: Optional[str] = None,
    due_before: Optional[str] = None,
    due_after: Optional[str] = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    repo = _service_repo()
    f = _filters(tenant_id=str(tenant_id), is_deleted=False)
    if client_id:
        f["client_id"] = f"eq.{client_id}"
    if meeting_id:
        f["meeting_id"] = f"eq.{meeting_id}"
    if status:
        f["status"] = f"eq.{status}"
    if owner_type:
        f["owner_type"] = f"eq.{owner_type}"
    if due_before:
        f["due_date"] = f"lte.{due_before}"
    if due_after:
        f["due_date"] = f"gte.{due_after}"
    rows = await repo.list(
        "action_items",
        filters={**f, "limit": str(limit)},
        order="created_at.desc",
    )
    return [_action_item_doc_from_row(r) for r in (rows or [])]


async def get_action_item_for_tenant(tenant_id: str, item_id: str) -> Optional[dict[str, Any]]:
    repo = _service_repo()
    row = await repo.get_one(
        "action_items",
        filters=_filters(tenant_id=str(tenant_id), id=str(item_id), is_deleted=False),
    )
    return _action_item_doc_from_row(row) if row else None


async def upsert_action_item(ctx: RequestContext, doc: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_for_ctx(ctx)
    payload = _action_item_row_from_doc({**dict(doc or {}), "tenant_id": ctx.tenant_id, "is_deleted": False})
    row = await repo.upsert("action_items", payload, on_conflict="id")
    return _action_item_doc_from_row(row or payload)


async def upsert_action_item_for_tenant(tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    repo = _service_repo()
    payload = _action_item_row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
    row = await repo.upsert("action_items", payload, on_conflict="id")
    return _action_item_doc_from_row(row or payload)


async def soft_delete_action_item(ctx: RequestContext, item_id: str) -> None:
    repo = _repo_for_ctx(ctx)
    await repo.update(
        "action_items",
        {"is_deleted": True},
        filters=_filters(tenant_id=ctx.tenant_id, id=str(item_id)),
    )


async def soft_delete_action_items_for_client(ctx: RequestContext, client_id: str) -> None:
    repo = _repo_for_ctx(ctx)
    await repo.update(
        "action_items",
        {"is_deleted": True},
        filters=_filters(tenant_id=ctx.tenant_id, client_id=str(client_id), is_deleted=False),
    )


async def soft_delete_action_items_for_meeting(ctx: RequestContext, meeting_id: str) -> None:
    repo = _repo_for_ctx(ctx)
    await repo.update(
        "action_items",
        {"is_deleted": True},
        filters=_filters(tenant_id=ctx.tenant_id, meeting_id=str(meeting_id), is_deleted=False),
    )



async def require_row(doc: Optional[dict[str, Any]], *, not_found: str) -> dict[str, Any]:
    if not doc:
        raise HTTPException(404, not_found)
