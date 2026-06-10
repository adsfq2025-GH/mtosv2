"""Configuration for Phase 2 bridge scripts."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeSettings:
    mongo_url: str
    db_name: str
    supabase_url: str
    supabase_service_role_key: str
    supabase_db_schema: str = "public"
    source_system: str = "mongo"


def _read_required(name: str) -> str:
    value = str(os.environ.get(name, "")).strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_settings() -> BridgeSettings:
    return BridgeSettings(
        mongo_url=_read_required("MONGO_URL"),
        db_name=_read_required("DB_NAME"),
        supabase_url=_read_required("SUPABASE_URL").rstrip("/"),
        supabase_service_role_key=_read_required("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_db_schema=str(os.environ.get("SUPABASE_DB_SCHEMA", "public")).strip() or "public",
        source_system=str(os.environ.get("BRIDGE_SOURCE_SYSTEM", "mongo")).strip() or "mongo",
    )
