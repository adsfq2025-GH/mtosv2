import asyncio
import os
from types import SimpleNamespace

import jwt
from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "unit-test-jwt-secret")
os.environ.setdefault("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())

import connectors
from db import encrypt_secret
import oauth_runtime
from oauth_runtime import (
    OAUTH_STATE_ALG,
    OAUTH_STATE_SECRET,
    backfill_google_oauth_tokens_from_mongo,
    build_google_oauth_state,
    build_inline_oauth_connection_ref,
    clear_google_oauth_token,
    decode_google_oauth_state,
    decode_inline_oauth_connection_ref,
    get_google_oauth_runtime_doc,
    write_google_oauth_token,
)


class _FakeTokenCollection:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, query):
        return self.doc

    def find(self, query):
        raise AssertionError("find should not be called in this test")


class _FakeUpdateResult:
    matched_count = 0
    modified_count = 1
    upserted_id = "mongo-upsert-id"


class _FakeDeleteResult:
    deleted_count = 1


class _FakeWritableTokenCollection:
    def __init__(self):
        self.updates = []
        self.deletes = []

    async def update_one(self, query, update, upsert=False):
        self.updates.append({"query": query, "update": update, "upsert": upsert})
        return _FakeUpdateResult()

    async def delete_one(self, query):
        self.deletes.append({"query": query})
        return _FakeDeleteResult()


class _FakeUsersCollection:
    def __init__(self, users_by_id=None):
        self.users_by_id = users_by_id or {}

    async def find_one(self, query):
        return self.users_by_id.get(str((query or {}).get("_id") or "").strip())


class _FakeAsyncCursor:
    def __init__(self, docs):
        self.docs = list(docs)
        self._limit = None

    def limit(self, limit_value):
        self._limit = int(limit_value)
        return self

    def __aiter__(self):
        items = self.docs[: self._limit] if self._limit else self.docs
        self._iter = iter(items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeBackfillTokenCollection:
    def __init__(self, docs):
        self.docs = list(docs)
        self.queries = []

    def find(self, query):
        self.queries.append(query)
        return _FakeAsyncCursor(self.docs)


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


def test_inline_oauth_connection_ref_round_trip():
    ref = build_inline_oauth_connection_ref("refresh-token-123")

    assert ref.startswith("enc-v1:")
    assert decode_inline_oauth_connection_ref(ref) == "refresh-token-123"


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


def test_get_google_oauth_runtime_doc_falls_back_to_mongo(monkeypatch):
    async def fake_bridge_doc(tenant_id: str, user_id: str, platform: str):
        return None

    monkeypatch.setattr(oauth_runtime, "get_google_oauth_bridge_account", fake_bridge_doc)
    monkeypatch.setattr(oauth_runtime, "is_no_mongo_oauth_token_read_enabled", lambda: False)
    monkeypatch.setattr(oauth_runtime, "is_mongo_configured", lambda: True)
    monkeypatch.setattr(
        oauth_runtime,
        "db",
        SimpleNamespace(
            user_oauth_tokens=_FakeTokenCollection(
                {
                    "_id": "mongo-token-id",
                    "tenant_id": "tenant-123",
                    "user_id": "user-456",
                    "provider": "google",
                    "platform": "google_calendar",
                    "refresh_token_encrypted": encrypt_secret("mongo-refresh-token"),
                    "scopes": ["calendar.readonly"],
                    "account_email": "owner@example.com",
                    "updated_at": "2026-01-02T00:00:00+00:00",
                }
            )
        ),
    )

    doc = asyncio.run(get_google_oauth_runtime_doc("tenant-123", "user-456", "google_calendar"))

    assert doc is not None
    assert doc["provider"] == "google"
    assert doc["platform"] == "google_calendar"
    assert doc["account_email"] == "owner@example.com"
    assert doc["scopes"] == ["calendar.readonly"]
    assert decode_inline_oauth_connection_ref(doc["oauth_connection_ref"]) == "mongo-refresh-token"


def test_write_google_oauth_token_uses_supabase_primary_with_mongo_mirror(monkeypatch):
    collection = _FakeWritableTokenCollection()
    bridge = _FakeBridge(mirror_ok=True)
    monkeypatch.setattr(
        oauth_runtime,
        "get_oauth_token_store_settings",
        lambda: {"supabase_primary_enabled": True, "mongo_mirror_enabled": True},
    )
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)
    monkeypatch.setattr(oauth_runtime, "db", SimpleNamespace(user_oauth_tokens=collection))

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
    assert len(collection.updates) == 1


