"""Optional Supabase configuration helpers for phased cutover."""

import os
from functools import lru_cache
from typing import Any, Iterable

DEFAULT_RUNTIME_BRIDGE_DOMAINS = ("tenants", "clients", "meetings", "integrations", "profiles")
SUPPORTED_RUNTIME_BRIDGE_DOMAINS = DEFAULT_RUNTIME_BRIDGE_DOMAINS + (
    "settings",
    "domains",
    "client_bindings",
    "oauth_accounts",
    "clickup_sync",
    "ai_visibility",
)
DEFAULT_RUNTIME_MIRROR_DOMAINS: tuple[str, ...] = ()
SUPPORTED_RUNTIME_MIRROR_DOMAINS = ("settings", "integrations", "oauth_accounts")


def _to_bool(value: str, default: bool = False) -> bool:
    raw = str(value if value is not None else "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _safe_float(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _parse_csv(value: str, default: Iterable[str], *, allowed: Iterable[str] | None = None) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw:
        items = {str(item).strip().lower() for item in default if str(item).strip()}
    else:
        items = {part.strip().lower() for part in raw.split(",") if part.strip()}
    if allowed is not None:
        allowed_set = {str(item).strip().lower() for item in allowed if str(item).strip()}
        items = {item for item in items if item in allowed_set}
    return tuple(sorted(items))


def _mask_secret(value: str) -> str:
    secret = str(value or "").strip()
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


@lru_cache(maxsize=1)
def get_supabase_settings() -> dict[str, Any]:
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


@lru_cache(maxsize=1)
def get_runtime_bridge_settings() -> dict[str, Any]:
    supabase = get_supabase_settings()
    enabled = _to_bool(os.environ.get("SUPABASE_RUNTIME_BRIDGE_ENABLED"), bool(supabase.get("enabled")))
    timeout_seconds = max(2.0, _safe_float(os.environ.get("SUPABASE_RUNTIME_BRIDGE_TIMEOUT_SECONDS", "8"), 8.0))
    smoke_timeout_seconds = max(
        1.0,
        _safe_float(
            os.environ.get("SUPABASE_RUNTIME_BRIDGE_SMOKE_TIMEOUT_SECONDS", ""),
            min(timeout_seconds, 5.0),
        ),
    )
    domains = _parse_csv(
        os.environ.get("SUPABASE_RUNTIME_BRIDGE_DOMAINS", ""),
        DEFAULT_RUNTIME_BRIDGE_DOMAINS,
        allowed=SUPPORTED_RUNTIME_BRIDGE_DOMAINS,
    )
    mirror_domains = _parse_csv(
        os.environ.get("SUPABASE_RUNTIME_MIRROR_DOMAINS", ""),
        DEFAULT_RUNTIME_MIRROR_DOMAINS,
        allowed=SUPPORTED_RUNTIME_MIRROR_DOMAINS,
    )

    return {
        "enabled": enabled,
        "domains": domains,
        "supported_domains": SUPPORTED_RUNTIME_BRIDGE_DOMAINS,
        "mirror_domains": mirror_domains,
        "supported_mirror_domains": SUPPORTED_RUNTIME_MIRROR_DOMAINS,
        "timeout_seconds": timeout_seconds,
        "smoke_timeout_seconds": smoke_timeout_seconds,
        "url": str(supabase.get("url") or "").rstrip("/"),
        "service_role_key": str(supabase.get("service_role_key") or "").strip(),
        "db_schema": str(supabase.get("db_schema") or "public").strip() or "public",
        "service_configured": bool(enabled and supabase.get("service_configured")),
    }


@lru_cache(maxsize=1)
def get_oauth_token_store_settings() -> dict[str, Any]:
    return {
        "supabase_primary_enabled": _to_bool(
            os.environ.get("SUPABASE_OAUTH_TOKEN_PRIMARY_WRITE_ENABLED", "false")
        ),
        "mongo_mirror_enabled": _to_bool(
            os.environ.get("SUPABASE_OAUTH_TOKEN_MONGO_MIRROR_ENABLED", "true"),
            True,
        ),
        "no_mongo_read_enabled": _to_bool(
            os.environ.get("SUPABASE_OAUTH_TOKEN_NO_MONGO_READS_ENABLED", "false")
        ),
    }


def get_runtime_bridge_env_summary() -> dict[str, Any]:
    settings = get_runtime_bridge_settings()
    oauth_token_store = get_oauth_token_store_settings()
    return {
        "enabled": bool(settings.get("enabled")),
        "service_configured": bool(settings.get("service_configured")),
        "url": settings.get("url") or "",
        "db_schema": settings.get("db_schema") or "public",
        "domains": tuple(settings.get("domains") or ()),
        "supported_domains": tuple(settings.get("supported_domains") or ()),
        "mirror_domains": tuple(settings.get("mirror_domains") or ()),
        "supported_mirror_domains": tuple(settings.get("supported_mirror_domains") or ()),
        "timeout_seconds": float(settings.get("timeout_seconds") or 0),
        "smoke_timeout_seconds": float(settings.get("smoke_timeout_seconds") or 0),
        "service_role_key_masked": _mask_secret(str(settings.get("service_role_key") or "")),
        "oauth_token_store": {
            "supabase_primary_enabled": bool(oauth_token_store.get("supabase_primary_enabled")),
            "mongo_mirror_enabled": bool(oauth_token_store.get("mongo_mirror_enabled")),
            "no_mongo_read_enabled": bool(oauth_token_store.get("no_mongo_read_enabled")),
        },
    }


def is_supabase_service_configured() -> bool:
    return bool(get_supabase_settings()["service_configured"])


def reset_supabase_settings_cache() -> None:
    get_supabase_settings.cache_clear()
    get_runtime_bridge_settings.cache_clear()
    get_oauth_token_store_settings.cache_clear()
