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


def test_get_tenant_domain_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("domains",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_domains":
            return [
                {
                    "id": "domain-row-id",
                    "tenant_id": "supabase-tenant-id",
                    "domain": "acme.example.com",
                    "is_primary": False,
                }
            ]
        if relation == "tenants":
            return [{"id": "supabase-tenant-id", "legacy_source_id": "mongo-tenant-id"}]
        return []

    bridge._safe_select = fake_select  # type: ignore[method-assign]

    doc = asyncio.run(bridge.get_tenant_domain("acme.example.com"))

    assert doc is not None
    assert doc["_id"] == "domain-row-id"
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["domain"] == "acme.example.com"


def test_upsert_tenant_domain_posts_supabase_payload():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("domains",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    captured = []

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_domains":
            return []
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "payload": kwargs.get("payload")})
        return [
            {
                "id": "domain-row-id",
                "tenant_id": "supabase-tenant-id",
                "domain": "acme.example.com",
                "is_primary": True,
            }
        ]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    doc = asyncio.run(bridge.upsert_tenant_domain("mongo-tenant-id", "Acme.Example.com", is_primary=True))

    assert doc is not None
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["domain"] == "acme.example.com"
    assert captured[0]["relation"] == "tenant_domains"
    assert captured[0]["payload"]["tenant_id"] == "supabase-tenant-id"
    assert captured[0]["payload"]["domain"] == "acme.example.com"
    assert captured[0]["payload"]["is_primary"] is True


def test_delete_tenant_domain_soft_deletes_row():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("domains",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    captured = []

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_domains":
            return [{"id": "domain-row-id"}]
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "params": kwargs.get("params"), "payload": kwargs.get("payload")})
        return None

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    deleted = asyncio.run(bridge.delete_tenant_domain("mongo-tenant-id", "acme.example.com"))

    assert deleted is True
    assert captured[0]["relation"] == "tenant_domains"
    assert captured[0]["params"] == {"id": "eq.domain-row-id"}
    assert captured[0]["payload"] == {"is_deleted": True}


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


def test_upsert_tenant_integration_posts_supabase_payload():
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

    captured = []

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_integrations":
            return []
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "payload": kwargs.get("payload")})
        return [
            {
                "id": "integration-row-id",
                "tenant_id": "supabase-tenant-id",
                "platform": "clickup",
                "label": "ClickUp",
                "status": "connected",
                "metadata": {"team_id": "team_123"},
                "credentials_encrypted": {},
            }
        ]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    doc = asyncio.run(
        bridge.upsert_tenant_integration(
            "mongo-tenant-id",
            {
                "platform": "clickup",
                "label": "ClickUp",
                "status": "connected",
                "metadata": {"team_id": "team_123"},
            },
        )
    )

    assert doc is not None
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["platform"] == "clickup"
    assert captured[0]["relation"] == "tenant_integrations"
    assert captured[0]["payload"]["tenant_id"] == "supabase-tenant-id"
    assert captured[0]["payload"]["metadata"]["team_id"] == "team_123"


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


def test_list_user_profiles_preserves_legacy_shape():
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
                    "auth_provider": "email",
                    "system_role": "customer",
                }
            ]
        return []

    bridge._safe_select = fake_select  # type: ignore[method-assign]

    profiles = asyncio.run(bridge.list_user_profiles(limit=10))

    assert len(profiles) == 1
    assert profiles[0]["id"] == "mongo-user-id"
    assert profiles[0]["email"] == "owner@example.com"
    assert profiles[0]["role"] == "customer"


def test_get_user_membership_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("tenants", "profiles"),
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
        if relation == "tenant_members":
            return [
                {
                    "id": "membership-row-id",
                    "tenant_id": "supabase-tenant-id",
                    "user_id": "supabase-user-id",
                    "role": "tenant_owner",
                    "status": "active",
                    "is_default": True,
                }
            ]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_user_id = fake_resolve_target_user_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    membership = asyncio.run(bridge.get_user_membership("mongo-tenant-id", "mongo-user-id"))

    assert membership is not None
    assert membership["tenant_id"] == "mongo-tenant-id"
    assert membership["user_id"] == "mongo-user-id"
    assert membership["role"] == "owner"
    assert membership["status"] == "active"


def test_get_client_binding_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("client_bindings",),
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
                    "tenant_id": "supabase-tenant-id",
                    "client_id": "supabase-client-id",
                    "platform": "clickup",
                    "enabled": True,
                    "external_ids": {"folder_id": "folder_123"},
                    "config": {"team_id": "team_123"},
                }
            ]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_client_id = fake_resolve_target_client_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    doc = asyncio.run(bridge.get_client_binding("mongo-tenant-id", "mongo-client-id", "clickup"))

    assert doc is not None
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["client_id"] == "mongo-client-id"
    assert doc["platform"] == "clickup"
    assert doc["external_ids"]["folder_id"] == "folder_123"