def test_write_google_oauth_token_falls_back_to_mongo_when_supabase_primary_fails(monkeypatch):
    collection = _FakeWritableTokenCollection()
    bridge = _FakeBridge(mirror_ok=False)
    monkeypatch.setattr(
        oauth_runtime,
        "get_oauth_token_store_settings",
        lambda: {"supabase_primary_enabled": True, "mongo_mirror_enabled": True},
    )
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)
    monkeypatch.setattr(oauth_runtime, "db", SimpleNamespace(user_oauth_tokens=collection))

    result = asyncio.run(
        write_google_oauth_token(
            "tenant-123",
            "user-456",
            "google_calendar",
            "refresh-token-123",
            ["calendar.readonly"],
        )
    )

    assert result["ok"] is True
    assert result["primary_store"] == "supabase"
    assert result["effective_store"] == "mongo"
    assert result["degraded"] is True
    assert len(collection.updates) == 1


def test_clear_google_oauth_token_clears_supabase_then_deletes_mongo(monkeypatch):
    collection = _FakeWritableTokenCollection()
    bridge = _FakeBridge(mirror_ok=True)
    monkeypatch.setattr(
        oauth_runtime,
        "get_oauth_token_store_settings",
        lambda: {"supabase_primary_enabled": True, "mongo_mirror_enabled": True},
    )
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)
    monkeypatch.setattr(oauth_runtime, "db", SimpleNamespace(user_oauth_tokens=collection))

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
    assert len(collection.deletes) == 1


def test_clear_google_oauth_token_succeeds_without_mongo_when_supabase_is_available(monkeypatch):
    bridge = _FakeBridge(mirror_ok=True)
    monkeypatch.setattr(
        oauth_runtime,
        "get_oauth_token_store_settings",
        lambda: {"supabase_primary_enabled": True, "mongo_mirror_enabled": False},
    )
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)
    monkeypatch.setattr(oauth_runtime, "is_mongo_configured", lambda: False)

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
    assert result["mongo"]["reason"] == "mongo_not_configured"


def test_backfill_google_oauth_tokens_from_mongo_mirrors_active_tokens(monkeypatch):
    encrypted = encrypt_secret("mongo-refresh-token")
    token_collection = _FakeBackfillTokenCollection(
        [
            {
                "tenant_id": "tenant-123",
                "user_id": "user-456",
                "provider": "google",
                "platform": "google_calendar",
                "refresh_token_encrypted": encrypted,
                "scopes": ["calendar.readonly"],
                "updated_at": "2026-01-02T00:00:00+00:00",
            }
        ]
    )
    bridge = _FakeBridge(mirror_ok=True)
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)
    monkeypatch.setattr(
        oauth_runtime,
        "db",
        SimpleNamespace(
            user_oauth_tokens=token_collection,
            users=_FakeUsersCollection({"user-456": {"_id": "user-456", "email": "owner@example.com"}}),
        ),
    )

    result = asyncio.run(backfill_google_oauth_tokens_from_mongo(limit=10))

    assert result["ok"] is True
    assert result["scanned"] == 1
    assert result["eligible"] == 1
    assert result["mirrored"] == 1
    assert result["failed"] == 0
    assert token_collection.queries[0]["provider"] == "google"
    assert bridge.mirror_calls[0]["reason"] == "oauth_token_mongo_backfill"
    assert bridge.mirror_calls[0]["doc"]["oauth_connection_ref"].startswith("enc-v1:")


def test_backfill_google_oauth_tokens_from_mongo_reports_failures(monkeypatch):
    encrypted = encrypt_secret("mongo-refresh-token")
    token_collection = _FakeBackfillTokenCollection(
        [
            {
                "tenant_id": "tenant-123",
                "user_id": "user-456",
                "provider": "google",
                "platform": "google_calendar",
                "refresh_token_encrypted": encrypted,
            }
        ]
    )
    bridge = _FakeBridge(mirror_ok=False)
    monkeypatch.setattr(oauth_runtime, "get_runtime_bridge", lambda: bridge)
    monkeypatch.setattr(
        oauth_runtime,
        "db",
        SimpleNamespace(
            user_oauth_tokens=token_collection,
            users=_FakeUsersCollection({"user-456": {"_id": "user-456", "email": "owner@example.com"}}),
        ),
    )

    result = asyncio.run(backfill_google_oauth_tokens_from_mongo())

    assert result["ok"] is False
    assert result["mirrored"] == 0
    assert result["failed"] == 1
    assert result["sample_failures"][0]["tenant_id"] == "tenant-123"


def test_backfill_google_oauth_tokens_from_mongo_reports_when_mongo_is_not_configured(monkeypatch):
    monkeypatch.setattr(oauth_runtime, "is_mongo_configured", lambda: False)

    result = asyncio.run(backfill_google_oauth_tokens_from_mongo())

    assert result["ok"] is False
    assert result["reason"] == "mongo_not_configured"
