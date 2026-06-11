"""Typer CLI for Phase 2 additive Mongo-to-Supabase bridge runs."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from .config import get_settings
from .mongo_stage import ENTITY_COLLECTIONS, build_stage_rows, open_mongo
from .postgrest import SupabaseBridgeClient

app = typer.Typer(add_completion=False, help="Phase 2 additive bridge CLI.")

DEFAULT_ENTITIES = ",".join(ENTITY_COLLECTIONS.keys())
ENTITY_TO_RPC = {
    "users": "bridge_apply_users",
    "tenants": "bridge_apply_tenants",
    "memberships": "bridge_apply_memberships",
    "clients": "bridge_apply_clients",
    "meetings": "bridge_apply_meetings",
    "integrations": "bridge_apply_integrations",
    "client_bindings": "bridge_apply_client_bindings",
}


def _parse_entities(raw: str) -> list[str]:
    entities = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    if not entities:
        raise typer.BadParameter("At least one entity is required.")
    unknown = [entity for entity in entities if entity not in ENTITY_COLLECTIONS]
    if unknown:
        raise typer.BadParameter(f"Unknown entities: {', '.join(sorted(unknown))}")
    return entities


def _chunks(items: list[dict], size: int = 250):
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def _bridge_client() -> SupabaseBridgeClient:
    return SupabaseBridgeClient(get_settings())


def _create_import_run(
    client: SupabaseBridgeClient,
    *,
    entities: list[str],
    notes: str,
    git_branch: Optional[str] = None,
    neon_branch: Optional[str] = None,
) -> str:
    row = client.insert_row(
        "bridge_import_runs",
        {
            "source_system": client.settings.source_system,
            "entity_scope": entities,
            "status": "staged",
            "notes": notes,
            "git_branch": git_branch,
            "neon_branch": neon_branch,
        },
    )
    run_id = str(row.get("id") or "").strip()
    if not run_id:
        raise RuntimeError("Failed to create bridge_import_runs row.")
    return run_id


def _stage_entities(
    run_id: str,
    *,
    entities: list[str],
    tenant_source_id: Optional[str],
    limit_per_entity: Optional[int],
) -> dict[str, int]:
    settings = get_settings()
    client = _bridge_client()
    mongo_client, mongo_db = open_mongo(settings)
    staged_counts: dict[str, int] = {}
    try:
        for entity in entities:
            rows = build_stage_rows(
                mongo_db,
                entity,
                run_id,
                source_system=settings.source_system,
                tenant_source_id=tenant_source_id,
                limit=limit_per_entity,
            )
            for chunk in _chunks(rows):
                client.insert_rows(
                    "bridge_staging_payloads",
                    chunk,
                    on_conflict="import_run_id,entity_type,source_id",
                )
            staged_counts[entity] = len(rows)
    finally:
        mongo_client.close()
    return staged_counts


@app.command("stage")
def stage_command(
    run_id: Optional[str] = typer.Option(None, help="Existing import run id. If omitted, a new run is created."),
    entities: str = typer.Option(DEFAULT_ENTITIES, help="Comma-separated entity list."),
    notes: str = typer.Option("Phase 2 staged backfill", help="Run notes."),
    git_branch: Optional[str] = typer.Option(None, help="Git branch label."),
    neon_branch: Optional[str] = typer.Option(None, help="Neon branch label."),
    tenant_source_id: Optional[str] = typer.Option(None, help="Optional source tenant id filter."),
    limit_per_entity: Optional[int] = typer.Option(None, help="Optional per-entity Mongo limit."),
):
    entity_list = _parse_entities(entities)
    client = _bridge_client()
    final_run_id = run_id or _create_import_run(
        client,
        entities=entity_list,
        notes=notes,
        git_branch=git_branch,
        neon_branch=neon_branch,
    )
    staged_counts = _stage_entities(
        final_run_id,
        entities=entity_list,
        tenant_source_id=tenant_source_id,
        limit_per_entity=limit_per_entity,
    )
    typer.echo(json.dumps({"run_id": final_run_id, "staged": staged_counts}, indent=2))


@app.command("apply")
def apply_command(
    run_id: str = typer.Option(..., help="Existing import run id."),
    entities: str = typer.Option(DEFAULT_ENTITIES, help="Comma-separated entity list."),
    use_all_rpc: bool = typer.Option(True, help="Call bridge_apply_all when true."),
):
    entity_list = _parse_entities(entities)
    client = _bridge_client()

    if use_all_rpc and entity_list == list(ENTITY_COLLECTIONS.keys()):
        result = client.rpc("bridge_apply_all", {"p_import_run_id": run_id})
    else:
        result = {}
        for entity in entity_list:
            result[entity] = client.rpc(ENTITY_TO_RPC[entity], {"p_import_run_id": run_id})
        client.rpc("bridge_refresh_run_snapshots", {"p_import_run_id": run_id})

    typer.echo(json.dumps({"run_id": run_id, "result": result}, indent=2))


@app.command("summary")
def summary_command(
    run_id: str = typer.Option(..., help="Existing import run id."),
):
    client = _bridge_client()
    summary = client.select(
        "bridge_run_entity_summary_v",
        import_run_id=f"eq.{run_id}",
        order="entity_type.asc",
    )
    issues = client.select(
        "bridge_issue_summary_v",
        import_run_id=f"eq.{run_id}",
        order="entity_type.asc,severity.asc,code.asc",
    )
    typer.echo(json.dumps({"run_id": run_id, "summary": summary, "issues": issues}, indent=2))


@app.command("run-all")
def run_all_command(
    entities: str = typer.Option(DEFAULT_ENTITIES, help="Comma-separated entity list."),
    notes: str = typer.Option("Phase 2 additive backfill run", help="Run notes."),
    git_branch: Optional[str] = typer.Option(None, help="Git branch label."),
    neon_branch: Optional[str] = typer.Option(None, help="Neon branch label."),
    tenant_source_id: Optional[str] = typer.Option(None, help="Optional source tenant id filter."),
    limit_per_entity: Optional[int] = typer.Option(None, help="Optional per-entity Mongo limit."),
):
    entity_list = _parse_entities(entities)
    client = _bridge_client()
    run_id = _create_import_run(
        client,
        entities=entity_list,
        notes=notes,
        git_branch=git_branch,
        neon_branch=neon_branch,
    )
    staged = _stage_entities(
        run_id,
        entities=entity_list,
        tenant_source_id=tenant_source_id,
        limit_per_entity=limit_per_entity,
    )

    if entity_list == list(ENTITY_COLLECTIONS.keys()):
        result = client.rpc("bridge_apply_all", {"p_import_run_id": run_id})
    else:
        result = {}
        for entity in entity_list:
            result[entity] = client.rpc(ENTITY_TO_RPC[entity], {"p_import_run_id": run_id})
        client.rpc("bridge_refresh_run_snapshots", {"p_import_run_id": run_id})

    summary = client.select(
        "bridge_run_entity_summary_v",
        import_run_id=f"eq.{run_id}",
        order="entity_type.asc",
    )
    issues = client.select(
        "bridge_issue_summary_v",
        import_run_id=f"eq.{run_id}",
        order="entity_type.asc,severity.asc,code.asc",
    )

    typer.echo(
        json.dumps(
            {
                "run_id": run_id,
                "staged": staged,
                "result": result,
                "summary": summary,
                "issues": issues,
            },
            indent=2,
        )
    )


@app.command("oauth-token-backfill")
def oauth_token_backfill_command(
    tenant_id: Optional[str] = typer.Option(None, help="Optional legacy tenant id filter."),
    user_id: Optional[str] = typer.Option(None, help="Optional legacy user id filter."),
    platform: Optional[str] = typer.Option(None, help="Optional platform filter."),
    limit: Optional[int] = typer.Option(None, help="Optional Mongo row limit."),
):
    from oauth_runtime import backfill_google_oauth_tokens_from_mongo

    result = asyncio.run(
        backfill_google_oauth_tokens_from_mongo(
            tenant_id=tenant_id,
            user_id=user_id,
            platform=platform,
            limit=limit,
        )
    )
    typer.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    app()