def test_list_user_memberships_maps_tenant_ids_back_to_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("tenants", "profiles"),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_user_id(_: str):
        return "supabase-user-id"

    async def fake_load_tenant_legacy_map(tenant_ids):
        assert tenant_ids == ["supabase-tenant-id"]
        return {"supabase-tenant-id": "mongo-tenant-id"}

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_members":
            return [
                {
                    "id": "membership-row-id",
                    "tenant_id": "supabase-tenant-id",
                    "user_id": "supabase-user-id",
                    "role": "manager",
                    "status": "active",
                    "is_default": False,
                }
            ]
        return []

    bridge.resolve_target_user_id = fake_resolve_target_user_id  # type: ignore[method-assign]
    bridge._load_tenant_legacy_map = fake_load_tenant_legacy_map  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    memberships = asyncio.run(bridge.list_user_memberships("mongo-user-id", limit=10))

    assert len(memberships) == 1
    assert memberships[0]["tenant_id"] == "mongo-tenant-id"
    assert memberships[0]["role"] == "admin"


def test_create_tenant_membership_maps_legacy_role_to_supabase_payload():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("tenants", "profiles"),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    captured = []

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_resolve_target_user_id(_: str):
        return "supabase-user-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "tenant_members":
            return []
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "payload": kwargs.get("payload")})
        return [
            {
                "id": "membership-row-id",
                "tenant_id": "supabase-tenant-id",
                "user_id": "supabase-user-id",
                "role": "tenant_owner",
                "status": "active",
                "is_default": True,
            }
        ]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_user_id = fake_resolve_target_user_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    membership = asyncio.run(
        bridge.create_tenant_membership(
            "mongo-tenant-id",
            "mongo-user-id",
            role="owner",
            status="active",
            is_default=True,
        )
    )

    assert membership is not None
    assert membership["role"] == "owner"
    assert captured[0]["relation"] == "tenant_members"
    assert captured[0]["payload"]["role"] == "tenant_owner"
    assert captured[0]["payload"]["is_default"] is True


def test_upsert_client_binding_posts_supabase_payload():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("client_bindings",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    captured = []

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_resolve_target_client_id(_: str, __: str):
        return "supabase-client-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "client_integration_bindings":
            return []
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "payload": kwargs.get("payload")})
        return [
            {
                "id": "binding-row-id",
                "tenant_id": "supabase-tenant-id",
                "client_id": "supabase-client-id",
                "platform": "clickup",
                "enabled": True,
                "external_ids": {"folder_id": "folder_123"},
                "config": {"team_id": "team_123"},
            }
        ]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_client_id = fake_resolve_target_client_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    doc = asyncio.run(
        bridge.upsert_client_binding(
            "mongo-tenant-id",
            "mongo-client-id",
            {
                "platform": "clickup",
                "enabled": True,
                "external_ids": {"folder_id": "folder_123"},
                "config": {"team_id": "team_123"},
            },
        )
    )

    assert doc is not None
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["client_id"] == "mongo-client-id"
    assert captured[0]["relation"] == "client_integration_bindings"
    assert captured[0]["payload"]["tenant_id"] == "supabase-tenant-id"
    assert captured[0]["payload"]["client_id"] == "supabase-client-id"
    assert captured[0]["payload"]["external_ids"]["folder_id"] == "folder_123"


def test_upsert_client_posts_supabase_payload():
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

    captured = []

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_resolve_target_user_id(_: str):
        return "supabase-user-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "clients":
            return []
        if relation == "user_profiles":
            return [{"id": "supabase-user-id", "legacy_source_id": "mongo-user-id"}]
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "payload": kwargs.get("payload")})
        return [
            {
                "id": "supabase-client-id",
                "tenant_id": "supabase-tenant-id",
                "legacy_source_id": "mongo-client-id",
                "name": "Acme",
                "company": "Acme Co",
                "account_manager_user_id": "supabase-user-id",
                "services": ["SEO"],
                "assigned_products": [],
                "crm_data": {},
                "gbp_data": {},
                "suggestions": [],
                "feedback_rolling_avg": {},
                "churn_risk_indicators": [],
                "sentiment_rolling": {},
                "mrr": 99,
                "health_score": 75,
                "churn_risk_score": 0,
            }
        ]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_user_id = fake_resolve_target_user_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    doc = asyncio.run(
        bridge.upsert_client(
            "mongo-tenant-id",
            {
                "_id": "mongo-client-id",
                "name": "Acme",
                "company": "Acme Co",
                "account_manager_id": "mongo-user-id",
                "services": ["SEO"],
                "mrr": 99,
            },
        )
    )

    assert doc is not None
    assert doc["_id"] == "mongo-client-id"
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert captured[0]["relation"] == "clients"
    assert captured[0]["payload"]["tenant_id"] == "supabase-tenant-id"
    assert captured[0]["payload"]["account_manager_user_id"] == "supabase-user-id"
    assert captured[0]["payload"]["company"] == "Acme Co"


