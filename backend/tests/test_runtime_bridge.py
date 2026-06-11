import asyncio

from runtime_bridge import RuntimeBridge, merge_prefer_bridge
from supabase_config import (
    get_oauth_token_store_settings,
    get_runtime_bridge_settings,
    reset_supabase_settings_cache,
)


def test_merge_prefer_bridge_replaces_matches_only():
    mongo_docs = [
        {"_id": "client-a", "name": "Mongo A", "status": "active"},
        {"_id": "client-b", "name": "Mongo B", "status": "paused"},
    ]
    bridge_docs = [
        {"_id": "client-a", "name": "Supabase A", "status": "active"},
        {"_id": "client-c", "name": "Supabase C", "status": "active"},
    ]

    merged = merge_prefer_bridge(mongo_docs, bridge_docs)

    assert merged == [
        {"_id": "client-a", "name": "Supabase A", "status": "active"},
        {"_id": "client-b", "name": "Mongo B", "status": "paused"},
    ]


def test_merge_prefer_bridge_can_include_bridge_only_docs():
    mongo_docs = [{"platform": "clickup", "status": "not_connected"}]
    bridge_docs = [
        {"platform": "clickup", "status": "connected"},
        {"platform": "google_ads", "status": "connected"},
    ]

    merged = merge_prefer_bridge(
        mongo_docs,
        bridge_docs,
        key_field="platform",
        include_bridge_only=True,
    )

    assert merged[0]["status"] == "connected"
    assert any(item["platform"] == "google_ads" for item in merged)


