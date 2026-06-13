import asyncio
import os

import jwt
from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "unit-test-jwt-secret")
os.environ.setdefault("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())

import connectors
import oauth_runtime
from oauth_runtime import (
    OAUTH_STATE_ALG,
    OAUTH_STATE_SECRET,
    backfill_google_oauth_tokens_from_mongo,
    build_clickup_oauth_state,
    build_google_oauth_state,
    build_inline_oauth_connection_ref,
    clear_google_oauth_token,
    decode_clickup_oauth_state,
    decode_google_oauth_state,
    decode_inline_oauth_connection_ref,
    get_google_oauth_runtime_doc,
    write_google_oauth_token,
)


class _FakeBridge:
    def __init__(self, *, mirror_ok=True, bridge_doc=None):
        self.mirror_ok = mirror_ok
        self.bridge_doc = bridge_doc
        self.mirror_calls = []

    def is_mirror_enabled_for(self, domain: str) -> bool:
        return domain == "oauth_accounts"

    async def safe_mirror_user_oauth_account(self, tenant_id, user_id, doc, *, reason=""):
        self.mirror_calls.append(
            {"tenant_id": tenant_id, "user_id": user_id, "doc": dict(doc), "reason": reason}
        )
        return {
            "attempted": True,
            "ok": self.mirror_ok,
            "reason": reason,
            "mode": "update",
        }

    async def get_user_oauth_account(self, tenant_id, user_id, provider, platform):
        return self.bridge_doc

    async def list_user_oauth_accounts(self, tenant_id, *, provider=None, platform=None, limit=100):
        if not self.bridge_doc:
            return []
        return [self.bridge_doc]


def test_google_oauth_state_round_trip_preserves_context():
    state = build_google_oauth_state(
        tenant_id="tenant-123",
        user_id="user-456",
        platform="google_calendar",
        scopes=["calendar.readonly", "openid"],
    )

    payload = decode_google_oauth_state(state)

    assert payload["provider"] == "google"
    assert payload["tenant_id"] == "tenant-123"
    assert payload["user_id"] == "user-456"
    assert payload["platform"] == "google_calendar"
    assert payload["scopes"] == ["calendar.readonly", "openid"]


def test_google_oauth_state_rejects_wrong_provider():
    state = jwt.encode(
        {
            "provider": "microsoft",
            "tenant_id": "tenant-123",
            "user_id": "user-456",
            "platform": "google_calendar",
        },
        OAUTH_STATE_SECRET,
        algorithm=OAUTH_STATE_ALG,
    )

    try:
        decode_google_oauth_state(state)
    except jwt.InvalidTokenError as exc:
        assert str(exc) == "invalid_provider"
    else:
        raise AssertionError("Expected decode_google_oauth_state to reject non-google providers")


def test_clickup_oauth_state_round_trip_preserves_context():
    state = build_clickup_oauth_state(
        tenant_id="tenant-123",
        user_id="user-456",
    )

    payload = decode_clickup_oauth_state(state)

    assert payload["provider"] == "clickup"
    assert payload["tenant_id"] == "tenant-123"
    assert payload["user_id"] == "user-456"


def test_clickup_oauth_state_rejects_wrong_provider():
    state = jwt.encode(
        {
            "provider": "google",
            "tenant_id": "tenant-123",
            "user_id": "user-456",
        },
        OAUTH_STATE_SECRET,
        algorithm=OAUTH_STATE_ALG,
    )

    try:
        decode_clickup_oauth_state(state)
    except jwt.InvalidTokenError as exc:
        assert str(exc) == "invalid_provider"
    else:
        raise AssertionError("Expected decode_clickup_oauth_state to reject non-clickup providers")


def test_inline_oauth_connection_ref_round_trip():
    ref = build_inline_oauth_connection_ref("refresh-token-123")

    assert ref.startswith("enc-v1:")
    assert decode_inline_oauth_connection_ref(ref) == "refresh-token-123"


def test_clickup_token_from_creds_prefers_access_token():
    token = connectors._clickup_token_from_creds({"api_token": "pk_direct", "access_token": "oauth_token"})

    assert token == "oauth_token"


def test_clickup_token_from_creds_falls_back_to_personal_token():
    token = connectors._clickup_token_from_creds({"api_token": "pk_direct"})

    assert token == "pk_direct"


def test_get_google_refresh_token_prefers_bridge(monkeypatch):
    runtime_doc = {
        "oauth_connection_ref": build_inline_oauth_connection_ref("bridge-refresh-token")
    }
    async def fake_runtime_doc(tenant_id: str, user_id: str, platform: str):
        assert tenant_id == "tenant-123"
        assert user_id == "user-456"
        assert platform == "google_calendar"
        return runtime_doc

    monkeypatch.setattr(connectors, "get_google_oauth_runtime_doc", fake_runtime_doc)

    token = asyncio.run(connectors.get_google_refresh_token("tenant-123", "user-456", "google_calendar"))

    assert token == "bridge-refresh-token"


def test_get_google_refresh_token_falls_back_to_mongo(monkeypatch):
    async def fake_runtime_doc(tenant_id: str, user_id: str, platform: str):
        return {"oauth_connection_ref": build_inline_oauth_connection_ref("mongo-refresh-token")}

    monkeypatch.setattr(connectors, "get_google_oauth_runtime_doc", fake_runtime_doc)

    token = asyncio.run(connectors.get_google_refresh_token("tenant-123", "user-456", "google_calendar"))

    assert token == "mongo-refresh-token"


def test_get_google_refresh_token_treats_empty_bridge_ref_as_authoritative_disconnect(monkeypatch):
    async def fake_runtime_doc(tenant_id: str, user_id: str, platform: str):
        return {"oauth_connection_ref": ""}

    monkeypatch.setattr(connectors, "get_google_oauth_runtime_doc", fake_runtime_doc)

    token = asyncio.run(connectors.get_google_refresh_token("tenant-123", "user-456", "google_calendar"))

    assert token == ""


def test_get_google_refresh_token_skips_mongo_when_no_mongo_reads_enabled(monkeypatch):
    async def fake_runtime_doc(tenant_id: str, user_id: str, platform: str):
        return None

    monkeypatch.setattr(connectors, "get_google_oauth_runtime_doc", fake_runtime_doc)

    token = asyncio.run(connectors.get_google_refresh_token("tenant-123", "user-456", "google_calendar"))

    assert token == ""


def test_get_google_oauth_runtime_doc_returns_bridge_doc(monkeypatch):
    bridge_doc = {
        "provider": "google",
        "platform": "google_calendar",
        "account_email": "owner@example.com",
        "scopes": ["calendar.readonly"],
        "oauth_connection_ref": build_inline_oauth_connection_ref("bridge-refresh-token"),
    }

    async def fake_bridge_doc(tenant_id: str, user_id: str, platform: str):
        assert tenant_id == "tenant-123"
        assert user_id == "user-456"
        assert platform == "google_calendar"
        return bridge_doc

    monkeypatch.setattr(oauth_runtime, "get_google_oauth_bridge_account", fake_bridge_doc)

    doc = asyncio.run(get_google_oauth_runtime_doc("tenant-123", "user-456", "google_calendar"))

    assert doc == bridge_doc


def test_write_google_oauth_token_uses_supabase_primary(monkeypatch):
    bridge = _FakeBridge(mirror_ok=True)
    monkeypatch.setattr(
        oauth_runtime,
        "get_oauth_token_store_settings",
        lambda: {"supabase_primary_enabled": True, "mongo_mirror_enabled": True},
    )
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)

    result = asyncio.run(
        write_google_oauth_token(
            "tenant-123",
            "user-456",
            "google_calendar",
            "refresh-token-123",
            ["calendar.readonly"],
            account_email="owner@example.com",
            updated_at="2026-01-02T00:00:00+00:00",
        )
    )

    assert result["ok"] is True
    assert result["primary_store"] == "supabase"
    assert result["effective_store"] == "supabase"
    assert result["degraded"] is False
    assert len(bridge.mirror_calls) == 1
    assert bridge.mirror_calls[0]["doc"]["oauth_connection_ref"].startswith("enc-v1:")
    assert result["mongo"]["reason"] == "removed"