def test_soft_delete_client_marks_row_deleted():
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

    captured = []

    async def fake_resolve_target_client_id(_: str, __: str):
        return "supabase-client-id"

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "params": kwargs.get("params"), "payload": kwargs.get("payload")})
        return None

    bridge.resolve_target_client_id = fake_resolve_target_client_id  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    deleted = asyncio.run(bridge.soft_delete_client("mongo-tenant-id", "mongo-client-id"))

    assert deleted is True
    assert captured[0]["relation"] == "clients"
    assert captured[0]["params"] == {"id": "eq.supabase-client-id"}
    assert captured[0]["payload"] == {"is_deleted": True}


def test_upsert_meeting_posts_supabase_payload():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("meetings", "clients"),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    captured = []

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_resolve_target_client_id(_: str, __: str):
        return "supabase-client-id"

    async def fake_resolve_target_user_id(_: str):
        return "supabase-user-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "meetings":
            return []
        if relation == "clients":
            return [{"id": "supabase-client-id", "legacy_source_id": "mongo-client-id"}]
        if relation == "user_profiles":
            return [{"id": "supabase-user-id", "legacy_source_id": "mongo-user-id"}]
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "payload": kwargs.get("payload")})
        return [
            {
                "id": "supabase-meeting-id",
                "tenant_id": "supabase-tenant-id",
                "legacy_source_id": "mongo-meeting-id",
                "client_id": "supabase-client-id",
                "account_manager_user_id": "supabase-user-id",
                "title": "Monthly Touch",
                "status": "scheduled",
                "duration_minutes": 60,
                "wins": [],
                "wins_library": [],
                "issues": [],
                "issues_library": [],
                "talking_points": [],
                "talking_points_library": [],
                "suggested_questions": [],
                "prep_checklist": [],
                "ace_up_the_sleeve": [],
                "strategic_recommendations": [],
                "campaign_recommendations": [],
                "automation_draft": {},
                "kpi_snapshot": {},
                "transcript_source": {},
                "transcript_analysis": {},
                "transcript_analysis_by_model": {},
                "checklist": {},
                "deliverable_reviews": {},
                "discovery_questions": [],
                "feedback": None,
            }
        ]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_client_id = fake_resolve_target_client_id  # type: ignore[method-assign]
    bridge.resolve_target_user_id = fake_resolve_target_user_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    doc = asyncio.run(
        bridge.upsert_meeting(
            "mongo-tenant-id",
            {
                "_id": "mongo-meeting-id",
                "client_id": "mongo-client-id",
                "account_manager_id": "mongo-user-id",
                "title": "Monthly Touch",
                "duration_minutes": 60,
            },
        )
    )

    assert doc is not None
    assert doc["_id"] == "mongo-meeting-id"
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert captured[0]["relation"] == "meetings"
    assert captured[0]["payload"]["tenant_id"] == "supabase-tenant-id"
    assert captured[0]["payload"]["client_id"] == "supabase-client-id"
    assert captured[0]["payload"]["account_manager_user_id"] == "supabase-user-id"


def test_soft_delete_meeting_marks_row_deleted():
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

    captured = []

    async def fake_resolve_target_meeting_id(_: str, __: str):
        return "supabase-meeting-id"

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "params": kwargs.get("params"), "payload": kwargs.get("payload")})
        return None

    bridge.resolve_target_meeting_id = fake_resolve_target_meeting_id  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    deleted = asyncio.run(bridge.soft_delete_meeting("mongo-tenant-id", "mongo-meeting-id"))

    assert deleted is True
    assert captured[0]["relation"] == "meetings"
    assert captured[0]["params"] == {"id": "eq.supabase-meeting-id"}
    assert captured[0]["payload"] == {"is_deleted": True}


