"""Supabase-only data store.

This module replaces the legacy Mongo + ``runtime_bridge`` stack. All
collections live in Supabase (Postgres / PostgREST). The store exposes a
single ``SupabaseStore`` singleton with domain methods that the rest of the
backend uses.

Usage::

    from supabase_store import store
    docs = await store.list_clients(ctx.tenant_id, limit=100)
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any, Optional

from supabase_native_repository import (
    SupabaseNativeConfig,
    SupabaseNativeRepository,
    SupabaseRepositoryError,
)
from supabase_config import get_supabase_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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
    return str(row.get("id") or row.get("_id") or "").strip()


def _to_doc(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not row:
        return None
    out = dict(row)
    if "id" in out:
        out["_id"] = str(out.get("id") or "").strip()
    return out


def _row_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc or {})
    if "_id" in out:
        out["id"] = str(out.get("_id") or "").strip()
        out.pop("_id", None)
    return out


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class SupabaseStore:
    """Single Supabase-backed store that exposes domain helpers."""

    def __init__(self) -> None:
        self._config: Optional[SupabaseNativeConfig] = None
        self._service_repo: Optional[SupabaseNativeRepository] = None

    # -- lazy repo accessors ------------------------------------------------
    def _repo(self, *, access_token: Optional[str] = None) -> SupabaseNativeRepository:
        if self._service_repo is None:
            settings = get_supabase_settings()
            self._config = SupabaseNativeConfig(
                url=str(settings.get("url") or "").strip(),
                service_role_key=str(settings.get("service_role_key") or "").strip(),
                anon_key=str(settings.get("anon_key") or "").strip() or None,
                schema=str(settings.get("db_schema") or "public").strip() or "public",
            )
            self._service_repo = SupabaseNativeRepository(self._config)
        if access_token and self._config and self._config.anon_key:
            try:
                return self._service_repo.for_user(access_token)
            except SupabaseRepositoryError:
                return self._service_repo
        return self._service_repo

    def service_configured(self) -> bool:
        try:
            settings = get_supabase_settings()
            return bool(settings.get("service_configured"))
        except Exception:
            return False

    # -- low-level postgrest helpers (used by ownership_sync etc.) ---------
    def _headers(self) -> dict[str, str]:
        settings = get_supabase_settings()
        service_key = str(settings.get("service_role_key") or "")
        schema = str(settings.get("db_schema") or "public").strip() or "public"
        return {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Accept-Profile": schema,
        }

    def _write_headers(self, *, prefer: Optional[str] = None) -> dict[str, str]:
        settings = get_supabase_settings()
        schema = str(settings.get("db_schema") or "public").strip() or "public"
        headers = {**self._headers(), "Content-Profile": schema, "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _request(
        self,
        method: str,
        relation: str,
        *,
        params: Optional[dict[str, Any]] = None,
        payload: Any = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        import httpx

        settings = get_supabase_settings()
        url = str(settings.get("url") or "").rstrip("/")
        if not url:
            return None
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.request(
                method.upper(),
                f"{url}/rest/v1/{str(relation or '').lstrip('/')}",
                params=params,
                json=payload,
                headers=headers or self._write_headers(),
            )
        response.raise_for_status()
        if not response.text.strip():
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    async def _safe_select(
        self,
        relation: str,
        *,
        select: str = "*",
        filters: Optional[dict[str, Any]] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Optional[list[dict[str, Any]]]:
        try:
            return await self._select(relation, select=select, filters=filters, order=order, limit=limit)
        except Exception:
            return None

    async def _select(
        self,
        relation: str,
        *,
        select: str = "*",
        filters: Optional[dict[str, Any]] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": select}
        for key, value in (filters or {}).items():
            if value is None:
                continue
            params[key] = str(value)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(int(limit))
        result = await self._request("GET", relation, params=params)
        return list(result or []) if isinstance(result, list) else []

    async def resolve_target_tenant_id(self, tenant_legacy_id: str) -> Optional[str]:
        if not self.service_configured():
            return None
        target = str(tenant_legacy_id or "").strip()
        if not target:
            return None
        row = await self._safe_select(
            "tenants",
            select="id",
            filters={"id": f"eq.{target}", "is_deleted": "eq.false"},
            limit=1,
        )
        if row:
            rid = str((row[0] or {}).get("id") or "").strip()
            if rid:
                return rid
        return None

    async def resolve_target_user_id(self, user_legacy_id: str) -> Optional[str]:
        target = str(user_legacy_id or "").strip()
        if not target:
            return None
        row = await self._safe_select(
            "user_profiles",
            select="id",
            filters={"id": f"eq.{target}", "is_deleted": "eq.false"},
            limit=1,
        )
        if row:
            rid = str((row[0] or {}).get("id") or "").strip()
            if rid:
                return rid
        return None

    async def resolve_target_client_id(self, tenant_id: str, client_id: str) -> Optional[str]:
        target_tenant_id = await self.resolve_target_tenant_id(tenant_id)
        if not target_tenant_id:
            return None
        row = await self._safe_select(
            "clients",
            select="id",
            filters={"id": f"eq.{client_id}", "tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
            limit=1,
        )
        if row:
            return str((row[0] or {}).get("id") or "").strip() or None
        return None

    def is_enabled_for(self, domain: str) -> bool:
        """Backward-compatible gate. Supabase is the only store now."""
        return self.service_configured()

    def is_mirror_enabled_for(self, domain: str) -> bool:
        """Backward-compatible mirror gate. Supabase is the primary store."""
        return self.service_configured()

    # -- tenant / membership ------------------------------------------------
    async def list_tenants(self, *, status: Optional[str] = None, limit: int = 5000) -> list[dict[str, Any]]:
        f = _filters(status=status, is_deleted=False)
        f["limit"] = str(limit)
        rows = await self._repo().list("tenants", filters=f, order="created_at.desc")
        return [_to_doc(r) for r in (rows or []) if r]

    async def get_tenant(self, tenant_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id:
            return None
        row = await self._repo().get_one(
            "tenants",
            filters=_filters(id=str(tenant_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def get_tenant_by_slug(self, slug: str) -> Optional[dict[str, Any]]:
        if not slug:
            return None
        row = await self._repo().get_one(
            "tenants",
            filters=_filters(slug=str(slug), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def create_tenant(self, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().insert("tenants", payload)
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def resolve_tenant_legacy_id_from_host(self, host: str) -> Optional[str]:
        if not host:
            return None
        normalized = str(host or "").strip().lower()
        for prefix in ("http://", "https://"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
        if "/" in normalized:
            normalized = normalized.split("/", 1)[0]
        if ":" in normalized:
            normalized = normalized.split(":", 1)[0]
        if not normalized:
            return None
        row = await self._repo().get_one(
            "tenant_domains",
            filters=_filters(domain=normalized, is_deleted=False),
        )
        if row:
            tenant_id = str((row or {}).get("tenant_id") or "").strip()
            if tenant_id:
                return tenant_id
        row = await self._repo().get_one(
            "tenants",
            filters=_filters(slug=normalized, is_deleted=False),
        )
        if row:
            return str((row or {}).get("id") or "").strip() or None
        return None

    # -- profiles / users ---------------------------------------------------
    async def get_user_profile(self, user_id: str) -> Optional[dict[str, Any]]:
        if not user_id:
            return None
        row = await self._repo().get_one(
            "user_profiles",
            filters=_filters(id=str(user_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def get_user_profile_by_email(self, email: str) -> Optional[dict[str, Any]]:
        if not email:
            return None
        row = await self._repo().get_one(
            "user_profiles",
            filters=_filters(email=str(email).strip().lower(), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def list_user_profiles(self, *, limit: int = 500) -> list[dict[str, Any]]:
        rows = await self._repo().list(
            "user_profiles",
            filters={"limit": str(limit), "is_deleted": "eq.false"},
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def has_user_profiles(self) -> bool:
        rows = await self._repo().list(
            "user_profiles",
            filters={"limit": "1", "is_deleted": "eq.false"},
        )
        return bool(rows)

    # -- memberships --------------------------------------------------------
    async def get_user_membership(self, tenant_id: str, user_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not user_id:
            return None
        row = await self._repo().get_one(
            "tenant_members",
            filters=_filters(tenant_id=str(tenant_id), user_id=str(user_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def list_user_memberships(self, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        if not user_id:
            return []
        rows = await self._repo().list(
            "tenant_members",
            filters={**_filters(user_id=str(user_id), is_deleted=False), "limit": str(limit)},
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def count_active_members_for_tenant(self, tenant_id: str) -> int:
        rows = await self._repo().list(
            "tenant_members",
            filters=_filters(tenant_id=str(tenant_id), status="active", is_deleted=False),
        )
        return len(rows or [])

    async def create_tenant_membership(self, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().insert("tenant_members", payload)
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    # -- settings -----------------------------------------------------------
    async def get_tenant_settings(self, tenant_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id:
            return None
        row = await self._repo().get_one(
            "tenant_settings",
            filters=_filters(tenant_id=str(tenant_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def upsert_tenant_settings(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        row = await self._repo().upsert("tenant_settings", payload, on_conflict="tenant_id")
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def mirror_tenant_settings(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.upsert_tenant_settings(tenant_id, doc)
        except Exception as exc:  # noqa: BLE001
            return {"attempted": True, "ok": False, "error": str(exc)}

    async def safe_mirror_tenant_settings(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.mirror_tenant_settings(tenant_id, doc)

    # -- domains ------------------------------------------------------------
    async def list_tenant_domains(self, tenant_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        rows = await self._repo().list(
            "tenant_domains",
            filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def get_tenant_domain(self, domain: str) -> Optional[dict[str, Any]]:
        if not domain:
            return None
        row = await self._repo().get_one(
            "tenant_domains",
            filters=_filters(domain=str(domain), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def upsert_tenant_domain(self, tenant_id: str, domain: str, *, verified: bool = False) -> dict[str, Any]:
        payload = {
            "tenant_id": str(tenant_id),
            "domain": str(domain),
            "verified": bool(verified),
            "is_deleted": False,
        }
        row = await self._repo().upsert(
            "tenant_domains",
            payload,
            on_conflict="tenant_id,domain",
        )
        return _to_doc(row) or payload

    async def delete_tenant_domain(self, tenant_id: str, domain: str) -> bool:
        await self._repo().update(
            "tenant_domains",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), domain=str(domain)),
        )
        return True

    # -- clients ------------------------------------------------------------
    async def list_clients(self, tenant_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        rows = await self._repo().list(
            "clients",
            filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
            order="created_at.desc",
        )
        docs = [_to_doc(r) for r in (rows or []) if r]
        for d in docs:
            if d and d.get("account_manager_user_id") and not d.get("account_manager_id"):
                d["account_manager_id"] = d.get("account_manager_user_id")
        return [d for d in docs if d]

    async def get_client(self, tenant_id: str, client_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not client_id:
            return None
        row = await self._repo().get_one(
            "clients",
            filters=_filters(tenant_id=str(tenant_id), id=str(client_id), is_deleted=False),
        )
        if not row:
            return None
        doc = _to_doc(row)
        if doc and doc.get("account_manager_user_id") and not doc.get("account_manager_id"):
            doc["account_manager_id"] = doc.get("account_manager_user_id")
        return doc

    async def upsert_client(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if payload.get("account_manager_id") and "account_manager_user_id" not in payload:
            payload["account_manager_user_id"] = payload.get("account_manager_id")
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert("clients", payload, on_conflict="id")
        out = _to_doc(row) or _to_doc(payload)
        if out and out.get("account_manager_user_id") and not out.get("account_manager_id"):
            out["account_manager_id"] = out.get("account_manager_user_id")
        return out  # type: ignore[return-value]

    async def soft_delete_client(self, tenant_id: str, client_id: str) -> bool:
        await self._repo().update(
            "clients",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), id=str(client_id)),
        )
        return True

    # -- meetings -----------------------------------------------------------
    async def list_meetings(self, tenant_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        rows = await self._repo().list(
            "meetings",
            filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
            order="created_at.desc",
        )
        docs = [_to_doc(r) for r in (rows or []) if r]
        for d in docs:
            if d and d.get("account_manager_user_id") and not d.get("account_manager_id"):
                d["account_manager_id"] = d.get("account_manager_user_id")
        return docs

    async def get_meeting(self, tenant_id: str, meeting_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not meeting_id:
            return None
        row = await self._repo().get_one(
            "meetings",
            filters=_filters(tenant_id=str(tenant_id), id=str(meeting_id), is_deleted=False),
        )
        if not row:
            return None
        doc = _to_doc(row)
        if doc and doc.get("account_manager_user_id") and not doc.get("account_manager_id"):
            doc["account_manager_id"] = doc.get("account_manager_user_id")
        return doc

    async def upsert_meeting(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if payload.get("account_manager_id") and "account_manager_user_id" not in payload:
            payload["account_manager_user_id"] = payload.get("account_manager_id")
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert("meetings", payload, on_conflict="id")
        out = _to_doc(row) or _to_doc(payload)
        if out and out.get("account_manager_user_id") and not out.get("account_manager_id"):
            out["account_manager_id"] = out.get("account_manager_user_id")
        return out  # type: ignore[return-value]

    async def soft_delete_meeting(self, tenant_id: str, meeting_id: str) -> bool:
        await self._repo().update(
            "meetings",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), id=str(meeting_id)),
        )
        return True

    async def soft_delete_meetings_for_client(self, tenant_id: str, client_id: str) -> bool:
        await self._repo().update(
            "meetings",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), client_id=str(client_id), is_deleted=False),
        )
        return True

    # -- action items -------------------------------------------------------
    async def list_action_items(
        self,
        tenant_id: str,
        *,
        client_id: Optional[str] = None,
        meeting_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        f = _filters(tenant_id=str(tenant_id), is_deleted=False)
        if client_id:
            f["client_id"] = f"eq.{client_id}"
        if meeting_id:
            f["meeting_id"] = f"eq.{meeting_id}"
        if status:
            f["status"] = f"eq.{status}"
        f["limit"] = str(limit)
        rows = await self._repo().list("action_items", filters=f, order="created_at.desc")
        return [_to_doc(r) for r in (rows or []) if r]

    async def get_action_item(self, tenant_id: str, item_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not item_id:
            return None
        row = await self._repo().get_one(
            "action_items",
            filters=_filters(tenant_id=str(tenant_id), id=str(item_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def upsert_action_item(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert("action_items", payload, on_conflict="id")
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def soft_delete_action_item(self, tenant_id: str, item_id: str) -> bool:
        await self._repo().update(
            "action_items",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), id=str(item_id)),
        )
        return True

    async def soft_delete_action_items_for_client(self, tenant_id: str, client_id: str) -> bool:
        await self._repo().update(
            "action_items",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), client_id=str(client_id), is_deleted=False),
        )
        return True

    async def soft_delete_action_items_for_meeting(self, tenant_id: str, meeting_id: str) -> bool:
        await self._repo().update(
            "action_items",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), meeting_id=str(meeting_id), is_deleted=False),
        )
        return True

    # -- reviews ------------------------------------------------------------
    async def get_client_review_goal(self, tenant_id: str, client_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not client_id:
            return None
        row = await self._repo().get_one(
            "client_review_goals",
            filters=_filters(tenant_id=str(tenant_id), client_id=str(client_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def upsert_client_review_goal(self, tenant_id: str, client_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc(
            {**dict(doc or {}), "tenant_id": str(tenant_id), "client_id": str(client_id), "is_deleted": False}
        )
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert("client_review_goals", payload, on_conflict="tenant_id,client_id")
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def create_review_event(self, tenant_id: str, client_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc(
            {**dict(doc or {}), "tenant_id": str(tenant_id), "client_id": str(client_id), "is_deleted": False}
        )
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().insert("review_events", payload)
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def list_review_events(
        self,
        tenant_id: str,
        *,
        client_id: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        f = _filters(tenant_id=str(tenant_id), is_deleted=False)
        if client_id:
            f["client_id"] = f"eq.{client_id}"
        f["limit"] = str(limit)
        rows = await self._repo().list("review_events", filters=f, order="occurred_on.desc")
        return [_to_doc(r) for r in (rows or []) if r]

    async def list_review_monthly_snapshots(
        self,
        tenant_id: str,
        *,
        client_id: Optional[str] = None,
        client_legacy_id: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        cid = client_id or client_legacy_id
        f = _filters(tenant_id=str(tenant_id), is_deleted=False)
        if cid:
            f["client_id"] = f"eq.{cid}"
        f["limit"] = str(limit)
        rows = await self._repo().list(
            "review_monthly_snapshots", filters=f, order="month.desc"
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def upsert_review_monthly_snapshot(
        self, tenant_id: str, client_id: str, doc: dict[str, Any]
    ) -> dict[str, Any]:
        payload = _row_from_doc(
            {**dict(doc or {}), "tenant_id": str(tenant_id), "client_id": str(client_id), "is_deleted": False}
        )
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert(
            "review_monthly_snapshots", payload, on_conflict="tenant_id,client_id,month"
        )
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    # -- discovery question templates --------------------------------------
    async def list_discovery_question_templates(
        self, tenant_id: str, *, limit: int = 2000
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        rows = await self._repo().list(
            "discovery_question_templates",
            filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def get_discovery_question_template(
        self, tenant_id: str, template_id: str
    ) -> Optional[dict[str, Any]]:
        if not tenant_id or not template_id:
            return None
        row = await self._repo().get_one(
            "discovery_question_templates",
            filters=_filters(tenant_id=str(tenant_id), id=str(template_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def upsert_discovery_question_template(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert(
            "discovery_question_templates", payload, on_conflict="id"
        )
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def soft_delete_discovery_question_template(self, tenant_id: str, template_id: str) -> bool:
        await self._repo().update(
            "discovery_question_templates",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), id=str(template_id)),
        )
        return True

    # -- roadmap plans ------------------------------------------------------
    async def get_roadmap_plan(self, tenant_id: str, client_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not client_id:
            return None
        row = await self._repo().get_one(
            "roadmap_plans",
            filters=_filters(tenant_id=str(tenant_id), client_id=str(client_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def upsert_roadmap_plan(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert("roadmap_plans", payload, on_conflict="id")
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    # -- content captures ---------------------------------------------------
    async def list_content_captures(
        self,
        tenant_id: str,
        *,
        client_id: Optional[str] = None,
        meeting_id: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        f = _filters(tenant_id=str(tenant_id), is_deleted=False)
        if client_id:
            f["client_id"] = f"eq.{client_id}"
        if meeting_id:
            f["meeting_id"] = f"eq.{meeting_id}"
        f["limit"] = str(limit)
        rows = await self._repo().list(
            "content_captures", filters=f, order="created_at.desc"
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def get_content_capture(self, tenant_id: str, cap_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not cap_id:
            return None
        row = await self._repo().get_one(
            "content_captures",
            filters=_filters(tenant_id=str(tenant_id), id=str(cap_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def upsert_content_capture(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert("content_captures", payload, on_conflict="id")
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def soft_delete_content_capture(self, tenant_id: str, cap_id: str) -> bool:
        await self._repo().update(
            "content_captures",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), id=str(cap_id)),
        )
        return True

    async def soft_delete_content_captures_for_client(self, tenant_id: str, client_id: str) -> bool:
        await self._repo().update(
            "content_captures",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), client_id=str(client_id), is_deleted=False),
        )
        return True

    async def soft_delete_content_captures_for_meeting(self, tenant_id: str, meeting_id: str) -> bool:
        await self._repo().update(
            "content_captures",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), meeting_id=str(meeting_id), is_deleted=False),
        )
        return True

    # -- tickets / qa scorecards -------------------------------------------
    async def list_tickets(
        self,
        tenant_id: str,
        *,
        client_id: Optional[str] = None,
        meeting_id: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        f = _filters(tenant_id=str(tenant_id), is_deleted=False)
        if client_id:
            f["client_id"] = f"eq.{client_id}"
        if meeting_id:
            f["meeting_id"] = f"eq.{meeting_id}"
        f["limit"] = str(limit)
        rows = await self._repo().list("tickets", filters=f, order="created_at.desc")
        return [_to_doc(r) for r in (rows or []) if r]

    async def get_ticket(self, tenant_id: str, ticket_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not ticket_id:
            return None
        row = await self._repo().get_one(
            "tickets",
            filters=_filters(tenant_id=str(tenant_id), id=str(ticket_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def upsert_ticket(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert("tickets", payload, on_conflict="id")
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def soft_delete_tickets_for_client(self, tenant_id: str, client_id: str) -> bool:
        await self._repo().update(
            "tickets",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), client_id=str(client_id), is_deleted=False),
        )
        return True

    async def soft_delete_tickets_for_meeting(self, tenant_id: str, meeting_id: str) -> bool:
        await self._repo().update(
            "tickets",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), meeting_id=str(meeting_id), is_deleted=False),
        )
        return True

    async def get_latest_qa_scorecard(self, tenant_id: str, meeting_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not meeting_id:
            return None
        rows = await self._repo().list(
            "qa_scorecards",
            filters={**_filters(tenant_id=str(tenant_id), meeting_id=str(meeting_id), is_deleted=False), "limit": "1"},
            order="created_at.desc",
        )
        return _to_doc(rows[0]) if rows else None

    async def create_qa_scorecard(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().insert("qa_scorecards", payload)
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def soft_delete_qa_scorecards_for_client(self, tenant_id: str, client_id: str) -> bool:
        await self._repo().update(
            "qa_scorecards",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), client_id=str(client_id), is_deleted=False),
        )
        return True

    async def soft_delete_qa_scorecards_for_meeting(self, tenant_id: str, meeting_id: str) -> bool:
        await self._repo().update(
            "qa_scorecards",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), meeting_id=str(meeting_id), is_deleted=False),
        )
        return True

    # -- tenant files -------------------------------------------------------
    async def list_tenant_files(self, tenant_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        rows = await self._repo().list(
            "tenant_files",
            filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def create_tenant_file(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().insert("tenant_files", payload)
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    # -- tenant integrations -----------------------------------------------
    async def list_tenant_integrations(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        rows = await self._repo().list(
            "tenant_integrations",
            filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def get_tenant_integration(self, tenant_id: str, platform: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not platform:
            return None
        row = await self._repo().get_one(
            "tenant_integrations",
            filters=_filters(
                tenant_id=str(tenant_id), platform=str(platform).strip().lower(), is_deleted=False
            ),
        )
        return _to_doc(row) if row else None

    async def upsert_tenant_integration(self, tenant_id: str, platform: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc(
            {
                **dict(doc or {}),
                "tenant_id": str(tenant_id),
                "platform": str(platform).strip().lower(),
                "is_deleted": False,
            }
        )
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert(
            "tenant_integrations", payload, on_conflict="tenant_id,platform"
        )
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def mirror_tenant_integration(self, tenant_id: str, platform: str, doc: dict[str, Any]) -> dict[str, Any]:
        try:
            stored = await self.upsert_tenant_integration(tenant_id, platform, doc)
            return {"attempted": True, "ok": True, "result": stored}
        except Exception as exc:  # noqa: BLE001
            return {"attempted": True, "ok": False, "error": str(exc)}

    async def safe_mirror_tenant_integration(self, tenant_id: str, platform: str, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.mirror_tenant_integration(tenant_id, platform, doc)

    async def soft_delete_tenant_integration(self, tenant_id: str, platform: str) -> bool:
        await self._repo().update(
            "tenant_integrations",
            {"is_deleted": True},
            filters=_filters(tenant_id=str(tenant_id), platform=str(platform).strip().lower()),
        )
        return True

    async def safe_soft_delete_tenant_integration(self, tenant_id: str, platform: str) -> dict[str, Any]:
        try:
            await self.soft_delete_tenant_integration(tenant_id, platform)
            return {"attempted": True, "ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"attempted": True, "ok": False, "error": str(exc)}

    # -- client bindings ----------------------------------------------------
    async def list_client_bindings(
        self,
        tenant_id: str,
        client_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not tenant_id or not client_id:
            return []
        rows = await self._repo().list(
            "client_integration_bindings",
            filters={
                **_filters(tenant_id=str(tenant_id), client_id=str(client_id), is_deleted=False),
                "limit": str(limit),
            },
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def get_client_binding(
        self,
        tenant_id: str,
        client_id: str,
        platform: str,
    ) -> Optional[dict[str, Any]]:
        if not tenant_id or not client_id or not platform:
            return None
        row = await self._repo().get_one(
            "client_integration_bindings",
            filters=_filters(
                tenant_id=str(tenant_id),
                client_id=str(client_id),
                platform=str(platform).strip().lower(),
                is_deleted=False,
            ),
        )
        return _to_doc(row) if row else None

    async def list_tenant_client_bindings(self, tenant_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        rows = await self._repo().list(
            "client_integration_bindings",
            filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def upsert_client_binding(
        self,
        tenant_id: str,
        client_id: str,
        doc: dict[str, Any],
    ) -> dict[str, Any]:
        payload = _row_from_doc(
            {
                **dict(doc or {}),
                "tenant_id": str(tenant_id),
                "client_id": str(client_id),
                "is_deleted": False,
            }
        )
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert(
            "client_integration_bindings", payload, on_conflict="tenant_id,client_id,platform"
        )
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def soft_delete_client_binding(self, tenant_id: str, client_id: str, platform: str) -> bool:
        await self._repo().update(
            "client_integration_bindings",
            {"is_deleted": True},
            filters=_filters(
                tenant_id=str(tenant_id),
                client_id=str(client_id),
                platform=str(platform).strip().lower(),
            ),
        )
        return True

    # -- clickup sync -------------------------------------------------------
    async def get_clickup_client_sync_state(self, tenant_id: str, user_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not user_id:
            return None
        row = await self._repo().get_one(
            "clickup_client_sync_state",
            filters=_filters(tenant_id=str(tenant_id), user_id=str(user_id), is_deleted=False),
        )
        return _to_doc(row) if row else None

    async def upsert_clickup_client_sync_state(self, tenant_id: str, user_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc(
            {**dict(doc or {}), "tenant_id": str(tenant_id), "user_id": str(user_id), "is_deleted": False}
        )
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert(
            "clickup_client_sync_state", payload, on_conflict="tenant_id,user_id"
        )
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def get_clickup_client_sync_log(self, tenant_id: str, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if not tenant_id or not user_id:
            return []
        rows = await self._repo().list(
            "clickup_client_sync_log",
            filters={
                **_filters(tenant_id=str(tenant_id), user_id=str(user_id), is_deleted=False),
                "limit": str(limit),
            },
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def create_clickup_client_sync_log(self, tenant_id: str, user_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc(
            {**dict(doc or {}), "tenant_id": str(tenant_id), "user_id": str(user_id), "is_deleted": False}
        )
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().insert("clickup_client_sync_log", payload)
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    # -- ai visibility ------------------------------------------------------
    async def get_ai_visibility_config_for_client(self, tenant_id: str, client_id: str) -> Optional[dict[str, Any]]:
        return await self.get_ai_visibility_config(tenant_id=tenant_id, client_id=client_id)

    async def list_ai_visibility_configs(self, tenant_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        rows = await self._repo().list(
            "ai_visibility_configs",
            filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def get_ai_visibility_config(
        self,
        tenant_id: str,
        *,
        client_id: Optional[str] = None,
        config_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if not tenant_id:
            return None
        f = _filters(tenant_id=str(tenant_id), is_deleted=False)
        if client_id:
            f["client_id"] = f"eq.{client_id}"
        if config_id:
            f["id"] = f"eq.{config_id}"
        row = await self._repo().get_one("ai_visibility_configs", filters=f)
        return _to_doc(row) if row else None

    async def upsert_ai_visibility_config(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().upsert("ai_visibility_configs", payload, on_conflict="tenant_id,client_id")
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def list_ai_visibility_runs(
        self, tenant_id: str, *, config_id: Optional[str] = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        f = _filters(tenant_id=str(tenant_id), is_deleted=False)
        if config_id:
            f["config_id"] = f"eq.{config_id}"
        f["limit"] = str(limit)
        rows = await self._repo().list("ai_visibility_runs", filters=f, order="created_at.desc")
        return [_to_doc(r) for r in (rows or []) if r]

    async def create_ai_visibility_run(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().insert("ai_visibility_runs", payload)
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def get_latest_ai_visibility_scan(self, tenant_id: str, config_id: str) -> Optional[dict[str, Any]]:
        if not tenant_id or not config_id:
            return None
        rows = await self._repo().list(
            "ai_visibility_scans",
            filters={
                **_filters(tenant_id=str(tenant_id), config_id=str(config_id), is_deleted=False),
                "limit": "1",
            },
            order="created_at.desc",
        )
        return _to_doc(rows[0]) if rows else None

    async def create_ai_visibility_scan(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        row = await self._repo().insert("ai_visibility_scans", payload)
        return _to_doc(row) or _to_doc(payload)  # type: ignore[return-value]

    async def list_ai_visibility_scans(self, tenant_id: str, *, config_id: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        f = _filters(tenant_id=str(tenant_id), is_deleted=False)
        if config_id:
            f["config_id"] = f"eq.{config_id}"
        f["limit"] = str(limit)
        rows = await self._repo().list("ai_visibility_scans", filters=f, order="created_at.desc")
        return [_to_doc(r) for r in (rows or []) if r]

    async def list_ai_territory_events(self, tenant_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        rows = await self._repo().list(
            "ai_territory_events",
            filters={**_filters(tenant_id=str(tenant_id), is_deleted=False), "limit": str(limit)},
            order="created_at.desc",
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def create_ai_territory_events(self, tenant_id: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for doc in docs or []:
            payload = _row_from_doc({**dict(doc or {}), "tenant_id": str(tenant_id), "is_deleted": False})
            if not payload.get("id"):
                import uuid

                payload["id"] = str(uuid.uuid4())
            row = await self._repo().insert("ai_territory_events", payload)
            out.append(_to_doc(row) or _to_doc(payload))  # type: ignore[arg-type]
        return out

    # -- oauth accounts -----------------------------------------------------
    async def get_user_oauth_account(
        self,
        tenant_id: str,
        user_id: str,
        provider: str,
        platform: str,
    ) -> Optional[dict[str, Any]]:
        if not tenant_id or not user_id or not provider or not platform:
            return None
        row = await self._repo().get_one(
            "user_oauth_accounts",
            filters=_filters(
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                provider=str(provider).strip().lower(),
                platform=str(platform).strip().lower(),
                is_deleted=False,
            ),
        )
        return _to_doc(row) if row else None

    async def list_user_oauth_accounts(self, tenant_id: str, *, user_id: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        if not tenant_id:
            return []
        f = _filters(tenant_id=str(tenant_id), is_deleted=False)
        if user_id:
            f["user_id"] = f"eq.{user_id}"
        f["limit"] = str(limit)
        rows = await self._repo().list(
            "user_oauth_accounts", filters=f, order="created_at.desc"
        )
        return [_to_doc(r) for r in (rows or []) if r]

    async def mirror_user_oauth_account(self, tenant_id: str, user_id: str, doc: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
        payload = _row_from_doc(
            {
                **dict(doc or {}),
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "is_deleted": False,
            }
        )
        if not payload.get("id"):
            import uuid

            payload["id"] = str(uuid.uuid4())
        try:
            row = await self._repo().upsert(
                "user_oauth_accounts",
                payload,
                on_conflict="tenant_id,user_id,provider,platform",
            )
            return {"attempted": True, "ok": True, "result": _to_doc(row) or _to_doc(payload)}
        except Exception as exc:  # noqa: BLE001
            return {"attempted": True, "ok": False, "reason": reason or "unknown", "error": str(exc)}

    async def safe_mirror_user_oauth_account(self, tenant_id: str, user_id: str, doc: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
        return await self.mirror_user_oauth_account(tenant_id, user_id, doc, reason=reason)

    async def soft_delete_user_oauth_account(
        self,
        tenant_id: str,
        user_id: str,
        provider: str,
        platform: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        try:
            await self._repo().update(
                "user_oauth_accounts",
                {"is_deleted": True},
                filters=_filters(
                    tenant_id=str(tenant_id),
                    user_id=str(user_id),
                    provider=str(provider).strip().lower(),
                    platform=str(platform).strip().lower(),
                    is_deleted=False,
                ),
            )
            return {"attempted": True, "ok": True, "reason": reason}
        except Exception as exc:  # noqa: BLE001
            return {"attempted": True, "ok": False, "reason": reason or "unknown", "error": str(exc)}

    async def safe_soft_delete_user_oauth_account(
        self,
        tenant_id: str,
        user_id: str,
        provider: str,
        platform: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        return await self.soft_delete_user_oauth_account(
            tenant_id, user_id, provider, platform, reason=reason
        )

    # -- diagnostics --------------------------------------------------------
    async def smoke_check(self, tenant_legacy_id: Optional[str] = None) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "enabled": self.service_configured(),
            "tenant_source_id": tenant_legacy_id,
            "checks": [],
        }
        if not summary["enabled"]:
            return summary
        try:
            tenants = await self.list_tenants(limit=10)
            summary["checks"].append({"domain": "tenants", "ok": True, "count": len(tenants)})
        except Exception as exc:  # noqa: BLE001
            summary["checks"].append({"domain": "tenants", "ok": False, "error": str(exc)})
        return summary


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _build_store() -> SupabaseStore:
    return SupabaseStore()


store = _build_store()


def get_store() -> SupabaseStore:
    return store