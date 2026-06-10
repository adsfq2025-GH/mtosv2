"""Optional Supabase configuration helpers for phased cutover."""

import os
from functools import lru_cache


def _to_bool(value: str, default: bool = False) -> bool:
    raw = str(value if value is not None else "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_supabase_settings() -> dict:
    enabled = _to_bool(os.environ.get("SUPABASE_ENABLED", "false"))
    url = str(os.environ.get("SUPABASE_URL", "")).strip()
    service_role_key = str(os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    db_schema = str(os.environ.get("SUPABASE_DB_SCHEMA", "public")).strip() or "public"

    return {
        "enabled": enabled,
        "url": url,
        "service_role_key": service_role_key,
        "db_schema": db_schema,
        "service_configured": bool(enabled and url and service_role_key),
    }


def is_supabase_service_configured() -> bool:
    return bool(get_supabase_settings()["service_configured"])