def test_write_google_oauth_token_fails_when_supabase_primary_fails(monkeypatch):
    bridge = _FakeBridge(mirror_ok=False)
    monkeypatch.setattr(
        oauth_runtime,
        "get_oauth_token_store_settings",
        lambda: {"supabase_primary_enabled": True, "mongo_mirror_enabled": True},
    )
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)

    result = asyncio.run(
        write_google_oauth_token(
            "tenant-123",
            "user-456",
            "google_calendar",
            "refresh-token-123",
            ["calendar.readonly"],
        )
    )

    assert result["ok"] is False
    assert result["primary_store"] == "supabase"
    assert result["effective_store"] is None
    assert result["degraded"] is False
    assert result["mongo"]["reason"] == "removed"


def test_clear_google_oauth_token_clears_supabase_only(monkeypatch):
    bridge = _FakeBridge(mirror_ok=True)
    monkeypatch.setattr(
        oauth_runtime,
        "get_oauth_token_store_settings",
        lambda: {"supabase_primary_enabled": True, "mongo_mirror_enabled": True},
    )
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)

    result = asyncio.run(
        clear_google_oauth_token(
            "tenant-123",
            "user-456",
            "google_calendar",
            account_email="owner@example.com",
            scopes=["calendar.readonly"],
            updated_at="2026-01-03T00:00:00+00:00",
        )
    )

    assert result["ok"] is True
    assert result["primary_store"] == "supabase"
    assert result["effective_store"] == "supabase"
    assert bridge.mirror_calls[0]["doc"]["oauth_connection_ref"] == ""
    assert result["mongo"]["reason"] == "removed"


def test_clear_google_oauth_token_succeeds_without_mongo_when_supabase_is_available(monkeypatch):
    bridge = _FakeBridge(mirror_ok=True)
    monkeypatch.setattr(
        oauth_runtime,
        "get_oauth_token_store_settings",
        lambda: {"supabase_primary_enabled": True, "mongo_mirror_enabled": False},
    )
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)

    result = asyncio.run(
        clear_google_oauth_token(
            "tenant-123",
            "user-456",
            "google_calendar",
            account_email="owner@example.com",
            scopes=["calendar.readonly"],
            updated_at="2026-01-03T00:00:00+00:00",
        )
    )

    assert result["ok"] is True
    assert result["effective_store"] == "supabase"
    assert result["mongo"]["reason"] == "removed"


def test_backfill_google_oauth_tokens_from_mongo_reports_removed():
    result = asyncio.run(backfill_google_oauth_tokens_from_mongo())

    assert result["ok"] is False
    assert result["reason"] == "mongo_backfill_removed"