def test_get_action_item_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("action_items", "clients", "meetings"),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "action_items":
            return [
                {
                    "id": "supabase-action-id",
                    "tenant_id": "supabase-tenant-id",
                    "legacy_source_id": "mongo-action-id",
                    "client_id": "supabase-client-id",
                    "meeting_id": "supabase-meeting-id",
                    "title": "Follow up",
                    "status": "open",
                    "priority": "medium",
                    "reminder_count": 2,
                }
            ]
        if relation == "clients":
            return [{"id": "supabase-client-id", "legacy_source_id": "mongo-client-id"}]
        if relation == "meetings":
            return [{"id": "supabase-meeting-id", "legacy_source_id": "mongo-meeting-id"}]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    doc = asyncio.run(bridge.get_action_item("mongo-tenant-id", "mongo-action-id"))

    assert doc is not None
    assert doc["_id"] == "mongo-action-id"
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["client_id"] == "mongo-client-id"
    assert doc["meeting_id"] == "mongo-meeting-id"
    assert doc["reminder_count"] == 2


def test_upsert_action_item_posts_supabase_payload():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("action_items", "clients", "meetings"),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    captured = []

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_resolve_target_client_id(_: str, __: str):
        return "supabase-client-id"

    async def fake_resolve_target_meeting_id(_: str, __: str):
        return "supabase-meeting-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "action_items":
            return []
        if relation == "clients":
            return [{"id": "supabase-client-id", "legacy_source_id": "mongo-client-id"}]
        if relation == "meetings":
            return [{"id": "supabase-meeting-id", "legacy_source_id": "mongo-meeting-id"}]
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "payload": kwargs.get("payload")})
        return [
            {
                "id": "supabase-action-id",
                "tenant_id": "supabase-tenant-id",
                "legacy_source_id": "mongo-action-id",
                "client_id": "supabase-client-id",
                "meeting_id": "supabase-meeting-id",
                "title": "Follow up",
                "status": "open",
                "priority": "medium",
                "owner_type": "agency",
                "reminder_count": 0,
            }
        ]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_client_id = fake_resolve_target_client_id  # type: ignore[method-assign]
    bridge.resolve_target_meeting_id = fake_resolve_target_meeting_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    doc = asyncio.run(
        bridge.upsert_action_item(
            "mongo-tenant-id",
            {
                "_id": "mongo-action-id",
                "client_id": "mongo-client-id",
                "meeting_id": "mongo-meeting-id",
                "title": "Follow up",
                "status": "open",
                "priority": "medium",
            },
        )
    )

    assert doc is not None
    assert doc["_id"] == "mongo-action-id"
    assert captured[0]["relation"] == "action_items"
    assert captured[0]["payload"]["tenant_id"] == "supabase-tenant-id"
    assert captured[0]["payload"]["client_id"] == "supabase-client-id"
    assert captured[0]["payload"]["meeting_id"] == "supabase-meeting-id"
    assert captured[0]["payload"]["legacy_source_id"] == "mongo-action-id"


def test_soft_delete_action_item_marks_row_deleted():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("action_items",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    captured = []

    async def fake_resolve_target_action_item_id(_: str, __: str):
        return "supabase-action-id"

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "params": kwargs.get("params"), "payload": kwargs.get("payload")})
        return None

    bridge.resolve_target_action_item_id = fake_resolve_target_action_item_id  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    deleted = asyncio.run(bridge.soft_delete_action_item("mongo-tenant-id", "mongo-action-id"))

    assert deleted is True
    assert captured[0]["relation"] == "action_items"
    assert captured[0]["params"] == {"id": "eq.supabase-action-id"}
    assert captured[0]["payload"] == {"is_deleted": True}


def test_list_action_items_maps_related_ids_back_to_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("action_items", "clients", "meetings"),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "action_items":
            return [
                {
                    "id": "supabase-action-id",
                    "tenant_id": "supabase-tenant-id",
                    "legacy_source_id": "mongo-action-id",
                    "client_id": "supabase-client-id",
                    "meeting_id": "supabase-meeting-id",
                    "title": "Follow up",
                    "status": "open",
                    "priority": "medium",
                    "owner_type": "agency",
                }
            ]
        if relation == "clients":
            return [{"id": "supabase-client-id", "legacy_source_id": "mongo-client-id"}]
        if relation == "meetings":
            return [{"id": "supabase-meeting-id", "legacy_source_id": "mongo-meeting-id"}]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    docs = asyncio.run(bridge.list_action_items("mongo-tenant-id", limit=10))

    assert len(docs) == 1
    assert docs[0]["_id"] == "mongo-action-id"
    assert docs[0]["client_id"] == "mongo-client-id"
    assert docs[0]["meeting_id"] == "mongo-meeting-id"


