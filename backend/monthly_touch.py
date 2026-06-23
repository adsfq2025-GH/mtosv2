from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

import ai
import connectors
from db import utcnow
from models import ActionItem, Client, Meeting, ReviewMonthlySnapshot, User
from supabase_store import get_store


async def _get_client_doc(tenant_id: str, client_id: str) -> Optional[dict]:
    bridge = get_store()
    if bridge.is_enabled_for("clients"):
        return await bridge.get_client(tenant_id, client_id)
    return None


async def _list_active_client_docs() -> List[dict]:
    bridge = get_store()
    if not bridge.is_enabled_for("clients"):
        return []
    if bridge.is_enabled_for("tenants"):
        tenants = await bridge.list_tenants(status="active", limit=5000)
        docs: List[dict] = []
        for tenant in tenants or []:
            tenant_id = str((tenant or {}).get("_id") or "").strip()
            if not tenant_id:
                continue
            docs.extend(await bridge.list_clients(tenant_id, limit=1000))
        return [doc for doc in docs if str((doc or {}).get("status") or "").strip().lower() == "active"]
    return []


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _parse_dateish(value: Optional[str]) -> Optional[datetime]:
    txt = str(value or "").strip()
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except Exception:
        pass
    try:
        return datetime.fromisoformat(txt[:10])
    except Exception:
        return None


def _month_key(value: Optional[str]) -> str:
    dt = _parse_dateish(value)
    base = dt.date().isoformat() if dt else utcnow().date().isoformat()
    return base[:7]


def merge_brief_extra_context(base: Optional[str], addition: Optional[str]) -> Optional[str]:
    parts = [str(p).strip() for p in (base, addition) if str(p or "").strip()]
    return "\n\n".join(parts) if parts else None


def _prepend_unique_text(items: Any, text: str) -> List[str]:
    out = [str(text).strip()] if str(text).strip() else []
    for item in items or []:
        item_txt = str(item or "").strip()
        if item_txt and item_txt.lower() not in {x.lower() for x in out}:
            out.append(item_txt)
    return out


def _prepend_unique_talking_point(items: Any, topic: str, angle: str) -> List[Dict[str, str]]:
    new_topic = str(topic or "").strip()
    new_angle = str(angle or "").strip()
    out: List[Dict[str, str]] = []
    if new_topic and new_angle:
        out.append({"topic": new_topic, "angle": new_angle})
    existing_topics = {new_topic.lower()} if new_topic else set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        topic_txt = str(item.get("topic") or "").strip()
        angle_txt = str(item.get("angle") or "").strip()
        if not topic_txt or not angle_txt:
            continue
        if topic_txt.lower() in existing_topics:
            continue
        existing_topics.add(topic_txt.lower())
        out.append({"topic": topic_txt, "angle": angle_txt})
    return out


async def _list_client_meeting_docs(tenant_id: str, client_id: str, *, limit: int = 1000) -> List[dict]:
    bridge = get_store()
    if bridge.is_enabled_for("meetings"):
        docs = await bridge.list_meetings(tenant_id, limit=limit)
        return [doc for doc in docs if str((doc or {}).get("client_id") or "") == str(client_id)]
    return []


async def _list_open_action_item_docs(tenant_id: str, client_id: str, *, limit: int = 1000) -> List[dict]:
    bridge = get_store()
    if not bridge.is_enabled_for("action_items"):
        return []
    docs = await bridge.list_action_items(tenant_id, limit=limit)
    return [
        doc for doc in docs
        if str((doc or {}).get("client_id") or "") == str(client_id)
        and not bool((doc or {}).get("is_deleted", False))
        and str((doc or {}).get("status") or "open").strip().lower() != "done"
    ]


