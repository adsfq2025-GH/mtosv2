import asyncio

from runtime_bridge import RuntimeBridge, merge_prefer_bridge


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
