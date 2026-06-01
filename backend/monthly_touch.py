from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

import httpx

import ai
import connectors
from db import db, utcnow
from models import ActionItem, Client, Meeting, User


async def _ensure_meeting_for_client(client: Client, user: Optional[User]) -> Meeting:
    title = f"Monthly Touch — {utcnow().strftime('%B %Y')}"
    existing = await db.meetings.find_one({"client_id": client.id, "title": title})
    if existing:
        return Meeting.from_mongo(existing)

    meeting = Meeting(
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


async def _upsert_action_item(client_id: str, meeting_id: str, title: str, description: str, owner: Optional[str]) -> ActionItem:
    existing = await db.action_items.find_one({"client_id": client_id, "meeting_id": meeting_id, "title": title})
    if existing:
        return ActionItem.from_mongo(existing)
    due = (utcnow() + timedelta(days=14)).date().isoformat()
    item = ActionItem(
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


async def _push_action_item_to_clickup(item: ActionItem, client_id: str) -> ActionItem:
    if item.external_id or item.pushed_to:
        return item

    creds = await connectors.get_credentials("clickup")
    binding = await connectors.get_client_binding(client_id, "clickup")
    token = (creds or {}).get("api_token", "").strip()
    list_id = (binding.get("external_ids") or {}).get("list_id") or (binding.get("config") or {}).get("list_id")
    if not token or not list_id:
        return item

    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    payload: Dict[str, Any] = {"name": item.title, "description": item.description or ""}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        return item

    data = resp.json() or {}
    external_id = data.get("id")
    external_url = data.get("url")
    update: Dict[str, Any] = {"pushed_to": "clickup", "external_id": external_id, "external_url": external_url, "updated_at": utcnow().isoformat()}
    await db.action_items.update_one({"_id": item.id}, {"$set": update})
    doc = await db.action_items.find_one({"_id": item.id})
    return ActionItem.from_mongo(doc) if doc else item


async def generate_for_client(
    client_id: str,
    *,
    user: Optional[User] = None,
    model_key: Optional[str] = None,
    extra_context: Optional[str] = None,
    push_clickup_actions: bool = True,
) -> Meeting:
    c_doc = await db.clients.find_one({"_id": client_id})
    if not c_doc:
        raise ValueError("Client not found")
    client = Client.from_mongo(c_doc)

    meeting = await _ensure_meeting_for_client(client, user)

    kpi = await connectors.build_kpi_snapshot(client_id, client.company)
    brief = await ai.generate_meeting_brief(
        client=client.model_dump(),
        kpi_snapshot=kpi,
        extra_context=extra_context,
        model_key=model_key or ai.DEFAULT_MODEL,
        session_id=f"monthly-touch-{meeting.id}",
    )

    update = {
        "wins": brief["wins"],
        "issues": brief["issues"],
        "talking_points": brief["talking_points"],
        "suggested_questions": brief["suggested_questions"],
        "testimonial_opportunity": brief["testimonial_opportunity"],
        "strategic_recommendations": brief["strategic_recommendations"],
        "health_signal": brief["health_signal"],
        "kpi_snapshot": kpi,
        "brief_generated_at": utcnow().isoformat(),
        "brief_model": model_key or ai.DEFAULT_MODEL,
        "status": "prep",
        "updated_at": utcnow().isoformat(),
    }
    await db.meetings.update_one({"_id": meeting.id}, {"$set": update})
    m_doc = await db.meetings.find_one({"_id": meeting.id})
    meeting = Meeting.from_mongo(m_doc) if m_doc else meeting

    owner = meeting.account_manager_name or meeting.account_manager_id
    created_items: List[ActionItem] = []

    for issue in meeting.issues or []:
        title = f"Fix: {issue.title}".strip()
        desc = (issue.action_plan or issue.description or "").strip()
        if desc:
            created_items.append(await _upsert_action_item(client.id, meeting.id, title, desc, owner))

    for rec in meeting.strategic_recommendations or []:
        r = (rec or "").strip()
        if r:
            created_items.append(await _upsert_action_item(client.id, meeting.id, f"Recommendation: {r}", r, owner))

    if push_clickup_actions:
        for item in created_items:
            await _push_action_item_to_clickup(item, client.id)

    return meeting


async def generate_for_all(*, model_key: Optional[str] = None, extra_context: Optional[str] = None) -> Dict[str, Any]:
    clients = await db.clients.find({"status": "active"}).to_list(1000)
    ok = 0
    failed: List[Dict[str, str]] = []
    for c in clients:
        try:
            await generate_for_client(Client.from_mongo(c).id, model_key=model_key, extra_context=extra_context, push_clickup_actions=True)
            ok += 1
        except Exception as e:
            failed.append({"client_id": str(c.get("_id")), "error": str(e)})
    return {"ok": True, "processed": len(clients), "succeeded": ok, "failed": failed}