async def _build_advanced_prep_context(tenant_id: str, client: Client, user: Optional[User]) -> str:
    sections: List[str] = []

    meetings = await _list_client_meeting_docs(tenant_id, client.id, limit=25)
    meetings = sorted(meetings, key=lambda doc: str((doc or {}).get("scheduled_at") or (doc or {}).get("updated_at") or ""), reverse=True)
    if meetings:
        history_lines: List[str] = []
        for doc in meetings[:3]:
            history_lines.append(
                f"- {str((doc or {}).get('title') or 'Monthly Touch').strip()} | "
                f"when={str((doc or {}).get('scheduled_at') or (doc or {}).get('updated_at') or '').strip() or 'unknown'} | "
                f"sentiment={str((doc or {}).get('sentiment') or '').strip() or 'unknown'} | "
                f"health={str((doc or {}).get('health_signal') or '').strip() or 'n/a'} | "
                f"issues={len((doc or {}).get('issues') or [])}"
            )
        sections.append("PREVIOUS MONTHLY TOUCH HISTORY:\n" + "\n".join(history_lines))

    open_actions = await _list_open_action_item_docs(tenant_id, client.id, limit=50)
    if open_actions:
        action_lines: List[str] = []
        for doc in open_actions[:8]:
            action_lines.append(
                f"- {str((doc or {}).get('title') or 'Action item').strip()} | "
                f"owner={str((doc or {}).get('owner') or '').strip() or 'unassigned'} | "
                f"due={str((doc or {}).get('due_date') or '').strip() or 'unscheduled'} | "
                f"priority={str((doc or {}).get('priority') or '').strip() or 'n/a'}"
            )
        sections.append("OPEN ACTION ITEMS / UNRESOLVED COMMITMENTS:\n" + "\n".join(action_lines))

    client_email = str(getattr(client, "email", "") or "").strip()
    if user and client_email:
        try:
            gmail = await connectors.list_gmail_messages_for_contact(tenant_id, user.id, client_email, max_messages=5)
        except Exception:
            gmail = {"ok": False, "messages": []}
        messages = list((gmail or {}).get("messages") or [])
        if messages:
            message_lines: List[str] = []
            for msg in messages[:5]:
                message_lines.append(
                    f"- {str(msg.get('date') or '').strip()[:32]} | "
                    f"{str(msg.get('subject') or '').strip() or 'No subject'} | "
                    f"{str(msg.get('snippet') or '').strip()[:180]}"
                )
            sections.append("RECENT CLIENT COMMUNICATION HISTORY:\n" + "\n".join(message_lines))

    return "\n\n".join(section for section in sections if section.strip())


async def _count_monthly_touch_meetings(tenant_id: str, client_id: str) -> int:
    docs = await _list_client_meeting_docs(tenant_id, client_id, limit=1000)
    return sum(1 for doc in docs if str((doc or {}).get("title") or "").startswith("Monthly Touch"))


async def _get_previous_review_snapshot(tenant_id: str, client_id: str, current_month: str) -> Optional[dict]:
    bridge = get_store()
    if bridge.is_enabled_for("reviews"):
        docs = await bridge.list_review_monthly_snapshots(
            tenant_id,
            client_legacy_id=str(client_id),
            limit=24,
        )
        for doc in docs or []:
            if str((doc or {}).get("month") or "") != current_month:
                return doc
        return None
    return None


async def upsert_review_snapshot_from_kpi(tenant_id: str, client_id: str, kpi: Dict[str, Any]) -> None:
    try:
        gbp = (kpi or {}).get("google_business_profile") or {}
        nr = gbp.get("new_reviews") or {}
        received = _safe_int(nr.get("value"), 0)
        avg_rating = _safe_float(nr.get("avg_rating"))
        period = (kpi or {}).get("_period") or {}
        cur_end = ((period.get("current") or {}).get("end") or "")[:10]
        month = _month_key(cur_end or utcnow().date().isoformat())
        snap = ReviewMonthlySnapshot(
            tenant_id=tenant_id,
            client_id=client_id,
            month=month,
            received=max(0, int(received)),
            avg_rating=avg_rating,
            source="gbp",
            kpi_period_kind=str(period.get("kind") or ""),
            kpi_period_current_end=cur_end or None,
        )
        bridge = get_store()
        if bridge.is_enabled_for("reviews"):
            await bridge.upsert_review_monthly_snapshot(tenant_id, client_id, snap.to_mongo())
            return
    except Exception:
        pass


