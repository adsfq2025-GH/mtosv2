from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx


class SupabaseRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SupabaseNativeConfig:
    url: str
    service_role_key: str
    anon_key: Optional[str] = None
    schema: str = "public"

    @property
    def rest_url(self) -> str:
        return f"{self.url.rstrip('/')}/rest/v1"

    @property
    def rpc_url(self) -> str:
        return f"{self.url.rstrip('/')}/rest/v1/rpc"

    @classmethod
    def from_env(cls) -> "SupabaseNativeConfig":
        url = str(os.environ.get("SUPABASE_URL") or "").strip()
        service_role_key = str(os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        if not url or not service_role_key:
            raise SupabaseRepositoryError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        anon_key = str(os.environ.get("SUPABASE_ANON_KEY") or "").strip() or None
        return cls(url=url, service_role_key=service_role_key, anon_key=anon_key)


class SupabaseNativeRepository:
    def __init__(
        self,
        config: Optional[SupabaseNativeConfig] = None,
        *,
        api_key: Optional[str] = None,
        authorization_bearer: Optional[str] = None,
    ) -> None:
        self.config = config or SupabaseNativeConfig.from_env()
        self.api_key = str(api_key or "").strip() or None
        self.authorization_bearer = str(authorization_bearer or "").strip() or None

    def for_user(self, access_token: str) -> "SupabaseNativeRepository":
        if not self.config.anon_key:
            raise SupabaseRepositoryError("SUPABASE_ANON_KEY is required for user-scoped Supabase access")
        return SupabaseNativeRepository(
            self.config,
            api_key=self.config.anon_key,
            authorization_bearer=str(access_token or "").strip(),
        )

    def _headers(self, *, prefer: Optional[str] = None) -> dict[str, str]:
        api_key = self.api_key or self.config.service_role_key
        bearer = self.authorization_bearer or self.config.service_role_key
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Any = None,
        prefer: Optional[str] = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.config.rest_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method.upper(),
                url,
                params=params,
                json=json,
                headers=self._headers(prefer=prefer),
            )
        if response.status_code >= 400:
            detail = response.text[:1000] if response.text else f"HTTP {response.status_code}"
            raise SupabaseRepositoryError(detail)
        if not response.content:
            return None
        return response.json()

    async def list(
        self,
        table: str,
        *,
        select: str = "*",
        filters: Optional[dict[str, Any]] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": select}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        data = await self._request("GET", table, params=params)
        return list(data or [])

    async def get_one(
        self,
        table: str,
        *,
        select: str = "*",
        filters: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        rows = await self.list(table, select=select, filters=filters, limit=1)
        return rows[0] if rows else None

    async def insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        rows = await self._request("POST", table, json=payload, prefer="return=representation")
        return dict((rows or [None])[0] or {})

    async def upsert(
        self,
        table: str,
        payload: dict[str, Any],
        *,
        on_conflict: Optional[str] = None,
    ) -> dict[str, Any]:
        params = {"on_conflict": on_conflict} if on_conflict else None
        rows = await self._request(
            "POST",
            table,
            params=params,
            json=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return dict((rows or [None])[0] or {})

    async def update(
        self,
        table: str,
        payload: dict[str, Any],
        *,
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows = await self._request(
            "PATCH",
            table,
            params=filters,
            json=payload,
            prefer="return=representation",
        )
        return list(rows or [])

    async def soft_delete(self, table: str, *, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.update(
            table,
            {"is_deleted": True},
            filters=filters,
        )

    async def rpc(self, function_name: str, payload: Optional[dict[str, Any]] = None) -> Any:
        url = f"{self.config.rpc_url}/{function_name}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                json=payload or {},
                headers=self._headers(),
            )
        if response.status_code >= 400:
            detail = response.text[:1000] if response.text else f"HTTP {response.status_code}"
            raise SupabaseRepositoryError(detail)
        if not response.content:
            return None
        return response.json()