def test_list_tenant_client_bindings_maps_client_ids_back_to_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("client_bindings", "clients"),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "client_integration_bindings":
            return [
                {
                    "id": "binding-row-id",
                    "tenant_id": "supabase-tenant-id",
                    "client_id": "supabase-client-id",
                    "platform": "clickup_client_health_tracker",
                    "enabled": True,
                    "external_ids": {"task_id": "task_123"},
                    "config": {},
                }
            ]
        if relation == "clients":
            return [{"id": "supabase-client-id", "legacy_source_id": "mongo-client-id"}]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    docs = asyncio.run(bridge.list_tenant_client_bindings("mongo-tenant-id", platform="clickup_client_health_tracker", enabled=True, limit=10))

    assert len(docs) == 1
    assert docs[0]["client_id"] == "mongo-client-id"
    assert docs[0]["external_ids"]["task_id"] == "task_123"


def test_get_clickup_client_sync_state_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("clickup_sync",),
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
        if relation == "clickup_client_sync_state":
            return [
                {
                    "id": "state-row-id",
                    "tenant_id": "supabase-tenant-id",
                    "user_id": "supabase-user-id",
                    "running": True,
                    "last_run_id": "run_123",
                    "metadata": {"list_id": "list_123"},
                }
            ]
        return []

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_user_id = fake_resolve_target_user_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]

    doc = asyncio.run(bridge.get_clickup_client_sync_state("mongo-tenant-id", "mongo-user-id"))

    assert doc is not None
    assert doc["tenant_id"] == "mongo-tenant-id"
    assert doc["user_id"] == "mongo-user-id"
    assert doc["last_run_id"] == "run_123"
    assert doc["metadata"]["list_id"] == "list_123"


def test_list_tenants_preserves_legacy_shape():
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
            return [
                {
                    "id": "supabase-tenant-id",
                    "legacy_source_id": "mongo-tenant-id",
                    "slug": "acme",
                    "name": "Acme",
                    "status": "active",
                    "metadata": {"plan": "pro"},
                }
            ]
        return []

    bridge._safe_select = fake_select  # type: ignore[method-assign]

    docs = asyncio.run(bridge.list_tenants(status="active", limit=10))

    assert len(docs) == 1
    assert docs[0]["_id"] == "mongo-tenant-id"
    assert docs[0]["id"] == "mongo-tenant-id"
    assert docs[0]["slug"] == "acme"
    assert docs[0]["metadata"]["plan"] == "pro"


def test_create_clickup_client_sync_log_preserves_legacy_shape():
    bridge = RuntimeBridge(
        {
            "service_configured": True,
            "domains": ("clickup_sync",),
            "timeout_seconds": 5,
            "url": "https://example.supabase.co",
            "service_role_key": "test",
            "db_schema": "public",
        }
    )

    captured = []

    async def fake_resolve_target_tenant_id(_: str):
        return "supabase-tenant-id"

    async def fake_resolve_target_user_id(_: str):
        return "supabase-user-id"

    async def fake_select(relation: str, **kwargs):
        if relation == "clickup_client_sync_logs":
            return []
        return []

    async def fake_request(method: str, relation: str, **kwargs):
        captured.append({"method": method, "relation": relation, "payload": kwargs.get("payload")})
        return [
            {
                "id": "log-row-id",
                "tenant_id": "supabase-tenant-id",
                "user_id": "supabase-user-id",
                "legacy_source_id": "run_123",
                "ok": True,
                "created_count": 1,
                "updated_count": 2,
                "paused_count": 3,
                "assigned_found": 4,
                "details": {"debug_sample_account_managers": ["Jane"], "debug_sample_custom_field_names": ["Account Manager"]},
            }
        ]

    bridge.resolve_target_tenant_id = fake_resolve_target_tenant_id  # type: ignore[method-assign]
    bridge.resolve_target_user_id = fake_resolve_target_user_id  # type: ignore[method-assign]
    bridge._safe_select = fake_select  # type: ignore[method-assign]
    bridge._request = fake_request  # type: ignore[method-assign]

    doc = asyncio.run(
        bridge.create_clickup_client_sync_log(
            "mongo-tenant-id",
            "mongo-user-id",
            {
                "run_id": "run_123",
                "ok": True,
                "created": 1,
                "updated": 2,
                "paused": 3,
                "assigned_found": 4,
                "debug_sample_account_managers": ["Jane"],
                "debug_sample_custom_field_names": ["Account Manager"],
            },
        )
    )

    assert doc is not None
    assert doc["run_id"] == "run_123"
    assert doc["created"] == 1
    assert doc["updated"] == 2
    assert captured[0]["relation"] == "clickup_client_sync_logs"
    assert captured[0]["payload"]["legacy_source_id"] == "run_123"


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