def test_client_row_to_doc_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("clients",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    row = {
        "id": "supabase-client-id",
        "legacy_source_id": "mongo-client-id",
        "tenant_id": "supabase-tenant-id",
        "name": "Acme",
        "company": "Acme Co",
        "account_manager_user_id": "supabase-user-id",
        "mrr": "4500.25",
        "health_score": "82",
        "crm_data": {"pipeline": "won"},
        "services": ["SEO"],
        "is_deleted": False,
    }

    doc = bridge._client_row_to_doc(
        row,
        "mongo-tenant-id",
        {"supabase-user-id": "mongo-user-id"},
    )

    assert doc["_id"] == "mongo-client-id"
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["account_manager_id"] == "mongo-user-id"
    assert doc["mrr"] == 4500.25
    assert doc["health_score"] == 82
    assert doc["services"] == ["SEO"]


def test_meeting_row_to_doc_requires_client_legacy_mapping():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("meetings",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    row = {
        "id": "supabase-meeting-id",
        "legacy_source_id": "mongo-meeting-id",
        "client_id": "supabase-client-id",
        "account_manager_user_id": "supabase-user-id",
        "title": "QBR",
        "wins": [{"title": "More leads", "description": "Up 20%"}],
        "feedback": {"lead_quality": 5},
        "duration_minutes": "45",
    }

    doc = bridge._meeting_row_to_doc(
        row,
        "mongo-tenant-id",
        {"supabase-client-id": "mongo-client-id"},
        {"supabase-user-id": "mongo-user-id"},
    )

    assert doc is not None
    assert doc["_id"] == "mongo-meeting-id"
    assert doc["client_id"] == "mongo-client-id"
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["account_manager_id"] == "mongo-user-id"
    assert doc["duration_minutes"] == 45
    assert doc["feedback"] == {"lead_quality": 5}


def test_resolve_tenant_legacy_id_from_host_uses_supabase_slug_lookup():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("tenants",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_select(relation: str, **kwargs):
        if relation == "tenants":
            return [{"id": "supabase-tenant-id", "legacy_source_id": "mongo-tenant-id", "slug": "acme", "status": "active"}]
        return []

    bridge._safe_select = fake_select  # type: ignore[method-assign]

    result = asyncio.run(bridge.resolve_tenant_legacy_id_from_host("acme.mapranking.com"))

    assert result == "mongo-tenant-id"


def test_runtime_bridge_settings_allow_opt_in_phase4_domains(monkeypatch):
    monkeypatch.setenv("SUPABASE_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    monkeypatch.setenv("SUPABASE_RUNTIME_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_RUNTIME_BRIDGE_DOMAINS", "clients,settings,domains,client_bindings,unknown")
    reset_supabase_settings_cache()

    settings = get_runtime_bridge_settings()

    assert settings["service_configured"] is True
    assert settings["domains"] == ("client_bindings", "clients", "domains", "settings")
    assert "settings" in settings["supported_domains"]
    assert "client_bindings" in settings["supported_domains"]
    reset_supabase_settings_cache()


def test_runtime_bridge_settings_allow_opt_in_mirror_domains(monkeypatch):
    monkeypatch.setenv("SUPABASE_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    monkeypatch.setenv("SUPABASE_RUNTIME_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_RUNTIME_MIRROR_DOMAINS", "settings,unknown")
    reset_supabase_settings_cache()

    settings = get_runtime_bridge_settings()

    assert settings["service_configured"] is True
    assert settings["mirror_domains"] == ("settings",)
    assert "settings" in settings["supported_mirror_domains"]
    reset_supabase_settings_cache()


def test_runtime_bridge_settings_allow_oauth_account_domains(monkeypatch):
    monkeypatch.setenv("SUPABASE_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    monkeypatch.setenv("SUPABASE_RUNTIME_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_RUNTIME_BRIDGE_DOMAINS", "integrations,oauth_accounts")
    monkeypatch.setenv("SUPABASE_RUNTIME_MIRROR_DOMAINS", "integrations,oauth_accounts")
    reset_supabase_settings_cache()

    settings = get_runtime_bridge_settings()

    assert settings["domains"] == ("integrations", "oauth_accounts")
    assert settings["mirror_domains"] == ("integrations", "oauth_accounts")
    assert "oauth_accounts" in settings["supported_domains"]
    assert "oauth_accounts" in settings["supported_mirror_domains"]
    reset_supabase_settings_cache()


def test_oauth_token_store_settings_support_primary_supabase_flag(monkeypatch):
    monkeypatch.setenv("SUPABASE_OAUTH_TOKEN_PRIMARY_WRITE_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_OAUTH_TOKEN_MONGO_MIRROR_ENABLED", "false")
    monkeypatch.setenv("SUPABASE_OAUTH_TOKEN_NO_MONGO_READS_ENABLED", "true")
    reset_supabase_settings_cache()

    settings = get_oauth_token_store_settings()

    assert settings["supabase_primary_enabled"] is True
    assert settings["mongo_mirror_enabled"] is False
    assert settings["no_mongo_read_enabled"] is True
    reset_supabase_settings_cache()


def test_get_tenant_settings_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("settings",),
            "supported_domains": ("settings",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_settings":
            return [
                {
                    "id": "settings-row-id",
                    "tenant_id": "supabase-tenant-id",
                    "branding": {"product_name": "Monthly Touch OS"},
                    "terminology": {"client_singular": "Client"},
                    "workflows": {"meeting_types": [{"key": "monthly_touch"}]},
                    "analysis": {"ai_default_model": "claude-sonnet"},
                }
            ]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    doc = asyncio.run(bridge.get_tenant_settings("mongo-tenant-id"))

    assert doc is not None
    assert doc["_id"] == "settings-row-id"
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["branding"]["product_name"] == "Monthly Touch OS"


def test_get_tenant_integration_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("integrations",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_integrations":
            return [
                {
                    "id": "integration-row-id",
                    "legacy_source_id": "mongo-integration-id",
                    "platform": "google_oauth",
                    "label": "Google OAuth",
                    "status": "connected",
                    "metadata": {"client_id": "client-123", "redirect_uri": "https://app.example.com/oauth"},
                    "oauth_connection_ref": "vault://google-oauth",
                }
            ]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    doc = asyncio.run(bridge.get_tenant_integration("mongo-tenant-id", "google_oauth"))

    assert doc is not None
    assert doc["_id"] == "mongo-integration-id"
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["platform"] == "google_oauth"
    assert doc["metadata"]["client_id"] == "client-123"


def test_get_user_profile_by_email_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("profiles",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_select(relation: str, **kwargs):
        if relation == "user_profiles":
            return [
                {
                    "id": "supabase-user-id",
                    "legacy_source_id": "mongo-user-id",
                    "email": "owner@example.com",
                    "full_name": "Owner User",
                    "avatar_url": "https://example.com/avatar.png",
                    "auth_provider": "google",
                    "system_role": "platform_admin",
                }
            ]
        return []

    bridge._safe_select = fake_select  # type: ignore[method-assign]

    profile = asyncio.run(bridge.get_user_profile_by_email("owner@example.com"))

    assert profile is not None
    assert profile["id"] == "mongo-user-id"
    assert profile["email"] == "owner@example.com"
    assert profile["name"] == "Owner User"
    assert profile["auth_provider"] == "google"


def test_get_user_oauth_account_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("oauth_accounts",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_resolve_target_user_id(_: str):
        return "supabase-user-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "user_oauth_accounts":
            return [
                {
                    "id": "oauth-row-id",
                    "provider": "google",
                    "platform": "google_calendar",
                    "account_email": "owner@example.com",
                    "scopes": ["calendar.readonly"],
                    "oauth_connection_ref": "vault://oauth/google-calendar",
                }
            ]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_user_id = fake_resolve_target_user_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    doc = asyncio.run(bridge.get_user_oauth_account("mongo-tenant-id", "mongo-user-id", "google", "google_calendar"))

    assert doc is not None
    assert doc["_id"] == "oauth-row-id"
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["user_id"] == "mongo-user-id"
    assert doc["account_email"] == "owner@example.com"
    assert doc["scopes"] == ["calendar.readonly"]


def test_list_user_oauth_accounts_maps_supabase_user_ids_back_to_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("oauth_accounts",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_load_user_legacy_map(user_ids):
        assert user_ids == ["supabase-user-id"]
        return {"supabase-user-id": "mongo-user-id"}

    async def fake_select(relation: str, **kwargs):
        if relation == "user_oauth_accounts":
            return [
                {
                    "id": "oauth-row-id",
                    "tenant_id": "supabase-tenant-id",
                    "user_id": "supabase-user-id",
                    "provider": "google",
                    "platform": "google_business_profile",
                    "account_email": "owner@example.com",
                    "scopes": ["business.manage"],
                    "oauth_connection_ref": "enc-v1:test",
                }
            ]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._load_user_legacy_map = fake_load_user_legacy_map  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    docs = asyncio.run(
        bridge.list_user_oauth_accounts(
            "mongo-tenant-id",
            provider="google",
            platform="google_business_profile",
            limit=5,
        )
    )

    assert len(docs) == 1
    assert docs[0]["tenant_id"] == "mongo-tenant-id"
    assert docs[0]["user_id"] == "mongo-user-id"
    assert docs[0]["platform"] == "google_business_profile"


def test_list_client_bindings_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("client_bindings",),
            "supported_domains": ("client_bindings",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_resolve_target_client_id(_: str, __: str):
        return "supabase-client-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "client_integration_bindings":
            return [
                {
                    "id": "binding-row-id",
                    "legacy_source_id": "mongo-binding-id",
                    "platform": "clickup",
                    "enabled": True,
                    "external_ids": {"list_id": "123"},
                    "config": {"sync_direction": "bidirectional"},
                }
            ]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_client_id = fake_resolve_target_client_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    docs = asyncio.run(bridge.list_client_bindings("mongo-tenant-id", "mongo-client-id"))

    assert len(docs) == 1
    assert docs[0]["_id"] == "mongo-binding-id"
    assert docs[0]["tenant_id"] == "mongo-tenant-id"
    assert docs[0]["client_id"] == "mongo-client-id"
    assert docs[0]["platform"] == "clickup"


def test_smoke_check_reports_phase4_domains():
    bridge = RuntimeBridge(
        {
            "enabled": True,
            "service_configured": True,
            "domains": ("tenants", "settings", "domains", "clients", "client_bindings"),
            "supported_domains": ("tenants", "settings", "domains", "clients", "client_bindings"),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_get_tenant(tenant_id: str):
        return {"_id": tenant_id, "slug": "acme", "status": "active"}

    async def fake_get_tenant_settings(tenant_id: str):
        return {"_id": "settings-row-id", "tenant_id": tenant_id}

    async def fake_list_tenant_domains(tenant_id: str, *, limit: int = 200):
        return [{"_id": "domain-row-id", "tenant_id": tenant_id, "domain": "acme.example.com"}]

    async def fake_list_clients(tenant_id: str, *, limit: int = 1000):
        return [{"_id": "mongo-client-id", "tenant_id": tenant_id, "name": "Acme"}]

    async def fake_list_client_bindings(tenant_id: str, client_id: str, *, limit: int = 100):
        return [{"_id": "mongo-binding-id", "tenant_id": tenant_id, "client_id": client_id, "platform": "clickup"}]

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    bridge.get_tenant = fake_get_tenant  # type: ignore[method-assign]
    bridge.get_tenant_settings = fake_get_tenant_settings  # type: ignore[method-assign]
    bridge.list_tenant_domains = fake_list_tenant_domains  # type: ignore[method-assign]
    bridge.list_clients = fake_list_clients  # type: ignore[method-assign]
    bridge.list_client_bindings = fake_list_client_bindings  # type: ignore[method-assign]
    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]

    result = asyncio.run(bridge.smoke_check("mongo-tenant-id"))

    assert result["target_tenant_id"] == "supabase-tenant-id"
    assert any(check["domain"] == "settings" and check["present"] for check in result["checks"])
    assert any(check["domain"] == "domains" and check["count"] == 1 for check in result["checks"])
    assert any(check["domain"] == "client_bindings" and check["count"] == 1 for check in result["checks"])


def test_safe_mirror_tenant_settings_updates_existing_row():
    bridge = RuntimeBridge(
        {
            "enabled": True,
            "service_configured": True,
            "domains": ("settings",),
            "mirror_domains": ("settings",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_settings":
            return [{"id": "settings-row-id"}]
        return []

    captured: list[dict] = []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, **kwargs})
        return [{"id": "settings-row-id", "tenant_id": "supabase-tenant-id"}]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    result = asyncio.run(
        bridge.safe_mirror_tenant_settings(
            "mongo-tenant-id",
            {
                "tenant_id": "mongo-tenant-id",
                "branding": {"product_name": "Monthly Touch OS"},
                "terminology": {"client_singular": "Client"},
                "workflows": {"meeting_types": [{"key": "monthly_touch"}]},
                "analysis": {"ai_default_model": "claude-sonnet"},
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-02T00:00:00+00:00",
            },
            reason="unit_test_update",
        )
    )

    assert result["attempted"] is True
    assert result["ok"] is True
    assert result["mode"] == "update"
    assert captured[0]["method"] == "PATCH"
    assert captured[0]["relation"] == "tenant_settings"
    assert captured[0]["params"] == {"id": "eq.settings-row-id"}
    assert captured[0]["payload"]["tenant_id"] == "supabase-tenant-id"
    assert captured[0]["payload"]["branding"]["product_name"] == "Monthly Touch OS"


def test_safe_mirror_user_oauth_account_updates_existing_row():
    bridge = RuntimeBridge(
        {
            "enabled": True,
            "service_configured": True,
            "domains": ("oauth_accounts",),
            "mirror_domains": ("oauth_accounts",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_resolve_target_user_id(_: str):
        return "supabase-user-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "user_oauth_accounts":
            return [{"id": "oauth-row-id"}]
        return []

    captured: list[dict] = []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, **kwargs})
        return [{"id": "oauth-row-id", "tenant_id": "supabase-tenant-id"}]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_user_id = fake_resolve_target_user_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    result = asyncio.run(
        bridge.safe_mirror_user_oauth_account(
            "mongo-tenant-id",
            "mongo-user-id",
            {
                "provider": "google",
                "platform": "google_calendar",
                "account_email": "owner@example.com",
                "scopes": ["calendar.readonly"],
                "last_synced_at": "2026-01-02T00:00:00+00:00",
            },
            reason="unit_test_oauth_update",
        )
    )

    assert result["attempted"] is True
    assert result["ok"] is True
    assert result["mode"] == "update"
    assert captured[0]["method"] == "PATCH"
    assert captured[0]["relation"] == "user_oauth_accounts"
    assert captured[0]["params"] == {"id": "eq.oauth-row-id"}
    assert captured[0]["payload"]["tenant_id"] == "supabase-tenant-id"
    assert captured[0]["payload"]["user_id"] == "supabase-user-id"
    assert captured[0]["payload"]["platform"] == "google_calendar"


def test_safe_mirror_tenant_settings_returns_soft_failure():
    bridge = RuntimeBridge(
        {
            "enabled": True,
            "service_configured": True,
            "domains": ("settings",),
            "mirror_domains": ("settings",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_settings":
            return []
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        raise RuntimeError("supabase write unavailable")

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    result = asyncio.run(
        bridge.safe_mirror_tenant_settings(
            "mongo-tenant-id",
            {
                "tenant_id": "mongo-tenant-id",
                "branding": {},
                "terminology": {},
                "workflows": {},
                "analysis": {},
            },
            reason="unit_test_failure",
        )
    )

    assert result["attempted"] is True
    assert result["ok"] is False
    assert result["reason"] == "unit_test_failure"
    assert "unavailable" in result["error"]
