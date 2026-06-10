"""Mongo extract + stage helpers for the Phase 2 bridge."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Iterator, Optional

from bson import ObjectId
from pymongo import MongoClient

from .config import BridgeSettings


ENTITY_COLLECTIONS: dict[str, str] = {
    "users": "users",
    "tenants": "tenants",
    "memberships": "tenant_memberships",
    "clients": "clients",
    "meetings": "meetings",
    "integrations": "integrations",
    "client_bindings": "client_bindings",
}


def open_mongo(settings: BridgeSettings):
    client = MongoClient(settings.mongo_url)
    return client, client[settings.db_name]


def _json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return value


def sanitize_source_document(entity: str, doc: dict[str, Any]) -> dict[str, Any]:
    clean = _json_safe(dict(doc))
    clean["_id"] = str(clean.get("_id", ""))

    if entity == "integrations":
        clean.pop("credentials_encrypted", None)
        clean.pop("access_token_encrypted", None)
        clean.pop("refresh_token_encrypted", None)

    return clean


def iter_source_documents(
    db,
    entity: str,
    *,
    tenant_source_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> Iterator[dict[str, Any]]:
    collection_name = ENTITY_COLLECTIONS[entity]
    query: dict[str, Any] = {}

    if tenant_source_id:
        if entity == "tenants":
            query["_id"] = tenant_source_id
        elif entity != "users":
            query["tenant_id"] = tenant_source_id

    cursor = db[collection_name].find(query)
    if limit:
        cursor = cursor.limit(int(limit))

    for doc in cursor:
        yield sanitize_source_document(entity, doc)


def build_stage_row(
    entity: str,
    run_id: str,
    source_system: str,
    doc: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(doc)
    source_id = str(payload.pop("_id"))
    tenant_source_id = None
    if entity != "tenants":
        tenant_source_id = str(payload.get("tenant_id") or "").strip() or None

    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    return {
        "import_run_id": run_id,
        "entity_type": entity,
        "source_system": source_system,
        "source_collection": ENTITY_COLLECTIONS[entity],
        "source_id": source_id,
        "tenant_source_id": tenant_source_id,
        "payload": payload,
        "payload_checksum": checksum,
        "status": "staged",
    }


def build_stage_rows(
    db,
    entity: str,
    run_id: str,
    *,
    source_system: str,
    tenant_source_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    return [
        build_stage_row(entity, run_id, source_system, doc)
        for doc in iter_source_documents(db, entity, tenant_source_id=tenant_source_id, limit=limit)
    ]
