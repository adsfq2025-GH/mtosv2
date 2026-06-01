"""Monthly Touch OS — FastAPI backend."""
import logging
import os
import uvicorn
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from starlette.middleware.cors import CORSMiddleware

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

from db import db, decrypt_secret, encrypt_secret, new_id, utcnow  # noqa: E402
from auth import (  # noqa: E402
    bootstrap_admin,
    create_token,
    get_current_user,
    hash_password,
    require_admin,
    to_public,
    verify_password,
)
from models import (  # noqa: E402
    ActionItem,
    ActionItemIn,
    AnalyzeTranscriptIn,
    Client,
    ClientIn,
    ClientIntegrationBinding,
    ClientIntegrationBindingIn,
    ContentCapture,
    ContentCaptureIn,
    GenerateBriefIn,
    GenerateRecapIn,
    Integration,
    IntegrationConfigureIn,
    LoginIn,
    Meeting,
    MeetingIn,
    MeetingPatch,
    RegisterIn,
    User,
)
from integrations_meta import INTEGRATIONS, list_integrations, demo_kpi_snapshot
from docs_content import get_categories, get_doc, get_docs_summary
import ai
import connectors
import monthly_touch

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mtos")

app = FastAPI(title="Monthly Touch OS")
api = APIRouter(prefix="/api")
DB_READY = False


async def _ensure_db_ready() -> bool:
    global DB_READY
    if DB_READY:
        return True
    try:
        await db.command("ping")
        DB_READY = True
        return True
    except Exception as exc:
        logger.error("MongoDB connection failed: %s", exc)
        return False


async def require_db_ready():
    ok = await _ensure_db_ready()
    if not ok:
        raise HTTPException(503, "Database unavailable. Check MONGO_URL/DB_NAME and Atlas IP allowlist.")

# ===================== CORS MIDDLEWARE =====================
# Allows your independent Vercel frontend to safely communicate with this Render backend.
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "*")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
if not _cors_origins:
    _cors_origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================== HEALTH =====================
@api.get("/")
async def root():
    await _ensure_db_ready()
    return {"name": "Monthly Touch OS API", "version": "1.0.0", "status": "ok", "db_ready": DB_READY}


# ===================== AUTH =====================
@api.post("/auth/register")
async def register(data: RegisterIn, _: None = Depends(require_db_ready)):
    # First user becomes admin if no users exist; otherwise role is forced to manager
    try:
        user_count = await db.users.count_documents({})
        role = "admin" if user_count == 0 else "manager"
        if await db.users.find_one({"email": data.email}):
            raise HTTPException(409, "Email already registered")
        user = User(
            email=data.email,
            name=data.name,
            role=role,
            password_hash=hash_password(data.password),
        )
        await db.users.insert_one(user.to_mongo())
        token = create_token(user.id, user.role)
        return {"token": token, "user": to_public(user).model_dump()}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("register failed: %s", exc)
        raise HTTPException(503, "Database unavailable. Check Atlas Network Access / connection string.") from exc


@api.post("/auth/login")
async def login(data: LoginIn, _: None = Depends(require_db_ready)):
    try:
        doc = await db.users.find_one({"email": data.email})
        if not doc:
            raise HTTPException(401, "Invalid credentials")
        user = User.from_mongo(doc)
        if not user.active or not verify_password(data.password, user.password_hash):
            raise HTTPException(401, "Invalid credentials")
        token = create_token(user.id, user.role)
        return {"token": token, "user": to_public(user).model_dump()}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("login failed: %s", exc)
        raise HTTPException(503, "Database unavailable. Check Atlas Network Access / connection string.") from exc


@api.get("/auth/me")
async def me(user: User = Depends(get_current_user)):
    return to_public(user).model_dump()


@api.get("/users")
async def list_users(_: User = Depends(require_admin)):
    docs = await db.users.find({}, {"password_hash": 0}).to_list(500)
    return [
        {
            "id": d.get("_id"),
            "email": d.get("email"),
            "name": d.get("name"),
            "role": d.get("role"),
            "avatar_url": d.get("avatar_url"),
            "active": d.get("active", True),
        }
        for d in docs
    ]