async def build_first_90_day_brief_support(
    tenant_id: str,
    client_doc: Dict[str, Any],
    kpi_snapshot: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    client_id = str((client_doc or {}).get("_id") or "")
    if not client_id:
        return None

    touch_number = await _count_monthly_touch_meetings(tenant_id, client_id)
    onboarding_dt = _parse_dateish((client_doc or {}).get("onboarding_date"))
    days_since_onboarding: Optional[int] = None
    weeks_since_onboarding: Optional[int] = None
    if onboarding_dt:
        ref = onboarding_dt
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        days_since_onboarding = max(0, (utcnow().replace(tzinfo=timezone.utc) - ref).days)
        weeks_since_onboarding = max(1, round(days_since_onboarding / 7.0))

    is_first_90_days = touch_number in (1, 2, 3)
    if days_since_onboarding is not None:
        is_first_90_days = is_first_90_days or days_since_onboarding <= 95
    if not is_first_90_days:
        return None

    gbp = (kpi_snapshot or {}).get("google_business_profile") or {}
    reviews = gbp.get("new_reviews") or {}
    map_checkins = (kpi_snapshot or {}).get("map_checkins") or {}
    current_reviews = _safe_int(reviews.get("value"), 0)
    avg_rating = _safe_float(reviews.get("avg_rating"))
    photo_views = _safe_int((gbp.get("photo_views") or {}).get("value"), 0)
    photo_views_prev = _safe_int((gbp.get("photo_views") or {}).get("previous"), 0)
    field_checkins = _safe_int(map_checkins.get("field_checkins"), 0)
    avg_grid_rank = _safe_float((map_checkins.get("avg_grid_rank") or {}).get("value"))
    avg_grid_rank_prev = _safe_float((map_checkins.get("avg_grid_rank") or {}).get("previous"))
    top_3_pct = _safe_float((map_checkins.get("top_3_pct") or {}).get("value"))
    top_3_pct_prev = _safe_float((map_checkins.get("top_3_pct") or {}).get("previous"))

    period = (kpi_snapshot or {}).get("_period") or {}
    current_end = ((period.get("current") or {}).get("end") or "")[:10]
    previous_snapshot = await _get_previous_review_snapshot(tenant_id, client_id, _month_key(current_end))
    previous_reviews = _safe_int((previous_snapshot or {}).get("received"), 0) if previous_snapshot else None
    review_compare_text = (
        f"{current_reviews} new reviews this period versus {previous_reviews} last tracked period"
        if previous_reviews is not None
        else f"{current_reviews} new reviews this period"
    )

    weeks_phrase = f"about {weeks_since_onboarding} weeks" if weeks_since_onboarding else "the first 90 days"
    touch_label = touch_number if touch_number in (1, 2, 3) else min(max((((weeks_since_onboarding or 12) - 1) // 4) + 1, 1), 3)
    photo_compare = (
        f"Photo views are {photo_views} versus {photo_views_prev} last period."
        if photo_views_prev
        else f"Photo views are currently {photo_views}."
    )
    checkin_compare_parts = []
    if field_checkins:
        checkin_compare_parts.append(f"field check-ins logged: {field_checkins}")
    if avg_grid_rank is not None:
        if avg_grid_rank_prev is not None:
            checkin_compare_parts.append(f"average grid rank {avg_grid_rank} versus {avg_grid_rank_prev} last period")
        else:
            checkin_compare_parts.append(f"average grid rank {avg_grid_rank}")
    if top_3_pct is not None:
        if top_3_pct_prev is not None:
            checkin_compare_parts.append(f"top 3 visibility {top_3_pct}% versus {top_3_pct_prev}% last period")
        else:
            checkin_compare_parts.append(f"top 3 visibility {top_3_pct}%")
    checkins_text = "; ".join(checkin_compare_parts) if checkin_compare_parts else "map check-in progress should be reviewed if available"
    rating_text = f" Average rating is {avg_rating}." if avg_rating is not None else ""

    extra_context = (
        f"This client is still in the first 90 days of onboarding and this is monthly touch #{touch_label}. "
        f"In the brief, explicitly remind the client that early momentum depends on their participation. "
        f"Ask about the reviews we requested, any fresh team or jobsite images we still need, and map check-ins or local activity updates. "
        f"Use only supported metrics. Review progress: {review_compare_text}.{rating_text} {photo_compare} "
        f"Map check-in context: {checkins_text}. "
        f"Include at least one talking point, one suggested question, and one prep reminder tied to this 90-day roadmap."
    )

    review_question = (
        f"It has been {weeks_phrase} since we started together. Were you able to help us bring in the reviews we need? "
        f"We are seeing {review_compare_text}; what can we do together before the next monthly touch to increase that?"
    )
    asset_question = (
        "Can we line up fresh jobsite or team images and keep the local check-in activity moving so we can strengthen visibility during these first 90 days?"
    )
    talking_angle = (
        f"Reinforce that this is monthly touch #{touch_label} of the first 90 days, review {review_compare_text}, "
        f"and align on the client actions needed next: reviews, fresh images, and check-ins."
    )
    prep_item = "Review first-90-days roadmap progress: requested reviews, fresh images, and map check-ins before the client call."
    recommendation = (
        "Keep the 90-day onboarding roadmap active by assigning clear asks for reviews, fresh photos, and local check-ins before the next meeting."
    )
    return {
        "extra_context": extra_context,
        "talking_point": {"topic": "First 90 Days Progress", "angle": talking_angle},
        "suggested_questions": [review_question, asset_question],
        "prep_checklist": [prep_item],
        "strategic_recommendation": recommendation,
    }


def apply_first_90_day_brief_support(brief: Dict[str, Any], support: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not support:
        return brief
    next_brief = dict(brief or {})
    tp = support.get("talking_point") or {}
    next_brief["talking_points"] = _prepend_unique_talking_point(
        next_brief.get("talking_points") or [],
        str(tp.get("topic") or ""),
        str(tp.get("angle") or ""),
    )
    next_brief["suggested_questions"] = list(next_brief.get("suggested_questions") or [])
    for question in reversed(list(support.get("suggested_questions") or [])):
        next_brief["suggested_questions"] = _prepend_unique_text(next_brief.get("suggested_questions") or [], question)
    next_brief["prep_checklist"] = list(next_brief.get("prep_checklist") or [])
    for item in reversed(list(support.get("prep_checklist") or [])):
        next_brief["prep_checklist"] = _prepend_unique_text(next_brief.get("prep_checklist") or [], item)
    recommendation = str(support.get("strategic_recommendation") or "").strip()
    if recommendation:
        next_brief["strategic_recommendations"] = _prepend_unique_text(
            next_brief.get("strategic_recommendations") or [],
            recommendation,
        )
    return next_brief


async def _ensure_meeting_for_client(tenant_id: str, client: Client, user: Optional[User]) -> Meeting:
    title = f"Monthly Touch — {utcnow().strftime('%B %Y')}"
    bridge = get_store()
    if bridge.is_enabled_for("meetings"):
        meetings = await bridge.list_meetings(tenant_id, limit=500)
        existing = next(
            (
                doc
                for doc in meetings
                if str((doc or {}).get("client_id") or "") == str(client.id)
                and str((doc or {}).get("title") or "") == title
            ),
            None,
        )
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
    if bridge.is_enabled_for("meetings"):
        stored = await bridge.upsert_meeting(tenant_id, meeting.to_mongo())
        if stored:
            return Meeting.from_mongo(stored)
        raise RuntimeError("Unable to create monthly touch meeting in Supabase")
    return meeting


async def _upsert_action_item(tenant_id: str, client_id: str, meeting_id: str, title: str, description: str, owner: Optional[str]) -> ActionItem:
    bridge = get_store()
    due = (utcnow() + timedelta(days=14)).date().isoformat()
    if bridge.is_enabled_for("action_items"):
        existing_items = await bridge.list_action_items(tenant_id, client_legacy_id=client_id, meeting_legacy_id=meeting_id, limit=500)
        existing = next((doc for doc in existing_items if str((doc or {}).get("title") or "") == title), None)
        if existing:
            return ActionItem.from_mongo(existing)
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
        stored = await bridge.upsert_action_item(tenant_id, item.to_mongo())
        if stored:
            return ActionItem.from_mongo(stored)
        raise RuntimeError("Unable to create action item in Supabase")
    return ActionItem(
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
            await connectors._update_client_binding_external_ids(tenant_id, client_id, "clickup", {"action_list_id": str(list_id)})
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
    bridge = get_store()
    if bridge.is_enabled_for("action_items"):
        stored = await bridge.upsert_action_item(tenant_id, {**item.to_mongo(), **update})
        if stored:
            return ActionItem.from_mongo(stored)
    return item.model_copy(update=update)


async def generate_for_client(
    tenant_id: str,
    client_id: str,
    *,
    user: Optional[User] = None,
    model_key: Optional[str] = None,
    extra_context: Optional[str] = None,
    push_clickup_actions: bool = True,
) -> Meeting:
    c_doc = await _get_client_doc(tenant_id, client_id)
    if not c_doc:
        raise ValueError("Client not found")
    client = Client.from_mongo(c_doc)

    meeting = await _ensure_meeting_for_client(tenant_id, client, user)

    kpi = await connectors.build_kpi_snapshot(tenant_id, client_id, client.company, user_id=(user.id if user else None))
    onboarding_support = await build_first_90_day_brief_support(tenant_id, client.to_mongo(), kpi)
    advanced_context = await _build_advanced_prep_context(tenant_id, client, user)
    brief = await ai.generate_meeting_brief(
        client=client.model_dump(),
        kpi_snapshot=kpi,
        extra_context=merge_brief_extra_context(
            merge_brief_extra_context(extra_context, (onboarding_support or {}).get("extra_context")),
            advanced_context,
        ),
        model_key=model_key or ai.DEFAULT_MODEL,
        session_id=f"monthly-touch-{meeting.id}",
    )
    brief = apply_first_90_day_brief_support(brief, onboarding_support)

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
    bridge = get_store()
    next_doc = {**meeting.to_mongo(), **update}
    if bridge.is_enabled_for("meetings"):
        m_doc = await bridge.upsert_meeting(tenant_id, next_doc)
        meeting = Meeting.from_mongo(m_doc) if m_doc else meeting
    else:
        meeting = meeting.model_copy(update=update)

    await upsert_review_snapshot_from_kpi(tenant_id, client.id, kpi)

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
    clients = await _list_active_client_docs()
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
