"""OAuth runtime helpers for stateless state and Supabase-backed token refs."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from db import db, decrypt_secret, encrypt_secret, is_mongo_configured, new_id
from runtime_bridge import get_runtime_bridge
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
    bridge_doc = await get_runtime_bridge().get_user_oauth_account(tenant_id, user_id, "google", platform)
    if not bridge_doc:
        return ""
    return decode_inline_oauth_connection_ref((bridge_doc or {}).get("oauth_connection_ref"))


async def get_google_oauth_bridge_account(tenant_id: str, user_id: str, platform: str) -> Optional[dict[str, Any]]:
    return await get_runtime_bridge().get_user_oauth_account(tenant_id, user_id, "google", platform)


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
    bridge_doc = await get_google_oauth_bridge_account(tenant_id, user_id, platform)
    if bridge_doc is not None:
        return bridge_doc
    if is_no_mongo_oauth_token_read_enabled() or not is_mongo_configured():
        return None
    mongo_doc = await db.user_oauth_tokens.find_one(
        {"tenant_id": tenant_id, "user_id": user_id, "provider": "google", "platform": platform}
    )
    return _mongo_google_oauth_doc_to_runtime_doc(mongo_doc)


async def get_google_refresh_token(tenant_id: str, user_id: str, platform: str) -> str:
    runtime_doc = await get_google_oauth_runtime_doc(tenant_id, user_id, platform)
    return decode_inline_oauth_connection_ref((runtime_doc or {}).get("oauth_connection_ref"))


def is_supabase_primary_oauth_token_write_enabled() -> bool:
    return bool(get_oauth_token_store_settings().get("supabase_primary_enabled"))


def is_mongo_oauth_token_mirror_enabled() -> bool:
    return bool(get_oauth_token_store_settings().get("mongo_mirror_enabled"))


def is_no_mongo_oauth_token_read_enabled() -> bool:
    return bool(get_oauth_token_store_settings().get("no_mongo_read_enabled"))


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


async def _upsert_mongo_google_oauth_token(
    tenant_id: str,
    user_id: str,
    platform: str,
    refresh_token: str,
    scopes: list[str],
    *,
    account_email: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> dict[str, Any]:
    if not is_mongo_configured():
        return {"attempted": False, "ok": False, "reason": "mongo_not_configured"}
    now = str(updated_at or datetime.now(timezone.utc).isoformat())
    result = await db.user_oauth_tokens.update_one(
        {"tenant_id": tenant_id, "user_id": user_id, "provider": "google", "platform": platform},
        {"$set": {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "provider": "google",
            "platform": platform,
            "refresh_token_encrypted": encrypt_secret(str(refresh_token)),
            "scopes": [str(scope).strip() for scope in (scopes or []) if str(scope).strip()],
            "account_email": str(account_email or "").strip() or None,
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {
        "attempted": True,
        "ok": True,
        "matched_count": int(getattr(result, "matched_count", 0) or 0),
        "modified_count": int(getattr(result, "modified_count", 0) or 0),
        "upserted_id": getattr(result, "upserted_id", None),
    }


async def _delete_mongo_google_oauth_token(tenant_id: str, user_id: str, platform: str) -> dict[str, Any]:
    if not is_mongo_configured():
        return {"attempted": False, "ok": False, "reason": "mongo_not_configured", "deleted_count": 0}
    result = await db.user_oauth_tokens.delete_one(
        {"tenant_id": tenant_id, "user_id": user_id, "provider": "google", "platform": platform}
    )
    return {
        "attempted": True,
        "ok": True,
        "deleted_count": int(getattr(result, "deleted_count", 0) or 0),
    }


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
    bridge = get_runtime_bridge()
    now = str(updated_at or datetime.now(timezone.utc).isoformat())
    bridge_payload = {
        "provider": "google",
        "platform": str(platform or "").strip(),
        "account_email": str(account_email or "").strip() or None,
        "scopes": [str(scope).strip() for scope in (scopes or []) if str(scope).strip()],
        "last_synced_at": now,
        "oauth_connection_ref": build_inline_oauth_connection_ref(refresh_token),
    }
    primary_supabase = is_supabase_primary_oauth_token_write_enabled()
    mongo_mirror_enabled = is_mongo_oauth_token_mirror_enabled()
    mongo_available = is_mongo_configured()
    bridge_enabled = bridge.is_mirror_enabled_for("oauth_accounts")

    if primary_supabase or not mongo_available:
        if not bridge_enabled:
            return {
                "ok": False,
                "primary_store": "supabase",
                "effective_store": None,
                "degraded": False,
                "bridge": {"attempted": False, "ok": False, "reason": "disabled"},
                "mongo": {"attempted": False, "ok": False, "reason": "mongo_not_configured" if not mongo_available else "disabled"},
            }
        bridge_result = await bridge.safe_mirror_user_oauth_account(
            tenant_id,
            user_id,
            bridge_payload,
            reason="oauth_token_primary_write",
        )
        mongo_result = None
        degraded = False
        if mongo_mirror_enabled and mongo_available:
            mongo_result = await _upsert_mongo_google_oauth_token(
                tenant_id,
                user_id,
                platform,
                refresh_token,
                scopes,
                account_email=account_email,
                updated_at=now,
            )
            degraded = not bool(bridge_result.get("ok"))
        elif mongo_mirror_enabled:
            mongo_result = {"attempted": False, "ok": False, "reason": "mongo_not_configured"}
        return {
            "ok": bool(bridge_result.get("ok")) or bool(mongo_result and mongo_result.get("ok")),
            "primary_store": "supabase",
            "effective_store": "supabase" if bridge_result.get("ok") else "mongo",
            "degraded": degraded,
            "bridge": bridge_result,
            "mongo": mongo_result,
        }

    mongo_result = await _upsert_mongo_google_oauth_token(
        tenant_id,
        user_id,
        platform,
        refresh_token,
        scopes,
        account_email=account_email,
        updated_at=now,
    )
    bridge_result = await bridge.safe_mirror_user_oauth_account(
        tenant_id,
        user_id,
        bridge_payload,
        reason="oauth_token_mirror_write",
    ) if bridge_enabled else {
        "attempted": False,
        "ok": False,
        "reason": "disabled",
    }
    return {
        "ok": bool(mongo_result.get("ok")),
        "primary_store": "mongo",
        "effective_store": "mongo",
        "degraded": bool(bridge_enabled and not bridge_result.get("ok")),
        "bridge": bridge_result,
        "mongo": mongo_result,
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
    bridge = get_runtime_bridge()
    now = str(updated_at or datetime.now(timezone.utc).isoformat())
    bridge_enabled = bridge.is_mirror_enabled_for("oauth_accounts")
    mongo_available = is_mongo_configured()
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
                "primary_store": "supabase" if is_supabase_primary_oauth_token_write_enabled() else "mongo",
                "effective_store": None,
                "degraded": False,
                "bridge": bridge_result,
                "mongo": None,
            }

    mongo_result = await _delete_mongo_google_oauth_token(tenant_id, user_id, platform) if mongo_available else {
        "attempted": False,
        "ok": False,
        "reason": "mongo_not_configured",
        "deleted_count": 0,
    }
    return {
        "ok": bool((bridge_result or {}).get("ok")) if bridge_enabled else bool(mongo_result.get("ok")),
        "primary_store": "supabase" if is_supabase_primary_oauth_token_write_enabled() and bridge_enabled else "mongo",
        "effective_store": "supabase" if bridge_enabled else "mongo",
        "degraded": False,
        "bridge": bridge_result or {"attempted": False, "ok": False, "reason": "disabled"},
        "mongo": mongo_result,
    }


async def _resolve_oauth_account_email(user_id: str, fallback_email: Optional[str] = None) -> Optional[str]:
    candidate = str(fallback_email or "").strip()
    if candidate:
        return candidate
    if not is_mongo_configured():
        return None
    user_doc = await db.users.find_one({"_id": str(user_id or "").strip()})
    email = str((user_doc or {}).get("email") or "").strip()
    return email or None


async def backfill_google_oauth_tokens_from_mongo(
    *,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    platform: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    bridge = get_runtime_bridge()
    if not is_mongo_configured():
        return {
            "ok": False,
            "reason": "mongo_not_configured",
            "filters": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "platform": platform,
                "limit": limit,
            },
            "scanned": 0,
            "eligible": 0,
            "mirrored": 0,
            "failed": 0,
            "skipped_missing_fields": 0,
            "skipped_empty_refresh_token": 0,
            "sample_failures": [],
        }
    if not bridge.is_mirror_enabled_for("oauth_accounts"):
        return {
            "ok": False,
            "reason": "oauth_accounts_mirror_disabled",
            "filters": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "platform": platform,
                "limit": limit,
            },
            "scanned": 0,
            "eligible": 0,
            "mirrored": 0,
            "failed": 0,
            "skipped_missing_fields": 0,
            "skipped_empty_refresh_token": 0,
            "sample_failures": [],
        }

    query: dict[str, Any] = {
        "provider": "google",
        "refresh_token_encrypted": {"$exists": True, "$ne": ""},
    }
    if tenant_id:
        query["tenant_id"] = str(tenant_id).strip()
    if user_id:
        query["user_id"] = str(user_id).strip()
    if platform:
        query["platform"] = str(platform).strip()

    cursor = db.user_oauth_tokens.find(query)
    if limit:
        cursor = cursor.limit(int(limit))

    summary = {
        "ok": True,
        "reason": "completed",
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

    async for mongo_doc in cursor:
        summary["scanned"] += 1
        legacy_tenant_id = str((mongo_doc or {}).get("tenant_id") or "").strip()
        legacy_user_id = str((mongo_doc or {}).get("user_id") or "").strip()
        provider = str((mongo_doc or {}).get("provider") or "").strip().lower()
        normalized_platform = str((mongo_doc or {}).get("platform") or "").strip().lower()
        try:
            encrypted_refresh_token = str((mongo_doc or {}).get("refresh_token_encrypted") or "").strip()

            if not legacy_tenant_id or not legacy_user_id or provider != "google" or not normalized_platform:
                summary["skipped_missing_fields"] += 1
                continue
            if not encrypted_refresh_token:
                summary["skipped_empty_refresh_token"] += 1
                continue

            refresh_token = decrypt_secret(encrypted_refresh_token)
            if not str(refresh_token or "").strip():
                summary["skipped_empty_refresh_token"] += 1
                continue

            summary["eligible"] += 1
            account_email = await _resolve_oauth_account_email(legacy_user_id, (mongo_doc or {}).get("account_email"))
            mirror_result = await bridge.safe_mirror_user_oauth_account(
                legacy_tenant_id,
                legacy_user_id,
                {
                    "provider": "google",
                    "platform": normalized_platform,
                    "account_email": account_email,
                    "scopes": [str(scope).strip() for scope in ((mongo_doc or {}).get("scopes") or []) if str(scope).strip()],
                    "last_synced_at": (mongo_doc or {}).get("updated_at") or (mongo_doc or {}).get("created_at"),
                    "oauth_connection_ref": build_inline_oauth_connection_ref(refresh_token),
                },
                reason="oauth_token_mongo_backfill",
            )
            if mirror_result.get("ok"):
                summary["mirrored"] += 1
                continue

            failure_reason = str(mirror_result.get("reason") or mirror_result.get("error") or "unknown")
        except Exception as exc:
            failure_reason = str(exc)

        summary["failed"] += 1
        summary["ok"] = False
        if len(summary["sample_failures"]) < 20:
            summary["sample_failures"].append(
                {
                    "tenant_id": legacy_tenant_id,
                    "user_id": legacy_user_id,
                    "platform": normalized_platform,
                    "reason": failure_reason,
                }
            )

    return summary
