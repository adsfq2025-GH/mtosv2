import asyncio

from db import db
from models import TenantSettings
import ai_territory_intelligence


async def main() -> None:
    tenants = await db.tenants.find({"status": "active"}).to_list(5000)
    for t in tenants or []:
        tenant_id = str(t.get("_id") or "").strip()
        if not tenant_id:
            continue
        sdoc = await db.tenant_settings.find_one({"tenant_id": tenant_id})
        settings = TenantSettings.from_mongo(sdoc) if sdoc else TenantSettings(tenant_id=tenant_id)
        analysis = settings.analysis or {}
        if not isinstance(analysis, dict):
            analysis = {}
        freq = int(analysis.get("ai_territory_scan_frequency_hours") or 24)
        max_prompts = int(analysis.get("ai_territory_max_prompts") or 60)
        freq = max(1, min(freq, 168))
        max_prompts = max(10, min(max_prompts, 200))

        clients = await db.clients.find({"$and": [{"tenant_id": tenant_id}, {"status": "active"}]}).to_list(5000)
        for c in clients or []:
            try:
                await ai_territory_intelligence.run_ai_territory_scan_for_client(
                    tenant_id=tenant_id,
                    client_doc=c,
                    max_prompts=max_prompts,
                    min_hours_between_scans=freq,
                    force=False,
                    reason="scheduled",
                )
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())

