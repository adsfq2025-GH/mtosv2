"""Minimal PostgREST client for Supabase bridge scripts."""

from __future__ import annotations

from typing import Any, Iterable, Optional

import requests

from .config import BridgeSettings


class SupabaseBridgeClient:
    def __init__(self, settings: BridgeSettings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": settings.supabase_service_role_key,
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "Accept-Profile": settings.supabase_db_schema,
                "Content-Profile": settings.supabase_db_schema,
                "Content-Type": "application/json",
            }
        )

    def _url(self, path: str) -> str:
        return f"{self.settings.supabase_url}/rest/v1/{path.lstrip('/')}"

    def insert_rows(
        self,
        table: str,
        rows: Iterable[dict[str, Any]],
        *,
        on_conflict: Optional[str] = None,
        returning: str = "representation",
    ) -> list[dict[str, Any]]:
        payload = list(rows)
        if not payload:
            return []

        headers = {"Prefer": f"resolution=merge-duplicates,return={returning}"}
        params: dict[str, str] = {}
        if on_conflict:
            params["on_conflict"] = on_conflict

        response = self.session.post(self._url(table), json=payload, params=params, headers=headers, timeout=120)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else [data]

    def insert_row(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        items = self.insert_rows(table, [row])
        return items[0] if items else {}

    def rpc(self, function_name: str, payload: Optional[dict[str, Any]] = None) -> Any:
        response = self.session.post(self._url(f"rpc/{function_name}"), json=payload or {}, timeout=300)
        response.raise_for_status()
        if not response.text.strip():
            return None
        return response.json()

    def select(self, relation: str, **params: Any) -> Any:
        clean_params = {k: str(v) for k, v in params.items() if v is not None}
        response = self.session.get(self._url(relation), params=clean_params, timeout=120)
        response.raise_for_status()
        return response.json()
