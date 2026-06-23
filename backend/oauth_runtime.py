"""OAuth runtime helpers for stateless state and Supabase-backed token refs."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from db import decrypt_secret, encrypt_secret, new_id
from supabase_store import get_store
from supabase_config import get_oauth_token_store_settings

OAUTH_STATE_SECRET = str(os.environ.get("OAUTH_STATE_SECRET") or os.environ["JWT_SECRET"]).strip()
OAUTH_STATE_ALG = str(os.environ.get("OAUTH_STATE_ALG") or os.environ.get("JWT_ALG") or "HS256").strip() or "HS256"
OAUTH_STATE_TTL_SECONDS = max(300, int(os.environ.get("OAUTH_STATE_TTL_SECONDS", "1800")))
INLINE_OAUTH_CONNECTION_REF_PREFIX = "enc-v1:"


def build_google_oauth_state(
    *,
    tenant_id: str,
    user_id: str,
    platform: str,
    scopes: list[str],
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "jti": new_id(),
        "provider": "google",
        "tenant_id": str(tenant_id or "").strip(),
        "user_id": str(user_id or "").strip(),
        "platform": str(platform or "").strip(),
        "scopes": [str(scope).strip() for scope in (scopes or []) if str(scope).strip()],
        "iat": now,
        "exp": now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS),
    }
    return jwt.encode(payload, OAUTH_STATE_SECRET, algorithm=OAUTH_STATE_ALG)


def build_clickup_oauth_state(
    *,
    tenant_id: str,
    user_id: str,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "jti": new_id(),
        "provider": "clickup",
        "tenant_id": str(tenant_id or "").strip(),
        "user_id": str(user_id or "").strip(),
        "iat": now,
        "exp": now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS),
    }
    return jwt.encode(payload, OAUTH_STATE_SECRET, algorithm=OAUTH_STATE_ALG)


def decode_google_oauth_state(state: str) -> dict[str, Any]:
    payload = jwt.decode(str(state or ""), OAUTH_STATE_SECRET, algorithms=[OAUTH_STATE_ALG])
    if str(payload.get("provider") or "").strip().lower() != "google":
        raise jwt.InvalidTokenError("invalid_provider")
    if not str(payload.get("tenant_id") or "").strip():
        raise jwt.InvalidTokenError("missing_tenant_id")
    if not str(payload.get("user_id") or "").strip():
        raise jwt.InvalidTokenError("missing_user_id")
    if not str(payload.get("platform") or "").strip():
        raise jwt.InvalidTokenError("missing_platform")
    payload["scopes"] = [str(scope).strip() for scope in (payload.get("scopes") or []) if str(scope).strip()]
    return payload


def decode_clickup_oauth_state(state: str) -> dict[str, Any]:
    payload = jwt.decode(str(state or ""), OAUTH_STATE_SECRET, algorithms=[OAUTH_STATE_ALG])
    if str(payload.get("provider") or "").strip().lower() != "clickup":
        raise jwt.InvalidTokenError("invalid_provider")
    if not str(payload.get("tenant_id") or "").strip():
        raise jwt.InvalidTokenError("missing_tenant_id")
    if not str(payload.get("user_id") or "").strip():
        raise jwt.InvalidTokenError("missing_user_id")
    return payload


def build_inline_oauth_connection_ref(refresh_token: str) -> str:
    token = str(refresh_token or "").strip()
    if not token:
        return ""
    return f"{INLINE_OAUTH_CONNECTION_REF_PREFIX}{encrypt_secret(token)}"


def decode_inline_oauth_connection_ref(oauth_connection_ref: Any) -> str:
    raw = str(oauth_connection_ref or "").strip()
    if not raw or not raw.startswith(INLINE_OAUTH_CONNECTION_REF_PREFIX):
        return ""
    encrypted = raw[len(INLINE_OAUTH_CONNECTION_REF_PREFIX):].strip()
    if not encrypted:
        return ""
    return decrypt_secret(encrypted)


async def get_google_refresh_token_from_bridge(tenant_id: str, user_id: str, platform: str) -> str:
    bridge_doc = await get_store().get_user_oauth_account(tenant_id, user_id, "google", platform)
    if not bridge_doc:
        return ""
    return decode_inline_oauth_connection_ref((bridge_doc or {}).get("oauth_connection_ref"))


async def get_google_oauth_bridge_account(tenant_id: str, user_id: str, platform: str) -> Optional[dict[str, Any]]:
    return await get_store().get_user_oauth_account(tenant_id, user_id, "google", platform)


def _normalize_scopes(scopes: Any) -> list[str]:
    return [str(scope).strip() for scope in (scopes or []) if str(scope).strip()]


def _mongo_google_oauth_doc_to_runtime_doc(doc: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not doc:
        return None
    encrypted_refresh_token = str((doc or {}).get("refresh_token_encrypted") or "").strip()
    refresh_token = ""
    if encrypted_refresh_token:
        try:
            refresh_token = decrypt_secret(encrypted_refresh_token)
        except Exception:
            refresh_token = ""
    normalized_platform = str((doc or {}).get("platform") or "").strip()
    normalized_provider = str((doc or {}).get("provider") or "google").strip() or "google"
    return {
        "_id": str((doc or {}).get("_id") or f"{normalized_provider}:{normalized_platform}"),
        "tenant_id": str((doc or {}).get("tenant_id") or "").strip(),
        "user_id": str((doc or {}).get("user_id") or "").strip(),
        "provider": normalized_provider,
        "platform": normalized_platform,
        "account_email": str((doc or {}).get("account_email") or "").strip() or None,
        "scopes": _normalize_scopes((doc or {}).get("scopes") or []),
        "updated_at": (doc or {}).get("updated_at"),
        "created_at": (doc or {}).get("created_at"),
        "last_synced_at": (doc or {}).get("updated_at") or (doc or {}).get("created_at"),
        "oauth_connection_ref": build_inline_oauth_connection_ref(refresh_token) if str(refresh_token or "").strip() else "",
    }


async def get_google_oauth_runtime_doc(tenant_id: str, user_id: str, platform: str) -> Optional[dict[str, Any]]:
    return await get_google_oauth_bridge_account(tenant_id, user_id, platform)


async def get_google_refresh_token(tenant_id: str, user_id: str, platform: str) -> str:
    runtime_doc = await get_google_oauth_runtime_doc(tenant_id, user_id, platform)
    return decode_inline_oauth_connection_ref((runtime_doc or {}).get("oauth_connection_ref"))


def is_supabase_primary_oauth_token_write_enabled() -> bool:
    return bool(get_oauth_token_store_settings().get("supabase_primary_enabled"))


async def has_google_oauth_connection(tenant_id: str, user_id: str, platform: str) -> bool:
    return bool(await get_google_refresh_token(tenant_id, user_id, platform))


async def pick_google_oauth_user_id(
    tenant_id: str,
    preferred_user_id: Optional[str],
    platform: str,
) -> Optional[str]:
    preferred = str(preferred_user_id or "").strip()
    if preferred and await has_google_oauth_connection(tenant_id, preferred, platform):
        return preferred
    return None


async def write_google_oauth_token(
    tenant_id: str,
    user_id: str,
    platform: str,
    refresh_token: str,
    scopes: list[str],
    *,
    account_email: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> dict[str, Any]:
    bridge = get_store()
    now = str(updated_at or datetime.now(timezone.utc).isoformat())
    bridge_payload = {
        "provider": "google",
        "platform": str(platform or "").strip(),
        "account_email": str(account_email or "").strip() or None,
        "scopes": [str(scope).strip() for scope in (scopes or []) if str(scope).strip()],
        "last_synced_at": now,
        "oauth_connection_ref": build_inline_oauth_connection_ref(refresh_token),
    }
    bridge_enabled = bridge.is_mirror_enabled_for("oauth_accounts")

    if not bridge_enabled:
        return {
            "ok": False,
            "primary_store": "supabase",
            "effective_store": None,
            "degraded": False,
            "bridge": {"attempted": False, "ok": False, "reason": "disabled"},
            "mongo": {"attempted": False, "ok": False, "reason": "removed"},
        }

    bridge_result = await bridge.safe_mirror_user_oauth_account(
        tenant_id,
        user_id,
        bridge_payload,
        reason="oauth_token_primary_write",
    )
    return {
        "ok": bool(bridge_result.get("ok")),
        "primary_store": "supabase",
        "effective_store": "supabase" if bridge_result.get("ok") else None,
        "degraded": False,
        "bridge": bridge_result,
        "mongo": {"attempted": False, "ok": False, "reason": "removed"},
    }


async def clear_google_oauth_token(
    tenant_id: str,
    user_id: str,
    platform: str,
    *,
    account_email: Optional[str] = None,
    scopes: Optional[list[str]] = None,
    updated_at: Optional[str] = None,
) -> dict[str, Any]:
    bridge = get_store()
    now = str(updated_at or datetime.now(timezone.utc).isoformat())
    bridge_enabled = bridge.is_mirror_enabled_for("oauth_accounts")
    bridge_result: Optional[dict[str, Any]] = None

    if bridge_enabled:
        bridge_result = await bridge.safe_mirror_user_oauth_account(
            tenant_id,
            user_id,
            {
                "provider": "google",
                "platform": str(platform or "").strip(),
                "account_email": str(account_email or "").strip() or None,
                "scopes": [str(scope).strip() for scope in (scopes or []) if str(scope).strip()],
                "last_synced_at": now,
                "oauth_connection_ref": "",
            },
            reason="oauth_token_disconnect_clear",
        )
        if not bridge_result.get("ok"):
            return {
                "ok": False,
                "primary_store": "supabase" if is_supabase_primary_oauth_token_write_enabled() else None,
                "effective_store": None,
                "degraded": False,
                "bridge": bridge_result,
                "mongo": None,
            }
    return {
        "ok": bool((bridge_result or {}).get("ok")) if bridge_enabled else False,
        "primary_store": "supabase",
        "effective_store": "supabase" if bridge_enabled else None,
        "degraded": False,
        "bridge": bridge_result or {"attempted": False, "ok": False, "reason": "disabled"},
        "mongo": {"attempted": False, "ok": False, "reason": "removed", "deleted_count": 0},
    }


async def _resolve_oauth_account_email(user_id: str, fallback_email: Optional[str] = None) -> Optional[str]:
    candidate = str(fallback_email or "").strip()
    if candidate:
        return candidate
    user_doc = await get_store().get_user_profile(str(user_id or "").strip())
    email = str((user_doc or {}).get("email") or "").strip()
    return email or None


async def backfill_google_oauth_tokens_from_mongo(
    *,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    platform: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "reason": "mongo_backfill_removed",
        "filters": {
            "tenant_id": str(tenant_id or "").strip() or None,
            "user_id": str(user_id or "").strip() or None,
            "platform": str(platform or "").strip() or None,
            "limit": int(limit) if limit else None,
        },
        "scanned": 0,
        "eligible": 0,
        "mirrored": 0,
        "failed": 0,
        "skipped_missing_fields": 0,
        "skipped_empty_refresh_token": 0,
        "sample_failures": [],
    }
