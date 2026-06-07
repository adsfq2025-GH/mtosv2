from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

import httpx

import ai
import connectors
from db import db, utcnow
from models import ActionItem, Client, Meeting, User


def _tenant_scope(tenant_id: str) -> dict:
    return {"$or": [{"tenant_id": tenant_id}, {"tenant_id": {"$exists": False}}]}


async def _ensure_meeting_for_client(tenant_id: str, client: Client, user: Optional[User]) -> Meeting:
    title = f"Monthly Touch — {utcnow().strftime('%B %Y')}"
    existing = await db.meetings.find_one({"$and": [{"client_id": client.id, "title": title}, _tenant_scope(tenant_id)]})
    if existing:
        return Meeting.from_mongo(existing)

    meeting = Meeting(
        tenant_id=tenant_id,
        client_id=client.id,
        client_name=client.name,
        account_manager_id=(user.id if user else client.account_manager_id),
        account_manager_name=(user.name if user else client.account_manager_name),
        title=title,
        scheduled_at=None,
        google_meet_url=None,
        duration_minutes=60,
        status="prep",
    )
    await db.meetings.insert_one(meeting.to_mongo())
    return meeting


async def _upsert_action_item(tenant_id: str, client_id: str, meeting_id: str, title: str, description: str, owner: Optional[str]) -> ActionItem:
    existing = await db.action_items.find_one(
        {"$and": [{"client_id": client_id, "meeting_id": meeting_id, "title": title}, _tenant_scope(tenant_id)]}
    )
    if existing:
        return ActionItem.from_mongo(existing)
    due = (utcnow() + timedelta(days=14)).date().isoformat()
    item = ActionItem(
        tenant_id=tenant_id,
        client_id=client_id,
        meeting_id=meeting_id,
        title=title,
        description=description,
        owner=owner,
        due_date=due,
        priority="medium",
        status="open",
    )
    await db.action_items.insert_one(item.to_mongo())
    return item


async def _push_action_item_to_clickup(tenant_id: str, item: ActionItem, client_id: str) -> ActionItem:
    if item.external_id or item.pushed_to:
        return item

    creds = await connectors.get_credentials(tenant_id, "clickup")
    binding = await connectors.get_client_binding(tenant_id, client_id, "clickup")
    token = (creds or {}).get("api_token", "").strip()
    external_ids = (binding.get("external_ids") or {}) if binding else {}
    config = (binding.get("config") or {}) if binding else {}
    list_id = external_ids.get("action_list_id") or external_ids.get("list_id") or config.get("action_list_id") or config.get("list_id")
    folder_id = external_ids.get("folder_id") or config.get("folder_id")
    if not token or (not list_id and not folder_id):
        return item

    headers = {"Authorization": token, "Content-Type": "application/json", "Accept": "application/json"}

    async def ensure_action_list_id() -> Optional[str]:
        nonlocal list_id
        if list_id:
            return str(list_id)
        if not folder_id:
            return None
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"https://api.clickup.com/api/v2/folder/{folder_id}/list", headers={"Authorization": token, "Accept": "application/json"}, params={"archived": "false"})
        if resp.status_code == 200:
            lists = (resp.json() or {}).get("lists") or []
            for l in lists:
                if (l.get("name") or "").strip().lower() == "mtos action items" and l.get("id"):
                    list_id = str(l.get("id"))
                    break
            if not list_id and lists and (lists[0] or {}).get("id"):
                list_id = str((lists[0] or {}).get("id"))
        if not list_id:
            async with httpx.AsyncClient(timeout=30) as client:
                resp2 = await client.post(
                    f"https://api.clickup.com/api/v2/folder/{folder_id}/list",
                    headers={"Authorization": token, "Content-Type": "application/json", "Accept": "application/json"},
                    json={"name": "MTOS Action Items"},
                )
            if resp2.status_code in (200, 201):
                list_id = str((resp2.json() or {}).get("id") or (resp2.json() or {}).get("list", {}).get("id") or "")
        if list_id:
            await db.client_bindings.update_one(
                {"$and": [{"client_id": client_id, "platform": "clickup"}, _tenant_scope(tenant_id)]},
                {"$set": {"external_ids.action_list_id": str(list_id), "updated_at": utcnow().isoformat()}},
            )
        return str(list_id) if list_id else None

    target_list_id = await ensure_action_list_id()
    if not target_list_id:
        return item

    url = f"https://api.clickup.com/api/v2/list/{target_list_id}/task"
    payload: Dict[str, Any] = {"name": item.title, "description": item.description or ""}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        return item

    data = resp.json() or {}
    external_id = data.get("id")
    external_url = data.get("url")
    update: Dict[str, Any] = {"pushed_to": "clickup", "external_id": external_id, "external_url": external_url, "updated_at": utcnow().isoformat()}
    await db.action_items.update_one({"_id": item.id, **_tenant_scope(tenant_id)}, {"$set": update})
    doc = await db.action_items.find_one({"_id": item.id, **_tenant_scope(tenant_id)})
    return ActionItem.from_mongo(doc) if doc else item