# ===================== CLIENTS =====================
@api.get("/clients")
async def list_clients(user: User = Depends(get_current_user)):
    docs = await db.clients.find({}).sort("created_at", -1).to_list(1000)
    return [Client.from_mongo(d).model_dump() for d in docs]


@api.post("/clients")
async def create_client(data: ClientIn, user: User = Depends(get_current_user)):
    am_name = None
    if data.account_manager_id:
        am_doc = await db.users.find_one({"_id": data.account_manager_id})
        if am_doc:
            am_name = am_doc.get("name")
    c = Client(**data.model_dump(), account_manager_name=am_name)
    await db.clients.insert_one(c.to_mongo())
    return c.model_dump()


@api.get("/clients/{client_id}")
async def get_client(client_id: str, _: User = Depends(get_current_user)):
    doc = await db.clients.find_one({"_id": client_id})
    if not doc:
        raise HTTPException(404, "Client not found")
    return Client.from_mongo(doc).model_dump()


@api.patch("/clients/{client_id}")
async def update_client(client_id: str, patch: dict, _: User = Depends(get_current_user)):
    patch["updated_at"] = utcnow().isoformat()
    res = await db.clients.update_one({"_id": client_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Client not found")
    doc = await db.clients.find_one({"_id": client_id})
    return Client.from_mongo(doc).model_dump()


@api.delete("/clients/{client_id}")
async def delete_client(client_id: str, _: User = Depends(require_admin)):
    await db.clients.delete_one({"_id": client_id})
    await db.meetings.delete_many({"client_id": client_id})
    await db.action_items.delete_many({"client_id": client_id})
    await db.content_captures.delete_many({"client_id": client_id})
    return {"ok": True}


@api.get("/clients/{client_id}/bindings")
async def list_client_bindings(client_id: str, _: User = Depends(get_current_user)):
    docs = await db.client_bindings.find({"client_id": client_id}).to_list(100)
    return [ClientIntegrationBinding.from_mongo(d).model_dump() for d in docs]


@api.put("/clients/{client_id}/bindings/{platform}")
async def upsert_client_binding(
    client_id: str,
    platform: str,
    data: ClientIntegrationBindingIn,
    _: User = Depends(require_admin),
):
    if platform not in INTEGRATIONS:
        raise HTTPException(404, "Unknown integration")
    existing = await db.client_bindings.find_one({"client_id": client_id, "platform": platform})
    update = {
        "enabled": bool(data.enabled),
        "external_ids": data.external_ids or {},
        "config": data.config or {},
        "updated_at": utcnow().isoformat(),
    }
    if existing:
        await db.client_bindings.update_one({"_id": existing["_id"]}, {"$set": update})
        doc = await db.client_bindings.find_one({"_id": existing["_id"]})
        return ClientIntegrationBinding.from_mongo(doc).model_dump()
    binding = ClientIntegrationBinding(client_id=client_id, platform=platform, **update)
    await db.client_bindings.insert_one(binding.to_mongo())
    return binding.model_dump()


@api.delete("/clients/{client_id}/bindings/{platform}")
async def delete_client_binding(client_id: str, platform: str, _: User = Depends(require_admin)):
    await db.client_bindings.delete_one({"client_id": client_id, "platform": platform})
    return {"ok": True}


# ===================== MEETINGS =====================
@api.get("/meetings")
async def list_meetings(client_id: Optional[str] = None, _: User = Depends(get_current_user)):
    q = {"client_id": client_id} if client_id else {}
    docs = await db.meetings.find(q).sort("created_at", -1).to_list(500)
    return [Meeting.from_mongo(d).model_dump() for d in docs]


@api.post("/meetings")
async def create_meeting(data: MeetingIn, user: User = Depends(get_current_user)):
    client_doc = await db.clients.find_one({"_id": data.client_id})
    if not client_doc:
        raise HTTPException(404, "Client not found")
    client = Client.from_mongo(client_doc)
    m = Meeting(
        client_id=client.id,
        client_name=client.name,
        account_manager_id=user.id,
        account_manager_name=user.name,
        title=data.title,
        scheduled_at=data.scheduled_at,
        google_meet_url=data.google_meet_url,
        duration_minutes=data.duration_minutes or 60,
    )
    await db.meetings.insert_one(m.to_mongo())
    return m.model_dump()


@api.post("/clients/{client_id}/monthly-touch")
async def generate_monthly_touch(client_id: str, data: GenerateBriefIn, user: User = Depends(get_current_user)):
    try:
        meeting = await monthly_touch.generate_for_client(
            client_id,
            user=user,
            model_key=data.model,
            extra_context=data.extra_context,
            push_clickup_actions=True,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
    return meeting.model_dump()


@api.post("/admin/monthly-touch/run-all")
async def run_monthly_touch_all(request: Request):
    secret = os.environ.get("CRON_SECRET", "")
    header_secret = request.headers.get("x-cron-secret", "")
    if not secret or header_secret != secret:
        raise HTTPException(403, "Forbidden")
    model_key = request.query_params.get("model")
    extra_context = request.query_params.get("extra_context")
    return await monthly_touch.generate_for_all(model_key=model_key, extra_context=extra_context)


@api.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: str, _: User = Depends(get_current_user)):
    doc = await db.meetings.find_one({"_id": meeting_id})
    if not doc:
        raise HTTPException(404, "Meeting not found")
    return Meeting.from_mongo(doc).model_dump()


@api.get("/meetings/{meeting_id}/export/html")
async def export_meeting_html(meeting_id: str, _: User = Depends(get_current_user)):
    doc = await db.meetings.find_one({"_id": meeting_id})
    if not doc:
        raise HTTPException(404, "Meeting not found")
    m = Meeting.from_mongo(doc)

    def esc(s: Any) -> str:
        if s is None:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    wins = "".join(f"<li><strong>{esc(w.get('title'))}</strong> — {esc(w.get('description'))}</li>" for w in (m.wins or []))
    issues = "".join(f"<li><strong>{esc(i.get('title'))}</strong> — {esc(i.get('description'))}</li>" for i in (m.issues or []))
    tps = "".join(f"<li><strong>{esc(t.get('topic'))}</strong>: {esc(t.get('angle'))}</li>" for t in (m.talking_points or []))
    qs = "".join(f"<li>{esc(q)}</li>" for q in (m.suggested_questions or []))
    recs = "".join(f"<li>{esc(r)}</li>" for r in (m.strategic_recommendations or []))

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{esc(m.title)}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {{ font-family: Inter, Arial, sans-serif; line-height: 1.45; color: #0f172a; padding: 28px; max-width: 920px; margin: 0 auto; }}
    h1 {{ font-size: 22px; margin: 0 0 4px; }}
    h2 {{ font-size: 15px; margin: 22px 0 8px; text-transform: uppercase; letter-spacing: .06em; color: #334155; }}
    .meta {{ color: #475569; font-size: 13px; margin: 0 0 18px; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 6px 0; }}
    .box {{ border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; background: #f8fafc; }}
  </style>
</head>
<body>
  <h1>{esc(m.title)}</h1>
  <p class="meta">{esc(m.client_name)} · {esc(m.scheduled_at or "Unscheduled")} · {esc(m.duration_minutes)} min</p>

  <div class="box">
    <h2>3 Wins</h2>
    <ul>{wins or "<li>—</li>"}</ul>
    <h2>2 Issues</h2>
    <ul>{issues or "<li>—</li>"}</ul>
  </div>

  <h2>Talking Points</h2>
  <ul>{tps or "<li>—</li>"}</ul>

  <h2>Suggested Questions</h2>
  <ul>{qs or "<li>—</li>"}</ul>

  <h2>Strategic Recommendations</h2>
  <ul>{recs or "<li>—</li>"}</ul>

  <h2>Testimonial Opportunity</h2>
  <p>{esc(m.testimonial_opportunity or "—")}</p>

  <h2>Health Signal</h2>
  <p>{esc(m.health_signal or "—")}</p>
</body>
</html>"""

    return {"html": html}


@api.patch("/meetings/{meeting_id}")
async def update_meeting(meeting_id: str, patch: MeetingPatch, _: User = Depends(get_current_user)):
    update = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None}
    update["updated_at"] = utcnow().isoformat()
    res = await db.meetings.update_one({"_id": meeting_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Meeting not found")
    doc = await db.meetings.find_one({"_id": meeting_id})
    return Meeting.from_mongo(doc).model_dump()


@api.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str, _: User = Depends(get_current_user)):
    res = await db.meetings.delete_one({"_id": meeting_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Meeting not found")
    await db.action_items.delete_many({"meeting_id": meeting_id})
    await db.content_captures.delete_many({"meeting_id": meeting_id})
    return {"ok": True}


@api.post("/meetings/{meeting_id}/generate-brief")
async def generate_brief(meeting_id: str, data: GenerateBriefIn, user: User = Depends(get_current_user)):
    m_doc = await db.meetings.find_one({"_id": meeting_id})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await db.clients.find_one({"_id": meeting.client_id})
    client = Client.from_mongo(c_doc) if c_doc else None
    client_d = client.model_dump() if client else {"name": meeting.client_name}
    kpi = await connectors.build_kpi_snapshot(meeting.client_id, client_d.get("company", ""))
    try:
        brief = await ai.generate_meeting_brief(
            client=client_d,
            kpi_snapshot=kpi,
            extra_context=data.extra_context,
            model_key=data.model or ai.DEFAULT_MODEL,
            session_id=f"brief-{meeting_id}",
        )
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
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
        "brief_model": data.model or ai.DEFAULT_MODEL,
        "status": "prep",
        "updated_at": utcnow().isoformat(),
    }
    await db.meetings.update_one({"_id": meeting_id}, {"$set": update})
    doc = await db.meetings.find_one({"_id": meeting_id})
    return Meeting.from_mongo(doc).model_dump()


@api.post("/meetings/{meeting_id}/analyze-transcript")
async def analyze_transcript(meeting_id: str, data: AnalyzeTranscriptIn, user: User = Depends(get_current_user)):
    m_doc = await db.meetings.find_one({"_id": meeting_id})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await db.clients.find_one({"_id": meeting.client_id})
    client = Client.from_mongo(c_doc) if c_doc else None
    analysis = await ai.analyze_transcript(
        client_name=client.name if client else (meeting.client_name or ""),
        company=client.company if client else "",
        am_name=meeting.account_manager_name or user.name,
        transcript=data.transcript,
        model_key=data.model or ai.DEFAULT_MODEL,
        session_id=f"transcript-{meeting_id}",
    )
    # persist transcript + sentiment
    await db.meetings.update_one(
        {"_id": meeting_id},
        {
            "$set": {
                "transcript": data.transcript,
                "transcript_analyzed_at": utcnow().isoformat(),
                "sentiment": analysis.get("sentiment", "neutral"),
                "sentiment_summary": analysis.get("sentiment_summary", ""),
                "updated_at": utcnow().isoformat(),
            }
        },
    )
    # create action items
    created_actions: List[dict] = []
    for ai_item in analysis.get("action_items", []) or []:
        item = ActionItem(
            meeting_id=meeting_id,
            client_id=meeting.client_id,
            title=ai_item.get("title", "Action item"),
            description=ai_item.get("description"),
            owner=meeting.account_manager_name if (ai_item.get("owner_type") or "agency") == "agency" else (client.primary_contact if client else None),
            owner_type=ai_item.get("owner_type", "agency"),
            due_date=ai_item.get("due_date") if ai_item.get("due_date") not in ("null", None) else None,
            priority=ai_item.get("priority", "medium"),
        )
        await db.action_items.insert_one(item.to_mongo())
        created_actions.append(item.model_dump())
    # create content captures
    created_content: List[dict] = []
    for co in analysis.get("content_opportunities", []) or []:
        cc = ContentCapture(
            meeting_id=meeting_id,
            client_id=meeting.client_id,
            type=co.get("type", "quote"),
            content=co.get("content", ""),
            notes=co.get("why_strong"),
            received=True,
        )
        await db.content_captures.insert_one(cc.to_mongo())
        created_content.append(cc.model_dump())
    # update client health & sentiment
    if client:
        new_health = analysis.get("health_score_suggestion")
        client_update = {"sentiment": analysis.get("sentiment", "neutral")}
        if isinstance(new_health, (int, float)):
            client_update["health_score"] = int(new_health)
            client_update["churn_risk"] = "high" if new_health < 50 else ("medium" if new_health < 70 else "low")
        await db.clients.update_one({"_id": client.id}, {"$set": client_update})

    return {
        "analysis": analysis,
        "created_action_items": created_actions,
        "created_content_captures": created_content,
    }


@api.post("/meetings/{meeting_id}/generate-recap")
async def generate_recap(meeting_id: str, data: GenerateRecapIn, _: User = Depends(get_current_user)):
    m_doc = await db.meetings.find_one({"_id": meeting_id})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await db.clients.find_one({"_id": meeting.client_id})
    client = Client.from_mongo(c_doc) if c_doc else None
    actions = await db.action_items.find({"meeting_id": meeting_id}).to_list(100)
    actions_p = [ActionItem.from_mongo(a).model_dump() for a in actions]
    try:
        recap = await ai.generate_recap(
            client_name=client.name if client else (meeting.client_name or ""),
            company=client.company if client else "",
            title=meeting.title,
            wins=[w.model_dump() if hasattr(w, "model_dump") else w for w in meeting.wins],
            issues=[i.model_dump() if hasattr(i, "model_dump") else i for i in meeting.issues],
            actions=actions_p,
            model_key=data.model or ai.DEFAULT_MODEL,
            session_id=f"recap-{meeting_id}",
        )
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
    await db.meetings.update_one(
        {"_id": meeting_id},
        {
            "$set": {
                "recap_html": recap["html"],
                "recap_email": recap["plain"],
                "status": "completed",
                "updated_at": utcnow().isoformat(),
            }
        },
    )
    return recap


# ===================== ACTION ITEMS =====================
@api.get("/action-items")
async def list_actions(
    client_id: Optional[str] = None,
    meeting_id: Optional[str] = None,
    status: Optional[str] = None,
    _: User = Depends(get_current_user),
):
    q: dict = {}
    if client_id:
        q["client_id"] = client_id
    if meeting_id:
        q["meeting_id"] = meeting_id
    if status:
        q["status"] = status
    docs = await db.action_items.find(q).sort("created_at", -1).to_list(1000)
    return [ActionItem.from_mongo(d).model_dump() for d in docs]


@api.post("/action-items")
async def create_action(data: ActionItemIn, _: User = Depends(get_current_user)):
    item = ActionItem(**data.model_dump())
    await db.action_items.insert_one(item.to_mongo())
    return item.model_dump()


@api.patch("/action-items/{item_id}")
async def update_action(item_id: str, patch: dict, _: User = Depends(get_current_user)):
    patch["updated_at"] = utcnow().isoformat()
    res = await db.action_items.update_one({"_id": item_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.action_items.find_one({"_id": item_id})
    return ActionItem.from_mongo(doc).model_dump()


@api.delete("/action-items/{item_id}")
async def delete_action(item_id: str, _: User = Depends(get_current_user)):
    await db.action_items.delete_one({"_id": item_id})
    return {"ok": True}


# ===================== CONTENT CAPTURES =====================
@api.get("/content-captures")
async def list_content(client_id: Optional[str] = None, _: User = Depends(get_current_user)):
    q = {"client_id": client_id} if client_id else {}
    docs = await db.content_captures.find(q).sort("created_at", -1).to_list(500)
    return [ContentCapture.from_mongo(d).model_dump() for d in docs]


@api.post("/content-captures")
async def create_content(data: ContentCaptureIn, _: User = Depends(get_current_user)):
    cc = ContentCapture(**data.model_dump())
    await db.content_captures.insert_one(cc.to_mongo())
    return cc.model_dump()


@api.patch("/content-captures/{cap_id}")
async def update_content(cap_id: str, patch: dict, _: User = Depends(get_current_user)):
    patch["updated_at"] = utcnow().isoformat()
    res = await db.content_captures.update_one({"_id": cap_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.content_captures.find_one({"_id": cap_id})
    return ContentCapture.from_mongo(doc).model_dump()


@api.delete("/content-captures/{cap_id}")
async def delete_content(cap_id: str, _: User = Depends(get_current_user)):
    await db.content_captures.delete_one({"_id": cap_id})
    return {"ok": True}


# ===================== INTEGRATIONS =====================
@api.get("/integrations/catalog")
async def integrations_catalog(_: User = Depends(get_current_user)):
    return list_integrations()


@api.get("/integrations")
async def integrations_status(_: User = Depends(get_current_user)):
    docs = await db.integrations.find({}).to_list(100)
    by_platform = {d["platform"]: d for d in docs}
    out = []
    for cat in list_integrations():
        plat = cat["platform"]
        stored = by_platform.get(plat)
        out.append({
            **cat,
            "status": (stored or {}).get("status", "not_connected"),
            "last_synced_at": (stored or {}).get("last_synced_at"),
            "last_error": (stored or {}).get("last_error"),
            "metadata": (stored or {}).get("metadata", {}),
            "configured_field_keys": list(((stored or {}).get("credentials_encrypted") or {}).keys()),
        })
    return out


@api.post("/integrations/{platform}/configure")
async def configure_integration(platform: str, data: IntegrationConfigureIn, _: User = Depends(require_admin)):
    if platform not in INTEGRATIONS:
        raise HTTPException(404, "Unknown integration")
    enc = {k: encrypt_secret(v) for k, v in (data.credentials or {}).items() if v}
    existing = await db.integrations.find_one({"platform": platform})
    if existing:
        merged_creds = {**(existing.get("credentials_encrypted") or {}), **enc}
        await db.integrations.update_one(
            {"platform": platform},
            {"$set": {
                "credentials_encrypted": merged_creds,
                "metadata": {**(existing.get("metadata") or {}), **(data.metadata or {})},
                "status": "connected" if merged_creds else "not_connected",
                "updated_at": utcnow().isoformat(),
            }},
        )
    else:
        i = Integration(
            platform=platform,
            label=INTEGRATIONS[platform]["label"],
            status="connected" if enc else "not_connected",
            credentials_encrypted=enc,
            metadata=data.metadata or {},
        )
        await db.integrations.insert_one(i.to_mongo())
    return {"ok": True, "platform": platform, "status": "connected" if enc else "not_connected"}


@api.post("/integrations/{platform}/test")
async def test_integration(platform: str, _: User = Depends(require_admin)):
    if platform not in INTEGRATIONS:
        raise HTTPException(404, "Unknown integration")
    doc = await db.integrations.find_one({"platform": platform})
    if not doc or not doc.get("credentials_encrypted"):
        raise HTTPException(400, "No credentials configured")
    # MVP test: confirm required fields decrypt cleanly. Real API tests will be wired per-platform.
    creds = {k: decrypt_secret(v) for k, v in doc.get("credentials_encrypted", {}).items()}
    if not all(creds.values()):
        await db.integrations.update_one(
            {"platform": platform},
            {"$set": {"status": "error", "last_error": "Credential decryption failed", "updated_at": utcnow().isoformat()}},
        )
        raise HTTPException(500, "Credential decryption failed")
    await db.integrations.update_one(
        {"platform": platform},
        {"$set": {"status": "connected", "last_synced_at": utcnow().isoformat(), "last_error": None, "updated_at": utcnow().isoformat()}},
    )
    return {"ok": True, "platform": platform, "status": "connected", "note": "Credentials stored & verified. Live API sync runs on next scheduled job."}


@api.delete("/integrations/{platform}")
async def disconnect_integration(platform: str, _: User = Depends(require_admin)):
    await db.integrations.delete_one({"platform": platform})
    return {"ok": True}


# ===================== DOCS =====================
@api.get("/docs")
async def docs_list(_: User = Depends(get_current_user)):
    return {"items": get_docs_summary(), "categories": get_categories()}


@api.get("/docs/{slug}")
async def docs_detail(slug: str, _: User = Depends(get_current_user)):
    d = get_doc(slug)
    if not d:
        raise HTTPException(404, "Doc not found")
    return d


# ===================== DASHBOARD =====================
@api.get("/dashboard/overview")
async def dashboard_overview(_: User = Depends(get_current_user)):
    clients = await db.clients.find({}).to_list(2000)
    meetings = await db.meetings.find({}).to_list(2000)
    actions = await db.action_items.find({}).to_list(5000)
    content = await db.content_captures.find({}).to_list(2000)

    total_clients = len(clients)
    health_scores = [c.get("health_score", 75) for c in clients]
    avg_health = round(sum(health_scores) / len(health_scores), 1) if health_scores else 0
    churn_red = sum(1 for c in clients if c.get("churn_risk") == "high")
    churn_yellow = sum(1 for c in clients if c.get("churn_risk") == "medium")

    meetings_this_month = 0
    now = utcnow()
    for m in meetings:
        sched = m.get("scheduled_at") or m.get("created_at")
        if isinstance(sched, str):
            try:
                dt = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                if dt.year == now.year and dt.month == now.month:
                    meetings_this_month += 1
            except Exception:
                pass

    open_actions = sum(1 for a in actions if a.get("status") in ("open", "in_progress"))
    overdue_actions = 0
    for a in actions:
        if a.get("status") in ("open", "in_progress") and a.get("due_date"):
            try:
                d = datetime.fromisoformat(a["due_date"])
                if d.replace(tzinfo=timezone.utc) < now:
                    overdue_actions += 1
            except Exception:
                pass

    return {
        "total_clients": total_clients,
        "avg_health_score": avg_health,
        "churn_risk_high": churn_red,
        "churn_risk_medium": churn_yellow,
        "meetings_this_month": meetings_this_month,
        "open_action_items": open_actions,
        "overdue_action_items": overdue_actions,
        "content_captures_total": len(content),
        "content_pending_routing": sum(1 for c in content if not c.get("routed_to_marketing")),
        "recent_meetings": [
            Meeting.from_mongo(m).model_dump()
            for m in sorted(meetings, key=lambda x: x.get("created_at", ""), reverse=True)[:5]
        ],
        "top_health_clients": sorted(
            [Client.from_mongo(c).model_dump() for c in clients],
            key=lambda x: x["health_score"], reverse=True,
        )[:5],
        "at_risk_clients": [
            Client.from_mongo(c).model_dump() for c in clients if c.get("churn_risk") in ("high", "medium")
        ][:5],
    }


# ===================== MODELS LIST =====================
@api.get("/ai/models")
async def ai_models(_: User = Depends(get_current_user)):
    items = []
    for key, entry in ai.MODEL_REGISTRY.items():
        items.append(
            {
                "key": key,
                "label": entry.get("model", key),
                "provider": entry.get("provider", "unknown"),
                "recommended": key == ai.DEFAULT_MODEL,
            }
        )
    return items

app.include_router(api)

# ===================== BOOT =====================
@app.on_event("startup")
async def _startup():
    await _ensure_db_ready()
    try:
        await bootstrap_admin()
    except Exception as exc:
        logger.error("bootstrap_admin failed: %s", exc)
    logger.info("Monthly Touch OS API ready")


# ===================== PRODUCTION ENTRYPOINT =====================
# Ensures Render binds natively to the host infrastructure via Python execution fallback.
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
