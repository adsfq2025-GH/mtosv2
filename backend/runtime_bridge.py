"""Optional Supabase runtime read bridge with Mongo overlay fallback."""
from __future__ import annotations

import logging
import os
import uuid
from functools import lru_cache
from typing import Any, Optional, Sequence

import httpx

from supabase_config import get_supabase_settings

logger = logging.getLogger("mtos.runtime_bridge")

DEFAULT_RUNTIME_BRIDGE_DOMAINS = ("tenants", "clients", "meetings", "integrations", "profiles")


def _to_bool(value: Any, default: bool = False) -> bool:
    raw = str(value if value is not None else "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _parse_csv(value: str, default: Sequence[str]) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw:
        return tuple(default)
    return tuple(sorted({part.strip().lower() for part in raw.split(",") if part.strip()}))


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


@lru_cache(maxsize=1)
def get_runtime_bridge_settings() -> dict[str, Any]:
    supabase = get_supabase_settings()
    enabled = _to_bool(os.environ.get("SUPABASE_RUNTIME_BRIDGE_ENABLED"), bool(supabase.get("enabled")))
    timeout_seconds = max(2.0, float(os.environ.get("SUPABASE_RUNTIME_BRIDGE_TIMEOUT_SECONDS", "8") or "8"))
    domains = _parse_csv(
        os.environ.get("SUPABASE_RUNTIME_BRIDGE_DOMAINS", ""),
        DEFAULT_RUNTIME_BRIDGE_DOMAINS,
    )
    return {
        "enabled": enabled,
        "domains": domains,
        "timeout_seconds": timeout_seconds,
        "url": str(supabase.get("url") or "").rstrip("/"),
        "service_role_key": str(supabase.get("service_role_key") or "").strip(),
        "db_schema": str(supabase.get("db_schema") or "public").strip() or "public",
        "service_configured": bool(enabled and supabase.get("service_configured")),
    }


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

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": str(self.settings.get("service_role_key") or ""),
            "Authorization": f"Bearer {self.settings.get('service_role_key') or ''}",
            "Accept-Profile": str(self.settings.get("db_schema") or "public"),
        }

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
        }

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


@lru_cache(maxsize=1)
def get_runtime_bridge() -> RuntimeBridge:
    return RuntimeBridge()


def reset_runtime_bridge_cache() -> None:
    get_runtime_bridge_settings.cache_clear()
    get_runtime_bridge.cache_clear()
