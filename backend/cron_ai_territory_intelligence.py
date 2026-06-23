import asyncio

from models import TenantSettings
import ai_territory_intelligence
from supabase_store import get_store


async def main() -> None:
    bridge = get_store()
    tenants = await bridge.list_tenants(status="active", limit=5000) if bridge.is_enabled_for("tenants") else []
    for t in tenants or []:
        tenant_id = str(t.get("_id") or "").strip()
        if not tenant_id:
            continue
        sdoc = await bridge.get_tenant_settings(tenant_id) if bridge.is_enabled_for("settings") else None
        settings = TenantSettings.model_validate(sdoc) if sdoc else TenantSettings(tenant_id=tenant_id)
        analysis = settings.analysis or {}
        if not isinstance(analysis, dict):
            analysis = {}
        freq = int(analysis.get("ai_territory_scan_frequency_hours") or 24)
        max_prompts = int(analysis.get("ai_territory_max_prompts") or 60)
        freq = max(1, min(freq, 168))
        max_prompts = max(10, min(max_prompts, 200))

        clients = await bridge.list_clients(tenant_id, limit=5000) if bridge.is_enabled_for("clients") else []
        for c in clients or []:
            if str((c or {}).get("status") or "").strip().lower() not in ("", "active"):
                continue
            try:
                uid = str((c or {}).get("account_manager_id") or "").strip()
                await ai_territory_intelligence.run_ai_territory_scan_for_client(
                    tenant_id=tenant_id,
                    client_doc=c,
                    user_id=uid or None,
                    max_prompts=max_prompts,
                    min_hours_between_scans=freq,
                    force=False,
                    reason="scheduled",
                )
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
