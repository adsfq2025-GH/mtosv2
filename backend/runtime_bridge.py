"""Optional Supabase runtime read bridge with Mongo overlay fallback."""
from __future__ import annotations

import logging
import os
import uuid
from functools import lru_cache
from typing import Any, Optional, Sequence

import httpx

from supabase_config import get_runtime_bridge_settings, reset_supabase_settings_cache

logger = logging.getLogger("mtos.runtime_bridge")


def _to_bool(value: Any, default: bool = False) -> bool:
    raw = str(value if value is not None else "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except Exception:
        return default


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except Exception:
        return False


def _norm_host(host: str) -> str:
    h = str(host or "").strip().lower()
    if not h:
        return ""
    if "://" in h:
        h = h.split("://", 1)[1]
    if "/" in h:
        h = h.split("/", 1)[0]
    if ":" in h:
        h = h.split(":", 1)[0]
    return h


def merge_prefer_bridge(
    primary_docs: Sequence[dict[str, Any]],
    bridge_docs: Sequence[dict[str, Any]],
    *,
    key_field: str = "_id",
    include_bridge_only: bool = False,
) -> list[dict[str, Any]]:
    overlay = {
        str(doc.get(key_field) or ""): doc
        for doc in (bridge_docs or [])
        if str(doc.get(key_field) or "").strip()
    }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for doc in primary_docs or []:
        key = str(doc.get(key_field) or "").strip()
        if key:
            seen.add(key)
        out.append(overlay.get(key, doc))

    if include_bridge_only:
        for key, doc in overlay.items():
            if key not in seen:
                out.append(doc)

    return out


class RuntimeBridge:
    def __init__(self, settings: Optional[dict[str, Any]] = None):
        self.settings = settings or get_runtime_bridge_settings()

    @property
    def service_configured(self) -> bool:
        return bool(self.settings.get("service_configured"))

    def is_enabled_for(self, domain: str) -> bool:
        if not self.service_configured:
            return False
        return str(domain or "").strip().lower() in set(self.settings.get("domains") or ())

    def is_mirror_enabled_for(self, domain: str) -> bool:
        if not self.service_configured:
            return False
        return str(domain or "").strip().lower() in set(self.settings.get("mirror_domains") or ())

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": str(self.settings.get("service_role_key") or ""),
            "Authorization": f"Bearer {self.settings.get('service_role_key') or ''}",
            "Accept-Profile": str(self.settings.get("db_schema") or "public"),
        }

    def _write_headers(self, *, prefer: Optional[str] = None) -> dict[str, str]:
        headers = {
            **self._headers(),
            "Content-Profile": str(self.settings.get("db_schema") or "public"),
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _select(
        self,
        relation: str,
        *,
        select: str = "*",
        filters: Optional[dict[str, str]] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": select}
        for key, value in (filters or {}).items():
            if value is not None:
                params[key] = str(value)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(int(limit))

        async with httpx.AsyncClient(timeout=float(self.settings.get("timeout_seconds") or 8.0)) as client:
            response = await client.get(
                f"{self.settings['url']}/rest/v1/{relation.lstrip('/')}",
                params=params,
                headers=self._headers(),
            )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    async def _safe_select(self, relation: str, **kwargs: Any) -> Optional[list[dict[str, Any]]]:
        try:
            return await self._select(relation, **kwargs)
        except Exception as exc:
            logger.warning("runtime bridge query failed for %s: %s", relation, exc)
            return None

    async def _request(
        self,
        method: str,
        relation: str,
        *,
        params: Optional[dict[str, str]] = None,
        payload: Any = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        async with httpx.AsyncClient(timeout=float(self.settings.get("timeout_seconds") or 8.0)) as client:
            response = await client.request(
                method.upper(),
                f"{self.settings['url']}/rest/v1/{relation.lstrip('/')}",
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

    async def mirror_tenant_settings(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        if not self.is_mirror_enabled_for("settings"):
            return {"attempted": False, "ok": False, "reason": "disabled"}

        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return {"attempted": False, "ok": False, "reason": "tenant_not_mapped"}

        payload = {
            "tenant_id": target_tenant_id,
            "branding": dict(doc.get("branding") or {}),
            "terminology": dict(doc.get("terminology") or {}),
            "workflows": dict(doc.get("workflows") or {}),
            "analysis": dict(doc.get("analysis") or {}),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "is_deleted": False,
        }

        existing_rows = await self._safe_select(
            "tenant_settings",
            select="id",
            filters={"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
            limit=1,
        )
        if existing_rows is None:
            raise RuntimeError("tenant_settings mirror preflight failed")

        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            if not row_id:
                raise RuntimeError("tenant_settings mirror target row missing id")
            result = await self._request(
                "PATCH",
                "tenant_settings",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
            return {
                "attempted": True,
                "ok": True,
                "mode": "update",
                "reason": reason,
                "target_tenant_id": target_tenant_id,
                "result": result,
            }

        result = await self._request(
            "POST",
            "tenant_settings",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        return {
            "attempted": True,
            "ok": True,
            "mode": "insert",
            "reason": reason,
            "target_tenant_id": target_tenant_id,
            "result": result,
        }

    async def safe_mirror_tenant_settings(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        try:
            return await self.mirror_tenant_settings(tenant_legacy_id, doc, reason=reason)
        except Exception as exc:
            logger.warning("tenant_settings mirror failed for tenant %s (%s): %s", tenant_legacy_id, reason or "unknown", exc)
            return {"attempted": True, "ok": False, "reason": reason or "unknown", "error": str(exc)}

    async def resolve_target_tenant_id(self, tenant_legacy_id: str) -> Optional[str]:
        if not self.service_configured:
            return None
        filters = {"is_deleted": "eq.false"}
        if _is_uuid(tenant_legacy_id):
            filters["or"] = f"(legacy_source_id.eq.{tenant_legacy_id},id.eq.{tenant_legacy_id})"
        else:
            filters["legacy_source_id"] = f"eq.{tenant_legacy_id}"

        rows = await self._safe_select(
            "tenants",
            select="id,legacy_source_id",
            filters=filters,
            limit=1,
        )
        if not rows:
            return None
        tenant_id = str((rows[0] or {}).get("id") or "").strip()
        return tenant_id or None

    async def resolve_target_user_id(self, user_legacy_id: str) -> Optional[str]:
        if not self.service_configured:
            return None
        filters = {"email": "not.is.null"}
        if _is_uuid(user_legacy_id):
            filters["or"] = f"(legacy_source_id.eq.{user_legacy_id},id.eq.{user_legacy_id})"
        else:
            filters["legacy_source_id"] = f"eq.{user_legacy_id}"

        rows = await self._safe_select(
            "user_profiles",
            select="id,legacy_source_id",
            filters=filters,
            limit=1,
        )
        if not rows:
            return None
        user_id = str((rows[0] or {}).get("id") or "").strip()
        return user_id or None

    async def get_tenant(self, tenant_legacy_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("tenants"):
            return None
        filters = {"is_deleted": "eq.false"}
        if _is_uuid(tenant_legacy_id):
            filters["or"] = f"(legacy_source_id.eq.{tenant_legacy_id},id.eq.{tenant_legacy_id})"
        else:
            filters["legacy_source_id"] = f"eq.{tenant_legacy_id}"
        rows = await self._safe_select(
            "tenants",
            select="id,legacy_source_id,slug,name,status,subscription_status,subscription_expires_at,trial_ends_at,metadata",
            filters=filters,
            limit=1,
        )
        if not rows:
            return None
        row = dict(rows[0] or {})
        row["_id"] = str(row.get("legacy_source_id") or row.get("id") or tenant_legacy_id)
        row["id"] = row["_id"]
        row["metadata"] = dict(row.get("metadata") or {})
        return row

    async def list_tenants(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("tenants"):
            return []
        filters: dict[str, str] = {"is_deleted": "eq.false"}
        normalized_status = str(status or "").strip().lower()
        if normalized_status:
            filters["status"] = f"eq.{normalized_status}"
        rows = await self._safe_select(
            "tenants",
            select="id,legacy_source_id,slug,name,status,subscription_status,subscription_expires_at,trial_ends_at,metadata",
            filters=filters,
            order="created_at.asc",
            limit=limit,
        )
        out: list[dict[str, Any]] = []
        for row in rows or []:
            doc = dict(row or {})
            doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
            doc["id"] = doc["_id"]
            doc["metadata"] = dict(doc.get("metadata") or {})
            out.append(doc)
        return out

    async def resolve_tenant_legacy_id_from_host(self, host: str) -> Optional[str]:
        if not self.is_enabled_for("tenants"):
            return None

        normalized_host = _norm_host(host)
        if not normalized_host:
            return None

        base_domain = str(os.environ.get("BASE_DOMAIN", "mapranking.com") or "").strip().lower()
        if base_domain and normalized_host.endswith("." + base_domain):
            slug = normalized_host[: -(len(base_domain) + 1)].split(".", 1)[0].strip()
            if slug:
                rows = await self._safe_select(
                    "tenants",
                    select="id,slug,legacy_source_id,status",
                    filters={"slug": f"eq.{slug}", "status": "eq.active", "is_deleted": "eq.false"},
                    limit=1,
                )
                if rows:
                    row = rows[0] or {}
                    return str(row.get("legacy_source_id") or row.get("id") or "").strip() or None

        domain_rows = await self._safe_select(
            "tenant_domains",
            select="tenant_id",
            filters={"domain": f"eq.{normalized_host}", "is_deleted": "eq.false"},
            limit=1,
        )
        if not domain_rows:
            return None

        tenant_id = str((domain_rows[0] or {}).get("tenant_id") or "").strip()
        if not tenant_id:
            return None

        tenant_rows = await self._safe_select(
            "tenants",
            select="id,legacy_source_id,status",
            filters={"id": f"eq.{tenant_id}", "status": "eq.active", "is_deleted": "eq.false"},
            limit=1,
        )
        if not tenant_rows:
            return None
        row = tenant_rows[0] or {}
        return str(row.get("legacy_source_id") or row.get("id") or "").strip() or None

    async def get_user_profile(self, user_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("profiles"):
            return None
        filters: dict[str, str]
        if _is_uuid(user_id):
            filters = {"or": f"(legacy_source_id.eq.{user_id},id.eq.{user_id})"}
        else:
            filters = {"legacy_source_id": f"eq.{user_id}"}

        rows = await self._safe_select(
            "user_profiles",
            select="id,email,full_name,avatar_url,auth_provider,system_role,legacy_source_id",
            filters=filters,
            limit=1,
        )
        if not rows:
            return None
        row = rows[0] or {}
        profile_id = str(row.get("legacy_source_id") or row.get("id") or user_id)
        display_name = str(row.get("full_name") or "").strip()
        if not display_name and row.get("email"):
            display_name = str(row.get("email")).split("@", 1)[0]
        return {
            "_id": profile_id,
            "id": profile_id,
            "email": row.get("email"),
            "name": display_name or None,
            "avatar_url": row.get("avatar_url"),
            "role": row.get("system_role"),
            "auth_provider": row.get("auth_provider"),
        }

    async def get_user_profile_by_email(self, email: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("profiles"):
            return None
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return None
        rows = await self._safe_select(
            "user_profiles",
            select="id,email,full_name,avatar_url,auth_provider,system_role,legacy_source_id",
            filters={"email": f"eq.{normalized_email}"},
            limit=1,
        )
        if not rows:
            return None
        row = rows[0] or {}
        profile_id = str(row.get("legacy_source_id") or row.get("id") or normalized_email)
        display_name = str(row.get("full_name") or "").strip()
        if not display_name and row.get("email"):
            display_name = str(row.get("email")).split("@", 1)[0]
        return {
            "_id": profile_id,
            "id": profile_id,
            "email": row.get("email"),
            "name": display_name or None,
            "avatar_url": row.get("avatar_url"),
            "role": row.get("system_role"),
            "auth_provider": row.get("auth_provider"),
        }

    async def list_user_profiles(self, *, limit: int = 500) -> list[dict[str, Any]]:
        if not self.is_enabled_for("profiles"):
            return []
        rows = await self._safe_select(
            "user_profiles",
            select="id,email,full_name,avatar_url,auth_provider,system_role,legacy_source_id",
            filters={"email": "not.is.null"},
            order="created_at.asc",
            limit=limit,
        )
        return [
            {
                "_id": str((row or {}).get("legacy_source_id") or (row or {}).get("id") or ""),
                "id": str((row or {}).get("legacy_source_id") or (row or {}).get("id") or ""),
                "email": (row or {}).get("email"),
                "name": str((row or {}).get("full_name") or "").strip()
                or str((row or {}).get("email") or "").split("@", 1)[0]
                or None,
                "avatar_url": (row or {}).get("avatar_url"),
                "role": (row or {}).get("system_role"),
                "auth_provider": (row or {}).get("auth_provider"),
            }
            for row in (rows or [])
        ]

    async def has_user_profiles(self) -> bool:
        if not self.is_enabled_for("profiles"):
            return False
        rows = await self._safe_select(
            "user_profiles",
            select="id",
            filters={"email": "not.is.null"},
            limit=1,
        )
        return bool(rows)

    def _legacy_membership_role(self, role: Any) -> str:
        normalized = str(role or "").strip().lower()
        return {
            "tenant_owner": "owner",
            "manager": "admin",
            "staff": "member",
            "customer": "viewer",
            "owner": "owner",
            "admin": "admin",
            "member": "member",
            "viewer": "viewer",
        }.get(normalized, "member")

    def _supabase_membership_role(self, role: Any) -> str:
        normalized = str(role or "").strip().lower()
        return {
            "owner": "tenant_owner",
            "admin": "manager",
            "member": "staff",
            "viewer": "customer",
            "tenant_owner": "tenant_owner",
            "manager": "manager",
            "staff": "staff",
            "customer": "customer",
        }.get(normalized, "staff")

    def _legacy_membership_status(self, status: Any) -> str:
        normalized = str(status or "").strip().lower()
        return {
            "active": "active",
            "invited": "invited",
            "disabled": "disabled",
            "inactive": "disabled",
            "suspended": "disabled",
        }.get(normalized, "active")

    def _tenant_member_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        user_legacy_id: str,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(
            doc.get("legacy_membership_id")
            or doc.get("legacy_source_id")
            or doc.get("id")
            or f"{tenant_legacy_id}:{user_legacy_id}"
        )
        doc["tenant_id"] = tenant_legacy_id
        doc["user_id"] = user_legacy_id
        doc["role"] = self._legacy_membership_role(doc.get("role"))
        doc["status"] = self._legacy_membership_status(doc.get("status"))
        doc["is_default"] = bool(doc.get("is_default"))
        for key in ("id", "legacy_membership_id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def _load_tenant_legacy_map(self, tenant_ids: Sequence[str]) -> dict[str, str]:
        clean_ids = [str(tenant_id).strip() for tenant_id in tenant_ids if str(tenant_id).strip()]
        if not clean_ids:
            return {}
        rows = await self._safe_select(
            "tenants",
            select="id,legacy_source_id",
            filters={"id": f"in.({','.join(clean_ids)})"},
            limit=len(clean_ids),
        )
        if not rows:
            return {}
        return {
            str(row.get("id") or ""): str(row.get("legacy_source_id") or row.get("id") or "")
            for row in rows
            if str(row.get("id") or "").strip()
        }

    async def get_tenant_by_slug(self, slug: str) -> Optional[dict[str, Any]]:
        normalized_slug = str(slug or "").strip().lower()
        if not self.is_enabled_for("tenants") or not normalized_slug:
            return None
        rows = await self._safe_select(
            "tenants",
            select="id,legacy_source_id,slug,name,status,subscription_status,subscription_expires_at,trial_ends_at,metadata",
            filters={"slug": f"eq.{normalized_slug}", "is_deleted": "eq.false"},
            limit=1,
        )
        if not rows:
            return None
        row = dict(rows[0] or {})
        row["_id"] = str(row.get("legacy_source_id") or row.get("id") or normalized_slug)
        row["id"] = row["_id"]
        row["metadata"] = dict(row.get("metadata") or {})
        return row

    async def create_tenant(
        self,
        *,
        slug: str,
        name: str,
        owner_user_legacy_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        status: str = "active",
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        normalized_slug = str(slug or "").strip().lower()
        normalized_name = str(name or "").strip()
        if not normalized_slug or not normalized_name:
            return None
        owner_user_id = await self.resolve_target_user_id(str(owner_user_legacy_id or "").strip()) if owner_user_legacy_id else None
        payload = {
            "slug": normalized_slug,
            "name": normalized_name,
            "status": str(status or "active").strip().lower() or "active",
            "owner_user_id": owner_user_id,
            "metadata": dict(metadata or {}),
            "is_deleted": False,
        }
        result = await self._request(
            "POST",
            "tenants",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        row = dict(rows[0] or {})
        row["_id"] = str(row.get("legacy_source_id") or row.get("id") or normalized_slug)
        row["id"] = row["_id"]
        row["metadata"] = dict(row.get("metadata") or {})
        return row

    async def get_user_membership(self, tenant_legacy_id: str, user_legacy_id: str) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        if not target_tenant_id or not target_user_id:
            return None
        rows = await self._safe_select(
            "tenant_members",
            select="id,tenant_id,user_id,role,status,is_default,joined_at,legacy_membership_id,legacy_source_id,created_at,updated_at",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "user_id": f"eq.{target_user_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return self._tenant_member_row_to_doc(rows[0], tenant_legacy_id, user_legacy_id)

    async def list_user_memberships(self, user_legacy_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        if not self.service_configured:
            return []
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        if not target_user_id:
            return []
        rows = await self._safe_select(
            "tenant_members",
            select="id,tenant_id,user_id,role,status,is_default,joined_at,legacy_membership_id,legacy_source_id,created_at,updated_at",
            filters={"user_id": f"eq.{target_user_id}", "is_deleted": "eq.false"},
            order="is_default.desc,created_at.asc",
            limit=limit,
        )
        if not rows:
            return []
        tenant_ids = [
            str((row or {}).get("tenant_id") or "").strip()
            for row in rows
            if str((row or {}).get("tenant_id") or "").strip()
        ]
        legacy_tenant_by_id = await self._load_tenant_legacy_map(tenant_ids)
        return [
            self._tenant_member_row_to_doc(
                row,
                legacy_tenant_by_id.get(str((row or {}).get("tenant_id") or "").strip())
                or str((row or {}).get("tenant_id") or "").strip(),
                user_legacy_id,
            )
            for row in rows
        ]

    async def count_active_members_for_tenant(self, tenant_legacy_id: str) -> int:
        if not self.service_configured:
            return 0
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return 0
        rows = await self._safe_select(
            "tenant_members",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "status": "eq.active",
                "is_deleted": "eq.false",
            },
            limit=1000,
        )
        return len(rows or [])

    async def create_tenant_membership(
        self,
        tenant_legacy_id: str,
        user_legacy_id: str,
        *,
        role: str,
        status: str = "active",
        is_default: bool = False,
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        if not target_tenant_id or not target_user_id:
            return None
        existing = await self._safe_select(
            "tenant_members",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "user_id": f"eq.{target_user_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        payload = {
            "tenant_id": target_tenant_id,
            "user_id": target_user_id,
            "role": self._supabase_membership_role(role),
            "status": self._legacy_membership_status(status),
            "is_default": bool(is_default),
            "is_deleted": False,
        }
        if existing:
            row_id = str((existing[0] or {}).get("id") or "").strip()
            if not row_id:
                return None
            result = await self._request(
                "PATCH",
                "tenant_members",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "tenant_members",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._tenant_member_row_to_doc(rows[0], tenant_legacy_id, user_legacy_id)

    async def upsert_tenant_settings(self, tenant_legacy_id: str, doc: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "branding": dict((doc or {}).get("branding") or {}),
            "terminology": dict((doc or {}).get("terminology") or {}),
            "workflows": dict((doc or {}).get("workflows") or {}),
            "analysis": dict((doc or {}).get("analysis") or {}),
            "created_at": (doc or {}).get("created_at"),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        existing_rows = await self._safe_select(
            "tenant_settings",
            select="id",
            filters={"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
            limit=1,
        )
        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            if not row_id:
                return None
            result = await self._request(
                "PATCH",
                "tenant_settings",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "tenant_settings",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._settings_row_to_doc(rows[0], tenant_legacy_id)

    def _settings_row_to_doc(self, row: dict[str, Any], tenant_legacy_id: str) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["branding"] = dict(doc.get("branding") or {})
        doc["terminology"] = dict(doc.get("terminology") or {})
        doc["workflows"] = dict(doc.get("workflows") or {})
        doc["analysis"] = dict(doc.get("analysis") or {})
        doc.pop("id", None)
        return doc

    async def get_tenant_settings(self, tenant_legacy_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("settings"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "tenant_settings",
            select="id,tenant_id,branding,terminology,workflows,analysis,created_at,updated_at",
            filters={"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
            limit=1,
        )
        if not rows:
            return None
        return self._settings_row_to_doc(rows[0], tenant_legacy_id)

    def _tenant_domain_row_to_doc(self, row: dict[str, Any], tenant_legacy_id: str) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("id") or doc.get("domain") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["domain"] = str(doc.get("domain") or "").strip().lower()
        doc["is_primary"] = bool(doc.get("is_primary"))
        doc.pop("id", None)
        return doc

    async def list_tenant_domains(self, tenant_legacy_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if not self.is_enabled_for("domains"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        rows = await self._safe_select(
            "tenant_domains",
            select="id,tenant_id,domain,is_primary,verified_at,created_at,updated_at",
            filters={"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
            order="is_primary.desc,domain.asc",
            limit=limit,
        )
        return [self._tenant_domain_row_to_doc(row, tenant_legacy_id) for row in (rows or [])]

    async def get_tenant_domain(self, domain: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("domains"):
            return None
        normalized_domain = _norm_host(domain)
        if not normalized_domain:
            return None
        rows = await self._safe_select(
            "tenant_domains",
            select="id,tenant_id,domain,is_primary,verified_at,created_at,updated_at",
            filters={"domain": f"eq.{normalized_domain}", "is_deleted": "eq.false"},
            limit=1,
        )
        if not rows:
            return None
        row = rows[0] or {}
        tenant_id = str(row.get("tenant_id") or "").strip()
        tenant_legacy_id = tenant_id
        if tenant_id:
            tenant_rows = await self._safe_select(
                "tenants",
                select="id,legacy_source_id",
                filters={"id": f"eq.{tenant_id}", "is_deleted": "eq.false"},
                limit=1,
            )
            if tenant_rows:
                tenant_legacy_id = str((tenant_rows[0] or {}).get("legacy_source_id") or tenant_id)
        return self._tenant_domain_row_to_doc(row, tenant_legacy_id)

    async def upsert_tenant_domain(
        self,
        tenant_legacy_id: str,
        domain: str,
        *,
        is_primary: bool = False,
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        normalized_domain = _norm_host(domain)
        if not target_tenant_id or not normalized_domain:
            return None
        existing_rows = await self._safe_select(
            "tenant_domains",
            select="id,tenant_id,domain,is_primary,verified_at,created_at,updated_at",
            filters={"domain": f"eq.{normalized_domain}", "is_deleted": "eq.false"},
            limit=1,
        )
        payload = {
            "tenant_id": target_tenant_id,
            "domain": normalized_domain,
            "is_primary": bool(is_primary),
            "is_deleted": False,
        }
        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            if not row_id:
                return None
            result = await self._request(
                "PATCH",
                "tenant_domains",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "tenant_domains",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._tenant_domain_row_to_doc(rows[0], tenant_legacy_id)

    async def delete_tenant_domain(self, tenant_legacy_id: str, domain: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        normalized_domain = _norm_host(domain)
        if not target_tenant_id or not normalized_domain:
            return False
        existing_rows = await self._safe_select(
            "tenant_domains",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "domain": f"eq.{normalized_domain}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not existing_rows:
            return True
        row_id = str((existing_rows[0] or {}).get("id") or "").strip()
        if not row_id:
            return False
        await self._request(
            "PATCH",
            "tenant_domains",
            params={"id": f"eq.{row_id}"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def _load_user_legacy_map(self, user_ids: Sequence[str]) -> dict[str, str]:
        clean_ids = [str(user_id).strip() for user_id in user_ids if str(user_id).strip()]
        if not clean_ids:
            return {}
        rows = await self._safe_select(
            "user_profiles",
            select="id,legacy_source_id",
            filters={"id": f"in.({','.join(clean_ids)})"},
            limit=len(clean_ids),
        )
        if not rows:
            return {}
        return {
            str(row.get("id") or ""): str(row.get("legacy_source_id") or row.get("id") or "")
            for row in rows
            if str(row.get("id") or "").strip()
        }

    def _client_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        user_legacy_by_id: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        account_manager_user_id = str(doc.pop("account_manager_user_id", "") or "").strip()
        doc["account_manager_id"] = (user_legacy_by_id or {}).get(account_manager_user_id) or account_manager_user_id or None
        doc["services"] = list(doc.get("services") or [])
        doc["assigned_products"] = list(doc.get("assigned_products") or [])
        doc["crm_data"] = dict(doc.get("crm_data") or {})
        doc["gbp_data"] = dict(doc.get("gbp_data") or {})
        doc["suggestions"] = list(doc.get("suggestions") or [])
        doc["feedback_rolling_avg"] = dict(doc.get("feedback_rolling_avg") or {})
        doc["churn_risk_indicators"] = list(doc.get("churn_risk_indicators") or [])
        doc["sentiment_rolling"] = dict(doc.get("sentiment_rolling") or {})
        doc["mrr"] = _safe_float(doc.get("mrr"), 0.0)
        doc["health_score"] = _safe_int(doc.get("health_score"), 75)
        doc["churn_risk_score"] = _safe_int(doc.get("churn_risk_score"), 0)
        for key in ("legacy_source_id", "legacy_source_kind", "id", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def list_clients(self, tenant_legacy_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        if not self.is_enabled_for("clients"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        rows = await self._safe_select(
            "clients",
            select="*",
            filters={"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
            order="created_at.desc",
            limit=limit,
        )
        user_legacy_by_id = await self._load_user_legacy_map(
            [str(row.get("account_manager_user_id") or "").strip() for row in (rows or [])]
        )
        return [self._client_row_to_doc(row, tenant_legacy_id, user_legacy_by_id) for row in (rows or [])]

    async def get_client(self, tenant_legacy_id: str, client_legacy_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("clients"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "clients",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "legacy_source_id": f"eq.{client_legacy_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows and _is_uuid(client_legacy_id):
            rows = await self._safe_select(
                "clients",
                select="*",
                filters={"tenant_id": f"eq.{target_tenant_id}", "id": f"eq.{client_legacy_id}", "is_deleted": "eq.false"},
                limit=1,
            )
        if not rows:
            return None
        user_legacy_by_id = await self._load_user_legacy_map([str((rows[0] or {}).get("account_manager_user_id") or "").strip()])
        return self._client_row_to_doc(rows[0], tenant_legacy_id, user_legacy_by_id)

    async def upsert_client(self, tenant_legacy_id: str, doc: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        client_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id) if client_legacy_id else None
        account_manager_user_id = await self.resolve_target_user_id(str((doc or {}).get("account_manager_id") or "").strip())
        payload = {
            "tenant_id": target_tenant_id,
            "name": str((doc or {}).get("name") or "").strip(),
            "company": str((doc or {}).get("company") or "").strip(),
            "external_ref": str((doc or {}).get("external_ref") or "").strip() or None,
            "industry": (doc or {}).get("industry"),
            "primary_contact": (doc or {}).get("primary_contact"),
            "email": (doc or {}).get("email"),
            "phone": (doc or {}).get("phone"),
            "website": (doc or {}).get("website"),
            "location": (doc or {}).get("location"),
            "account_manager_user_id": account_manager_user_id,
            "account_manager_name": (doc or {}).get("account_manager_name"),
            "services": list((doc or {}).get("services") or []),
            "assigned_products": list((doc or {}).get("assigned_products") or []),
            "crm_data": dict((doc or {}).get("crm_data") or {}),
            "gbp_data": dict((doc or {}).get("gbp_data") or {}),
            "onboarding_date": (doc or {}).get("onboarding_date"),
            "mrr": _safe_float((doc or {}).get("mrr"), 0.0),
            "health_score": _safe_int((doc or {}).get("health_score"), 75),
            "churn_risk": str((doc or {}).get("churn_risk") or "low"),
            "sentiment": str((doc or {}).get("sentiment") or "neutral"),
            "notes": (doc or {}).get("notes"),
            "avatar_url": (doc or {}).get("avatar_url"),
            "status": str((doc or {}).get("status") or "active"),
            "suggestions": list((doc or {}).get("suggestions") or []),
            "suggestions_generated_at": (doc or {}).get("suggestions_generated_at"),
            "suggestions_model": (doc or {}).get("suggestions_model"),
            "feedback_alert": bool((doc or {}).get("feedback_alert", False)),
            "feedback_alert_level": str((doc or {}).get("feedback_alert_level") or "low"),
            "feedback_alert_reason": (doc or {}).get("feedback_alert_reason"),
            "feedback_last_submitted_at": (doc or {}).get("feedback_last_submitted_at"),
            "feedback_rolling_avg": dict((doc or {}).get("feedback_rolling_avg") or {}),
            "health_alert": bool((doc or {}).get("health_alert", False)),
            "health_alert_level": str((doc or {}).get("health_alert_level") or "low"),
            "health_alert_reason": (doc or {}).get("health_alert_reason"),
            "churn_risk_score": _safe_int((doc or {}).get("churn_risk_score"), 0),
            "churn_risk_indicators": list((doc or {}).get("churn_risk_indicators") or []),
            "nps_rolling_avg": (doc or {}).get("nps_rolling_avg"),
            "sentiment_rolling": dict((doc or {}).get("sentiment_rolling") or {}),
            "health_last_submitted_at": (doc or {}).get("health_last_submitted_at"),
            "is_deleted": False,
        }
        if target_client_id:
            result = await self._request(
                "PATCH",
                "clients",
                params={"id": f"eq.{target_client_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "clients",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        user_legacy_by_id = await self._load_user_legacy_map([str((rows[0] or {}).get("account_manager_user_id") or "").strip()])
        return self._client_row_to_doc(rows[0], tenant_legacy_id, user_legacy_by_id)

    async def soft_delete_client(self, tenant_legacy_id: str, client_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_client_id:
            return False
        await self._request(
            "PATCH",
            "clients",
            params={"id": f"eq.{target_client_id}"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def _load_client_legacy_map(self, client_ids: Sequence[str]) -> dict[str, str]:
        clean_ids = [str(client_id).strip() for client_id in client_ids if str(client_id).strip()]
        if not clean_ids:
            return {}
        rows = await self._safe_select(
            "clients",
            select="id,legacy_source_id",
            filters={"id": f"in.({','.join(clean_ids)})"},
            limit=len(clean_ids),
        )
        if not rows:
            return {}
        return {
            str(row.get("id") or ""): str(row.get("legacy_source_id") or row.get("id") or "")
            for row in rows
            if str(row.get("id") or "").strip()
        }

    async def resolve_target_client_id(self, tenant_legacy_id: str, client_legacy_id: str) -> Optional[str]:
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "clients",
            select="id,legacy_source_id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "or": f"(legacy_source_id.eq.{client_legacy_id},id.eq.{client_legacy_id})",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return str((rows[0] or {}).get("id") or "").strip() or None

    def _meeting_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_by_id: dict[str, str],
        user_legacy_by_id: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        doc = dict(row or {})
        client_id = str(doc.get("client_id") or "").strip()
        legacy_client_id = client_legacy_by_id.get(client_id) or (client_id if _is_uuid(client_id) else "")
        if not legacy_client_id:
            return None

        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = legacy_client_id
        account_manager_user_id = str(doc.pop("account_manager_user_id", "") or "").strip()
        doc["account_manager_id"] = (user_legacy_by_id or {}).get(account_manager_user_id) or account_manager_user_id or None
        for key in (
            "wins",
            "wins_library",
            "issues",
            "issues_library",
            "talking_points",
            "talking_points_library",
            "suggested_questions",
            "prep_checklist",
            "ace_up_the_sleeve",
            "strategic_recommendations",
            "campaign_recommendations",
            "discovery_questions",
        ):
            doc[key] = list(doc.get(key) or [])
        for key in (
            "automation_draft",
            "kpi_snapshot",
            "transcript_source",
            "transcript_analysis",
            "transcript_analysis_by_model",
            "checklist",
            "deliverable_reviews",
            "feedback",
        ):
            doc[key] = dict(doc.get(key) or {}) if doc.get(key) is not None else None
        doc["duration_minutes"] = _safe_int(doc.get("duration_minutes"), 60)
        doc["nps_score"] = _safe_int(doc.get("nps_score"), 0) if doc.get("nps_score") is not None else None
        doc["meeting_score"] = _safe_int(doc.get("meeting_score"), 0) if doc.get("meeting_score") is not None else None
        for key in ("legacy_source_id", "legacy_source_kind", "id", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def list_meetings(self, tenant_legacy_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        if not self.is_enabled_for("meetings"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        rows = await self._safe_select(
            "meetings",
            select="*",
            filters={"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        client_legacy_by_id = await self._load_client_legacy_map(
            [str(row.get("client_id") or "").strip() for row in rows if str(row.get("client_id") or "").strip()]
        )
        user_legacy_by_id = await self._load_user_legacy_map(
            [str(row.get("account_manager_user_id") or "").strip() for row in rows if str(row.get("account_manager_user_id") or "").strip()]
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            doc = self._meeting_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, user_legacy_by_id)
            if doc:
                out.append(doc)
        return out

    async def get_meeting(self, tenant_legacy_id: str, meeting_legacy_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("meetings"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "meetings",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "legacy_source_id": f"eq.{meeting_legacy_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows and _is_uuid(meeting_legacy_id):
            rows = await self._safe_select(
                "meetings",
                select="*",
                filters={"tenant_id": f"eq.{target_tenant_id}", "id": f"eq.{meeting_legacy_id}", "is_deleted": "eq.false"},
                limit=1,
            )
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        user_legacy_by_id = await self._load_user_legacy_map([str(row.get("account_manager_user_id") or "").strip()])
        return self._meeting_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, user_legacy_by_id)

    async def resolve_target_meeting_id(self, tenant_legacy_id: str, meeting_legacy_id: str) -> Optional[str]:
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "meetings",
            select="id,legacy_source_id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "or": f"(legacy_source_id.eq.{meeting_legacy_id},id.eq.{meeting_legacy_id})",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return str((rows[0] or {}).get("id") or "").strip() or None

    async def upsert_meeting(self, tenant_legacy_id: str, doc: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        meeting_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id) if meeting_legacy_id else None
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, str((doc or {}).get("client_id") or "").strip())
        if not target_client_id:
            return None
        account_manager_user_id = await self.resolve_target_user_id(str((doc or {}).get("account_manager_id") or "").strip())
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "client_name": (doc or {}).get("client_name"),
            "account_manager_user_id": account_manager_user_id,
            "account_manager_name": (doc or {}).get("account_manager_name"),
            "title": str((doc or {}).get("title") or "").strip(),
            "scheduled_at": (doc or {}).get("scheduled_at"),
            "status": str((doc or {}).get("status") or "scheduled"),
            "google_meet_url": (doc or {}).get("google_meet_url"),
            "duration_minutes": _safe_int((doc or {}).get("duration_minutes"), 60),
            "brief_generated_at": (doc or {}).get("brief_generated_at"),
            "brief_model": (doc or {}).get("brief_model"),
            "wins": list((doc or {}).get("wins") or []),
            "wins_library": list((doc or {}).get("wins_library") or []),
            "issues": list((doc or {}).get("issues") or []),
            "issues_library": list((doc or {}).get("issues_library") or []),
            "talking_points": list((doc or {}).get("talking_points") or []),
            "talking_points_library": list((doc or {}).get("talking_points_library") or []),
            "suggested_questions": list((doc or {}).get("suggested_questions") or []),
            "prep_checklist": list((doc or {}).get("prep_checklist") or []),
            "ace_up_the_sleeve": list((doc or {}).get("ace_up_the_sleeve") or []),
            "testimonial_opportunity": (doc or {}).get("testimonial_opportunity"),
            "strategic_recommendations": list((doc or {}).get("strategic_recommendations") or []),
            "campaign_recommendations": list((doc or {}).get("campaign_recommendations") or []),
            "health_signal": (doc or {}).get("health_signal"),
            "automation_draft": dict((doc or {}).get("automation_draft") or {}),
            "automation_draft_generated_at": (doc or {}).get("automation_draft_generated_at"),
            "automation_approved_at": (doc or {}).get("automation_approved_at"),
            "kpi_snapshot": dict((doc or {}).get("kpi_snapshot") or {}),
            "notes": (doc or {}).get("notes"),
            "transcript": (doc or {}).get("transcript"),
            "transcript_source": dict((doc or {}).get("transcript_source") or {}),
            "transcript_analyzed_at": (doc or {}).get("transcript_analyzed_at"),
            "sentiment": (doc or {}).get("sentiment"),
            "sentiment_summary": (doc or {}).get("sentiment_summary"),
            "transcript_analysis": dict((doc or {}).get("transcript_analysis") or {}),
            "transcript_analysis_by_model": dict((doc or {}).get("transcript_analysis_by_model") or {}),
            "nps_score": (doc or {}).get("nps_score"),
            "sentiment_classification": (doc or {}).get("sentiment_classification"),
            "health_notes": (doc or {}).get("health_notes"),
            "recap_html": (doc or {}).get("recap_html"),
            "recap_email": (doc or {}).get("recap_email"),
            "recap_subject": (doc or {}).get("recap_subject"),
            "recap_sent_at": (doc or {}).get("recap_sent_at"),
            "meeting_score": (doc or {}).get("meeting_score"),
            "checklist": dict((doc or {}).get("checklist") or {}),
            "deliverable_reviews": dict((doc or {}).get("deliverable_reviews") or {}),
            "discovery_questions": list((doc or {}).get("discovery_questions") or []),
            "feedback": dict((doc or {}).get("feedback") or {}) if (doc or {}).get("feedback") is not None else None,
            "is_deleted": False,
        }
        if target_meeting_id:
            result = await self._request(
                "PATCH",
                "meetings",
                params={"id": f"eq.{target_meeting_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "meetings",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        user_legacy_by_id = await self._load_user_legacy_map([str(row.get("account_manager_user_id") or "").strip()])
        return self._meeting_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, user_legacy_by_id)

    async def soft_delete_meeting(self, tenant_legacy_id: str, meeting_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id)
        if not target_meeting_id:
            return False
        await self._request(
            "PATCH",
            "meetings",
            params={"id": f"eq.{target_meeting_id}"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def soft_delete_meetings_for_client(self, tenant_legacy_id: str, client_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return False
        await self._request(
            "PATCH",
            "meetings",
            params={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def _load_meeting_legacy_map(self, meeting_ids: Sequence[str]) -> dict[str, str]:
        clean_ids = [str(meeting_id).strip() for meeting_id in meeting_ids if str(meeting_id).strip()]
        if not clean_ids:
            return {}
        rows = await self._safe_select(
            "meetings",
            select="id,legacy_source_id",
            filters={"id": f"in.({','.join(clean_ids)})"},
            limit=len(clean_ids),
        )
        if not rows:
            return {}
        return {
            str(row.get("id") or ""): str(row.get("legacy_source_id") or row.get("id") or "")
            for row in rows
            if str(row.get("id") or "").strip()
        }

    def _action_item_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_by_id: dict[str, str],
        meeting_legacy_by_id: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        doc = dict(row or {})
        client_id = str(doc.get("client_id") or "").strip()
        legacy_client_id = client_legacy_by_id.get(client_id) or (client_id if _is_uuid(client_id) else "")
        if not legacy_client_id:
            return None
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = legacy_client_id
        meeting_id = str(doc.get("meeting_id") or "").strip()
        doc["meeting_id"] = (meeting_legacy_by_id or {}).get(meeting_id) or (meeting_id if _is_uuid(meeting_id) else None) or None
        doc["reminder_count"] = _safe_int(doc.get("reminder_count"), 0)
        for key in ("legacy_source_id", "legacy_source_kind", "id", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def list_action_items(
        self,
        tenant_legacy_id: str,
        *,
        client_legacy_id: Optional[str] = None,
        meeting_legacy_id: Optional[str] = None,
        status: Optional[str] = None,
        owner_type: Optional[str] = None,
        due_before: Optional[str] = None,
        due_after: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("action_items"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        filters: dict[str, str] = {"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"}
        if client_legacy_id:
            target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
            if not target_client_id:
                return []
            filters["client_id"] = f"eq.{target_client_id}"
        if meeting_legacy_id:
            target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id)
            if not target_meeting_id:
                return []
            filters["meeting_id"] = f"eq.{target_meeting_id}"
        if status:
            filters["status"] = f"eq.{status}"
        if owner_type:
            filters["owner_type"] = f"eq.{owner_type}"
        if due_before:
            filters["due_date"] = f"lte.{due_before}"
        if due_after:
            filters["due_date"] = f"gte.{due_after}" if "due_date" not in filters else filters["due_date"]
        rows = await self._safe_select(
            "action_items",
            select="*",
            filters=filters,
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        client_legacy_by_id = await self._load_client_legacy_map(
            [str(row.get("client_id") or "").strip() for row in rows if str(row.get("client_id") or "").strip()]
        )
        meeting_legacy_by_id = await self._load_meeting_legacy_map(
            [str(row.get("meeting_id") or "").strip() for row in rows if str(row.get("meeting_id") or "").strip()]
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            doc = self._action_item_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id)
            if doc:
                out.append(doc)
        if due_before and due_after:
            out = [
                doc
                for doc in out
                if (not doc.get("due_date") or (str(due_after) <= str(doc.get("due_date")) <= str(due_before)))
            ]
        return out

    async def get_action_item(self, tenant_legacy_id: str, action_item_legacy_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("action_items"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "action_items",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "legacy_source_id": f"eq.{action_item_legacy_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows and _is_uuid(action_item_legacy_id):
            rows = await self._safe_select(
                "action_items",
                select="*",
                filters={"tenant_id": f"eq.{target_tenant_id}", "id": f"eq.{action_item_legacy_id}", "is_deleted": "eq.false"},
                limit=1,
            )
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        meeting_legacy_by_id = await self._load_meeting_legacy_map([str(row.get("meeting_id") or "").strip()])
        return self._action_item_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id)

    async def resolve_target_action_item_id(self, tenant_legacy_id: str, action_item_legacy_id: str) -> Optional[str]:
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "action_items",
            select="id,legacy_source_id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "or": f"(legacy_source_id.eq.{action_item_legacy_id},id.eq.{action_item_legacy_id})",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return str((rows[0] or {}).get("id") or "").strip() or None

    async def upsert_action_item(self, tenant_legacy_id: str, doc: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        action_item_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        target_action_item_id = (
            await self.resolve_target_action_item_id(tenant_legacy_id, action_item_legacy_id) if action_item_legacy_id else None
        )
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, str((doc or {}).get("client_id") or "").strip())
        if not target_client_id:
            return None
        meeting_legacy_id = str((doc or {}).get("meeting_id") or "").strip()
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id) if meeting_legacy_id else None
        if meeting_legacy_id and not target_meeting_id:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "meeting_id": target_meeting_id,
            "client_id": target_client_id,
            "title": str((doc or {}).get("title") or "").strip(),
            "description": (doc or {}).get("description"),
            "owner": (doc or {}).get("owner"),
            "owner_type": str((doc or {}).get("owner_type") or "agency"),
            "due_date": (doc or {}).get("due_date"),
            "status": str((doc or {}).get("status") or "open"),
            "priority": str((doc or {}).get("priority") or "medium"),
            "pushed_to": (doc or {}).get("pushed_to"),
            "external_id": (doc or {}).get("external_id"),
            "external_url": (doc or {}).get("external_url"),
            "last_reminded_at": (doc or {}).get("last_reminded_at"),
            "reminder_count": _safe_int((doc or {}).get("reminder_count"), 0),
            "legacy_source_id": action_item_legacy_id or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "mongo"),
            "is_deleted": False,
        }
        if target_action_item_id:
            result = await self._request(
                "PATCH",
                "action_items",
                params={"id": f"eq.{target_action_item_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "action_items",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        meeting_legacy_by_id = await self._load_meeting_legacy_map([str(row.get("meeting_id") or "").strip()])
        return self._action_item_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id)

    async def soft_delete_action_item(self, tenant_legacy_id: str, action_item_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_action_item_id = await self.resolve_target_action_item_id(tenant_legacy_id, action_item_legacy_id)
        if not target_action_item_id:
            return False
        await self._request(
            "PATCH",
            "action_items",
            params={"id": f"eq.{target_action_item_id}"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def soft_delete_action_items_for_client(self, tenant_legacy_id: str, client_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return False
        await self._request(
            "PATCH",
            "action_items",
            params={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def soft_delete_action_items_for_meeting(self, tenant_legacy_id: str, meeting_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id)
        if not target_tenant_id or not target_meeting_id:
            return False
        await self._request(
            "PATCH",
            "action_items",
            params={
                "tenant_id": f"eq.{target_tenant_id}",
                "meeting_id": f"eq.{target_meeting_id}",
                "is_deleted": "eq.false",
            },
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    def _client_review_goal_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_id: str,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = client_legacy_id
        doc["monthly_goal"] = _safe_int(doc.get("monthly_goal"), 10)
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    def _review_event_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_id: str,
        meeting_legacy_by_id: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        meeting_id = str(doc.get("meeting_id") or "").strip()
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = client_legacy_id
        doc["meeting_id"] = (meeting_legacy_by_id or {}).get(meeting_id) or (meeting_id if _is_uuid(meeting_id) else None) or None
        doc["count"] = _safe_int(doc.get("count"), 1)
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    def _review_monthly_snapshot_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_id: str,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = client_legacy_id
        doc["received"] = _safe_int(doc.get("received"), 0)
        avg_rating = doc.get("avg_rating")
        doc["avg_rating"] = _safe_float(avg_rating) if avg_rating not in (None, "") else None
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def get_client_review_goal(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("reviews"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return None
        rows = await self._safe_select(
            "client_review_goals",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return self._client_review_goal_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id)

    async def upsert_client_review_goal(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "legacy_source_id": str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip() or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "runtime"),
            "monthly_goal": _safe_int((doc or {}).get("monthly_goal"), 10),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        existing_rows = await self._safe_select(
            "client_review_goals",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            result = await self._request(
                "PATCH",
                "client_review_goals",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "client_review_goals",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._client_review_goal_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id)

    async def create_review_event(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        meeting_legacy_id = str((doc or {}).get("meeting_id") or "").strip()
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id) if meeting_legacy_id else None
        if not target_tenant_id or not target_client_id or (meeting_legacy_id and not target_meeting_id):
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "meeting_id": target_meeting_id,
            "legacy_source_id": str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip() or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "runtime"),
            "kind": str((doc or {}).get("kind") or "requested"),
            "count": _safe_int((doc or {}).get("count"), 1),
            "occurred_on": (doc or {}).get("occurred_on"),
            "channel": str((doc or {}).get("channel") or "other"),
            "source": str((doc or {}).get("source") or "manual"),
            "notes": (doc or {}).get("notes"),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        result = await self._request(
            "POST",
            "review_events",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        meeting_legacy_by_id = await self._load_meeting_legacy_map([str((rows[0] or {}).get("meeting_id") or "").strip()])
        return self._review_event_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id, meeting_legacy_by_id)

    async def list_review_events(
        self,
        tenant_legacy_id: str,
        *,
        client_legacy_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("reviews"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return []
        rows = await self._safe_select(
            "review_events",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            order="occurred_on.desc,created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        meeting_legacy_by_id = await self._load_meeting_legacy_map(
            [str(row.get("meeting_id") or "").strip() for row in rows if str(row.get("meeting_id") or "").strip()]
        )
        return [
            self._review_event_row_to_doc(row, tenant_legacy_id, client_legacy_id, meeting_legacy_by_id)
            for row in rows
        ]

    async def list_review_monthly_snapshots(
        self,
        tenant_legacy_id: str,
        *,
        client_legacy_id: Optional[str] = None,
        months: Optional[Sequence[str]] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("reviews"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        filters: dict[str, str] = {
            "tenant_id": f"eq.{target_tenant_id}",
            "is_deleted": "eq.false",
        }
        client_legacy_by_id: dict[str, str] = {}
        if client_legacy_id:
            target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
            if not target_client_id:
                return []
            filters["client_id"] = f"eq.{target_client_id}"
        clean_months = [str(month).strip() for month in (months or []) if str(month).strip()]
        if clean_months:
            filters["month"] = f"in.({','.join(clean_months)})"
        rows = await self._safe_select(
            "review_monthly_snapshots",
            select="*",
            filters=filters,
            order="month.desc,created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        if client_legacy_id:
            client_legacy_by_id = {str((rows[0] or {}).get("client_id") or "").strip(): client_legacy_id}
        else:
            client_legacy_by_id = await self._load_client_legacy_map(
                [str(row.get("client_id") or "").strip() for row in rows if str(row.get("client_id") or "").strip()]
            )
        out: list[dict[str, Any]] = []
        for row in rows:
            target_client_id = str((row or {}).get("client_id") or "").strip()
            resolved_client_legacy_id = client_legacy_by_id.get(target_client_id) or (target_client_id if _is_uuid(target_client_id) else "")
            if not resolved_client_legacy_id:
                continue
            out.append(self._review_monthly_snapshot_row_to_doc(row, tenant_legacy_id, resolved_client_legacy_id))
        return out

    async def upsert_review_monthly_snapshot(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        month = str((doc or {}).get("month") or "").strip()
        if not target_tenant_id or not target_client_id or not month:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "legacy_source_id": str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip() or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "runtime"),
            "month": month,
            "received": _safe_int((doc or {}).get("received"), 0),
            "avg_rating": _safe_float((doc or {}).get("avg_rating")) if (doc or {}).get("avg_rating") not in (None, "") else None,
            "source": str((doc or {}).get("source") or "gbp"),
            "kpi_period_kind": (doc or {}).get("kpi_period_kind"),
            "kpi_period_current_end": (doc or {}).get("kpi_period_current_end"),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        existing_rows = await self._safe_select(
            "review_monthly_snapshots",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "month": f"eq.{month}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            result = await self._request(
                "PATCH",
                "review_monthly_snapshots",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "review_monthly_snapshots",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._review_monthly_snapshot_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id)

    def _discovery_question_template_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["tags"] = list(doc.get("tags") or [])
        doc["deliverables"] = list(doc.get("deliverables") or [])
        doc["active"] = bool(doc.get("active", True))
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def list_discovery_question_templates(
        self,
        tenant_legacy_id: str,
        *,
        active_only: bool = False,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("discovery"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        filters: dict[str, str] = {
            "tenant_id": f"eq.{target_tenant_id}",
            "is_deleted": "eq.false",
        }
        if active_only:
            filters["active"] = "eq.true"
        rows = await self._safe_select(
            "discovery_question_templates",
            select="*",
            filters=filters,
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        return [self._discovery_question_template_row_to_doc(row, tenant_legacy_id) for row in rows]

    async def get_discovery_question_template(
        self,
        tenant_legacy_id: str,
        template_legacy_id: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("discovery"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id or not str(template_legacy_id or "").strip():
            return None
        rows = await self._safe_select(
            "discovery_question_templates",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "or": f"(legacy_source_id.eq.{template_legacy_id},id.eq.{template_legacy_id})",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return self._discovery_question_template_row_to_doc(rows[0], tenant_legacy_id)

    async def resolve_target_discovery_question_template_id(
        self,
        tenant_legacy_id: str,
        template_legacy_id: str,
    ) -> Optional[str]:
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id or not str(template_legacy_id or "").strip():
            return None
        rows = await self._safe_select(
            "discovery_question_templates",
            select="id,legacy_source_id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "or": f"(legacy_source_id.eq.{template_legacy_id},id.eq.{template_legacy_id})",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return str((rows[0] or {}).get("id") or "").strip() or None

    async def upsert_discovery_question_template(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        template_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        target_template_id = (
            await self.resolve_target_discovery_question_template_id(tenant_legacy_id, template_legacy_id)
            if template_legacy_id
            else None
        )
        payload = {
            "tenant_id": target_tenant_id,
            "legacy_source_id": template_legacy_id or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "runtime"),
            "kind": str((doc or {}).get("kind") or "operational"),
            "category": str((doc or {}).get("category") or "").strip(),
            "question": str((doc or {}).get("question") or "").strip(),
            "tags": list((doc or {}).get("tags") or []),
            "deliverables": list((doc or {}).get("deliverables") or []),
            "active": bool((doc or {}).get("active", True)),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        if target_template_id:
            result = await self._request(
                "PATCH",
                "discovery_question_templates",
                params={"id": f"eq.{target_template_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "discovery_question_templates",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._discovery_question_template_row_to_doc(rows[0], tenant_legacy_id)

    async def soft_delete_discovery_question_template(
        self,
        tenant_legacy_id: str,
        template_legacy_id: str,
    ) -> bool:
        if not self.service_configured:
            return False
        target_template_id = await self.resolve_target_discovery_question_template_id(tenant_legacy_id, template_legacy_id)
        if not target_template_id:
            return False
        await self._request(
            "PATCH",
            "discovery_question_templates",
            params={"id": f"eq.{target_template_id}"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    def _roadmap_plan_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_id: str,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        items = doc.get("items") or []
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = client_legacy_id
        doc["weeks"] = _safe_int(doc.get("weeks"), 12)
        doc["items"] = [dict(item or {}) for item in items if isinstance(item, dict)]
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def get_roadmap_plan(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("roadmap"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return None
        rows = await self._safe_select(
            "roadmap_plans",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return self._roadmap_plan_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id)

    async def upsert_roadmap_plan(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return None
        plan_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "legacy_source_id": plan_legacy_id or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "runtime"),
            "start_date": (doc or {}).get("start_date"),
            "weeks": _safe_int((doc or {}).get("weeks"), 12),
            "items": [dict(item or {}) for item in ((doc or {}).get("items") or []) if isinstance(item, dict)],
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        existing_rows = await self._safe_select(
            "roadmap_plans",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            result = await self._request(
                "PATCH",
                "roadmap_plans",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "roadmap_plans",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._roadmap_plan_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id)

    def _content_capture_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_by_id: dict[str, str],
        meeting_legacy_by_id: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        doc = dict(row or {})
        client_id = str(doc.get("client_id") or "").strip()
        legacy_client_id = client_legacy_by_id.get(client_id) or (client_id if _is_uuid(client_id) else "")
        if not legacy_client_id:
            return None
        meeting_id = str(doc.get("meeting_id") or "").strip()
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = legacy_client_id
        doc["meeting_id"] = (meeting_legacy_by_id or {}).get(meeting_id) or (meeting_id if _is_uuid(meeting_id) else None) or None
        doc["requested"] = bool(doc.get("requested", False))
        doc["received"] = bool(doc.get("received", False))
        doc["routed_to_marketing"] = bool(doc.get("routed_to_marketing", False))
        sentiment_score = doc.get("sentiment_score")
        doc["sentiment_score"] = _safe_float(sentiment_score) if sentiment_score not in (None, "") else None
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def list_content_captures(
        self,
        tenant_legacy_id: str,
        *,
        client_legacy_id: Optional[str] = None,
        meeting_legacy_id: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("content_captures"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        filters: dict[str, str] = {
            "tenant_id": f"eq.{target_tenant_id}",
            "is_deleted": "eq.false",
        }
        if client_legacy_id:
            target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
            if not target_client_id:
                return []
            filters["client_id"] = f"eq.{target_client_id}"
        if meeting_legacy_id:
            target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id)
            if not target_meeting_id:
                return []
            filters["meeting_id"] = f"eq.{target_meeting_id}"
        rows = await self._safe_select(
            "content_captures",
            select="*",
            filters=filters,
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        client_legacy_by_id = await self._load_client_legacy_map(
            [str(row.get("client_id") or "").strip() for row in rows if str(row.get("client_id") or "").strip()]
        )
        meeting_legacy_by_id = await self._load_meeting_legacy_map(
            [str(row.get("meeting_id") or "").strip() for row in rows if str(row.get("meeting_id") or "").strip()]
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            doc = self._content_capture_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id)
            if doc:
                out.append(doc)
        return out

    async def get_content_capture(
        self,
        tenant_legacy_id: str,
        content_capture_legacy_id: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("content_captures"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "content_captures",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "legacy_source_id": f"eq.{content_capture_legacy_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows and _is_uuid(content_capture_legacy_id):
            rows = await self._safe_select(
                "content_captures",
                select="*",
                filters={"tenant_id": f"eq.{target_tenant_id}", "id": f"eq.{content_capture_legacy_id}", "is_deleted": "eq.false"},
                limit=1,
            )
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        meeting_legacy_by_id = await self._load_meeting_legacy_map([str(row.get("meeting_id") or "").strip()])
        return self._content_capture_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id)

    async def resolve_target_content_capture_id(
        self,
        tenant_legacy_id: str,
        content_capture_legacy_id: str,
    ) -> Optional[str]:
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "content_captures",
            select="id,legacy_source_id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "or": f"(legacy_source_id.eq.{content_capture_legacy_id},id.eq.{content_capture_legacy_id})",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return str((rows[0] or {}).get("id") or "").strip() or None

    async def upsert_content_capture(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        content_capture_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        target_content_capture_id = (
            await self.resolve_target_content_capture_id(tenant_legacy_id, content_capture_legacy_id)
            if content_capture_legacy_id
            else None
        )
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, str((doc or {}).get("client_id") or "").strip())
        if not target_client_id:
            return None
        meeting_legacy_id = str((doc or {}).get("meeting_id") or "").strip()
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id) if meeting_legacy_id else None
        if meeting_legacy_id and not target_meeting_id:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "meeting_id": target_meeting_id,
            "legacy_source_id": content_capture_legacy_id or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "runtime"),
            "type": str((doc or {}).get("type") or "quote"),
            "content": str((doc or {}).get("content") or ""),
            "sentiment_score": _safe_float((doc or {}).get("sentiment_score")) if (doc or {}).get("sentiment_score") not in (None, "") else None,
            "timestamp_in_meeting": (doc or {}).get("timestamp_in_meeting"),
            "requested": bool((doc or {}).get("requested", False)),
            "received": bool((doc or {}).get("received", False)),
            "routed_to_marketing": bool((doc or {}).get("routed_to_marketing", False)),
            "notes": (doc or {}).get("notes"),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        if target_content_capture_id:
            result = await self._request(
                "PATCH",
                "content_captures",
                params={"id": f"eq.{target_content_capture_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "content_captures",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        meeting_legacy_by_id = await self._load_meeting_legacy_map([str(row.get("meeting_id") or "").strip()])
        return self._content_capture_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id)

    async def soft_delete_content_capture(self, tenant_legacy_id: str, content_capture_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_content_capture_id = await self.resolve_target_content_capture_id(tenant_legacy_id, content_capture_legacy_id)
        if not target_content_capture_id:
            return False
        await self._request(
            "PATCH",
            "content_captures",
            params={"id": f"eq.{target_content_capture_id}"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def soft_delete_content_captures_for_client(self, tenant_legacy_id: str, client_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return False
        await self._request(
            "PATCH",
            "content_captures",
            params={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def soft_delete_content_captures_for_meeting(self, tenant_legacy_id: str, meeting_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id)
        if not target_tenant_id or not target_meeting_id:
            return False
        await self._request(
            "PATCH",
            "content_captures",
            params={
                "tenant_id": f"eq.{target_tenant_id}",
                "meeting_id": f"eq.{target_meeting_id}",
                "is_deleted": "eq.false",
            },
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    def _ticket_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_by_id: dict[str, str],
        meeting_legacy_by_id: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        doc = dict(row or {})
        client_id = str(doc.get("client_id") or "").strip()
        legacy_client_id = client_legacy_by_id.get(client_id) or (client_id if _is_uuid(client_id) else "")
        if not legacy_client_id:
            return None
        meeting_id = str(doc.get("meeting_id") or "").strip()
        legacy_meeting_id = (meeting_legacy_by_id or {}).get(meeting_id) or (meeting_id if _is_uuid(meeting_id) else "")
        if not legacy_meeting_id:
            return None
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = legacy_client_id
        doc["meeting_id"] = legacy_meeting_id
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    def _qa_scorecard_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_by_id: dict[str, str],
        meeting_legacy_by_id: Optional[dict[str, str]] = None,
        user_legacy_by_id: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        doc = dict(row or {})
        client_id = str(doc.get("client_id") or "").strip()
        legacy_client_id = client_legacy_by_id.get(client_id) or (client_id if _is_uuid(client_id) else "")
        if not legacy_client_id:
            return None
        meeting_id = str(doc.get("meeting_id") or "").strip()
        legacy_meeting_id = (meeting_legacy_by_id or {}).get(meeting_id) or (meeting_id if _is_uuid(meeting_id) else "")
        if not legacy_meeting_id:
            return None
        account_manager_user_id = str(doc.pop("account_manager_user_id", "") or "").strip()
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = legacy_client_id
        doc["meeting_id"] = legacy_meeting_id
        doc["account_manager_id"] = (user_legacy_by_id or {}).get(account_manager_user_id) or account_manager_user_id or None
        doc["total_score"] = _safe_int(doc.get("total_score"), 0)
        doc["dimensions"] = dict(doc.get("dimensions") or {})
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def list_tickets(
        self,
        tenant_legacy_id: str,
        *,
        meeting_legacy_id: Optional[str] = None,
        client_legacy_id: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("tickets"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        filters: dict[str, str] = {
            "tenant_id": f"eq.{target_tenant_id}",
            "is_deleted": "eq.false",
        }
        if meeting_legacy_id:
            target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id)
            if not target_meeting_id:
                return []
            filters["meeting_id"] = f"eq.{target_meeting_id}"
        if client_legacy_id:
            target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
            if not target_client_id:
                return []
            filters["client_id"] = f"eq.{target_client_id}"
        rows = await self._safe_select(
            "tickets",
            select="*",
            filters=filters,
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        client_legacy_by_id = await self._load_client_legacy_map(
            [str(row.get("client_id") or "").strip() for row in rows if str(row.get("client_id") or "").strip()]
        )
        meeting_legacy_by_id = await self._load_meeting_legacy_map(
            [str(row.get("meeting_id") or "").strip() for row in rows if str(row.get("meeting_id") or "").strip()]
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            doc = self._ticket_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id)
            if doc:
                out.append(doc)
        return out

    async def get_ticket(self, tenant_legacy_id: str, ticket_legacy_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("tickets"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "tickets",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "legacy_source_id": f"eq.{ticket_legacy_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows and _is_uuid(ticket_legacy_id):
            rows = await self._safe_select(
                "tickets",
                select="*",
                filters={"tenant_id": f"eq.{target_tenant_id}", "id": f"eq.{ticket_legacy_id}", "is_deleted": "eq.false"},
                limit=1,
            )
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        meeting_legacy_by_id = await self._load_meeting_legacy_map([str(row.get("meeting_id") or "").strip()])
        return self._ticket_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id)

    async def resolve_target_ticket_id(self, tenant_legacy_id: str, ticket_legacy_id: str) -> Optional[str]:
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        rows = await self._safe_select(
            "tickets",
            select="id,legacy_source_id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "or": f"(legacy_source_id.eq.{ticket_legacy_id},id.eq.{ticket_legacy_id})",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return str((rows[0] or {}).get("id") or "").strip() or None

    async def upsert_ticket(self, tenant_legacy_id: str, doc: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        ticket_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        target_ticket_id = await self.resolve_target_ticket_id(tenant_legacy_id, ticket_legacy_id) if ticket_legacy_id else None
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, str((doc or {}).get("client_id") or "").strip())
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, str((doc or {}).get("meeting_id") or "").strip())
        if not target_client_id or not target_meeting_id:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "meeting_id": target_meeting_id,
            "legacy_source_id": ticket_legacy_id or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "runtime"),
            "department": str((doc or {}).get("department") or "Other"),
            "title": str((doc or {}).get("title") or "Ticket"),
            "description": (doc or {}).get("description"),
            "priority": str((doc or {}).get("priority") or "medium"),
            "status": str((doc or {}).get("status") or "open"),
            "external_id": (doc or {}).get("external_id"),
            "external_url": (doc or {}).get("external_url"),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        if target_ticket_id:
            result = await self._request(
                "PATCH",
                "tickets",
                params={"id": f"eq.{target_ticket_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "tickets",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        meeting_legacy_by_id = await self._load_meeting_legacy_map([str(row.get("meeting_id") or "").strip()])
        return self._ticket_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id)

    async def soft_delete_tickets_for_client(self, tenant_legacy_id: str, client_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return False
        await self._request(
            "PATCH",
            "tickets",
            params={"tenant_id": f"eq.{target_tenant_id}", "client_id": f"eq.{target_client_id}", "is_deleted": "eq.false"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def soft_delete_tickets_for_meeting(self, tenant_legacy_id: str, meeting_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id)
        if not target_tenant_id or not target_meeting_id:
            return False
        await self._request(
            "PATCH",
            "tickets",
            params={"tenant_id": f"eq.{target_tenant_id}", "meeting_id": f"eq.{target_meeting_id}", "is_deleted": "eq.false"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def get_latest_qa_scorecard(self, tenant_legacy_id: str, meeting_legacy_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("qa_scorecards"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id)
        if not target_tenant_id or not target_meeting_id:
            return None
        rows = await self._safe_select(
            "qa_scorecards",
            select="*",
            filters={"tenant_id": f"eq.{target_tenant_id}", "meeting_id": f"eq.{target_meeting_id}", "is_deleted": "eq.false"},
            order="created_at.desc",
            limit=1,
        )
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        meeting_legacy_by_id = await self._load_meeting_legacy_map([str(row.get("meeting_id") or "").strip()])
        user_legacy_by_id = await self._load_user_legacy_map([str(row.get("account_manager_user_id") or "").strip()])
        return self._qa_scorecard_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id, user_legacy_by_id)

    async def create_qa_scorecard(self, tenant_legacy_id: str, doc: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, str((doc or {}).get("client_id") or "").strip())
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, str((doc or {}).get("meeting_id") or "").strip())
        account_manager_user_id = await self.resolve_target_user_id(str((doc or {}).get("account_manager_id") or "").strip())
        if not target_client_id or not target_meeting_id:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "meeting_id": target_meeting_id,
            "account_manager_user_id": account_manager_user_id,
            "legacy_source_id": str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip() or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "runtime"),
            "account_manager_name": (doc or {}).get("account_manager_name"),
            "total_score": _safe_int((doc or {}).get("total_score"), 0),
            "dimensions": dict((doc or {}).get("dimensions") or {}),
            "feedback": (doc or {}).get("feedback"),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        result = await self._request(
            "POST",
            "qa_scorecards",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        meeting_legacy_by_id = await self._load_meeting_legacy_map([str(row.get("meeting_id") or "").strip()])
        user_legacy_by_id = await self._load_user_legacy_map([str(row.get("account_manager_user_id") or "").strip()])
        return self._qa_scorecard_row_to_doc(row, tenant_legacy_id, client_legacy_by_id, meeting_legacy_by_id, user_legacy_by_id)

    async def soft_delete_qa_scorecards_for_client(self, tenant_legacy_id: str, client_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return False
        await self._request(
            "PATCH",
            "qa_scorecards",
            params={"tenant_id": f"eq.{target_tenant_id}", "client_id": f"eq.{target_client_id}", "is_deleted": "eq.false"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    async def soft_delete_qa_scorecards_for_meeting(self, tenant_legacy_id: str, meeting_legacy_id: str) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_meeting_id = await self.resolve_target_meeting_id(tenant_legacy_id, meeting_legacy_id)
        if not target_tenant_id or not target_meeting_id:
            return False
        await self._request(
            "PATCH",
            "qa_scorecards",
            params={"tenant_id": f"eq.{target_tenant_id}", "meeting_id": f"eq.{target_meeting_id}", "is_deleted": "eq.false"},
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    def _tenant_file_row_to_doc(self, row: dict[str, Any], tenant_legacy_id: str) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["size_bytes"] = _safe_int(doc.get("size_bytes"), 0)
        doc["extracted_chars"] = _safe_int(doc.get("extracted_chars"), 0)
        doc["storage"] = dict(doc.get("storage") or {})
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def list_tenant_files(self, tenant_legacy_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if not self.is_enabled_for("tenant_files"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        rows = await self._safe_select(
            "tenant_files",
            select="*",
            filters={"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        return [self._tenant_file_row_to_doc(row, tenant_legacy_id) for row in rows]

    async def create_tenant_file(self, tenant_legacy_id: str, doc: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "legacy_source_id": str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip() or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "runtime"),
            "purpose": str((doc or {}).get("purpose") or "documentation"),
            "filename": (doc or {}).get("filename"),
            "mime_type": (doc or {}).get("mime_type"),
            "size_bytes": _safe_int((doc or {}).get("size_bytes"), 0),
            "storage": dict((doc or {}).get("storage") or {}),
            "extracted_text": (doc or {}).get("extracted_text"),
            "extracted_chars": _safe_int((doc or {}).get("extracted_chars"), 0),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        result = await self._request(
            "POST",
            "tenant_files",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._tenant_file_row_to_doc(rows[0], tenant_legacy_id)

    def _integration_row_to_doc(self, row: dict[str, Any], tenant_legacy_id: str) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or doc.get("platform") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["metadata"] = dict(doc.get("metadata") or {})
        doc["credentials_encrypted"] = dict(doc.get("credentials_encrypted") or {})
        for key in ("legacy_source_id", "legacy_source_kind", "id", "created_by", "is_deleted", "vault_secret_ref", "oauth_connection_ref"):
            doc.pop(key, None)
        return doc

    async def list_tenant_integrations(self, tenant_legacy_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.is_enabled_for("integrations"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        rows = await self._safe_select(
            "tenant_integrations",
            select="*",
            filters={"tenant_id": f"eq.{target_tenant_id}", "is_deleted": "eq.false"},
            order="platform.asc",
            limit=limit,
        )
        return [self._integration_row_to_doc(row, tenant_legacy_id) for row in (rows or [])]

    async def get_tenant_integration(self, tenant_legacy_id: str, platform: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("integrations"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        normalized_platform = str(platform or "").strip().lower()
        if not target_tenant_id or not normalized_platform:
            return None
        rows = await self._safe_select(
            "tenant_integrations",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "platform": f"eq.{normalized_platform}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return self._integration_row_to_doc(rows[0], tenant_legacy_id)

    async def upsert_tenant_integration(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        platform = str((doc or {}).get("platform") or "").strip().lower()
        if not target_tenant_id or not platform:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "platform": platform,
            "label": str((doc or {}).get("label") or platform).strip() or platform,
            "status": str((doc or {}).get("status") or "not_connected").strip() or "not_connected",
            "last_synced_at": (doc or {}).get("last_synced_at"),
            "last_error": (doc or {}).get("last_error"),
            "metadata": dict((doc or {}).get("metadata") or {}),
            "vault_secret_ref": (doc or {}).get("vault_secret_ref"),
            "oauth_connection_ref": (doc or {}).get("oauth_connection_ref"),
            "is_deleted": False,
        }
        existing_rows = await self._safe_select(
            "tenant_integrations",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "platform": f"eq.{platform}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if existing_rows is None:
            return None
        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            if not row_id:
                return None
            result = await self._request(
                "PATCH",
                "tenant_integrations",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "tenant_integrations",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._integration_row_to_doc(rows[0], tenant_legacy_id)

    async def mirror_tenant_integration(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        if not self.is_mirror_enabled_for("integrations"):
            return {"attempted": False, "ok": False, "reason": "disabled"}

        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        platform = str((doc or {}).get("platform") or "").strip().lower()
        if not target_tenant_id or not platform:
            return {"attempted": False, "ok": False, "reason": "tenant_or_platform_not_mapped"}

        payload = {
            "tenant_id": target_tenant_id,
            "platform": platform,
            "label": str((doc or {}).get("label") or platform).strip() or platform,
            "status": str((doc or {}).get("status") or "not_connected").strip() or "not_connected",
            "last_synced_at": (doc or {}).get("last_synced_at"),
            "last_error": (doc or {}).get("last_error"),
            "metadata": dict((doc or {}).get("metadata") or {}),
            "vault_secret_ref": (doc or {}).get("vault_secret_ref"),
            "oauth_connection_ref": (doc or {}).get("oauth_connection_ref"),
            "is_deleted": False,
        }

        existing_rows = await self._safe_select(
            "tenant_integrations",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "platform": f"eq.{platform}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if existing_rows is None:
            raise RuntimeError("tenant_integrations mirror preflight failed")

        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            if not row_id:
                raise RuntimeError("tenant_integrations mirror target row missing id")
            result = await self._request(
                "PATCH",
                "tenant_integrations",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
            return {
                "attempted": True,
                "ok": True,
                "mode": "update",
                "reason": reason,
                "target_tenant_id": target_tenant_id,
                "platform": platform,
                "result": result,
            }

        result = await self._request(
            "POST",
            "tenant_integrations",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        return {
            "attempted": True,
            "ok": True,
            "mode": "insert",
            "reason": reason,
            "target_tenant_id": target_tenant_id,
            "platform": platform,
            "result": result,
        }

    async def safe_mirror_tenant_integration(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        try:
            return await self.mirror_tenant_integration(tenant_legacy_id, doc, reason=reason)
        except Exception as exc:
            logger.warning(
                "tenant_integrations mirror failed for tenant %s platform %s (%s): %s",
                tenant_legacy_id,
                str((doc or {}).get("platform") or "").strip(),
                reason or "unknown",
                exc,
            )
            return {"attempted": True, "ok": False, "reason": reason or "unknown", "error": str(exc)}

    async def soft_delete_tenant_integration(
        self,
        tenant_legacy_id: str,
        platform: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        if not self.is_mirror_enabled_for("integrations"):
            return {"attempted": False, "ok": False, "reason": "disabled"}

        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        normalized_platform = str(platform or "").strip().lower()
        if not target_tenant_id or not normalized_platform:
            return {"attempted": False, "ok": False, "reason": "tenant_or_platform_not_mapped"}

        result = await self._request(
            "PATCH",
            "tenant_integrations",
            params={
                "tenant_id": f"eq.{target_tenant_id}",
                "platform": f"eq.{normalized_platform}",
                "is_deleted": "eq.false",
            },
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=representation"),
        )
        return {
            "attempted": True,
            "ok": True,
            "mode": "soft_delete",
            "reason": reason,
            "target_tenant_id": target_tenant_id,
            "platform": normalized_platform,
            "result": result,
        }

    async def safe_soft_delete_tenant_integration(
        self,
        tenant_legacy_id: str,
        platform: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        try:
            return await self.soft_delete_tenant_integration(tenant_legacy_id, platform, reason=reason)
        except Exception as exc:
            logger.warning(
                "tenant_integrations soft delete failed for tenant %s platform %s (%s): %s",
                tenant_legacy_id,
                platform,
                reason or "unknown",
                exc,
            )
            return {"attempted": True, "ok": False, "reason": reason or "unknown", "error": str(exc)}

    def _client_binding_row_to_doc(self, row: dict[str, Any], tenant_legacy_id: str, client_legacy_id: str) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or doc.get("platform") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = client_legacy_id
        doc["enabled"] = bool(doc.get("enabled", True))
        doc["external_ids"] = dict(doc.get("external_ids") or {})
        doc["config"] = dict(doc.get("config") or {})
        for key in ("legacy_source_id", "legacy_source_kind", "id", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def list_client_bindings(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("client_bindings"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return []
        rows = await self._safe_select(
            "client_integration_bindings",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            order="platform.asc",
            limit=limit,
        )
        return [self._client_binding_row_to_doc(row, tenant_legacy_id, client_legacy_id) for row in (rows or [])]

    async def get_client_binding(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        platform: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("client_bindings"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        normalized_platform = str(platform or "").strip().lower()
        if not target_tenant_id or not target_client_id or not normalized_platform:
            return None
        rows = await self._safe_select(
            "client_integration_bindings",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "platform": f"eq.{normalized_platform}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return self._client_binding_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id)

    async def list_tenant_client_bindings(
        self,
        tenant_legacy_id: str,
        *,
        platform: Optional[str] = None,
        enabled: Optional[bool] = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("client_bindings"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        filters: dict[str, str] = {
            "tenant_id": f"eq.{target_tenant_id}",
            "is_deleted": "eq.false",
        }
        normalized_platform = str(platform or "").strip().lower()
        if normalized_platform:
            filters["platform"] = f"eq.{normalized_platform}"
        if enabled is not None:
            filters["enabled"] = f"eq.{str(bool(enabled)).lower()}"
        rows = await self._safe_select(
            "client_integration_bindings",
            select="*",
            filters=filters,
            order="updated_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        client_legacy_by_id = await self._load_client_legacy_map(
            [str(row.get("client_id") or "").strip() for row in rows if str(row.get("client_id") or "").strip()]
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            client_id = str((row or {}).get("client_id") or "").strip()
            client_legacy_id = client_legacy_by_id.get(client_id) or (client_id if _is_uuid(client_id) else "")
            if not client_legacy_id:
                continue
            out.append(self._client_binding_row_to_doc(row, tenant_legacy_id, client_legacy_id))
        return out

    async def upsert_client_binding(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        platform = str((doc or {}).get("platform") or "").strip().lower()
        if not target_tenant_id or not target_client_id or not platform:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "platform": platform,
            "enabled": bool((doc or {}).get("enabled", True)),
            "external_ids": dict((doc or {}).get("external_ids") or {}),
            "config": dict((doc or {}).get("config") or {}),
            "is_deleted": False,
        }
        existing_rows = await self._safe_select(
            "client_integration_bindings",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "platform": f"eq.{platform}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if existing_rows is None:
            return None
        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            if not row_id:
                return None
            result = await self._request(
                "PATCH",
                "client_integration_bindings",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "client_integration_bindings",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._client_binding_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id)

    async def soft_delete_client_binding(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        platform: str,
    ) -> bool:
        if not self.service_configured:
            return False
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        normalized_platform = str(platform or "").strip().lower()
        if not target_tenant_id or not target_client_id or not normalized_platform:
            return False
        await self._request(
            "PATCH",
            "client_integration_bindings",
            params={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "platform": f"eq.{normalized_platform}",
                "is_deleted": "eq.false",
            },
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=minimal"),
        )
        return True

    def _clickup_sync_state_row_to_doc(self, row: dict[str, Any], tenant_legacy_id: str, user_legacy_id: str) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("id") or f"{tenant_legacy_id}:{user_legacy_id}")
        doc["tenant_id"] = tenant_legacy_id
        doc["user_id"] = user_legacy_id
        doc["metadata"] = dict(doc.get("metadata") or {})
        for key in ("id", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    def _clickup_sync_log_row_to_doc(self, row: dict[str, Any], tenant_legacy_id: str, user_legacy_id: str) -> dict[str, Any]:
        doc = dict(row or {})
        details = dict(doc.pop("details", {}) or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["user_id"] = user_legacy_id
        doc["run_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["created"] = _safe_int(doc.pop("created_count", 0), 0)
        doc["updated"] = _safe_int(doc.pop("updated_count", 0), 0)
        doc["paused"] = _safe_int(doc.pop("paused_count", 0), 0)
        doc["assigned_found"] = _safe_int(doc.get("assigned_found"), 0)
        for key, value in details.items():
            if key not in doc:
                doc[key] = value
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def get_clickup_client_sync_state(self, tenant_legacy_id: str, user_legacy_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("clickup_sync"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        if not target_tenant_id or not target_user_id:
            return None
        rows = await self._safe_select(
            "clickup_client_sync_state",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "user_id": f"eq.{target_user_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return self._clickup_sync_state_row_to_doc(rows[0], tenant_legacy_id, user_legacy_id)

    async def upsert_clickup_client_sync_state(
        self,
        tenant_legacy_id: str,
        user_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        if not target_tenant_id or not target_user_id:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "user_id": target_user_id,
            "running": bool((doc or {}).get("running", False)),
            "started_at": (doc or {}).get("started_at"),
            "finished_at": (doc or {}).get("finished_at"),
            "last_success_at": (doc or {}).get("last_success_at"),
            "last_error": (doc or {}).get("last_error"),
            "last_run_id": str((doc or {}).get("last_run_id") or "").strip() or None,
            "metadata": dict((doc or {}).get("metadata") or {}),
            "is_deleted": False,
        }
        existing_rows = await self._safe_select(
            "clickup_client_sync_state",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "user_id": f"eq.{target_user_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            result = await self._request(
                "PATCH",
                "clickup_client_sync_state",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "clickup_client_sync_state",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._clickup_sync_state_row_to_doc(rows[0], tenant_legacy_id, user_legacy_id)

    async def get_clickup_client_sync_log(
        self,
        tenant_legacy_id: str,
        user_legacy_id: str,
        run_legacy_id: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("clickup_sync"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        if not target_tenant_id or not target_user_id or not str(run_legacy_id or "").strip():
            return None
        rows = await self._safe_select(
            "clickup_client_sync_logs",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "user_id": f"eq.{target_user_id}",
                "legacy_source_id": f"eq.{run_legacy_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return self._clickup_sync_log_row_to_doc(rows[0], tenant_legacy_id, user_legacy_id)

    async def create_clickup_client_sync_log(
        self,
        tenant_legacy_id: str,
        user_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        run_legacy_id = str((doc or {}).get("run_id") or (doc or {}).get("_id") or "").strip()
        if not target_tenant_id or not target_user_id or not run_legacy_id:
            return None
        payload = {
            "tenant_id": target_tenant_id,
            "user_id": target_user_id,
            "legacy_source_id": run_legacy_id,
            "legacy_source_kind": "runtime",
            "ok": bool((doc or {}).get("ok", False)),
            "started_at": (doc or {}).get("started_at"),
            "finished_at": (doc or {}).get("finished_at"),
            "list_id": (doc or {}).get("list_id"),
            "list_source": (doc or {}).get("list_source"),
            "created_count": _safe_int((doc or {}).get("created"), 0),
            "updated_count": _safe_int((doc or {}).get("updated"), 0),
            "paused_count": _safe_int((doc or {}).get("paused"), 0),
            "assigned_found": _safe_int((doc or {}).get("assigned_found"), 0),
            "error": (doc or {}).get("error"),
            "details": {
                "debug_sample_account_managers": list((doc or {}).get("debug_sample_account_managers") or []),
                "debug_sample_custom_field_names": list((doc or {}).get("debug_sample_custom_field_names") or []),
            },
            "is_deleted": False,
        }
        existing_rows = await self._safe_select(
            "clickup_client_sync_logs",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "user_id": f"eq.{target_user_id}",
                "legacy_source_id": f"eq.{run_legacy_id}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            result = await self._request(
                "PATCH",
                "clickup_client_sync_logs",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            result = await self._request(
                "POST",
                "clickup_client_sync_logs",
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._clickup_sync_log_row_to_doc(rows[0], tenant_legacy_id, user_legacy_id)

    def _ai_visibility_config_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_id: str,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = client_legacy_id
        doc["keywords"] = list(doc.get("keywords") or [])
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    def _ai_visibility_run_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_id: str,
        config_legacy_id: str,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = client_legacy_id
        doc["config_id"] = config_legacy_id
        doc["parsed"] = dict(doc.get("parsed") or {})
        doc["hit"] = bool(doc.get("hit", False))
        doc["hit_brand"] = bool(doc.get("hit_brand", False))
        doc["hit_domain"] = bool(doc.get("hit_domain", False))
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    def _ai_visibility_scan_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_id: str,
        config_legacy_id: str,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = client_legacy_id
        doc["config_id"] = config_legacy_id
        doc["providers"] = dict(doc.get("providers") or {})
        doc["share_of_voice"] = dict(doc.get("share_of_voice") or {})
        doc["platform_rankings"] = dict(doc.get("platform_rankings") or {})
        doc["themes"] = list(doc.get("themes") or [])
        doc["competitors"] = list(doc.get("competitors") or [])
        doc["content_intelligence"] = dict(doc.get("content_intelligence") or {})
        doc["growth_engine"] = dict(doc.get("growth_engine") or {})
        doc["territory_intelligence"] = dict(doc.get("territory_intelligence") or {})
        doc["data_confidence"] = dict(doc.get("data_confidence") or {})
        doc["total"] = _safe_int(doc.get("total"), 0)
        doc["hits"] = _safe_int(doc.get("hits"), 0)
        doc["prompts_total"] = _safe_int(doc.get("prompts_total"), 0)
        doc["overall_visibility_score"] = _safe_float(doc.get("overall_visibility_score"), 0.0)
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    def _ai_territory_event_row_to_doc(
        self,
        row: dict[str, Any],
        tenant_legacy_id: str,
        client_legacy_id: str,
        user_legacy_by_id: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        doc = dict(row or {})
        account_manager_user_id = str(doc.pop("account_manager_user_id", "") or "").strip()
        doc["_id"] = str(doc.get("legacy_source_id") or doc.get("id") or "")
        doc["tenant_id"] = tenant_legacy_id
        doc["client_id"] = client_legacy_id
        doc["account_manager_id"] = (user_legacy_by_id or {}).get(account_manager_user_id) or account_manager_user_id or None
        doc["explain"] = dict(doc.get("explain") or {})
        for key in ("id", "legacy_source_id", "legacy_source_kind", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def _load_ai_visibility_config_legacy_map(self, config_ids: Sequence[str]) -> dict[str, str]:
        clean_ids = [str(config_id).strip() for config_id in config_ids if str(config_id).strip()]
        if not clean_ids:
            return {}
        rows = await self._safe_select(
            "ai_visibility_configs",
            select="id,legacy_source_id",
            filters={"id": f"in.({','.join(clean_ids)})"},
            limit=len(clean_ids),
        )
        if not rows:
            return {}
        return {
            str(row.get("id") or ""): str(row.get("legacy_source_id") or row.get("id") or "")
            for row in rows
            if str(row.get("id") or "").strip()
        }

    async def resolve_target_ai_visibility_config_id(
        self,
        tenant_legacy_id: str,
        config_legacy_id: str,
    ) -> Optional[str]:
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id or not str(config_legacy_id or "").strip():
            return None
        rows = await self._safe_select(
            "ai_visibility_configs",
            select="id,legacy_source_id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "or": f"(legacy_source_id.eq.{config_legacy_id},id.eq.{config_legacy_id})",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return str((rows[0] or {}).get("id") or "").strip() or None

    async def get_ai_visibility_config_for_client(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("ai_visibility"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return None
        rows = await self._safe_select(
            "ai_visibility_configs",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            order="created_at.desc",
            limit=1,
        )
        if not rows:
            return None
        return self._ai_visibility_config_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id)

    async def list_ai_visibility_configs(
        self,
        tenant_legacy_id: str,
        *,
        client_legacy_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("ai_visibility"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        filters: dict[str, str] = {
            "tenant_id": f"eq.{target_tenant_id}",
            "is_deleted": "eq.false",
        }
        client_legacy_by_id: dict[str, str] = {}
        if client_legacy_id:
            target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
            if not target_client_id:
                return []
            filters["client_id"] = f"eq.{target_client_id}"
        rows = await self._safe_select(
            "ai_visibility_configs",
            select="*",
            filters=filters,
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        if client_legacy_id:
            client_legacy_by_id = {
                str((rows[0] or {}).get("client_id") or "").strip(): client_legacy_id,
            }
        else:
            client_legacy_by_id = await self._load_client_legacy_map(
                [str(row.get("client_id") or "").strip() for row in rows if str(row.get("client_id") or "").strip()]
            )
        out: list[dict[str, Any]] = []
        for row in rows:
            target_client_id = str((row or {}).get("client_id") or "").strip()
            resolved_client_legacy_id = client_legacy_by_id.get(target_client_id) or (target_client_id if _is_uuid(target_client_id) else "")
            if not resolved_client_legacy_id:
                continue
            out.append(self._ai_visibility_config_row_to_doc(row, tenant_legacy_id, resolved_client_legacy_id))
        return out

    async def get_ai_visibility_config(
        self,
        tenant_legacy_id: str,
        config_legacy_id: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("ai_visibility"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id or not str(config_legacy_id or "").strip():
            return None
        rows = await self._safe_select(
            "ai_visibility_configs",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "or": f"(legacy_source_id.eq.{config_legacy_id},id.eq.{config_legacy_id})",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        row = rows[0] or {}
        client_legacy_by_id = await self._load_client_legacy_map([str(row.get("client_id") or "").strip()])
        client_id = str(row.get("client_id") or "").strip()
        client_legacy_id = client_legacy_by_id.get(client_id) or (client_id if _is_uuid(client_id) else "")
        if not client_legacy_id:
            return None
        return self._ai_visibility_config_row_to_doc(row, tenant_legacy_id, client_legacy_id)

    async def upsert_ai_visibility_config(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        client_legacy_id = str((doc or {}).get("client_id") or "").strip()
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return None
        config_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        target_config_id = (
            await self.resolve_target_ai_visibility_config_id(tenant_legacy_id, config_legacy_id)
            if config_legacy_id
            else None
        )
        payload = {
            "tenant_id": target_tenant_id,
            "client_id": target_client_id,
            "legacy_source_id": config_legacy_id or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "mongo"),
            "market": str((doc or {}).get("market") or "").strip(),
            "market_override": (doc or {}).get("market_override"),
            "keywords": list((doc or {}).get("keywords") or []),
            "brand_override": (doc or {}).get("brand_override"),
            "domain_override": (doc or {}).get("domain_override"),
            "enabled": bool((doc or {}).get("enabled", True)),
            "created_at": (doc or {}).get("created_at"),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        if target_config_id:
            result = await self._request(
                "PATCH",
                "ai_visibility_configs",
                params={"id": f"eq.{target_config_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
        else:
            existing_rows = await self._safe_select(
                "ai_visibility_configs",
                select="id",
                filters={
                    "tenant_id": f"eq.{target_tenant_id}",
                    "client_id": f"eq.{target_client_id}",
                    "is_deleted": "eq.false",
                },
                limit=1,
            )
            if existing_rows:
                row_id = str((existing_rows[0] or {}).get("id") or "").strip()
                result = await self._request(
                    "PATCH",
                    "ai_visibility_configs",
                    params={"id": f"eq.{row_id}"},
                    payload=payload,
                    headers=self._write_headers(prefer="return=representation"),
                )
            else:
                result = await self._request(
                    "POST",
                    "ai_visibility_configs",
                    payload=payload,
                    headers=self._write_headers(prefer="return=representation"),
                )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._ai_visibility_config_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id)

    async def list_ai_visibility_runs(
        self,
        tenant_legacy_id: str,
        config_legacy_id: str,
        *,
        scan_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("ai_visibility"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_config_id = await self.resolve_target_ai_visibility_config_id(tenant_legacy_id, config_legacy_id)
        if not target_tenant_id or not target_config_id:
            return []
        filters: dict[str, str] = {
            "tenant_id": f"eq.{target_tenant_id}",
            "config_id": f"eq.{target_config_id}",
            "is_deleted": "eq.false",
        }
        normalized_scan_id = str(scan_id or "").strip()
        if normalized_scan_id:
            filters["scan_id"] = f"eq.{normalized_scan_id}"
        rows = await self._safe_select(
            "ai_visibility_runs",
            select="*",
            filters=filters,
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        config_legacy_map = await self._load_ai_visibility_config_legacy_map([target_config_id])
        client_legacy_by_id = await self._load_client_legacy_map(
            [str(row.get("client_id") or "").strip() for row in rows if str(row.get("client_id") or "").strip()]
        )
        resolved_config_legacy_id = config_legacy_map.get(target_config_id) or config_legacy_id
        out: list[dict[str, Any]] = []
        for row in rows:
            target_client_id = str((row or {}).get("client_id") or "").strip()
            resolved_client_legacy_id = client_legacy_by_id.get(target_client_id) or (target_client_id if _is_uuid(target_client_id) else "")
            if not resolved_client_legacy_id:
                continue
            out.append(
                self._ai_visibility_run_row_to_doc(
                    row,
                    tenant_legacy_id,
                    resolved_client_legacy_id,
                    resolved_config_legacy_id,
                )
            )
        return out

    async def create_ai_visibility_run(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        client_legacy_id = str((doc or {}).get("client_id") or "").strip()
        config_legacy_id = str((doc or {}).get("config_id") or "").strip()
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        target_config_id = await self.resolve_target_ai_visibility_config_id(tenant_legacy_id, config_legacy_id)
        if not target_tenant_id or not target_client_id or not target_config_id:
            return None
        run_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        payload = {
            "tenant_id": target_tenant_id,
            "config_id": target_config_id,
            "client_id": target_client_id,
            "legacy_source_id": run_legacy_id or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "mongo"),
            "scan_id": str((doc or {}).get("scan_id") or "").strip() or None,
            "market": str((doc or {}).get("market") or "").strip(),
            "keyword": str((doc or {}).get("keyword") or "").strip(),
            "theme": (doc or {}).get("theme"),
            "prompt_kind": (doc or {}).get("prompt_kind"),
            "provider": str((doc or {}).get("provider") or "").strip(),
            "prompt": str((doc or {}).get("prompt") or ""),
            "response_text": str((doc or {}).get("response_text") or ""),
            "parsed": dict((doc or {}).get("parsed") or {}),
            "hit": bool((doc or {}).get("hit", False)),
            "hit_brand": bool((doc or {}).get("hit_brand", False)),
            "hit_domain": bool((doc or {}).get("hit_domain", False)),
            "created_at": (doc or {}).get("created_at"),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        result = await self._request(
            "POST",
            "ai_visibility_runs",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._ai_visibility_run_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id, config_legacy_id)

    async def get_latest_ai_visibility_scan(
        self,
        tenant_legacy_id: str,
        config_legacy_id: str,
        client_legacy_id: str,
        *,
        exclude_scan_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("ai_visibility"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        target_config_id = await self.resolve_target_ai_visibility_config_id(tenant_legacy_id, config_legacy_id)
        if not target_tenant_id or not target_client_id or not target_config_id:
            return None
        filters = {
            "tenant_id": f"eq.{target_tenant_id}",
            "config_id": f"eq.{target_config_id}",
            "client_id": f"eq.{target_client_id}",
            "is_deleted": "eq.false",
        }
        if str(exclude_scan_id or "").strip():
            filters["scan_id"] = f"neq.{exclude_scan_id}"
        rows = await self._safe_select(
            "ai_visibility_scans",
            select="*",
            filters=filters,
            order="created_at.desc",
            limit=1,
        )
        if not rows:
            return None
        return self._ai_visibility_scan_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id, config_legacy_id)

    async def create_ai_visibility_scan(
        self,
        tenant_legacy_id: str,
        doc: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.service_configured:
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        client_legacy_id = str((doc or {}).get("client_id") or "").strip()
        config_legacy_id = str((doc or {}).get("config_id") or "").strip()
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        target_config_id = await self.resolve_target_ai_visibility_config_id(tenant_legacy_id, config_legacy_id)
        if not target_tenant_id or not target_client_id or not target_config_id:
            return None
        scan_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
        payload = {
            "tenant_id": target_tenant_id,
            "config_id": target_config_id,
            "client_id": target_client_id,
            "legacy_source_id": scan_legacy_id or None,
            "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "mongo"),
            "scan_id": str((doc or {}).get("scan_id") or "").strip() or None,
            "market": str((doc or {}).get("market") or "").strip(),
            "brand": str((doc or {}).get("brand") or "").strip(),
            "domain": str((doc or {}).get("domain") or "").strip(),
            "providers": dict((doc or {}).get("providers") or {}),
            "total": _safe_int((doc or {}).get("total"), 0),
            "hits": _safe_int((doc or {}).get("hits"), 0),
            "overall_visibility_score": _safe_float((doc or {}).get("overall_visibility_score"), 0.0),
            "share_of_voice": dict((doc or {}).get("share_of_voice") or {}),
            "platform_rankings": dict((doc or {}).get("platform_rankings") or {}),
            "themes": list((doc or {}).get("themes") or []),
            "prompts_total": _safe_int((doc or {}).get("prompts_total"), 0),
            "competitors": list((doc or {}).get("competitors") or []),
            "content_intelligence": dict((doc or {}).get("content_intelligence") or {}),
            "growth_engine": dict((doc or {}).get("growth_engine") or {}),
            "territory_intelligence": dict((doc or {}).get("territory_intelligence") or {}),
            "data_confidence": dict((doc or {}).get("data_confidence") or {}),
            "created_at": (doc or {}).get("created_at"),
            "updated_at": (doc or {}).get("updated_at"),
            "is_deleted": False,
        }
        result = await self._request(
            "POST",
            "ai_visibility_scans",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return None
        return self._ai_visibility_scan_row_to_doc(rows[0], tenant_legacy_id, client_legacy_id, config_legacy_id)

    async def list_ai_visibility_scans(
        self,
        tenant_legacy_id: str,
        config_legacy_id: str,
        *,
        client_legacy_id: Optional[str] = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("ai_visibility"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_config_id = await self.resolve_target_ai_visibility_config_id(tenant_legacy_id, config_legacy_id)
        if not target_tenant_id or not target_config_id:
            return []
        filters: dict[str, str] = {
            "tenant_id": f"eq.{target_tenant_id}",
            "config_id": f"eq.{target_config_id}",
            "is_deleted": "eq.false",
        }
        if client_legacy_id:
            target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
            if not target_client_id:
                return []
            filters["client_id"] = f"eq.{target_client_id}"
        rows = await self._safe_select(
            "ai_visibility_scans",
            select="*",
            filters=filters,
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        config_legacy_map = await self._load_ai_visibility_config_legacy_map([target_config_id])
        client_legacy_by_id = (
            {str((rows[0] or {}).get("client_id") or "").strip(): client_legacy_id}
            if client_legacy_id
            else await self._load_client_legacy_map(
                [str(row.get("client_id") or "").strip() for row in rows if str(row.get("client_id") or "").strip()]
            )
        )
        resolved_config_legacy_id = config_legacy_map.get(target_config_id) or config_legacy_id
        out: list[dict[str, Any]] = []
        for row in rows:
            target_client_id = str((row or {}).get("client_id") or "").strip()
            resolved_client_legacy_id = client_legacy_by_id.get(target_client_id) or (target_client_id if _is_uuid(target_client_id) else "")
            if not resolved_client_legacy_id:
                continue
            out.append(
                self._ai_visibility_scan_row_to_doc(
                    row,
                    tenant_legacy_id,
                    resolved_client_legacy_id,
                    resolved_config_legacy_id,
                )
            )
        return out

    async def list_ai_territory_events(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("ai_visibility"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id:
            return []
        rows = await self._safe_select(
            "ai_territory_events",
            select="*",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "client_id": f"eq.{target_client_id}",
                "is_deleted": "eq.false",
            },
            order="created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        user_legacy_by_id = await self._load_user_legacy_map(
            [str(row.get("account_manager_user_id") or "").strip() for row in rows if str(row.get("account_manager_user_id") or "").strip()]
        )
        return [
            self._ai_territory_event_row_to_doc(row, tenant_legacy_id, client_legacy_id, user_legacy_by_id)
            for row in rows
        ]

    async def create_ai_territory_events(
        self,
        tenant_legacy_id: str,
        client_legacy_id: str,
        docs: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not self.service_configured:
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_client_id = await self.resolve_target_client_id(tenant_legacy_id, client_legacy_id)
        if not target_tenant_id or not target_client_id or not docs:
            return []
        payload: list[dict[str, Any]] = []
        for doc in docs:
            account_manager_legacy_id = str((doc or {}).get("account_manager_id") or "").strip()
            target_account_manager_id = (
                await self.resolve_target_user_id(account_manager_legacy_id)
                if account_manager_legacy_id
                else None
            )
            event_legacy_id = str((doc or {}).get("_id") or (doc or {}).get("id") or "").strip()
            payload.append(
                {
                    "tenant_id": target_tenant_id,
                    "client_id": target_client_id,
                    "account_manager_user_id": target_account_manager_id,
                    "legacy_source_id": event_legacy_id or None,
                    "legacy_source_kind": str((doc or {}).get("legacy_source_kind") or "mongo"),
                    "kind": str((doc or {}).get("kind") or "").strip(),
                    "severity": str((doc or {}).get("severity") or "low").strip() or "low",
                    "title": str((doc or {}).get("title") or "").strip(),
                    "description": str((doc or {}).get("description") or ""),
                    "scan_id": str((doc or {}).get("scan_id") or "").strip() or None,
                    "explain": dict((doc or {}).get("explain") or {}),
                    "created_at": (doc or {}).get("created_at"),
                    "updated_at": (doc or {}).get("updated_at"),
                    "is_deleted": False,
                }
            )
        result = await self._request(
            "POST",
            "ai_territory_events",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        rows = result if isinstance(result, list) else [result]
        if not rows:
            return []
        user_legacy_by_id = await self._load_user_legacy_map(
            [str(row.get("account_manager_user_id") or "").strip() for row in rows if str(row.get("account_manager_user_id") or "").strip()]
        )
        return [
            self._ai_territory_event_row_to_doc(row, tenant_legacy_id, client_legacy_id, user_legacy_by_id)
            for row in rows
        ]

    def _user_oauth_row_to_doc(self, row: dict[str, Any], tenant_legacy_id: str, user_legacy_id: str) -> dict[str, Any]:
        doc = dict(row or {})
        doc["_id"] = str(doc.get("id") or f"{doc.get('provider') or 'oauth'}:{doc.get('platform') or ''}")
        doc["tenant_id"] = tenant_legacy_id
        doc["user_id"] = user_legacy_id
        doc["scopes"] = list(doc.get("scopes") or [])
        for key in ("id", "created_by", "is_deleted"):
            doc.pop(key, None)
        return doc

    async def get_user_oauth_account(
        self,
        tenant_legacy_id: str,
        user_legacy_id: str,
        provider: str,
        platform: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled_for("oauth_accounts"):
            return None
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        normalized_provider = str(provider or "").strip().lower()
        normalized_platform = str(platform or "").strip().lower()
        if not target_tenant_id or not target_user_id or not normalized_provider or not normalized_platform:
            return None
        rows = await self._safe_select(
            "user_oauth_accounts",
            select="id,tenant_id,user_id,provider,platform,account_email,external_account_id,scopes,last_synced_at,oauth_connection_ref,created_at,updated_at",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "user_id": f"eq.{target_user_id}",
                "provider": f"eq.{normalized_provider}",
                "platform": f"eq.{normalized_platform}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if not rows:
            return None
        return self._user_oauth_row_to_doc(rows[0], tenant_legacy_id, user_legacy_id)

    async def list_user_oauth_accounts(
        self,
        tenant_legacy_id: str,
        *,
        provider: Optional[str] = None,
        platform: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled_for("oauth_accounts"):
            return []
        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        if not target_tenant_id:
            return []
        filters = {
            "tenant_id": f"eq.{target_tenant_id}",
            "is_deleted": "eq.false",
        }
        normalized_provider = str(provider or "").strip().lower()
        normalized_platform = str(platform or "").strip().lower()
        if normalized_provider:
            filters["provider"] = f"eq.{normalized_provider}"
        if normalized_platform:
            filters["platform"] = f"eq.{normalized_platform}"
        rows = await self._safe_select(
            "user_oauth_accounts",
            select="id,tenant_id,user_id,provider,platform,account_email,external_account_id,scopes,last_synced_at,oauth_connection_ref,created_at,updated_at",
            filters=filters,
            order="updated_at.desc,created_at.desc",
            limit=limit,
        )
        if not rows:
            return []
        user_ids = [
            str((row or {}).get("user_id") or "").strip()
            for row in rows
            if str((row or {}).get("user_id") or "").strip()
        ]
        legacy_user_by_id = await self._load_user_legacy_map(user_ids)
        return [
            self._user_oauth_row_to_doc(
                row,
                tenant_legacy_id,
                legacy_user_by_id.get(str((row or {}).get("user_id") or "").strip())
                or str((row or {}).get("user_id") or "").strip(),
            )
            for row in rows
        ]

    async def mirror_user_oauth_account(
        self,
        tenant_legacy_id: str,
        user_legacy_id: str,
        doc: dict[str, Any],
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        if not self.is_mirror_enabled_for("oauth_accounts"):
            return {"attempted": False, "ok": False, "reason": "disabled"}

        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        provider = str((doc or {}).get("provider") or "").strip().lower()
        platform = str((doc or {}).get("platform") or "").strip().lower()
        if not target_tenant_id or not target_user_id or not provider or not platform:
            return {"attempted": False, "ok": False, "reason": "tenant_user_or_platform_not_mapped"}

        payload = {
            "tenant_id": target_tenant_id,
            "user_id": target_user_id,
            "provider": provider,
            "platform": platform,
            "account_email": (doc or {}).get("account_email"),
            "external_account_id": (doc or {}).get("external_account_id"),
            "scopes": list((doc or {}).get("scopes") or []),
            "last_synced_at": (doc or {}).get("last_synced_at"),
            "oauth_connection_ref": (doc or {}).get("oauth_connection_ref"),
            "is_deleted": False,
        }

        existing_rows = await self._safe_select(
            "user_oauth_accounts",
            select="id",
            filters={
                "tenant_id": f"eq.{target_tenant_id}",
                "user_id": f"eq.{target_user_id}",
                "provider": f"eq.{provider}",
                "platform": f"eq.{platform}",
                "is_deleted": "eq.false",
            },
            limit=1,
        )
        if existing_rows is None:
            raise RuntimeError("user_oauth_accounts mirror preflight failed")

        if existing_rows:
            row_id = str((existing_rows[0] or {}).get("id") or "").strip()
            if not row_id:
                raise RuntimeError("user_oauth_accounts mirror target row missing id")
            result = await self._request(
                "PATCH",
                "user_oauth_accounts",
                params={"id": f"eq.{row_id}"},
                payload=payload,
                headers=self._write_headers(prefer="return=representation"),
            )
            return {
                "attempted": True,
                "ok": True,
                "mode": "update",
                "reason": reason,
                "target_tenant_id": target_tenant_id,
                "target_user_id": target_user_id,
                "platform": platform,
                "result": result,
            }

        result = await self._request(
            "POST",
            "user_oauth_accounts",
            payload=payload,
            headers=self._write_headers(prefer="return=representation"),
        )
        return {
            "attempted": True,
            "ok": True,
            "mode": "insert",
            "reason": reason,
            "target_tenant_id": target_tenant_id,
            "target_user_id": target_user_id,
            "platform": platform,
            "result": result,
        }

    async def safe_mirror_user_oauth_account(
        self,
        tenant_legacy_id: str,
        user_legacy_id: str,
        doc: dict[str, Any],
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        try:
            return await self.mirror_user_oauth_account(tenant_legacy_id, user_legacy_id, doc, reason=reason)
        except Exception as exc:
            logger.warning(
                "user_oauth_accounts mirror failed for tenant %s user %s platform %s (%s): %s",
                tenant_legacy_id,
                user_legacy_id,
                str((doc or {}).get("platform") or "").strip(),
                reason or "unknown",
                exc,
            )
            return {"attempted": True, "ok": False, "reason": reason or "unknown", "error": str(exc)}

    async def soft_delete_user_oauth_account(
        self,
        tenant_legacy_id: str,
        user_legacy_id: str,
        provider: str,
        platform: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        if not self.is_mirror_enabled_for("oauth_accounts"):
            return {"attempted": False, "ok": False, "reason": "disabled"}

        target_tenant_id = await self.resolve_target_tenant_id(tenant_legacy_id)
        target_user_id = await self.resolve_target_user_id(user_legacy_id)
        normalized_provider = str(provider or "").strip().lower()
        normalized_platform = str(platform or "").strip().lower()
        if not target_tenant_id or not target_user_id or not normalized_provider or not normalized_platform:
            return {"attempted": False, "ok": False, "reason": "tenant_user_or_platform_not_mapped"}

        result = await self._request(
            "PATCH",
            "user_oauth_accounts",
            params={
                "tenant_id": f"eq.{target_tenant_id}",
                "user_id": f"eq.{target_user_id}",
                "provider": f"eq.{normalized_provider}",
                "platform": f"eq.{normalized_platform}",
                "is_deleted": "eq.false",
            },
            payload={"is_deleted": True},
            headers=self._write_headers(prefer="return=representation"),
        )
        return {
            "attempted": True,
            "ok": True,
            "mode": "soft_delete",
            "reason": reason,
            "target_tenant_id": target_tenant_id,
            "target_user_id": target_user_id,
            "platform": normalized_platform,
            "result": result,
        }

    async def safe_soft_delete_user_oauth_account(
        self,
        tenant_legacy_id: str,
        user_legacy_id: str,
        provider: str,
        platform: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        try:
            return await self.soft_delete_user_oauth_account(
                tenant_legacy_id,
                user_legacy_id,
                provider,
                platform,
                reason=reason,
            )
        except Exception as exc:
            logger.warning(
                "user_oauth_accounts soft delete failed for tenant %s user %s platform %s (%s): %s",
                tenant_legacy_id,
                user_legacy_id,
                platform,
                reason or "unknown",
                exc,
            )
            return {"attempted": True, "ok": False, "reason": reason or "unknown", "error": str(exc)}

    async def smoke_check(self, tenant_legacy_id: Optional[str] = None) -> dict[str, Any]:
        settings = self.settings
        summary: dict[str, Any] = {
            "enabled": bool(settings.get("enabled")),
            "service_configured": bool(settings.get("service_configured")),
            "url": str(settings.get("url") or ""),
            "db_schema": str(settings.get("db_schema") or "public"),
            "domains": list(settings.get("domains") or ()),
            "supported_domains": list(settings.get("supported_domains") or ()),
            "tenant_source_id": tenant_legacy_id,
            "target_tenant_id": None,
            "checks": [],
        }
        if not self.service_configured:
            return summary

        target_tenant_id = await self.resolve_target_tenant_id(str(tenant_legacy_id or ""))
        summary["target_tenant_id"] = target_tenant_id
        if tenant_legacy_id and not target_tenant_id:
            summary["checks"].append(
                {"domain": "tenants", "ok": False, "mode": "bridge", "reason": "tenant_not_mapped"}
            )
            return summary

        bridge_tenant = await self.get_tenant(str(tenant_legacy_id or "")) if tenant_legacy_id else None
        if bridge_tenant is not None:
            summary["checks"].append(
                {
                    "domain": "tenants",
                    "ok": True,
                    "mode": "bridge",
                    "slug": bridge_tenant.get("slug"),
                    "status": bridge_tenant.get("status"),
                }
            )

        bridged_client_id: Optional[str] = None

        if tenant_legacy_id and self.is_enabled_for("settings"):
            settings_doc = await self.get_tenant_settings(tenant_legacy_id)
            summary["checks"].append(
                {
                    "domain": "settings",
                    "ok": settings_doc is not None,
                    "mode": "bridge",
                    "present": settings_doc is not None,
                }
            )

        if tenant_legacy_id and self.is_enabled_for("domains"):
            tenant_domains = await self.list_tenant_domains(tenant_legacy_id, limit=5)
            summary["checks"].append(
                {
                    "domain": "domains",
                    "ok": True,
                    "mode": "bridge",
                    "count": len(tenant_domains),
                }
            )

        if tenant_legacy_id and self.is_enabled_for("clients"):
            clients = await self.list_clients(tenant_legacy_id, limit=1)
            bridged_client_id = str((clients[0] or {}).get("_id") or "").strip() if clients else None
            summary["checks"].append(
                {
                    "domain": "clients",
                    "ok": True,
                    "mode": "bridge",
                    "count": len(clients),
                    "sample_client_id": bridged_client_id,
                }
            )

        if tenant_legacy_id and self.is_enabled_for("meetings"):
            meetings = await self.list_meetings(tenant_legacy_id, limit=1)
            summary["checks"].append(
                {
                    "domain": "meetings",
                    "ok": True,
                    "mode": "bridge",
                    "count": len(meetings),
                }
            )

        if tenant_legacy_id and self.is_enabled_for("integrations"):
            integrations = await self.list_tenant_integrations(tenant_legacy_id, limit=3)
            summary["checks"].append(
                {
                    "domain": "integrations",
                    "ok": True,
                    "mode": "bridge",
                    "count": len(integrations),
                }
            )

        if tenant_legacy_id and self.is_enabled_for("oauth_accounts"):
            summary["checks"].append(
                {
                    "domain": "oauth_accounts",
                    "ok": True,
                    "mode": "bridge",
                    "reason": "configured_no_default_user_probe",
                }
            )

        if tenant_legacy_id and self.is_enabled_for("client_bindings"):
            if bridged_client_id:
                bindings = await self.list_client_bindings(tenant_legacy_id, bridged_client_id, limit=10)
                summary["checks"].append(
                    {
                        "domain": "client_bindings",
                        "ok": True,
                        "mode": "bridge",
                        "count": len(bindings),
                        "sample_client_id": bridged_client_id,
                    }
                )
            else:
                summary["checks"].append(
                    {
                        "domain": "client_bindings",
                        "ok": True,
                        "mode": "bridge",
                        "count": 0,
                        "reason": "skipped_no_client",
                    }
                )

        return summary


@lru_cache(maxsize=1)
def get_runtime_bridge() -> RuntimeBridge:
    return RuntimeBridge()


def reset_runtime_bridge_cache() -> None:
    reset_supabase_settings_cache()
    get_runtime_bridge.cache_clear()