async def generate_for_client(
    tenant_id: str,
    client_id: str,
    *,
    user: Optional[User] = None,
    model_key: Optional[str] = None,
    extra_context: Optional[str] = None,
    push_clickup_actions: bool = True,
) -> Meeting:
    c_doc = await db.clients.find_one({"_id": client_id, **_tenant_scope(tenant_id)})
    if not c_doc:
        raise ValueError("Client not found")
    client = Client.from_mongo(c_doc)

    meeting = await _ensure_meeting_for_client(tenant_id, client, user)

    kpi = await connectors.build_kpi_snapshot(tenant_id, client_id, client.company, user_id=(user.id if user else None))
    brief = await ai.generate_meeting_brief(
        client=client.model_dump(),
        kpi_snapshot=kpi,
        extra_context=extra_context,
        model_key=model_key or ai.DEFAULT_MODEL,
        session_id=f"monthly-touch-{meeting.id}",
    )

    update = {
        "wins": brief["wins"],
        "wins_library": brief.get("wins_library") or [],
        "issues": brief["issues"],
        "issues_library": brief.get("issues_library") or [],
        "talking_points": brief["talking_points"],
        "talking_points_library": brief.get("talking_points_library") or [],
        "suggested_questions": brief["suggested_questions"],
        "prep_checklist": brief.get("prep_checklist") or [],
        "ace_up_the_sleeve": brief.get("ace_up_the_sleeve") or [],
        "testimonial_opportunity": brief["testimonial_opportunity"],
        "strategic_recommendations": brief["strategic_recommendations"],
        "health_signal": brief["health_signal"],
        "kpi_snapshot": kpi,
        "brief_generated_at": utcnow().isoformat(),
        "brief_model": model_key or ai.DEFAULT_MODEL,
        "status": "prep",
        "updated_at": utcnow().isoformat(),
    }
    await db.meetings.update_one({"_id": meeting.id, **_tenant_scope(tenant_id)}, {"$set": update})
    m_doc = await db.meetings.find_one({"_id": meeting.id, **_tenant_scope(tenant_id)})
    meeting = Meeting.from_mongo(m_doc) if m_doc else meeting

    owner = meeting.account_manager_name or meeting.account_manager_id
    created_items: List[ActionItem] = []

    for issue in meeting.issues or []:
        title = f"Fix: {issue.title}".strip()
        desc = (issue.action_plan or issue.description or "").strip()
        if desc:
            created_items.append(await _upsert_action_item(tenant_id, client.id, meeting.id, title, desc, owner))

    for rec in meeting.strategic_recommendations or []:
        r = (rec or "").strip()
        if r:
            created_items.append(await _upsert_action_item(tenant_id, client.id, meeting.id, f"Recommendation: {r}", r, owner))

    if push_clickup_actions:
        for item in created_items:
            try:
                await _push_action_item_to_clickup(tenant_id, item, client.id)
            except Exception:
                pass

    return meeting


async def generate_for_all(*, model_key: Optional[str] = None, extra_context: Optional[str] = None) -> Dict[str, Any]:
    clients = await db.clients.find({"status": "active"}).to_list(1000)
    ok = 0
    failed: List[Dict[str, str]] = []
    for c in clients:
        try:
            client = Client.from_mongo(c)
            tenant_id = str(c.get("tenant_id") or "default")
            await generate_for_client(tenant_id, client.id, model_key=model_key, extra_context=extra_context, push_clickup_actions=True)
            ok += 1
        except Exception as e:
            failed.append({"client_id": str(c.get("_id")), "error": str(e)})
    return {"ok": True, "processed": len(clients), "succeeded": ok, "failed": failed}
