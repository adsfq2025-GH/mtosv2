"""Monthly Touch OS — FastAPI backend."""
import asyncio
import io
import copy
import logging
import os
import time
import uvicorn
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import zipfile
from urllib.parse import urlencode
from html import escape
import json
import urllib.request

from dotenv import load_dotenv
import httpx
from fastapi import APIRouter, Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from starlette.middleware.cors import CORSMiddleware

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
STORAGE_DIR = ROOT / "storage"

# #region debug-point D:init-debug-emitter
def _dbg_emit(hypothesis_id: str, location: str, msg: str, data: Optional[dict] = None) -> None:
    try:
        u = "http://127.0.0.1:7777/event"
        s = "monthly-touch-integrations"
        p = str(Path(".dbg") / f"{s}.env")
        try:
            with open(p, "r", encoding="utf-8") as f:
                c = f.read()
            for line in c.splitlines():
                if line.startswith("DEBUG_SERVER_URL="):
                    u = line.split("=", 1)[1].strip() or u
                elif line.startswith("DEBUG_SESSION_ID="):
                    s = line.split("=", 1)[1].strip() or s
        except Exception:
            pass
        payload = {
            "sessionId": s,
            "runId": "pre-fix",
            "hypothesisId": str(hypothesis_id),
            "location": str(location),
            "msg": f"[DEBUG] {msg}",
            "data": data or {},
        }
        urllib.request.urlopen(
            urllib.request.Request(u, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}),
            timeout=1.5,
        ).read()
    except Exception:
        return
# #endregion

GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()


async def _google_oauth_config(tenant_id: str) -> Dict[str, str]:
    out = {"client_id": GOOGLE_OAUTH_CLIENT_ID, "client_secret": GOOGLE_OAUTH_CLIENT_SECRET, "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI}
    try:
        doc = await db.integrations.find_one({"tenant_id": tenant_id, "platform": "google_oauth"})
        if doc:
            meta = doc.get("metadata") or {}
            enc = doc.get("credentials_encrypted") or {}
            if str(meta.get("client_id") or "").strip():
                out["client_id"] = str(meta.get("client_id") or "").strip()
            if str(meta.get("redirect_uri") or "").strip():
                out["redirect_uri"] = str(meta.get("redirect_uri") or "").strip()
            if str(enc.get("client_secret") or "").strip():
                out["client_secret"] = str(decrypt_secret(enc.get("client_secret")) or "").strip()
    except Exception:
        return out
    return out
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "").strip()

from db import db, decrypt_secret, encrypt_secret, new_id, utcnow  # noqa: E402
from auth import (  # noqa: E402
    bootstrap_admin,
    create_token,
    ensure_membership,
    ensure_membership_for_tenant,
    get_current_context,
    get_current_user,
    hash_password,
    require_admin,
    resolve_tenant_id_from_host,
    to_public,
    verify_password,
)
from models import (  # noqa: E402
    ActionItem,
    ActionItemIn,
    AnalyzeTranscriptIn,
    AiVisibilityConfig,
    AiVisibilityConfigIn,
    AiVisibilityRun,
    AiVisibilityScan,
    Client,
    ClientIn,
    ImportGhlClientsIn,
    GhlLocationTokenIn,
    ClientIntegrationBinding,
    ClientIntegrationBindingIn,
    ContentCapture,
    ContentCaptureIn,
    GenerateBriefIn,
    GenerateSuggestionsIn,
    GenerateRecapIn,
    Integration,
    IntegrationConfigureIn,
    LoginIn,
    GoogleLoginIn,
    Meeting,
    MeetingIn,
    MeetingPatch,
    PromptTemplate,
    PromptTemplateIn,
    QAScorecard,
    CampaignRecommendation,
    ClientReviewGoal,
    ClientReviewGoalIn,
    ReviewEvent,
    ReviewEventIn,
    ReviewMonthlySnapshot,
    DiscoveryQuestionTemplate,
    DiscoveryQuestionTemplateIn,
    MeetingDiscoveryQuestion,
    RoadmapItem,
    RoadmapItemIn,
    RoadmapItemPatch,
    RoadmapPlan,
    RoadmapPlanIn,
    RegisterIn,
    TenantMembership,
    TenantSettings,
    TenantSettingsIn,
    Ticket,
    User,
)
from integrations_meta import INTEGRATIONS, list_integrations
from docs_content import DOCS, get_categories, get_doc, get_docs_summary
import ai
import ai_visibility
import ai_territory_intelligence
import connectors
import monthly_touch
import clickup_client_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mtos")

app = FastAPI(title="Monthly Touch OS")
api = APIRouter(prefix="/api")
DB_READY = False


def tenant_scope(tenant_id: str) -> dict:
    return {"tenant_id": tenant_id}


def _parse_iso_date(v: str) -> Optional[str]:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except Exception:
        try:
            return datetime.fromisoformat(s.split("T", 1)[0]).date().isoformat()
        except Exception:
            return None


def _default_last_30_days() -> tuple[str, str]:
    end = utcnow().date().isoformat()
    start = (utcnow().date() - timedelta(days=30)).isoformat()
    return start, end


def _day_bounds(start_date: str, end_date: str) -> tuple[str, str]:
    s = _parse_iso_date(start_date) or _default_last_30_days()[0]
    e = _parse_iso_date(end_date) or _default_last_30_days()[1]
    return f"{s}T00:00:00", f"{e}T23:59:59.999999"


async def _require_client_access(ctx, client_id: str) -> dict:
    doc = await db.clients.find_one({"_id": str(client_id), **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Client not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    return doc


async def _require_meeting_access(ctx, meeting_id: str) -> dict:
    doc = await db.meetings.find_one({"_id": str(meeting_id), **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Meeting not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    return doc


async def _allowed_client_ids(ctx) -> Optional[List[str]]:
    if ctx.user.role == "admin" or ctx.tenant_role in ("owner", "admin"):
        return None
    docs = await db.clients.find({"$and": [tenant_scope(ctx.tenant_id), {"account_manager_id": ctx.user.id}, {"status": "active"}]}).to_list(5000)
    return [str(d.get("_id")) for d in (docs or []) if str(d.get("_id") or "").strip()]


async def _bg_publish_clickup_brief(tenant_id: str, meeting_id: str) -> None:
    try:
        m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(tenant_id)})
        if not m_doc:
            return
        c_doc = await db.clients.find_one({"_id": str(m_doc.get("client_id") or ""), **tenant_scope(tenant_id)})
        res = await connectors.publish_clickup_meeting_brief(tenant_id, m_doc, c_doc or {})
        if not res.get("ok"):
            return
        task_id = str(res.get("task_id") or "").strip()
        task_url = str(res.get("url") or "").strip()
        if not task_id:
            return
        await db.meetings.update_one(
            {"_id": meeting_id, **tenant_scope(tenant_id)},
            {"$set": {"clickup_client_book.brief_task_id": task_id, "clickup_client_book.brief_task_url": task_url, "updated_at": utcnow().isoformat()}},
        )
    except Exception as exc:
        logger.error("clickup brief publish failed: %s", exc)


async def _bg_publish_clickup_summary(tenant_id: str, meeting_id: str) -> None:
    try:
        m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(tenant_id)})
        if not m_doc:
            return
        if not str(m_doc.get("recap_email") or "").strip():
            return
        if not str(m_doc.get("automation_approved_at") or "").strip():
            return
        c_doc = await db.clients.find_one({"_id": str(m_doc.get("client_id") or ""), **tenant_scope(tenant_id)})
        actions = await db.action_items.find({"$and": [{"meeting_id": meeting_id}, tenant_scope(tenant_id)]}).to_list(500)
        tickets = await db.tickets.find({"$and": [{"meeting_id": meeting_id}, tenant_scope(tenant_id)]}).to_list(500)
        res = await connectors.publish_clickup_meeting_summary(tenant_id, m_doc, c_doc or {}, actions or [], tickets or [])
        if not res.get("ok"):
            return
        task_id = str(res.get("task_id") or "").strip()
        task_url = str(res.get("url") or "").strip()
        if not task_id:
            return
        await db.meetings.update_one(
            {"_id": meeting_id, **tenant_scope(tenant_id)},
            {"$set": {"clickup_client_book.summary_task_id": task_id, "clickup_client_book.summary_task_url": task_url, "updated_at": utcnow().isoformat()}},
        )
    except Exception as exc:
        logger.error("clickup summary publish failed: %s", exc)


async def _bg_publish_clickup_tickets(tenant_id: str, meeting_id: str) -> None:
    try:
        m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(tenant_id)})
        if not m_doc:
            return
        tickets = await db.tickets.find({"$and": [{"meeting_id": meeting_id}, tenant_scope(tenant_id)]}).to_list(1000)
        if not tickets:
            return
        res = await connectors.publish_clickup_department_tickets(tenant_id, m_doc, tickets)
        if not res.get("ok"):
            return
        for it in res.get("published") or []:
            tid = str(it.get("ticket_id") or "").strip()
            task_id = str(it.get("task_id") or "").strip()
            url = str(it.get("url") or "").strip()
            if tid and task_id:
                await db.tickets.update_one(
                    {"_id": tid, **tenant_scope(tenant_id)},
                    {"$set": {"external_id": task_id, "external_url": url, "updated_at": utcnow().isoformat()}},
                )
    except Exception as exc:
        logger.error("clickup tickets publish failed: %s", exc)


async def _bg_send_client_recap_email(tenant_id: str, meeting_id: str, user_id: str) -> None:
    try:
        m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(tenant_id)})
        if not m_doc:
            return
        if str(m_doc.get("recap_sent_at") or "").strip():
            return
        draft = m_doc.get("automation_draft") or {}
        email = (draft.get("client_recap_email") or {}) if isinstance(draft, dict) else {}
        subject = str(email.get("subject") or "").strip()
        plain = str(email.get("plain") or "").strip()
        if not plain:
            return
        client_id = str(m_doc.get("client_id") or "").strip()
        c_doc = await db.clients.find_one({"_id": client_id, **tenant_scope(tenant_id)})
        to_addr = str((c_doc or {}).get("email") or "").strip()
        if not to_addr:
            return
        res = await connectors.send_gmail_plain_email(tenant_id, user_id, to_addr, subject, plain)
        if not res.get("ok"):
            return
        await db.meetings.update_one(
            {"_id": meeting_id, **tenant_scope(tenant_id)},
            {"$set": {"recap_subject": subject, "recap_email": plain, "recap_sent_at": utcnow().isoformat(), "updated_at": utcnow().isoformat()}},
        )
    except Exception as exc:
        logger.error("gmail recap send failed: %s", exc)


GOOGLE_OAUTH_PLATFORMS = {
    "google_calendar",
    "google_meet",
    "google_drive",
    "gmail",
    "google_search_console",
    "google_analytics",
    "google_business_profile",
    "google_lsa",
    "google_ads",
}


def google_scopes_for_platform(platform: str) -> List[str]:
    if platform == "google_calendar":
        return ["https://www.googleapis.com/auth/calendar.events"]
    if platform == "gmail":
        return ["https://www.googleapis.com/auth/gmail.readonly"]
    if platform == "google_drive":
        return ["https://www.googleapis.com/auth/drive.readonly"]
    if platform == "google_meet":
        return [
            "https://www.googleapis.com/auth/meetings.space.readonly",
            "https://www.googleapis.com/auth/documents.readonly",
        ]
    if platform == "google_ads":
        return ["https://www.googleapis.com/auth/adwords"]
    if platform == "google_search_console":
        return ["https://www.googleapis.com/auth/webmasters.readonly"]
    if platform == "google_analytics":
        return ["https://www.googleapis.com/auth/analytics.readonly"]
    if platform == "google_business_profile":
        return ["https://www.googleapis.com/auth/business.manage"]
    if platform == "google_lsa":
        return ["https://www.googleapis.com/auth/adwords"]
    return []


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
_cors_origin_regex = os.environ.get("CORS_ORIGIN_REGEX", "").strip() or None
_cors_allow_credentials = True
if "*" in _cors_origins and not _cors_origin_regex:
    _cors_allow_credentials = False
app.add_middleware(
    CORSMiddleware,
    allow_credentials=_cors_allow_credentials,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================== HEALTH =====================
@api.get("/")
async def root():
    await _ensure_db_ready()
    return {
        "name": "Monthly Touch OS API",
        "version": "1.0.0",
        "status": "ok",
        "db_ready": DB_READY,
        "google_login_configured": bool(GOOGLE_OAUTH_CLIENT_ID),
        "google_oauth_configured": bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REDIRECT_URI),
    }


# ===================== AUTH =====================
@api.post("/auth/register")
async def register(request: Request, data: RegisterIn, _: None = Depends(require_db_ready)):
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
        host_tenant_id = await resolve_tenant_id_from_host(request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
        if host_tenant_id:
            existing_count = await db.tenant_memberships.count_documents({"tenant_id": str(host_tenant_id), "status": "active"})
            role_if_create = "owner" if existing_count == 0 else "member"
            membership = await ensure_membership_for_tenant(user, str(host_tenant_id), role_if_create=role_if_create)
        else:
            membership = await ensure_membership(user)
        if not await db.tenant_settings.find_one({"tenant_id": membership.tenant_id}):
            settings = TenantSettings(
                tenant_id=membership.tenant_id,
                branding={"product_name": "Monthly Touch OS"},
                terminology={"monthly_touch": "Monthly Touch", "client_singular": "Client", "client_plural": "Clients"},
                workflows={"meeting_types": [{"key": "monthly_touch", "label": "Monthly Touch", "wins_count": 3, "issues_count": 2}]},
                analysis={"ai_default_model": ai.DEFAULT_MODEL},
            )
            await db.tenant_settings.insert_one(settings.to_mongo())
        token = create_token(user.id, user.role, membership.tenant_id, membership.role)
        return {"token": token, "user": to_public(user).model_dump(), "tenant_id": membership.tenant_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("register failed: %s", exc)
        raise HTTPException(503, "Database unavailable. Check Atlas Network Access / connection string.") from exc


@api.post("/auth/login")
async def login(request: Request, data: LoginIn, _: None = Depends(require_db_ready)):
    try:
        doc = await db.users.find_one({"email": data.email})
        if not doc:
            raise HTTPException(401, "Invalid credentials")
        user = User.from_mongo(doc)
        if (user.auth_provider or "local") == "google":
            raise HTTPException(400, "This account uses Google sign-in. Use “Continue with Google”.")
        if not user.active or not verify_password(data.password, user.password_hash):
            raise HTTPException(401, "Invalid credentials")
        host_tenant_id = await resolve_tenant_id_from_host(request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
        if host_tenant_id:
            mdoc = await db.tenant_memberships.find_one({"tenant_id": str(host_tenant_id), "user_id": user.id, "status": "active"})
            if not mdoc:
                raise HTTPException(403, "Not a member of this tenant")
            membership = TenantMembership.from_mongo(mdoc)
        else:
            membership = await ensure_membership(user)
        token = create_token(user.id, user.role, membership.tenant_id, membership.role)
        return {"token": token, "user": to_public(user).model_dump(), "tenant_id": membership.tenant_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("login failed: %s", exc)
        raise HTTPException(503, "Database unavailable. Check Atlas Network Access / connection string.") from exc


@api.post("/auth/google")
async def google_login(request: Request, data: GoogleLoginIn, _: None = Depends(require_db_ready)):
    if not GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(500, "Google login is not configured on the backend")
    cred = (data.credential or "").strip()
    if not cred:
        raise HTTPException(400, "Missing credential")
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": cred})
    if resp.status_code != 200:
        raise HTTPException(400, "Invalid Google credential")
    info = resp.json() or {}
    if str(info.get("aud") or "") != str(GOOGLE_OAUTH_CLIENT_ID):
        raise HTTPException(400, "Google credential audience mismatch")
    email = str(info.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Google credential missing email")
    name = str(info.get("name") or "").strip() or email.split("@")[0]
    sub = str(info.get("sub") or "").strip() or None
    picture = str(info.get("picture") or "").strip() or None

    doc = await db.users.find_one({"email": email})
    if doc:
        user = User.from_mongo(doc)
        patch = {"updated_at": utcnow().isoformat()}
        if (user.auth_provider or "local") != "google":
            patch["auth_provider"] = "google"
        if sub and not user.google_sub:
            patch["google_sub"] = sub
        if picture and not user.avatar_url:
            patch["avatar_url"] = picture
        if patch.keys() != {"updated_at"}:
            await db.users.update_one({"_id": user.id}, {"$set": patch})
            doc = await db.users.find_one({"_id": user.id})
            user = User.from_mongo(doc)
    else:
        user_count = await db.users.count_documents({})
        role = "admin" if user_count == 0 else "manager"
        user = User(
            email=email,
            name=name,
            role=role,
            password_hash="",
            avatar_url=picture,
            auth_provider="google",
            google_sub=sub,
        )
        await db.users.insert_one(user.to_mongo())

    host_tenant_id = await resolve_tenant_id_from_host(request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
    if host_tenant_id:
        mdoc = await db.tenant_memberships.find_one({"tenant_id": str(host_tenant_id), "user_id": user.id, "status": "active"})
        if mdoc:
            membership = TenantMembership.from_mongo(mdoc)
        else:
            existing_count = await db.tenant_memberships.count_documents({"tenant_id": str(host_tenant_id), "status": "active"})
            role_if_create = "owner" if existing_count == 0 else "member"
            membership = await ensure_membership_for_tenant(user, str(host_tenant_id), role_if_create=role_if_create)
    else:
        membership = await ensure_membership(user)
    token = create_token(user.id, user.role, membership.tenant_id, membership.role)
    return {"token": token, "user": to_public(user).model_dump(), "tenant_id": membership.tenant_id}


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


@api.get("/oauth/google/start")
async def oauth_google_start(platform: str = Query(...), ctx=Depends(get_current_context)):
    if platform not in GOOGLE_OAUTH_PLATFORMS:
        raise HTTPException(400, "Unsupported platform")
    cfg = await _google_oauth_config(ctx.tenant_id)
    if not cfg.get("client_id") or not cfg.get("client_secret") or not cfg.get("redirect_uri"):
        raise HTTPException(500, "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET/GOOGLE_OAUTH_REDIRECT_URI on the backend or configure Integrations → Google OAuth.")
    scopes = google_scopes_for_platform(platform)
    if not scopes:
        raise HTTPException(400, "Missing scopes for platform")
    state = new_id()
    await db.oauth_states.insert_one(
        {
            "_id": state,
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user.id,
            "provider": "google",
            "platform": platform,
            "scopes": scopes,
            "created_at": utcnow().isoformat(),
        }
    )
    params = {
        "client_id": cfg.get("client_id"),
        "redirect_uri": cfg.get("redirect_uri"),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "scope": " ".join(scopes),
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return {"ok": True, "url": url}


@api.get("/oauth/google/status")
async def oauth_google_status(platform: str = Query(...), ctx=Depends(get_current_context)):
    doc = await db.user_oauth_tokens.find_one(
        {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "provider": "google", "platform": platform}
    )
    if not doc:
        return {"ok": True, "connected": False}
    return {"ok": True, "connected": True, "platform": platform, "scopes": doc.get("scopes") or [], "updated_at": doc.get("updated_at")}


@api.post("/oauth/google/disconnect")
async def oauth_google_disconnect(platform: str = Query(...), ctx=Depends(get_current_context)):
    await db.user_oauth_tokens.delete_one({"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "provider": "google", "platform": platform})
    return {"ok": True}


@api.get("/oauth/google/callback")
async def oauth_google_callback(code: str = Query(...), state: str = Query(...)):
    st = await db.oauth_states.find_one({"_id": state, "provider": "google"})
    if not st:
        raise HTTPException(400, "Invalid OAuth state")
    tenant_id = st.get("tenant_id")
    user_id = st.get("user_id")
    platform = st.get("platform")
    scopes = st.get("scopes") or []
    cfg = await _google_oauth_config(str(tenant_id))
    if not cfg.get("client_id") or not cfg.get("client_secret") or not cfg.get("redirect_uri"):
        raise HTTPException(500, "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET/GOOGLE_OAUTH_REDIRECT_URI on the backend or configure Integrations → Google OAuth.")

    payload = {
        "client_id": cfg.get("client_id"),
        "client_secret": cfg.get("client_secret"),
        "code": code,
        "redirect_uri": cfg.get("redirect_uri"),
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data=payload)
    if resp.status_code != 200:
        await db.oauth_states.delete_one({"_id": state})
        detail = resp.text[:300]
        try:
            j = resp.json() or {}
            if isinstance(j, dict) and (j.get("error") or j.get("error_description")):
                detail = f"{j.get('error') or 'oauth_error'}: {j.get('error_description') or ''}".strip()
        except Exception:
            pass
        raise HTTPException(400, f"oauth_http_{resp.status_code}: {detail}")
    data = resp.json() or {}
    refresh_token = data.get("refresh_token") or ""
    if not str(refresh_token).strip():
        await db.oauth_states.delete_one({"_id": state})
        raise HTTPException(400, "Google did not return a refresh_token. Re-run Connect and ensure prompt=consent is forced.")

    now = utcnow().isoformat()
    await db.user_oauth_tokens.update_one(
        {"tenant_id": tenant_id, "user_id": user_id, "provider": "google", "platform": platform},
        {"$set": {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "provider": "google",
            "platform": platform,
            "refresh_token_encrypted": encrypt_secret(str(refresh_token)),
            "scopes": scopes,
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    await db.oauth_states.delete_one({"_id": state})

    html = f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body><script>
try {{
  if (window.opener) {{
    window.opener.postMessage({{ type: "google_oauth_success", platform: "{platform}" }}, "*");
  }}
}} catch (e) {{}}
window.close();
</script>
<div style="font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 20px;">
  Connected. You can close this window.
</div>
</body></html>"""
    return Response(content=html, media_type="text/html")


@api.get("/settings")
async def get_settings(ctx=Depends(get_current_context)):
    doc = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    if not doc:
        settings = TenantSettings(
            tenant_id=ctx.tenant_id,
            branding={"product_name": "Monthly Touch OS"},
            terminology={"monthly_touch": "Monthly Touch", "client_singular": "Client", "client_plural": "Clients"},
            workflows={"meeting_types": [{"key": "monthly_touch", "label": "Monthly Touch", "wins_count": 3, "issues_count": 2}]},
            analysis={"ai_default_model": ai.DEFAULT_MODEL, "ai_territory_scan_frequency_hours": 24, "ai_territory_max_prompts": 60},
        )
        await db.tenant_settings.insert_one(settings.to_mongo())
        return settings.model_dump()
    return TenantSettings.from_mongo(doc).model_dump()


@api.put("/settings")
async def put_settings(data: TenantSettingsIn, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    patch = {
        "branding": data.branding or {},
        "terminology": data.terminology or {},
        "workflows": data.workflows or {},
        "analysis": data.analysis or {},
        "updated_at": utcnow().isoformat(),
    }
    await db.tenant_settings.update_one({"tenant_id": ctx.tenant_id}, {"$set": patch}, upsert=True)
    doc = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    return TenantSettings.from_mongo(doc).model_dump()


def _default_prompt_text(key: str) -> str:
    if key == "monthly_touch_analysis":
        return (
            "Analyze the transcript and produce a structured Monthly Touch analysis.\n"
            "Focus on:\n"
            "- Client personality and decision-making style\n"
            "- Trust issues, frustrations, and relationship opportunities\n"
            "- Business goals, growth goals, and hidden risks\n"
            "- Operational bottlenecks that affect lead handling, sales, fulfillment, retention\n"
            "- Clear action items with owner_type (agency|client) and suggested priority\n"
            "Be specific and evidence-based. Do not invent facts."
        )
    return ""


@api.get("/prompts/{key}")
async def get_prompt_template(key: str, ctx=Depends(get_current_context)):
    doc = await db.prompt_templates.find_one({"tenant_id": ctx.tenant_id, "key": str(key)})
    if not doc:
        return {"ok": True, "key": str(key), "text": _default_prompt_text(str(key))}
    return {"ok": True, **PromptTemplate.from_mongo(doc).model_dump()}


@api.put("/prompts/{key}")
async def put_prompt_template(key: str, data: PromptTemplateIn, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    now = utcnow().isoformat()
    patch = {"tenant_id": ctx.tenant_id, "key": str(key), "text": str(data.text or ""), "updated_at": now}
    await db.prompt_templates.update_one({"tenant_id": ctx.tenant_id, "key": str(key)}, {"$set": patch}, upsert=True)
    doc = await db.prompt_templates.find_one({"tenant_id": ctx.tenant_id, "key": str(key)})
    return {"ok": True, **PromptTemplate.from_mongo(doc).model_dump()}


async def _is_internal_tenant_id(tenant_id: str) -> bool:
    tdoc = await db.tenants.find_one({"_id": tenant_id})
    tslug = str((tdoc or {}).get("slug") or "")
    internal_slug = os.environ.get("INTERNAL_WIKI_TENANT_SLUG", "default").strip()
    return bool(tslug and internal_slug and tslug == internal_slug)


async def _ai_visibility_entitlement(ctx) -> dict:
    if ctx.user.role == "admin":
        return {"enabled": True, "trial_expires_at": None, "reason": "global_admin"}
    if await _is_internal_tenant_id(ctx.tenant_id):
        return {"enabled": True, "trial_expires_at": None, "reason": "internal_tenant"}

    sdoc = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    settings = TenantSettings.from_mongo(sdoc) if sdoc else TenantSettings(tenant_id=ctx.tenant_id)
    analysis = settings.analysis or {}
    ent = (analysis.get("entitlements") or {}) if isinstance(analysis, dict) else {}
    enabled = bool(ent.get("ai_visibility"))
    trial_expires_at = str(analysis.get("ai_visibility_trial_expires_at") or "").strip() or None

    if enabled:
        return {"enabled": True, "trial_expires_at": trial_expires_at, "reason": "enabled"}
    if trial_expires_at:
        try:
            exp = datetime.fromisoformat(trial_expires_at.replace("Z", "+00:00"))
            if exp > utcnow():
                return {"enabled": True, "trial_expires_at": trial_expires_at, "reason": "trial"}
        except Exception:
            pass

    return {"enabled": False, "trial_expires_at": trial_expires_at, "reason": "disabled"}


async def _require_ai_visibility(ctx=Depends(get_current_context)):
    ent = await _ai_visibility_entitlement(ctx)
    if not ent.get("enabled"):
        raise HTTPException(403, "AI Visibility is not enabled for this tenant")
    return ctx


@api.get("/ai-visibility/entitlement")
async def ai_visibility_entitlement(ctx=Depends(get_current_context)):
    ent = await _ai_visibility_entitlement(ctx)
    can_manage = bool(ctx.user.role == "admin" or ctx.tenant_role in ("owner", "admin"))
    return {"ok": True, **ent, "can_manage": can_manage}


@api.post("/super/ai-visibility/grant")
async def super_grant_ai_visibility(
    tenant_id: str = Query(...),
    enabled: bool = Query(True),
    trial_days: int = Query(14, ge=1, le=365),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    tdoc = await db.tenants.find_one({"_id": tenant_id})
    if not tdoc:
        raise HTTPException(404, "Tenant not found")

    sdoc = await db.tenant_settings.find_one({"tenant_id": tenant_id})
    settings = TenantSettings.from_mongo(sdoc) if sdoc else TenantSettings(tenant_id=tenant_id)
    analysis = dict(settings.analysis or {})
    ent = dict((analysis.get("entitlements") or {}) if isinstance(analysis, dict) else {})
    ent["ai_visibility"] = bool(enabled)
    analysis["entitlements"] = ent
    if enabled:
        analysis["ai_visibility_trial_expires_at"] = (utcnow() + timedelta(days=int(trial_days))).isoformat()
    else:
        analysis.pop("ai_visibility_trial_expires_at", None)

    patch = {"analysis": analysis, "updated_at": utcnow().isoformat()}
    await db.tenant_settings.update_one({"tenant_id": tenant_id}, {"$set": patch}, upsert=True)
    return {"ok": True}


@api.get("/ai-visibility/configs")
async def list_ai_visibility_configs(
    client_id: str = Query(...),
    ctx=Depends(_require_ai_visibility),
):
    docs = await db.ai_visibility_configs.find({"$and": [{"client_id": client_id}, tenant_scope(ctx.tenant_id)]}).sort("created_at", -1).to_list(200)
    client_doc = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    client_obj = client_doc or {}
    out = []
    for d in docs or []:
        cfg = AiVisibilityConfig.from_mongo(d).model_dump()
        brand, domain = ai_visibility.infer_brand_and_domain(client_obj, cfg.get("brand_override"), cfg.get("domain_override"))
        cfg["keyword_slots"] = []
        cfg["inferred_brand"] = brand
        cfg["inferred_domain"] = domain
        out.append(cfg)
    return {"ok": True, "configs": out}


@api.post("/ai-visibility/configs")
async def create_ai_visibility_config(
    data: AiVisibilityConfigIn,
    client_id: str = Query(...),
    ctx=Depends(_require_ai_visibility),
):
    existing = await db.ai_visibility_configs.find_one({"$and": [{"client_id": client_id}, tenant_scope(ctx.tenant_id)]})
    if existing:
        return {"ok": True, "config": AiVisibilityConfig.from_mongo(existing).model_dump()}

    client_doc = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    if not client_doc:
        raise HTTPException(404, "Client not found")

    intel = await ai_visibility.generate_prompt_intelligence(client_doc)
    cfg = AiVisibilityConfig(
        tenant_id=ctx.tenant_id,
        client_id=client_id,
        market=str(intel.get("market") or "").strip(),
        market_override=None,
        keywords=[],
        brand_override=None,
        domain_override=None,
        enabled=True,
    )
    await db.ai_visibility_configs.insert_one(cfg.to_mongo())
    return {"ok": True, "config": cfg.model_dump(), "prompt_intelligence": {"themes": intel.get("themes") or [], "prompts_total": intel.get("prompts_total") or 0}}


@api.patch("/ai-visibility/configs/{config_id}")
async def update_ai_visibility_config(
    config_id: str,
    data: Dict[str, Any] = Body(default_factory=dict),
    ctx=Depends(_require_ai_visibility),
):
    cfg_doc = await db.ai_visibility_configs.find_one({"_id": config_id, **tenant_scope(ctx.tenant_id)})
    if not cfg_doc:
        raise HTTPException(404, "Config not found")
    cfg = AiVisibilityConfig.from_mongo(cfg_doc)
    client_doc = await db.clients.find_one({"_id": cfg.client_id, **tenant_scope(ctx.tenant_id)})
    if not isinstance(data, dict):
        raise HTTPException(400, "Invalid payload")

    patch: Dict[str, Any] = {"updated_at": utcnow().isoformat()}

    if not data:
        intel = await ai_visibility.generate_prompt_intelligence(client_doc or {})
        patch["market"] = str(intel.get("market") or "").strip()
        await db.ai_visibility_configs.update_one({"_id": config_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
        doc = await db.ai_visibility_configs.find_one({"_id": config_id, **tenant_scope(ctx.tenant_id)})
        return {
            "ok": True,
            "config": AiVisibilityConfig.from_mongo(doc).model_dump(),
            "prompt_intelligence": {"themes": intel.get("themes") or [], "prompts_total": intel.get("prompts_total") or 0},
        }

    if "enabled" in data:
        patch["enabled"] = bool(data.get("enabled"))

    if "brand_override" in data:
        v = str(data.get("brand_override") or "").strip()
        patch["brand_override"] = v if v else None
    if "domain_override" in data:
        v = str(data.get("domain_override") or "").strip()
        patch["domain_override"] = v if v else None
    if "market_override" in data:
        v = str(data.get("market_override") or "").strip()
        patch["market_override"] = v if v else None

    await db.ai_visibility_configs.update_one({"_id": config_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    doc = await db.ai_visibility_configs.find_one({"_id": config_id, **tenant_scope(ctx.tenant_id)})
    return {"ok": True, "config": AiVisibilityConfig.from_mongo(doc).model_dump()}


@api.get("/ai-visibility/configs/{config_id}/runs")
async def list_ai_visibility_runs(
    config_id: str,
    limit: int = Query(100, ge=1, le=500),
    scan_id: Optional[str] = Query(None),
    ctx=Depends(_require_ai_visibility),
):
    q = {"$and": [{"config_id": config_id}, tenant_scope(ctx.tenant_id)]}
    if scan_id:
        q["$and"].append({"scan_id": str(scan_id)})
    docs = await db.ai_visibility_runs.find(q).sort("created_at", -1).to_list(int(limit))
    return {"ok": True, "runs": [AiVisibilityRun.from_mongo(d).model_dump() for d in (docs or [])]}


@api.get("/ai-visibility/configs/{config_id}/scans")
async def list_ai_visibility_scans(
    config_id: str,
    limit: int = Query(30, ge=1, le=200),
    ctx=Depends(_require_ai_visibility),
):
    docs = await db.ai_visibility_scans.find({"$and": [{"config_id": config_id}, tenant_scope(ctx.tenant_id)]}).sort("created_at", -1).to_list(int(limit))
    return {"ok": True, "scans": [AiVisibilityScan.from_mongo(d).model_dump() for d in (docs or [])]}


@api.post("/ai-visibility/configs/{config_id}/run")
async def run_ai_visibility_scan(config_id: str, ctx=Depends(_require_ai_visibility)):
    cfg_doc = await db.ai_visibility_configs.find_one({"_id": config_id, **tenant_scope(ctx.tenant_id)})
    if not cfg_doc:
        raise HTTPException(404, "Config not found")
    cfg = AiVisibilityConfig.from_mongo(cfg_doc)
    if not cfg.enabled:
        raise HTTPException(400, "Config is disabled")

    client_doc = await db.clients.find_one({"_id": cfg.client_id, **tenant_scope(ctx.tenant_id)})
    if not client_doc:
        raise HTTPException(404, "Client not found")

    brand, domain = ai_visibility.infer_brand_and_domain(client_doc, cfg.brand_override, cfg.domain_override)
    intel = await ai_visibility.generate_prompt_intelligence(client_doc)
    market = str(cfg.market_override or intel.get("market") or cfg.market or "").strip()
    themes = intel.get("themes") or []
    prompts = []
    for t in themes:
        if not isinstance(t, dict):
            continue
        tname = str(t.get("name") or "").strip()
        for p0 in (t.get("prompts") or []):
            if not isinstance(p0, dict):
                continue
            q0 = str(p0.get("query") or "").strip()
            pk0 = str(p0.get("kind") or "").strip()
            if not q0:
                continue
            prompts.append({"query": q0, "prompt_kind": pk0 or "commercial", "theme": tname or None})
    if not prompts:
        raise HTTPException(400, "Prompt generation failed (no prompts)")

    providers = []
    if os.environ.get("OPENAI_API_KEY", "").strip():
        providers.append("openai")
    if os.environ.get("GEMINI_API_KEY", "").strip():
        providers.append("gemini")
    if os.environ.get("PERPLEXITY_API_KEY", "").strip():
        providers.append("perplexity")
    if not providers:
        raise HTTPException(400, "No AI providers configured. Set GEMINI_API_KEY and/or OPENAI_API_KEY and/or PERPLEXITY_API_KEY.")
    created = 0
    hit_count = 0
    per_provider = {p: {"hits": 0, "total": 0, "errors": 0} for p in providers}
    scan_id = new_id()
    runs_for_metrics = []

    for it in prompts:
        for p in providers:
            per_provider[p]["total"] += 1
            try:
                r = await ai_visibility.scan_keyword(provider=p, keyword=it["query"], market=market, brand=brand, domain=domain)
                run = AiVisibilityRun(
                    tenant_id=ctx.tenant_id,
                    config_id=config_id,
                    client_id=cfg.client_id,
                    scan_id=scan_id,
                    market=market,
                    keyword=it["query"],
                    theme=it.get("theme"),
                    prompt_kind=it.get("prompt_kind"),
                    provider=p,
                    prompt=r.get("prompt") or "",
                    response_text=r.get("response_text") or "",
                    parsed=r.get("parsed") or {},
                    hit=bool(r.get("hit")),
                    hit_brand=bool(r.get("hit_brand")),
                    hit_domain=bool(r.get("hit_domain")),
                )
                await db.ai_visibility_runs.insert_one(run.to_mongo())
                created += 1
                if run.hit:
                    hit_count += 1
                    per_provider[p]["hits"] += 1
                runs_for_metrics.append(run.model_dump())
            except ai.AIProviderError:
                per_provider[p]["errors"] += 1
            except Exception:
                per_provider[p]["errors"] += 1

    total = sum(int(per_provider[p]["total"]) for p in providers)
    score = (float(hit_count) / float(total)) * 100.0 if total else 0.0
    comp = ai_visibility.competitor_discovery_from_runs(runs_for_metrics, brand=brand, domain=domain)
    platform_rankings = {}
    for p in providers:
        pt = int(per_provider[p]["total"] or 0)
        ph = int(per_provider[p]["hits"] or 0)
        platform_rankings[p] = {"hits": ph, "total": pt, "score": round((float(ph) / float(pt) * 100.0) if pt else 0.0, 2)}

    scan = AiVisibilityScan(
        tenant_id=ctx.tenant_id,
        config_id=config_id,
        client_id=cfg.client_id,
        scan_id=scan_id,
        market=market,
        brand=brand,
        domain=domain,
        providers=per_provider,
        total=total,
        hits=hit_count,
        overall_visibility_score=round(score, 2),
        share_of_voice={"items": comp.get("share_of_voice") or [], "market_rank": comp.get("market_rank")},
        platform_rankings=platform_rankings,
        themes=themes,
        prompts_total=len(prompts),
        competitors=comp.get("competitors") or [],
        content_intelligence={"status": "generated", "source": "website+gbp"},
        growth_engine={"status": "generated", "source": "scan_mentions"},
    )
    await db.ai_visibility_scans.insert_one(scan.to_mongo())
    await db.ai_visibility_configs.update_one({"_id": config_id, **tenant_scope(ctx.tenant_id)}, {"$set": {"market": market, "updated_at": utcnow().isoformat()}})

    return {
        "ok": True,
        "scan_id": scan_id,
        "scan": scan.model_dump(),
        "created": created,
        "hits": hit_count,
        "total": total,
        "providers": per_provider,
        "brand": brand,
        "domain": domain,
        "market": market,
    }


def _ai_territory_settings(settings: TenantSettings) -> Dict[str, Any]:
    analysis = settings.analysis or {}
    if not isinstance(analysis, dict):
        analysis = {}
    freq = int(analysis.get("ai_territory_scan_frequency_hours") or 24)
    max_prompts = int(analysis.get("ai_territory_max_prompts") or 60)
    freq = max(1, min(freq, 168))
    max_prompts = max(10, min(max_prompts, 200))
    return {"scan_frequency_hours": freq, "max_prompts": max_prompts}


@api.get("/ai-territory/settings")
async def get_ai_territory_settings(ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    sdoc = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    settings = TenantSettings.from_mongo(sdoc) if sdoc else TenantSettings(tenant_id=ctx.tenant_id)
    return {"ok": True, **_ai_territory_settings(settings)}


@api.put("/ai-territory/settings")
async def put_ai_territory_settings(
    scan_frequency_hours: int = Query(24, ge=1, le=168),
    max_prompts: int = Query(60, ge=10, le=200),
    ctx=Depends(get_current_context),
):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    sdoc = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    settings = TenantSettings.from_mongo(sdoc) if sdoc else TenantSettings(tenant_id=ctx.tenant_id)
    analysis = dict(settings.analysis or {}) if isinstance(settings.analysis, dict) else {}
    analysis["ai_territory_scan_frequency_hours"] = int(scan_frequency_hours)
    analysis["ai_territory_max_prompts"] = int(max_prompts)
    await db.tenant_settings.update_one(
        {"tenant_id": ctx.tenant_id},
        {"$set": {"analysis": analysis, "updated_at": utcnow().isoformat()}},
        upsert=True,
    )
    return {"ok": True}


@api.get("/ai-territory/{client_id}/latest")
async def ai_territory_latest(client_id: str, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, client_id)
    cfg = await db.ai_visibility_configs.find_one({"$and": [{"client_id": client_id}, tenant_scope(ctx.tenant_id)]})
    if not cfg:
        return {"ok": True, "scan": None, "events": []}
    scan = await db.ai_visibility_scans.find_one(
        {"$and": [{"config_id": str(cfg.get("_id"))}, {"client_id": client_id}, tenant_scope(ctx.tenant_id)]},
        sort=[("created_at", -1)],
    )
    events = await db.ai_territory_events.find({"$and": [{"client_id": client_id}, tenant_scope(ctx.tenant_id)]}).sort("created_at", -1).to_list(50)
    return {"ok": True, "scan": AiVisibilityScan.from_mongo(scan).model_dump() if scan else None, "events": events}


@api.get("/ai-territory/{client_id}/history")
async def ai_territory_history(client_id: str, limit: int = 30, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, client_id)
    limit = max(1, min(int(limit or 30), 200))
    cfg = await db.ai_visibility_configs.find_one({"$and": [{"client_id": client_id}, tenant_scope(ctx.tenant_id)]})
    if not cfg:
        return {"ok": True, "scans": []}
    docs = await db.ai_visibility_scans.find(
        {"$and": [{"config_id": str(cfg.get("_id"))}, {"client_id": client_id}, tenant_scope(ctx.tenant_id)]}
    ).sort("created_at", -1).to_list(limit)
    return {"ok": True, "scans": [AiVisibilityScan.from_mongo(d).model_dump() for d in (docs or [])]}


@api.post("/ai-territory/{client_id}/run")
async def ai_territory_run_now(client_id: str, ctx=Depends(get_current_context)):
    c_doc = await _require_client_access(ctx, client_id)
    sdoc = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    settings = TenantSettings.from_mongo(sdoc) if sdoc else TenantSettings(tenant_id=ctx.tenant_id)
    cfg = _ai_territory_settings(settings)
    res = await ai_territory_intelligence.run_ai_territory_scan_for_client(
        tenant_id=ctx.tenant_id,
        client_doc=c_doc,
        user_id=ctx.user.id,
        max_prompts=int(cfg.get("max_prompts") or 60),
        force=True,
        reason="manual",
    )
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Scan failed")
    scan = res.get("scan")
    return {"ok": True, "scan_id": res.get("scan_id"), "scan": AiVisibilityScan.from_mongo(scan).model_dump() if isinstance(scan, dict) else scan}


@api.get("/white-label/domains")
async def list_white_label_domains(ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    tdoc = await db.tenants.find_one({"_id": ctx.tenant_id})
    slug = (tdoc or {}).get("slug") or ""
    base_domain = os.environ.get("BASE_DOMAIN", "mapranking.com").strip().lower()
    default_subdomain = f"{slug}.{base_domain}" if slug and base_domain else ""
    docs = await db.tenant_domains.find({"tenant_id": ctx.tenant_id}).to_list(200)
    custom_domains = sorted({str(d.get("domain") or "").strip().lower() for d in (docs or []) if d.get("domain")})
    return {"ok": True, "default_subdomain": default_subdomain, "custom_domains": custom_domains}


@api.post("/white-label/domains")
async def add_white_label_domain(domain: str = Query(...), ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    d = str(domain or "").strip().lower()
    if not d or "." not in d:
        raise HTTPException(400, "Invalid domain")
    if ":" in d or "/" in d:
        raise HTTPException(400, "Invalid domain")
    existing = await db.tenant_domains.find_one({"domain": d})
    if existing and str(existing.get("tenant_id")) != str(ctx.tenant_id):
        raise HTTPException(409, "Domain already in use by another tenant")
    await db.tenant_domains.update_one(
        {"domain": d},
        {"$set": {"domain": d, "tenant_id": ctx.tenant_id, "updated_at": utcnow().isoformat()}, "$setOnInsert": {"created_at": utcnow().isoformat()}},
        upsert=True,
    )
    return {"ok": True}


@api.delete("/white-label/domains")
async def delete_white_label_domain(domain: str = Query(...), ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    d = str(domain or "").strip().lower()
    if not d:
        raise HTTPException(400, "Invalid domain")
    await db.tenant_domains.delete_one({"tenant_id": ctx.tenant_id, "domain": d})
    return {"ok": True}


@api.get("/white-label/uploads")
async def list_white_label_uploads(ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    docs = await db.tenant_files.find({"tenant_id": ctx.tenant_id}).sort("created_at", -1).to_list(200)
    return [{"id": d.get("_id"), "filename": d.get("filename"), "mime_type": d.get("mime_type"), "size_bytes": d.get("size_bytes"), "created_at": d.get("created_at"), "extracted_chars": d.get("extracted_chars", 0)} for d in docs]


@api.post("/white-label/uploads")
async def upload_white_label_doc(
    file: UploadFile = File(...),
    purpose: str = Form("documentation"),
    ctx=Depends(get_current_context),
):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    file_id = new_id()
    tenant_dir = STORAGE_DIR / "tenants" / str(ctx.tenant_id) / "uploads"
    tenant_dir.mkdir(parents=True, exist_ok=True)
    safe_name = (file.filename or "upload").replace("\\", "_").replace("/", "_")
    path = tenant_dir / f"{file_id}_{safe_name}"
    path.write_bytes(raw)

    extracted_text = ""
    try:
        name_l = (file.filename or "").lower()
        ct = (file.content_type or "").lower()
        if ct.startswith("text/") or name_l.endswith((".txt", ".md", ".json", ".csv")):
            extracted_text = raw.decode("utf-8", errors="ignore")
        elif name_l.endswith(".docx"):
            import docx  # type: ignore

            doc = docx.Document(str(path))
            extracted_text = "\n".join([p.text for p in doc.paragraphs if p.text])
        elif name_l.endswith(".pdf"):
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            pages = []
            for p in reader.pages:
                try:
                    pages.append(p.extract_text() or "")
                except Exception:
                    pages.append("")
            extracted_text = "\n".join([t for t in pages if t])
        elif name_l.endswith(".zip"):
            texts = []
            with zipfile.ZipFile(str(path), "r") as zf:
                for zi in zf.infolist():
                    if zi.is_dir():
                        continue
                    n = (zi.filename or "").lower()
                    if n.endswith((".txt", ".md", ".json", ".csv")) and zi.file_size <= 2_000_000:
                        with zf.open(zi) as f:
                            texts.append(f.read().decode("utf-8", errors="ignore"))
            extracted_text = "\n\n".join([t for t in texts if t])
    except Exception:
        extracted_text = ""

    doc = {
        "_id": file_id,
        "tenant_id": ctx.tenant_id,
        "purpose": purpose,
        "filename": file.filename,
        "mime_type": file.content_type,
        "size_bytes": len(raw),
        "storage": {"provider": "local", "path": str(path)},
        "extracted_text": extracted_text,
        "extracted_chars": len(extracted_text or ""),
        "created_at": utcnow().isoformat(),
        "updated_at": utcnow().isoformat(),
    }
    await db.tenant_files.insert_one(doc)
    return {"ok": True, "file": {"id": file_id, "filename": file.filename, "mime_type": file.content_type, "size_bytes": len(raw), "extracted_chars": len(extracted_text or "")}}


@api.post("/white-label/analyze")
async def analyze_white_label(ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")

    files = await db.tenant_files.find({"tenant_id": ctx.tenant_id}).sort("created_at", -1).to_list(50)
    corpus = "\n\n".join([(f.get("extracted_text") or "") for f in files if (f.get("extracted_text") or "").strip()])[:80_000]
    if not corpus.strip():
        raise HTTPException(400, "No extractable text found in uploads")

    sdoc = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    settings = TenantSettings.from_mongo(sdoc) if sdoc else TenantSettings(tenant_id=ctx.tenant_id)
    model_key = ((settings.analysis or {}).get("ai_default_model") or ai.DEFAULT_MODEL)

    system = "You analyze agency SOPs and produce a strict JSON configuration for a white-label account management dashboard. Output JSON only."
    user_text = (
        "From the documents below, infer preferred terminology, workflow structure, and communication style.\n"
        "Return JSON with keys: terminology (object), workflows (object), analysis (object).\n"
        "terminology should include: client_singular, client_plural, monthly_touch, account_manager.\n"
        "workflows should include meeting_types array with at least monthly_touch.\n"
        "analysis may include communication_style and prompt_overrides.\n\n"
        f"DOCUMENTS:\n{corpus}"
    )
    try:
        out = await ai.run_chat(system=system, user_text=user_text, model_key=model_key, session_id=f"wl-{ctx.tenant_id}")
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
    parsed = ai._extract_json(out)
    if not parsed:
        raise HTTPException(400, "Failed to parse AI response as JSON")

    next_doc = {
        "branding": settings.branding,
        "terminology": {**(settings.terminology or {}), **(parsed.get("terminology") or {})},
        "workflows": {**(settings.workflows or {}), **(parsed.get("workflows") or {})},
        "analysis": {**(settings.analysis or {}), **(parsed.get("analysis") or {})},
        "updated_at": utcnow().isoformat(),
    }
    await db.tenant_settings.update_one({"tenant_id": ctx.tenant_id}, {"$set": next_doc}, upsert=True)
    doc2 = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    return {"ok": True, "settings": TenantSettings.from_mongo(doc2).model_dump()}


# ===================== CLIENTS =====================
@api.get("/clients")
async def list_clients(ctx=Depends(get_current_context)):
    q = tenant_scope(ctx.tenant_id)
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        q = {"$and": [q, {"account_manager_id": ctx.user.id, "status": "active"}]}
    docs = await db.clients.find(q).sort("created_at", -1).to_list(1000)
    return [Client.from_mongo(d).model_dump() for d in docs]


@api.post("/clients")
async def create_client(data: ClientIn, ctx=Depends(get_current_context)):
    am_name = None
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        data.account_manager_id = ctx.user.id
    if data.account_manager_id:
        am_doc = await db.users.find_one({"_id": data.account_manager_id})
        if am_doc:
            am_name = am_doc.get("name")
    c = Client(tenant_id=ctx.tenant_id, **data.model_dump(), account_manager_name=am_name)
    await db.clients.insert_one(c.to_mongo())
    return c.model_dump()


@api.get("/clients/{client_id}")
async def get_client(client_id: str, ctx=Depends(get_current_context)):
    doc = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Client not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    return Client.from_mongo(doc).model_dump()


@api.get("/clients/{client_id}/suggestions")
async def get_client_suggestions(client_id: str, ctx=Depends(get_current_context)):
    doc = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Client not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    c = Client.from_mongo(doc)
    return {
        "client_id": c.id,
        "suggestions": c.suggestions or [],
        "generated_at": c.suggestions_generated_at,
        "model": c.suggestions_model,
    }


@api.post("/clients/{client_id}/suggestions/generate")
async def generate_client_suggestions(
    client_id: str,
    data: GenerateSuggestionsIn,
    start: str = Query(default=""),
    end: str = Query(default=""),
    compare_start: str = Query(default=""),
    compare_end: str = Query(default=""),
    ctx=Depends(get_current_context),
):
    c_doc = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    if not c_doc:
        raise HTTPException(404, "Client not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(c_doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    client = Client.from_mongo(c_doc)
    client_d = client.model_dump()

    start_d = _parse_iso_date(start or "") or _default_last_30_days()[0]
    end_d = _parse_iso_date(end or "") or _default_last_30_days()[1]
    cs = _parse_iso_date(compare_start or "")
    ce = _parse_iso_date(compare_end or "")
    period_start = datetime.fromisoformat(start_d).date()
    period_end = datetime.fromisoformat(end_d).date()
    comp_start = datetime.fromisoformat(cs).date() if cs else None
    comp_end = datetime.fromisoformat(ce).date() if ce else None
    kpi = await connectors.build_kpi_snapshot(
        ctx.tenant_id,
        client_id,
        client_d.get("company", ""),
        user_id=ctx.user.id,
        period_start=period_start,
        period_end=period_end,
        compare_start=comp_start,
        compare_end=comp_end,
    )
    kpi_for_ai = copy.deepcopy(kpi)

    def scrub(o):
        if isinstance(o, dict):
            o.pop("error", None)
            o.pop("error_detail", None)
            for v in list(o.values()):
                scrub(v)
        elif isinstance(o, list):
            for it in o:
                scrub(it)

    scrub(kpi_for_ai)

    try:
        out = await ai.generate_client_suggestions(
            client=client_d,
            kpi_snapshot=kpi_for_ai,
            extra_context=data.extra_context,
            model_key=data.model or ai.DEFAULT_MODEL,
            session_id=f"suggestions-{client_id}",
        )
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))

    patch = {
        "suggestions": out.get("suggestions") or [],
        "suggestions_generated_at": utcnow().isoformat(),
        "suggestions_model": data.model or ai.DEFAULT_MODEL,
        "updated_at": utcnow().isoformat(),
    }
    await db.clients.update_one({"_id": client_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    doc2 = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    c2 = Client.from_mongo(doc2)
    return {
        "client_id": c2.id,
        "suggestions": c2.suggestions or [],
        "generated_at": c2.suggestions_generated_at,
        "model": c2.suggestions_model,
        "kpi_snapshot": kpi,
        "_raw": out.get("_raw"),
    }


@api.patch("/clients/{client_id}")
async def update_client(client_id: str, patch: dict, ctx=Depends(get_current_context)):
    existing = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    if not existing:
        raise HTTPException(404, "Client not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(existing.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    patch["updated_at"] = utcnow().isoformat()
    await db.clients.update_one({"_id": client_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    doc = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    return Client.from_mongo(doc).model_dump()


@api.delete("/clients/{client_id}")
async def delete_client(client_id: str, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    await db.clients.delete_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    await db.meetings.delete_many({"client_id": client_id, **tenant_scope(ctx.tenant_id)})
    await db.action_items.delete_many({"client_id": client_id, **tenant_scope(ctx.tenant_id)})
    await db.content_captures.delete_many({"client_id": client_id, **tenant_scope(ctx.tenant_id)})
    return {"ok": True}


@api.get("/clients/{client_id}/bindings")
async def list_client_bindings(client_id: str, ctx=Depends(get_current_context)):
    docs = await db.client_bindings.find({"$and": [{"client_id": client_id}, tenant_scope(ctx.tenant_id)]}).to_list(100)
    return [ClientIntegrationBinding.from_mongo(d).model_dump() for d in docs]


@api.put("/clients/{client_id}/bindings/{platform}")
async def upsert_client_binding(
    client_id: str,
    platform: str,
    data: ClientIntegrationBindingIn,
    ctx=Depends(get_current_context),
):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    if platform not in INTEGRATIONS:
        raise HTTPException(404, "Unknown integration")
    existing = await db.client_bindings.find_one(
        {"$and": [{"client_id": client_id, "platform": platform}, tenant_scope(ctx.tenant_id)]}
    )
    update = {
        "enabled": bool(data.enabled),
        "external_ids": data.external_ids or {},
        "config": data.config or {},
        "tenant_id": ctx.tenant_id,
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
async def delete_client_binding(client_id: str, platform: str, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    await db.client_bindings.delete_one(
        {"$and": [{"client_id": client_id, "platform": platform}, tenant_scope(ctx.tenant_id)]}
    )
    return {"ok": True}


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


@api.get("/import/gohighlevel/contacts")
async def ghl_contacts_for_import(
    location_id: str = Query(...),
    query: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=200),
    ctx=Depends(get_current_context),
):
    raise HTTPException(410, "GoHighLevel contact import has been replaced by ClickUp Client Assignment Sync.")
    res = await connectors.list_gohighlevel_contacts(ctx.tenant_id, location_id=location_id, query=query, limit=limit)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "GoHighLevel import failed")
    return res


@api.post("/import/gohighlevel/clients")
async def import_clients_from_gohighlevel(data: ImportGhlClientsIn, ctx=Depends(get_current_context)):
    raise HTTPException(410, "GoHighLevel contact import has been replaced by ClickUp Client Assignment Sync.")
    location_id = (data.location_id or "").strip()
    if not location_id:
        raise HTTPException(400, "Missing location_id")

    selected = data.contacts or []
    if not selected and data.contact_ids:
        res = await connectors.list_gohighlevel_contacts(ctx.tenant_id, location_id=location_id, query="", limit=200)
        if not res.get("ok"):
            raise HTTPException(400, res.get("error_detail") or res.get("error") or "GoHighLevel import failed")
        contacts = res.get("contacts") or []
        wanted = {str(x) for x in (data.contact_ids or [])}
        selected = [c for c in contacts if str((c or {}).get("id")) in wanted]

    created = []
    skipped = []
    for c in selected:
        contact_id = str((c or {}).get("id") or "").strip()
        name = str((c or {}).get("name") or "").strip()
        company = str((c or {}).get("company") or "").strip()
        if not contact_id or not name or not company:
            continue
        detail = await connectors.fetch_gohighlevel_contact_detail(ctx.tenant_id, location_id=location_id, contact_id=contact_id)
        full_contact = (detail.get("contact") or {}) if detail.get("ok") else {}
        enriched = connectors._extract_services_products_from_ghl_contact(full_contact) if full_contact else {"services": [], "assigned_products": [], "crm_data": {}}
        website = (
            str(full_contact.get("website") or full_contact.get("websiteUrl") or full_contact.get("websiteUri") or (c or {}).get("website") or "").strip()
            if full_contact
            else str((c or {}).get("website") or "").strip()
        )
        existing = await db.clients.find_one(
            {"$and": [{"name": {"$regex": f"^{name}$", "$options": "i"}, "company": {"$regex": f"^{company}$", "$options": "i"}}, tenant_scope(ctx.tenant_id)]}
        )
        if existing:
            skipped.append({"contact_id": contact_id, "reason": "already_exists", "client_id": existing.get("_id")})
            continue

        client_in = ClientIn(
            name=name,
            company=company,
            email=(c or {}).get("email") or None,
            phone=(c or {}).get("phone") or None,
            website=website or None,
            services=enriched.get("services") or [],
            assigned_products=enriched.get("assigned_products") or [],
            crm_data=enriched.get("crm_data") or {},
            account_manager_id=ctx.user.id,
        )
        new_client = Client(tenant_id=ctx.tenant_id, **client_in.model_dump(), account_manager_name=ctx.user.name)
        await db.clients.insert_one(new_client.to_mongo())

        binding = ClientIntegrationBinding(
            tenant_id=ctx.tenant_id,
            client_id=new_client.id,
            platform="gohighlevel",
            enabled=True,
            external_ids={"location_id": str(location_id), "contact_id": str(contact_id)},
            config={},
            updated_at=utcnow().isoformat(),
        )
        await db.client_bindings.insert_one(binding.to_mongo())

        gbp_match = await connectors.find_best_gbp_location_for_client(
            ctx.tenant_id,
            user_id=ctx.user.id,
            company=company,
            website=website,
            phone=(c or {}).get("phone") or "",
        )
        if gbp_match.get("ok") and gbp_match.get("match"):
            match = gbp_match.get("match") or {}
            loc = match.get("location") or {}
            account_name = str(match.get("account_name") or "").strip()
            location_name = str(loc.get("name") or "").strip()
            gbp_data = {
                "account_name": account_name,
                "location_name": location_name,
                "location_title": loc.get("title"),
                "websiteUri": loc.get("websiteUri"),
                "phoneNumbers": loc.get("phoneNumbers"),
                "storefrontAddress": loc.get("storefrontAddress"),
                "match_score": match.get("match_score"),
            }
            await db.clients.update_one(
                {"_id": new_client.id, **tenant_scope(ctx.tenant_id)},
                {"$set": {"gbp_data": gbp_data, "updated_at": utcnow().isoformat()}},
            )
            if account_name and location_name:
                gbp_binding = ClientIntegrationBinding(
                    tenant_id=ctx.tenant_id,
                    client_id=new_client.id,
                    platform="google_business_profile",
                    enabled=True,
                    external_ids={"account_name": account_name, "location_name": location_name},
                    config={},
                    updated_at=utcnow().isoformat(),
                )
                await db.client_bindings.insert_one(gbp_binding.to_mongo())
        created.append(new_client.model_dump())

    return {"ok": True, "created": created, "skipped": skipped}


@api.get("/import/clickup/clients/status")
async def clickup_client_sync_status(user_id: str = Query(default=""), ctx=Depends(get_current_context)):
    # region debug-point B1:clickup-sync-status
    async def _dbg_emit(hypothesis_id: str, msg: str, data: dict) -> None:
        try:
            url = (os.environ.get("DEBUG_SERVER_URL") or "").strip()
            if not url:
                return
            async with httpx.AsyncClient(timeout=2) as c:
                await c.post(url, json={"sessionId": os.environ.get("DEBUG_SESSION_ID") or "clickup-client-sync", "runId": "pre", "hypothesisId": hypothesis_id, "location": "api:/import/clickup/clients/status", "msg": msg, "data": data, "ts": int(time.time() * 1000)})
        except Exception:
            return
    # endregion
    target_user_id = ctx.user.id
    if user_id and (ctx.user.role == "admin" or ctx.tenant_role in ("owner", "admin")):
        target_user_id = user_id
    await _dbg_emit("H1", "status:begin", {"tenant_id": ctx.tenant_id, "user_id": str(target_user_id)})
    doc = await db.clickup_client_sync_state.find_one({"tenant_id": ctx.tenant_id, "user_id": str(target_user_id)})
    state = doc or {"tenant_id": ctx.tenant_id, "user_id": str(target_user_id), "last_success_at": None, "last_error": None}
    await _dbg_emit("H1", "status:ok", {"state": state})
    return {"ok": True, "state": state}


@api.post("/import/clickup/clients/sync")
async def clickup_client_sync_now(ctx=Depends(get_current_context)):
    # region debug-point B2:clickup-sync-now
    async def _dbg_emit(hypothesis_id: str, msg: str, data: dict) -> None:
        try:
            url = (os.environ.get("DEBUG_SERVER_URL") or "").strip()
            if not url:
                return
            async with httpx.AsyncClient(timeout=2) as c:
                await c.post(url, json={"sessionId": os.environ.get("DEBUG_SESSION_ID") or "clickup-client-sync", "runId": "pre", "hypothesisId": hypothesis_id, "location": "api:/import/clickup/clients/sync", "msg": msg, "data": data, "ts": int(time.time() * 1000)})
        except Exception:
            return
    # endregion
    await _dbg_emit("H2", "sync:queued", {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "user_name": ctx.user.name, "user_email": ctx.user.email})
    async def _run():
        await _dbg_emit("H2", "sync:run:begin", {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id})
        res = await clickup_client_sync.sync_assigned_clients_for_user(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user.id,
            user_name=ctx.user.name,
            user_email=ctx.user.email,
        )
        await _dbg_emit("H2", "sync:run:done", {"res": res})
        if res.get("ok"):
            await db.integrations.update_one(
                {"tenant_id": ctx.tenant_id, "platform": "clickup"},
                {"$set": {"tenant_id": ctx.tenant_id, "platform": "clickup", "last_synced_at": utcnow().isoformat(), "last_error": None, "status": "connected", "updated_at": utcnow().isoformat()}},
                upsert=True,
            )
        else:
            await db.integrations.update_one(
                {"tenant_id": ctx.tenant_id, "platform": "clickup"},
                {"$set": {"tenant_id": ctx.tenant_id, "platform": "clickup", "last_error": res.get("error"), "updated_at": utcnow().isoformat()}},
                upsert=True,
            )
        return res

    asyncio.create_task(_run())
    return {"ok": True, "queued": True}


@api.post("/import/clickup/clients/sync/all")
async def clickup_client_sync_all(ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    return await clickup_client_sync.sync_assigned_clients_for_all_users(tenant_id=ctx.tenant_id)


def _client_comms_html(client: dict, ghl_msgs: List[dict], gmail_msgs: List[dict]) -> str:
    title = f"Client Communications — {client.get('company') or ''} — {client.get('name') or ''}".strip(" —")
    head = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{escape(title)}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {{ font-family: Inter, Arial, sans-serif; line-height: 1.45; color: #0f172a; padding: 28px; max-width: 980px; margin: 0 auto; }}
    h1 {{ font-size: 20px; margin: 0 0 4px; }}
    h2 {{ font-size: 14px; margin: 22px 0 10px; text-transform: uppercase; letter-spacing: .06em; color: #334155; }}
    .meta {{ color: #475569; font-size: 12.5px; margin: 0 0 18px; }}
    .row {{ border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; margin: 10px 0; background: #ffffff; }}
    .hdr {{ display: flex; gap: 10px; flex-wrap: wrap; color: #475569; font-size: 12px; margin-bottom: 6px; }}
    .tag {{ display: inline-block; border: 1px solid #e2e8f0; border-radius: 999px; padding: 2px 8px; background: #f8fafc; }}
    .body {{ white-space: pre-wrap; font-size: 13px; color: #0f172a; }}
    .muted {{ color: #64748b; }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <p class="meta">
    <span class="tag">Company: {escape(client.get("company") or "—")}</span>
    <span class="tag">Contact: {escape(client.get("name") or "—")}</span>
    <span class="tag">Email: {escape(client.get("email") or "—")}</span>
    <span class="tag">Phone: {escape(client.get("phone") or "—")}</span>
  </p>
"""

    def msg_row(source: str, when: str, direction: str, kind: str, frm: str, to: str, body: str) -> str:
        return f"""<div class="row">
  <div class="hdr">
    <span class="tag">{escape(source)}</span>
    <span class="tag">{escape(kind or "message")}</span>
    <span class="tag">{escape(direction or "—")}</span>
    <span class="muted">{escape(when or "")}</span>
  </div>
  <div class="hdr muted">
    <span>From: {escape(frm or "—")}</span>
    <span>To: {escape(to or "—")}</span>
  </div>
  <div class="body">{escape(body or "—")}</div>
</div>"""

    parts = [head]

    parts.append("<h2>GoHighLevel Conversations</h2>")
    if ghl_msgs:
        for m in ghl_msgs:
            parts.append(
                msg_row(
                    "GoHighLevel",
                    str(m.get("dateAdded") or ""),
                    str(m.get("direction") or ""),
                    str(m.get("messageType") or ""),
                    str(m.get("from") or ""),
                    str(m.get("to") or ""),
                    str(m.get("body") or ""),
                )
            )
    else:
        parts.append('<div class="row"><div class="body muted">No GoHighLevel messages found.</div></div>')

    parts.append("<h2>Gmail (Direct)</h2>")
    if gmail_msgs:
        for g in gmail_msgs:
            subj = str(g.get("subject") or "").strip()
            line = f"{subj}\n\n{str(g.get('snippet') or '').strip()}".strip()
            parts.append(
                msg_row(
                    "Gmail",
                    str(g.get("date") or ""),
                    "",
                    "email",
                    str(g.get("from") or ""),
                    str(g.get("to") or ""),
                    line,
                )
            )
    else:
        parts.append('<div class="row"><div class="body muted">No Gmail messages found (or Gmail is not connected).</div></div>')

    parts.append("</body></html>")
    return "\n".join(parts)


def _pdf_from_lines(title: str, lines: List[str]) -> bytes:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except Exception:
        raise HTTPException(500, "PDF export is not available on this backend. Use HTML export.")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    x = 50
    y = height - 60
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, title[:120])
    y -= 22
    c.setFont("Helvetica", 10)

    for raw in lines:
        text = (raw or "").replace("\r", "").strip()
        if not text:
            y -= 8
            continue
        for piece in text.split("\n"):
            s = piece
            while s:
                chunk = s[:110]
                s = s[110:]
                if y < 60:
                    c.showPage()
                    y = height - 60
                    c.setFont("Helvetica", 10)
                c.drawString(x, y, chunk)
                y -= 12
        y -= 10

    c.save()
    return buf.getvalue()


async def _collect_client_comms(client_doc: dict, ctx) -> dict:
    client = Client.from_mongo(client_doc).model_dump()
    binding = await db.client_bindings.find_one(
        {"$and": [{"client_id": client.get("id"), "platform": "gohighlevel", "enabled": True}, tenant_scope(ctx.tenant_id)]}
    )
    location_id = ((binding or {}).get("external_ids") or {}).get("location_id") or ((binding or {}).get("config") or {}).get("location_id")
    contact_id = ((binding or {}).get("external_ids") or {}).get("contact_id") or ((binding or {}).get("config") or {}).get("contact_id")
    if not location_id or not contact_id:
        raise HTTPException(400, "Client is missing GoHighLevel mapping (location_id/contact_id). Import from GHL or set mapping first.")

    convs = await connectors.list_gohighlevel_conversations(ctx.tenant_id, str(location_id), str(contact_id), limit=50)
    if not convs.get("ok"):
        raise HTTPException(400, convs.get("error_detail") or convs.get("error") or "Failed to fetch GoHighLevel conversations")
    ghl_msgs: List[dict] = []
    for c in convs.get("conversations") or []:
        cid = (c or {}).get("id")
        if not cid:
            continue
        msgs = await connectors.list_gohighlevel_messages(ctx.tenant_id, str(location_id), str(cid), limit=100)
        if msgs.get("ok"):
            ghl_msgs.extend(msgs.get("messages") or [])

    def _msg_dt(m: dict) -> str:
        return str((m or {}).get("dateAdded") or "")

    ghl_msgs.sort(key=_msg_dt)

    gmail_msgs: List[dict] = []
    if client.get("email"):
        g = await connectors.list_gmail_messages_for_contact(ctx.tenant_id, ctx.user.id, client.get("email"), max_messages=50)
        if g.get("ok"):
            gmail_msgs = g.get("messages") or []

    return {"client": client, "gohighlevel_messages": ghl_msgs, "gmail_messages": gmail_msgs}


@api.get("/exports/client-communications/{client_id}.html")
async def export_client_communications_html(client_id: str, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    doc = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Client not found")
    bundle = await _collect_client_comms(doc, ctx)
    html = _client_comms_html(bundle["client"], bundle["gohighlevel_messages"], bundle["gmail_messages"])
    filename = f"client-communications-{client_id}.html"
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.get("/exports/client-communications/{client_id}.pdf")
async def export_client_communications_pdf(client_id: str, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    doc = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Client not found")
    bundle = await _collect_client_comms(doc, ctx)
    c = bundle["client"]
    lines: List[str] = []
    lines.append(f"Company: {c.get('company') or ''}")
    lines.append(f"Contact: {c.get('name') or ''}")
    lines.append(f"Email: {c.get('email') or ''}")
    lines.append(f"Phone: {c.get('phone') or ''}")
    lines.append("")
    lines.append("GoHighLevel Messages")
    for m in bundle["gohighlevel_messages"]:
        lines.append(f"{m.get('dateAdded') or ''} | {m.get('messageType') or ''} | {m.get('direction') or ''}")
        lines.append(f"From: {m.get('from') or ''}  To: {m.get('to') or ''}")
        lines.append(str(m.get("body") or ""))
        lines.append("")
    lines.append("")
    lines.append("Gmail Messages")
    for g in bundle["gmail_messages"]:
        lines.append(f"{g.get('date') or ''} | {g.get('subject') or ''}")
        lines.append(f"From: {g.get('from') or ''}  To: {g.get('to') or ''}")
        lines.append(str(g.get("snippet") or ""))
        lines.append("")

    title = f"Client Communications — {c.get('company') or ''}"
    pdf = _pdf_from_lines(title, lines)
    filename = f"client-communications-{client_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ===================== MEETINGS =====================
@api.get("/meetings")
async def list_meetings(client_id: Optional[str] = None, ctx=Depends(get_current_context)):
    q = {"$and": [tenant_scope(ctx.tenant_id)]}
    if client_id:
        await _require_client_access(ctx, client_id)
        q["$and"].append({"client_id": client_id})
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        q["$and"].append({"account_manager_id": ctx.user.id})
    docs = await db.meetings.find(q).sort("created_at", -1).to_list(500)
    return [Meeting.from_mongo(d).model_dump() for d in docs]


@api.post("/meetings")
async def create_meeting(data: MeetingIn, ctx=Depends(get_current_context)):
    client_doc = await _require_client_access(ctx, data.client_id)
    client = Client.from_mongo(client_doc)
    m = Meeting(
        tenant_id=ctx.tenant_id,
        client_id=client.id,
        client_name=client.name,
        account_manager_id=ctx.user.id,
        account_manager_name=ctx.user.name,
        title=data.title,
        scheduled_at=data.scheduled_at,
        google_meet_url=data.google_meet_url,
        duration_minutes=data.duration_minutes or 60,
    )
    await db.meetings.insert_one(m.to_mongo())
    return m.model_dump()


@api.post("/clients/{client_id}/monthly-touch")
async def generate_monthly_touch(client_id: str, data: GenerateBriefIn, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, client_id)
    # #region debug-point H1:monthly-touch-entry
    _dbg_emit("H1", "server.py:/clients/{client_id}/monthly-touch", "monthly_touch_clicked", {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "role": ctx.user.role, "client_id": client_id, "model": data.model})
    # #endregion
    try:
        meeting = await monthly_touch.generate_for_client(
            ctx.tenant_id,
            client_id,
            user=ctx.user,
            model_key=data.model,
            extra_context=data.extra_context,
            push_clickup_actions=True,
        )
    except ValueError as e:
        # #region debug-point H1:monthly-touch-valueerror
        _dbg_emit("H1", "server.py:/clients/{client_id}/monthly-touch", "monthly_touch_value_error", {"client_id": client_id, "error": str(e)})
        # #endregion
        raise HTTPException(404, str(e))
    except ai.AIProviderError as e:
        # #region debug-point H1:monthly-touch-aierror
        _dbg_emit("H1", "server.py:/clients/{client_id}/monthly-touch", "monthly_touch_ai_provider_error", {"client_id": client_id, "error": str(e)})
        # #endregion
        raise HTTPException(400, str(e))
    except Exception as e:
        # #region debug-point H1:monthly-touch-unknown
        _dbg_emit("H1", "server.py:/clients/{client_id}/monthly-touch", "monthly_touch_unknown_error", {"client_id": client_id, "error": str(e)[:300]})
        # #endregion
        raise
    # #region debug-point H1:monthly-touch-success
    _dbg_emit("H1", "server.py:/clients/{client_id}/monthly-touch", "monthly_touch_success", {"client_id": client_id, "meeting_id": getattr(meeting, "id", None)})
    # #endregion
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
async def get_meeting(meeting_id: str, ctx=Depends(get_current_context)):
    doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Meeting not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    m = Meeting.from_mongo(doc)
    try:
        demo_enabled = str(os.environ.get("ENABLE_DEMO_KPI_SNAPSHOT", "") or "").strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        demo_enabled = False
    if not demo_enabled and isinstance(m.kpi_snapshot, dict):
        ks = m.kpi_snapshot
        if "_availability" not in ks and ks.get("period") == "Last 30 days":
            m.kpi_snapshot = {}
    return m.model_dump()


@api.get("/meetings/{meeting_id}/export/html")
async def export_meeting_html(meeting_id: str, ctx=Depends(get_current_context)):
    doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Meeting not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
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
    <h2>Wins</h2>
    <ul>{wins or "<li>—</li>"}</ul>
    <h2>Issues</h2>
    <ul>{issues or "<li>—</li>"}</ul>
  </div>

  <h2>Talking Points</h2>
  <ul>{tps or "<li>—</li>"}</ul>

  <h2>Suggested Questions</h2>
  <ul>{qs or "<li>—</li>"}</ul>

  <h2>Recommendations</h2>
  <ul>{recs or "<li>—</li>"}</ul>

  <h2>Testimonial Opportunity</h2>
  <p>{esc(m.testimonial_opportunity or "—")}</p>

  <h2>Health Signal</h2>
  <p>{esc(m.health_signal or "—")}</p>
</body>
</html>"""

    return {"html": html}


@api.patch("/meetings/{meeting_id}")
async def update_meeting(meeting_id: str, patch: MeetingPatch, ctx=Depends(get_current_context)):
    doc0 = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not doc0:
        raise HTTPException(404, "Meeting not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(doc0.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    update = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None}
    update["updated_at"] = utcnow().isoformat()
    updated_feedback = False
    feedback_payload = None
    updated_health = False
    health_payload: Dict[str, Any] = {}
    if "feedback" in update and isinstance(update.get("feedback"), dict):
        fb = _validate_feedback_dict(update["feedback"])
        if not fb.get("submitted_at"):
            fb["submitted_at"] = utcnow().isoformat()
        if not fb.get("submitted_by"):
            fb["submitted_by"] = ctx.user.id
        update["feedback"] = fb
        updated_feedback = True
        feedback_payload = fb
    if "nps_score" in update:
        update["nps_score"] = _validate_nps(update.get("nps_score"))
        updated_health = True
        health_payload["nps_score"] = update.get("nps_score")
    if "sentiment_classification" in update:
        update["sentiment_classification"] = _validate_sentiment_classification(update.get("sentiment_classification"))
        updated_health = True
        health_payload["sentiment_classification"] = update.get("sentiment_classification")
    if "health_notes" in update:
        update["health_notes"] = str(update.get("health_notes") or "")
        updated_health = True
        health_payload["health_notes"] = update.get("health_notes")
    res = await db.meetings.update_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Meeting not found")
    doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if updated_feedback:
        meeting = Meeting.from_mongo(doc)
        m_docs = await db.meetings.find(
            {"$and": [tenant_scope(ctx.tenant_id), {"client_id": meeting.client_id}, {"feedback": {"$exists": True, "$ne": None}}]}
        ).sort("updated_at", -1).to_list(50)
        series = []
        for d in m_docs or []:
            fb = (d.get("feedback") or {}) if isinstance(d, dict) else {}
            if not isinstance(fb, dict):
                continue
            try:
                series.append(
                    {
                        "meeting_id": d.get("_id"),
                        "submitted_at": fb.get("submitted_at") or d.get("updated_at"),
                        "lead_quality": _safe_int(fb.get("lead_quality"), 0),
                        "campaign_quality": _safe_int(fb.get("campaign_quality"), 0),
                        "satisfaction": _safe_int(fb.get("satisfaction"), 0),
                        "results": _safe_int(fb.get("results"), 0),
                    }
                )
            except Exception:
                continue
        alert, level, reason, rolling = _feedback_alert_from_series(series)
        await db.clients.update_one(
            {"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)},
            {
                "$set": {
                    "feedback_last_submitted_at": (feedback_payload or {}).get("submitted_at"),
                    "feedback_alert": alert,
                    "feedback_alert_level": level,
                    "feedback_alert_reason": reason,
                    "feedback_rolling_avg": rolling,
                    "updated_at": utcnow().isoformat(),
                }
            },
        )
    if updated_health:
        meeting = Meeting.from_mongo(doc)
        m_docs = await db.meetings.find(
            {
                "$and": [
                    tenant_scope(ctx.tenant_id),
                    {"client_id": meeting.client_id},
                    {
                        "$or": [
                            {"nps_score": {"$exists": True, "$ne": None}},
                            {"sentiment_classification": {"$exists": True, "$ne": None}},
                        ]
                    },
                ]
            }
        ).sort("updated_at", -1).to_list(60)
        series = []
        for d in m_docs or []:
            if not isinstance(d, dict):
                continue
            series.append(
                {
                    "meeting_id": d.get("_id"),
                    "submitted_at": d.get("updated_at"),
                    "nps_score": _safe_int(d.get("nps_score"), 0) if d.get("nps_score") is not None else None,
                    "sentiment_classification": str(d.get("sentiment_classification") or "").strip().lower() or None,
                }
            )
        alert, level, reason, churn_score, indicators, roll = _health_alert_from_series(series)
        await db.clients.update_one(
            {"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)},
            {
                "$set": {
                    "health_last_submitted_at": utcnow().isoformat(),
                    "health_alert": alert,
                    "health_alert_level": level,
                    "health_alert_reason": reason,
                    "churn_risk_score": churn_score,
                    "churn_risk_indicators": indicators,
                    "nps_rolling_avg": roll.get("nps_avg"),
                    "sentiment_rolling": roll.get("sentiment_counts") or {},
                    "updated_at": utcnow().isoformat(),
                }
            },
        )
    return Meeting.from_mongo(doc).model_dump()


@api.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str, ctx=Depends(get_current_context)):
    await _require_meeting_access(ctx, meeting_id)
    res = await db.meetings.delete_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if res.deleted_count == 0:
        raise HTTPException(404, "Meeting not found")
    await db.action_items.delete_many({"meeting_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    await db.content_captures.delete_many({"meeting_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    return {"ok": True}


@api.post("/meetings/{meeting_id}/generate-brief")
async def generate_brief(
    meeting_id: str,
    data: GenerateBriefIn,
    start: str = Query(default=""),
    end: str = Query(default=""),
    compare_start: str = Query(default=""),
    compare_end: str = Query(default=""),
    ctx=Depends(get_current_context),
):
    m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        if str(m_doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await db.clients.find_one({"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)})
    client = Client.from_mongo(c_doc) if c_doc else None
    client_d = client.model_dump() if client else {"name": meeting.client_name}
    start_d = _parse_iso_date(start or "") or _default_last_30_days()[0]
    end_d = _parse_iso_date(end or "") or _default_last_30_days()[1]
    cs = _parse_iso_date(compare_start or "")
    ce = _parse_iso_date(compare_end or "")
    period_start = datetime.fromisoformat(start_d).date()
    period_end = datetime.fromisoformat(end_d).date()
    comp_start = datetime.fromisoformat(cs).date() if cs else None
    comp_end = datetime.fromisoformat(ce).date() if ce else None
    kpi = await connectors.build_kpi_snapshot(
        ctx.tenant_id,
        meeting.client_id,
        client_d.get("company", ""),
        user_id=ctx.user.id,
        period_start=period_start,
        period_end=period_end,
        compare_start=comp_start,
        compare_end=comp_end,
    )
    kpi_for_ai = copy.deepcopy(kpi)

    def scrub(o):
        if isinstance(o, dict):
            o.pop("error", None)
            o.pop("error_detail", None)
            for v in list(o.values()):
                scrub(v)
        elif isinstance(o, list):
            for it in o:
                scrub(it)

    scrub(kpi_for_ai)
    try:
        brief = await ai.generate_meeting_brief(
            client=client_d,
            kpi_snapshot=kpi_for_ai,
            extra_context=data.extra_context,
            model_key=data.model or ai.DEFAULT_MODEL,
            session_id=f"brief-{meeting_id}",
        )
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
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
        "campaign_recommendations": brief.get("campaign_recommendations") or [],
        "health_signal": brief["health_signal"],
        "kpi_snapshot": kpi,
        "brief_generated_at": utcnow().isoformat(),
        "brief_model": data.model or ai.DEFAULT_MODEL,
        "status": "prep",
        "updated_at": utcnow().isoformat(),
    }
    await db.meetings.update_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)}, {"$set": update})
    try:
        gbp = (kpi or {}).get("google_business_profile") or {}
        nr = gbp.get("new_reviews") or {}
        received = _safe_int(nr.get("value"), 0)
        avg_rating = nr.get("avg_rating")
        period = (kpi or {}).get("_period") or {}
        cur_end = ((period.get("current") or {}).get("end") or "")[:10]
        month = _month_key(cur_end or utcnow().date().isoformat())
        snap = ReviewMonthlySnapshot(
            tenant_id=ctx.tenant_id,
            client_id=meeting.client_id,
            month=month,
            received=max(0, int(received)),
            avg_rating=float(avg_rating) if isinstance(avg_rating, (int, float)) else None,
            source="gbp",
            kpi_period_kind=str(period.get("kind") or ""),
            kpi_period_current_end=cur_end or None,
        )
        await db.review_monthly_snapshots.update_one(
            {"client_id": meeting.client_id, "month": month, **tenant_scope(ctx.tenant_id)},
            {"$set": snap.to_mongo(), "$setOnInsert": {"_id": snap.id}},
            upsert=True,
        )
    except Exception:
        pass
    doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    asyncio.create_task(_bg_publish_clickup_brief(ctx.tenant_id, meeting_id))
    return Meeting.from_mongo(doc).model_dump()


@api.post("/meetings/{meeting_id}/google-meet/sync-transcript")
async def sync_google_meet_transcript(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    res = await connectors.sync_google_meet_transcript_to_meeting(ctx.tenant_id, ctx.user.id, meeting.model_dump())
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
    patch = {
        "transcript": res.get("transcript"),
        "transcript_source": {
            "provider": "google_meet",
            "meet_code": res.get("meet_code"),
            "conference_record": res.get("conference_record"),
            "document_id": res.get("document_id"),
            "synced_at": utcnow().isoformat(),
        },
        "updated_at": utcnow().isoformat(),
    }
    await db.meetings.update_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    return Meeting.from_mongo(doc).model_dump()


@api.post("/meetings/{meeting_id}/analyze-transcript")
async def analyze_transcript(meeting_id: str, data: AnalyzeTranscriptIn, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await db.clients.find_one({"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)})
    client = Client.from_mongo(c_doc) if c_doc else None

    pdoc = await db.prompt_templates.find_one({"tenant_id": ctx.tenant_id, "key": "monthly_touch_analysis"})
    instructions = (PromptTemplate.from_mongo(pdoc).text if pdoc else _default_prompt_text("monthly_touch_analysis"))

    models = [m for m in (data.models or []) if str(m or "").strip()]
    if not models:
        models = [str((data.model or ai.DEFAULT_MODEL)).strip()]
    primary_model = models[0] if models else ai.DEFAULT_MODEL

    analysis_tasks = [
        asyncio.create_task(
            ai.analyze_transcript(
                client_name=client.name if client else (meeting.client_name or ""),
                company=client.company if client else "",
                am_name=meeting.account_manager_name or ctx.user.name,
                transcript=data.transcript,
                model_key=model_key,
                session_id=f"transcript-{meeting_id}-{model_key}",
                instructions=instructions,
            )
        )
        for model_key in models
    ]
    automation_task = asyncio.create_task(
        ai.generate_meeting_workflow(
            client_name=client.name if client else (meeting.client_name or ""),
            company=client.company if client else "",
            title=meeting.title,
            transcript=data.transcript,
            model_key=primary_model,
            session_id=f"automation-{meeting_id}",
        )
    )
    analysis_results, automation_draft = await asyncio.gather(asyncio.gather(*analysis_tasks), automation_task)
    analysis_by_model = {models[i]: analysis_results[i] for i in range(len(models))}
    analysis = analysis_results[0] if analysis_results else {}
    # persist transcript + sentiment
    await db.meetings.update_one(
        {"_id": meeting_id, **tenant_scope(ctx.tenant_id)},
        {
            "$set": {
                "transcript": data.transcript,
                "transcript_analyzed_at": utcnow().isoformat(),
                "sentiment": analysis.get("sentiment", "neutral"),
                "sentiment_summary": analysis.get("sentiment_summary", ""),
                "transcript_analysis": analysis,
                "transcript_analysis_by_model": analysis_by_model,
                "automation_draft": automation_draft,
                "automation_draft_generated_at": utcnow().isoformat(),
                "updated_at": utcnow().isoformat(),
            }
        },
    )
    # create action items
    created_actions: List[dict] = []
    for ai_item in analysis.get("action_items", []) or []:
        item = ActionItem(
            tenant_id=ctx.tenant_id,
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
            tenant_id=ctx.tenant_id,
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
        await db.clients.update_one({"_id": client.id, **tenant_scope(ctx.tenant_id)}, {"$set": client_update})

    return {
        "analysis": analysis,
        "automation_draft": automation_draft,
        "created_action_items": created_actions,
        "created_content_captures": created_content,
    }


@api.post("/meetings/{meeting_id}/generate-recap")
async def generate_recap(meeting_id: str, data: GenerateRecapIn, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await db.clients.find_one({"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)})
    client = Client.from_mongo(c_doc) if c_doc else None
    if client and _is_ads_client_services(client.services):
        fb = meeting.model_dump().get("feedback") or {}
        if not isinstance(fb, dict):
            fb = {}
        required = ("lead_quality", "campaign_quality", "satisfaction", "results")
        ok = all((k in fb and isinstance(fb.get(k), int) and 1 <= int(fb.get(k)) <= 5) for k in required)
        if not ok:
            raise HTTPException(400, "Client feedback (Lead Quality, Campaign Quality, Satisfaction, Results) is required for Ads clients before completing the meeting.")
    actions = await db.action_items.find({"$and": [{"meeting_id": meeting_id}, tenant_scope(ctx.tenant_id)]}).to_list(100)
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
        {"_id": meeting_id, **tenant_scope(ctx.tenant_id)},
        {
            "$set": {
                "recap_html": recap["html"],
                "recap_email": recap["plain"],
                "status": "completed",
                "updated_at": utcnow().isoformat(),
            }
        },
    )
    asyncio.create_task(_bg_publish_clickup_summary(ctx.tenant_id, meeting_id))
    return recap


@api.get("/feedback/{client_id}/trend")
async def feedback_trend(client_id: str, limit: int = 24, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, client_id)
    limit = max(1, min(int(limit or 24), 60))
    m_docs = await db.meetings.find(
        {"$and": [tenant_scope(ctx.tenant_id), {"client_id": client_id}, {"feedback": {"$exists": True, "$ne": None}}]}
    ).sort("updated_at", -1).to_list(limit)
    series = []
    for d in m_docs or []:
        fb = (d.get("feedback") or {}) if isinstance(d, dict) else {}
        if not isinstance(fb, dict):
            continue
        series.append(
            {
                "meeting_id": d.get("_id"),
                "meeting_title": d.get("title") or "",
                "submitted_at": fb.get("submitted_at") or d.get("updated_at"),
                "lead_quality": _safe_int(fb.get("lead_quality"), 0),
                "campaign_quality": _safe_int(fb.get("campaign_quality"), 0),
                "satisfaction": _safe_int(fb.get("satisfaction"), 0),
                "results": _safe_int(fb.get("results"), 0),
                "notes": fb.get("notes") or None,
            }
        )
    alert, level, reason, rolling = _feedback_alert_from_series(series)
    return {"client_id": client_id, "alert": alert, "alert_level": level, "alert_reason": reason, "rolling_avg": rolling, "items": series}


@api.get("/health/{client_id}/trend")
async def health_trend(client_id: str, limit: int = 24, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, client_id)
    limit = max(1, min(int(limit or 24), 60))
    m_docs = await db.meetings.find(
        {
            "$and": [
                tenant_scope(ctx.tenant_id),
                {"client_id": client_id},
                {
                    "$or": [
                        {"nps_score": {"$exists": True, "$ne": None}},
                        {"sentiment_classification": {"$exists": True, "$ne": None}},
                    ]
                },
            ]
        }
    ).sort("updated_at", -1).to_list(limit)
    series = []
    for d in m_docs or []:
        if not isinstance(d, dict):
            continue
        series.append(
            {
                "meeting_id": d.get("_id"),
                "meeting_title": d.get("title") or "",
                "submitted_at": d.get("updated_at"),
                "nps_score": _safe_int(d.get("nps_score"), 0) if d.get("nps_score") is not None else None,
                "sentiment_classification": str(d.get("sentiment_classification") or "").strip().lower() or None,
                "health_notes": d.get("health_notes") or None,
            }
        )
    alert, level, reason, churn_score, indicators, roll = _health_alert_from_series(series)
    return {
        "client_id": client_id,
        "alert": alert,
        "alert_level": level,
        "alert_reason": reason,
        "churn_risk_score": churn_score,
        "churn_risk_indicators": indicators,
        "nps_avg": roll.get("nps_avg"),
        "sentiment_counts": roll.get("sentiment_counts") or {},
        "items": series,
    }


@api.get("/wins/library")
async def wins_library(
    start: str = Query(default=""),
    end: str = Query(default=""),
    client_id: str = Query(default=""),
    account_manager_id: str = Query(default=""),
    q: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=2000),
    ctx=Depends(get_current_context),
):
    d0, d1 = _default_last_30_days()
    start_ts, end_ts = _day_bounds(start or d0, end or d1)
    query: dict = {"$and": [tenant_scope(ctx.tenant_id), {"wins_library": {"$exists": True, "$ne": []}}]}
    query["$and"].append({"brief_generated_at": {"$gte": start_ts, "$lte": end_ts}})

    if client_id:
        await _require_client_access(ctx, client_id)
        query["$and"].append({"client_id": client_id})

    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        query["$and"].append({"account_manager_id": ctx.user.id})
    elif account_manager_id:
        query["$and"].append({"account_manager_id": account_manager_id})

    docs = await db.meetings.find(query).sort("brief_generated_at", -1).limit(limit).to_list(limit)
    needle = _norm_text(q)
    out = []
    for d in docs or []:
        for w in (d.get("wins_library") or []):
            if not isinstance(w, dict):
                continue
            title = str(w.get("title") or "")
            desc = str(w.get("description") or "")
            metric = str(w.get("metric") or "")
            blob = _norm_text(f"{title} {desc} {metric}")
            if needle and needle not in blob:
                continue
            out.append(
                {
                    "meeting_id": d.get("_id"),
                    "meeting_title": d.get("title") or "",
                    "brief_generated_at": d.get("brief_generated_at") or d.get("updated_at") or d.get("created_at"),
                    "scheduled_at": d.get("scheduled_at"),
                    "client_id": d.get("client_id"),
                    "client_name": d.get("client_name") or "",
                    "account_manager_id": d.get("account_manager_id"),
                    "account_manager_name": d.get("account_manager_name"),
                    "win": w,
                }
            )
    return {"ok": True, "start": start_ts, "end": end_ts, "count": len(out), "items": out}


@api.get("/issues/library")
async def issues_library(
    start: str = Query(default=""),
    end: str = Query(default=""),
    client_id: str = Query(default=""),
    account_manager_id: str = Query(default=""),
    q: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=2000),
    ctx=Depends(get_current_context),
):
    d0, d1 = _default_last_30_days()
    start_ts, end_ts = _day_bounds(start or d0, end or d1)
    query: dict = {"$and": [tenant_scope(ctx.tenant_id), {"issues_library": {"$exists": True, "$ne": []}}]}
    query["$and"].append({"brief_generated_at": {"$gte": start_ts, "$lte": end_ts}})

    if client_id:
        await _require_client_access(ctx, client_id)
        query["$and"].append({"client_id": client_id})

    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        query["$and"].append({"account_manager_id": ctx.user.id})
    elif account_manager_id:
        query["$and"].append({"account_manager_id": account_manager_id})

    docs = await db.meetings.find(query).sort("brief_generated_at", -1).limit(limit).to_list(limit)
    needle = _norm_text(q)
    out = []
    for d in docs or []:
        for it in (d.get("issues_library") or []):
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "")
            desc = str(it.get("description") or "")
            plan = str(it.get("action_plan") or "")
            blob = _norm_text(f"{title} {desc} {plan}")
            if needle and needle not in blob:
                continue
            out.append(
                {
                    "meeting_id": d.get("_id"),
                    "meeting_title": d.get("title") or "",
                    "brief_generated_at": d.get("brief_generated_at") or d.get("updated_at") or d.get("created_at"),
                    "scheduled_at": d.get("scheduled_at"),
                    "client_id": d.get("client_id"),
                    "client_name": d.get("client_name") or "",
                    "account_manager_id": d.get("account_manager_id"),
                    "account_manager_name": d.get("account_manager_name"),
                    "issue": it,
                }
            )
    return {"ok": True, "start": start_ts, "end": end_ts, "count": len(out), "items": out}


@api.get("/meetings/{meeting_id}/automation")
async def get_meeting_automation(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    return {"ok": True, "draft": meeting.automation_draft, "generated_at": meeting.automation_draft_generated_at, "approved_at": meeting.automation_approved_at}


@api.post("/meetings/{meeting_id}/automation/generate")
async def generate_meeting_automation(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    if not (meeting.transcript or "").strip():
        raise HTTPException(400, "Missing transcript")
    c_doc = await db.clients.find_one({"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)})
    client = Client.from_mongo(c_doc) if c_doc else None
    try:
        draft = await ai.generate_meeting_workflow(
            client_name=client.name if client else (meeting.client_name or ""),
            company=client.company if client else "",
            title=meeting.title,
            transcript=meeting.transcript or "",
            model_key=ai.DEFAULT_MODEL,
            session_id=f"automation-{meeting_id}",
        )
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
    update = {"automation_draft": draft, "automation_draft_generated_at": utcnow().isoformat(), "updated_at": utcnow().isoformat()}
    await db.meetings.update_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)}, {"$set": update})
    return {"ok": True, "draft": draft}


@api.post("/meetings/{meeting_id}/automation/approve")
async def approve_meeting_automation(meeting_id: str, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
    meeting = Meeting.from_mongo(m_doc)
    draft = meeting.automation_draft or {}
    if not draft:
        raise HTTPException(400, "No automation draft found")

    created_actions = []
    for a in draft.get("follow_up_action_items") or []:
        item = ActionItem(
            tenant_id=ctx.tenant_id,
            meeting_id=meeting_id,
            client_id=meeting.client_id,
            title=a.get("title") or "Action item",
            description=a.get("description"),
            owner_type=a.get("owner_type") or "agency",
            due_date=a.get("due_date") if a.get("due_date") not in ("null", None) else None,
            priority=a.get("priority") or "medium",
            owner=meeting.account_manager_name or meeting.account_manager_id,
        )
        await db.action_items.insert_one(item.to_mongo())
        created_actions.append(item.model_dump())

    created_tickets = []
    for t in draft.get("department_tickets") or []:
        ticket = Ticket(
            tenant_id=ctx.tenant_id,
            meeting_id=meeting_id,
            client_id=meeting.client_id,
            department=t.get("department") or "Other",
            title=t.get("title") or "Ticket",
            description=t.get("description"),
            priority=t.get("priority") or "medium",
            status="open",
        )
        await db.tickets.insert_one(ticket.to_mongo())
        created_tickets.append(ticket.model_dump())

    await db.meetings.update_one(
        {"_id": meeting_id, **tenant_scope(ctx.tenant_id)},
        {"$set": {"automation_approved_at": utcnow().isoformat(), "updated_at": utcnow().isoformat()}},
    )
    asyncio.create_task(_bg_publish_clickup_tickets(ctx.tenant_id, meeting_id))
    asyncio.create_task(_bg_send_client_recap_email(ctx.tenant_id, meeting_id, meeting.account_manager_id or ctx.user.id))
    asyncio.create_task(_bg_publish_clickup_summary(ctx.tenant_id, meeting_id))
    return {"ok": True, "created_action_items": created_actions, "created_tickets": created_tickets}


@api.get("/meetings/{meeting_id}/qa")
async def get_meeting_qa(meeting_id: str, ctx=Depends(get_current_context)):
    await _require_meeting_access(ctx, meeting_id)
    doc = await db.qa_scorecards.find_one({"$and": [{"meeting_id": meeting_id}, tenant_scope(ctx.tenant_id)]}, sort=[("created_at", -1)])
    if not doc:
        return {"ok": True, "scorecard": None}
    return {"ok": True, "scorecard": QAScorecard.from_mongo(doc).model_dump()}


@api.post("/meetings/{meeting_id}/qa/score")
async def score_meeting(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    if not (meeting.transcript or "").strip():
        raise HTTPException(400, "Missing transcript")
    c_doc = await db.clients.find_one({"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)})
    client = Client.from_mongo(c_doc) if c_doc else None
    try:
        scored = await ai.score_meeting_qa(
            am_name=meeting.account_manager_name or ctx.user.name,
            client_name=client.name if client else (meeting.client_name or ""),
            company=client.company if client else "",
            title=meeting.title,
            transcript=meeting.transcript or "",
            checklist=meeting.checklist or {},
            model_key=ai.DEFAULT_MODEL,
            session_id=f"qa-{meeting_id}",
        )
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
    card = QAScorecard(
        tenant_id=ctx.tenant_id,
        meeting_id=meeting_id,
        client_id=meeting.client_id,
        account_manager_id=meeting.account_manager_id,
        account_manager_name=meeting.account_manager_name,
        total_score=int(scored.get("total_score") or 0),
        dimensions=scored.get("dimensions") or {},
        feedback=scored.get("feedback") or "",
    )
    await db.qa_scorecards.insert_one(card.to_mongo())
    await db.meetings.update_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)}, {"$set": {"meeting_score": card.total_score, "updated_at": utcnow().isoformat()}})
    return {"ok": True, "scorecard": card.model_dump()}


# ===================== ACTION ITEMS =====================
@api.get("/action-items")
async def list_actions(
    client_id: Optional[str] = None,
    meeting_id: Optional[str] = None,
    status: Optional[str] = None,
    owner_type: Optional[str] = None,
    due_before: Optional[str] = None,
    due_after: Optional[str] = None,
    ctx=Depends(get_current_context),
):
    q: dict = {"$and": [tenant_scope(ctx.tenant_id)]}
    allowed = await _allowed_client_ids(ctx)
    if allowed is not None:
        q["$and"].append({"client_id": {"$in": allowed}})
    if client_id:
        await _require_client_access(ctx, client_id)
        q["$and"].append({"client_id": client_id})
    if meeting_id:
        q["$and"].append({"meeting_id": meeting_id})
    if status:
        q["$and"].append({"status": status})
    if owner_type:
        q["$and"].append({"owner_type": owner_type})
    if due_before:
        q["$and"].append({"due_date": {"$lte": due_before}})
    if due_after:
        q["$and"].append({"due_date": {"$gte": due_after}})
    docs = await db.action_items.find(q).sort("created_at", -1).to_list(1000)
    return [ActionItem.from_mongo(d).model_dump() for d in docs]


@api.get("/action-items/follow-up")
async def action_follow_up(
    client_id: Optional[str] = None,
    meeting_id: Optional[str] = None,
    upcoming_days: int = 7,
    ctx=Depends(get_current_context),
):
    today = utcnow().date().isoformat()
    upcoming_days = max(1, min(int(upcoming_days or 7), 60))
    upcoming_end = (utcnow().date() + timedelta(days=upcoming_days)).isoformat()

    base: dict = {"$and": [tenant_scope(ctx.tenant_id)]}
    allowed = await _allowed_client_ids(ctx)
    if allowed is not None:
        base["$and"].append({"client_id": {"$in": allowed}})
    if client_id:
        await _require_client_access(ctx, client_id)
        base["$and"].append({"client_id": client_id})
    if meeting_id:
        base["$and"].append({"meeting_id": meeting_id})

    active_statuses = ["open", "in_progress", "blocked"]
    q_open = {"$and": base["$and"] + [{"status": {"$in": active_statuses}}]}
    docs = await db.action_items.find(q_open).sort("due_date", 1).sort("created_at", -1).to_list(2000)
    items = [ActionItem.from_mongo(d).model_dump() for d in docs]

    client_ids = {it.get("client_id") for it in items if it.get("client_id")}
    meeting_ids = {it.get("meeting_id") for it in items if it.get("meeting_id")}

    clients_docs = await db.clients.find({"$and": [{"_id": {"$in": list(client_ids)}}, tenant_scope(ctx.tenant_id)]}).to_list(500) if client_ids else []
    meetings_docs = await db.meetings.find({"$and": [{"_id": {"$in": list(meeting_ids)}}, tenant_scope(ctx.tenant_id)]}).to_list(500) if meeting_ids else []

    client_name_by_id = {c.get("_id"): c.get("name") or c.get("company") or "Client" for c in clients_docs}
    meeting_title_by_id = {m.get("_id"): m.get("title") or "Meeting" for m in meetings_docs}

    def reminder_due(it: dict) -> bool:
        due = it.get("due_date")
        if not due:
            return False
        if due > upcoming_end:
            return False
        last = it.get("last_reminded_at") or ""
        if last:
            try:
                last_date = str(last).split("T")[0]
                if last_date >= today:
                    return False
            except Exception:
                return False
        return True

    for it in items:
        it["client_name"] = client_name_by_id.get(it.get("client_id")) or "Client"
        it["meeting_title"] = meeting_title_by_id.get(it.get("meeting_id")) if it.get("meeting_id") else None
        it["is_overdue"] = bool(it.get("due_date") and it.get("due_date") < today)
        it["is_upcoming"] = bool(it.get("due_date") and today <= it.get("due_date") <= upcoming_end)
        it["reminder_due"] = reminder_due(it)

    client_pending = [it for it in items if it.get("owner_type") == "client" and it.get("status") != "completed"]
    internal_pending = [it for it in items if it.get("owner_type") == "agency" and it.get("status") != "completed"]
    overdue = [it for it in items if it.get("is_overdue")]
    upcoming = [it for it in items if it.get("is_upcoming")]
    reminders_due = [it for it in items if it.get("reminder_due")]

    return {
        "today": today,
        "upcoming_end": upcoming_end,
        "client_pending": client_pending,
        "internal_pending": internal_pending,
        "overdue": overdue,
        "upcoming": upcoming,
        "reminders_due": reminders_due,
        "counts": {
            "client_pending": len(client_pending),
            "internal_pending": len(internal_pending),
            "overdue": len(overdue),
            "upcoming": len(upcoming),
            "reminders_due": len(reminders_due),
        },
    }


@api.post("/action-items/{item_id}/remind")
async def action_remind(item_id: str, ctx=Depends(get_current_context)):
    now = utcnow().isoformat()
    doc = await db.action_items.find_one({"_id": item_id, **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc.get("client_id") or ""))
    item = ActionItem.from_mongo(doc)
    patch = {
        "last_reminded_at": now,
        "reminder_count": int((item.reminder_count or 0) + 1),
        "updated_at": now,
    }
    await db.action_items.update_one({"_id": item_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    doc2 = await db.action_items.find_one({"_id": item_id, **tenant_scope(ctx.tenant_id)})
    return ActionItem.from_mongo(doc2).model_dump()


def _month_key(iso_date: str) -> str:
    try:
        d = datetime.fromisoformat(iso_date).date()
        return f"{d.year:04d}-{d.month:02d}"
    except Exception:
        d = utcnow().date()
        return f"{d.year:04d}-{d.month:02d}"


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    m = (year * 12 + (month - 1)) + int(delta)
    return (m // 12, (m % 12) + 1)


def _last_n_months(n: int) -> list[str]:
    n = max(1, min(int(n or 12), 36))
    today = utcnow().date()
    out: list[str] = []
    for i in range(n - 1, -1, -1):
        y, m = _add_months(today.year, today.month, -i)
        out.append(f"{y:04d}-{m:02d}")
    return out


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _is_ads_client_services(services: list[str]) -> bool:
    ss = [str(s or "").lower() for s in (services or [])]
    return any(
        ("google ads" in s)
        or ("meta" in s)
        or ("facebook" in s)
        or ("instagram" in s)
        or ("paid ads" in s)
        for s in ss
    )


def _validate_feedback_dict(fb: dict) -> dict:
    out = dict(fb or {})
    for k in ("lead_quality", "campaign_quality", "satisfaction", "results"):
        if k not in out:
            raise HTTPException(400, f"Missing feedback field: {k}")
        v = _safe_int(out.get(k), 0)
        if v < 1 or v > 5:
            raise HTTPException(400, f"{k} must be between 1 and 5")
        out[k] = v
    if out.get("notes") is not None:
        out["notes"] = str(out.get("notes") or "")
    return out


def _feedback_alert_from_series(series: list[dict]) -> tuple[bool, str, str | None, dict]:
    if not series:
        return False, "low", None, {}

    def avg(key: str, items: list[dict]) -> float:
        vals = [float(x.get(key) or 0) for x in items if x.get(key) is not None]
        return round(sum(vals) / max(1, len(vals)), 3)

    rolling = {
        "lead_quality": avg("lead_quality", series[:3]),
        "campaign_quality": avg("campaign_quality", series[:3]),
        "satisfaction": avg("satisfaction", series[:3]),
        "results": avg("results", series[:3]),
    }
    last3 = series[:3]
    prev3 = series[3:6]
    last3_sat = avg("satisfaction", last3)
    prev3_sat = avg("satisfaction", prev3) if prev3 else last3_sat
    last2_sat_min = min([int(x.get("satisfaction") or 5) for x in series[:2]]) if series else 5
    last3_res_avg = avg("results", last3)

    level = "low"
    reason = None
    if last2_sat_min <= 2:
        level = "high"
        reason = "Satisfaction has been very low in recent meetings."
    elif prev3 and (prev3_sat - last3_sat) >= 1.5:
        level = "high"
        reason = "Satisfaction has dropped sharply compared to prior meetings."
    elif prev3 and (prev3_sat - last3_sat) >= 0.75:
        level = "medium"
        reason = "Satisfaction is trending down compared to prior meetings."
    elif last3_res_avg <= 2.0:
        level = "medium"
        reason = "Results score is low over recent meetings."

    return level != "low", level, reason, rolling


def _validate_nps(v: Any) -> Optional[int]:
    if v is None:
        return None
    n = _safe_int(v, 0)
    if n < 1 or n > 10:
        raise HTTPException(400, "nps_score must be between 1 and 10")
    return n


def _validate_sentiment_classification(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v or "").strip().lower()
    if s not in ("happy", "neutral", "concerned", "at_risk"):
        raise HTTPException(400, "sentiment_classification must be one of: happy, neutral, concerned, at_risk")
    return s


def _health_alert_from_series(series: list[dict]) -> tuple[bool, str, str | None, int, list[str], dict]:
    if not series:
        return False, "low", None, 0, [], {"nps_avg": None, "sentiment_counts": {}}

    def avg_nps(items: list[dict]) -> Optional[float]:
        vals = [float(x.get("nps_score")) for x in items if isinstance(x.get("nps_score"), (int, float))]
        if not vals:
            return None
        return round(sum(vals) / float(len(vals)), 3)

    sent_weight = {"happy": 0, "neutral": 1, "concerned": 2, "at_risk": 3}
    last3 = series[:3]
    prev3 = series[3:6]
    nps_last3 = avg_nps(last3)
    nps_prev3 = avg_nps(prev3) if prev3 else nps_last3
    last_sent = str(series[0].get("sentiment_classification") or "").strip().lower()
    last2_sent = [str(x.get("sentiment_classification") or "").strip().lower() for x in series[:2]]

    counts: dict[str, int] = {"happy": 0, "neutral": 0, "concerned": 0, "at_risk": 0}
    for it in series[:12]:
        s = str(it.get("sentiment_classification") or "").strip().lower()
        if s in counts:
            counts[s] += 1

    indicators: list[str] = []
    level = "low"
    reason = None

    if last_sent == "at_risk":
        level = "high"
        reason = "Latest meeting sentiment is At Risk."
        indicators.append("latest_sentiment_at_risk")
    elif "at_risk" in last2_sent:
        level = "high"
        reason = "At Risk sentiment occurred recently."
        indicators.append("recent_at_risk_sentiment")
    elif last_sent == "concerned":
        level = "medium"
        reason = "Latest meeting sentiment is Concerned."
        indicators.append("latest_sentiment_concerned")

    if nps_last3 is not None:
        if nps_last3 <= 4:
            level = "high"
            if not reason:
                reason = "NPS is very low in recent meetings."
            indicators.append("nps_very_low")
        elif nps_last3 <= 6 and level == "low":
            level = "medium"
            if not reason:
                reason = "NPS is low in recent meetings."
            indicators.append("nps_low")

        if nps_prev3 is not None and (nps_prev3 - nps_last3) >= 2.0:
            level = "high"
            reason = "NPS dropped sharply compared to prior meetings."
            indicators.append("nps_drop_sharp")
        elif nps_prev3 is not None and (nps_prev3 - nps_last3) >= 1.0 and level == "low":
            level = "medium"
            reason = "NPS is trending down compared to prior meetings."
            indicators.append("nps_drop")

    churn_score = 0
    churn_score += 45 if "latest_sentiment_at_risk" in indicators else 0
    churn_score += 25 if "recent_at_risk_sentiment" in indicators else 0
    churn_score += 15 if "latest_sentiment_concerned" in indicators else 0
    churn_score += 20 if "nps_very_low" in indicators else 0
    churn_score += 10 if "nps_low" in indicators else 0
    churn_score += 20 if "nps_drop_sharp" in indicators else 0
    churn_score += 10 if "nps_drop" in indicators else 0
    churn_score = int(max(0, min(100, churn_score)))

    return level != "low", level, reason, churn_score, indicators, {"nps_avg": nps_last3, "sentiment_counts": counts}


def _default_discovery_templates() -> list[dict]:
    return [
        {"kind": "operational", "category": "Lead Handling", "question": "Who answers the phone and how quickly do you typically respond to new leads?", "tags": ["calls", "follow_up"], "deliverables": ["google_ads", "meta_ads", "gbp", "seo"], "active": True},
        {"kind": "operational", "category": "Lead Handling", "question": "How are leads followed up (SMS, call, email), and what is the follow-up cadence?", "tags": ["follow_up", "sms"], "deliverables": ["google_ads", "meta_ads"], "active": True},
        {"kind": "operational", "category": "CRM Process", "question": "What CRM process is used today (stages, ownership, notes), and who is responsible for updating it?", "tags": ["crm", "pipeline"], "deliverables": ["google_ads", "meta_ads", "seo"], "active": True},
        {"kind": "operational", "category": "Sales Cycle", "question": "What is the average sales cycle from first contact to closed sale, and what are the biggest drop-off points?", "tags": ["sales_cycle", "conversion"], "deliverables": ["google_ads", "meta_ads", "seo"], "active": True},
        {"kind": "operational", "category": "After Lead", "question": "What happens after a lead submits a form or calls—what is the exact step-by-step workflow?", "tags": ["workflow", "conversion"], "deliverables": ["google_ads", "meta_ads"], "active": True},
        {"kind": "operational", "category": "Missed Calls", "question": "How are missed calls handled, and do you have a process for calling back within 5–15 minutes?", "tags": ["missed_calls", "calls"], "deliverables": ["gbp", "google_ads"], "active": True},
        {"kind": "operational", "category": "Reviews", "question": "When and how do you ask for reviews today, and who is responsible for requesting them?", "tags": ["reviews"], "deliverables": ["gbp", "seo"], "active": True},
        {"kind": "operational", "category": "Offers", "question": "What offers are you currently running (discounts, bundles, guarantees), and which one converts best?", "tags": ["offers", "promotions"], "deliverables": ["google_ads", "meta_ads"], "active": True},

        {"kind": "market", "category": "Competitors", "question": "Who are your top 3 competitors in this market, and what do you believe they do better than you?", "tags": ["competitors"], "deliverables": ["seo", "gbp", "google_ads", "meta_ads"], "active": True},
        {"kind": "market", "category": "Customer Behavior", "question": "What does a high-intent customer typically search for right before they call or fill out a form?", "tags": ["intent", "keywords"], "deliverables": ["seo", "gbp", "google_ads"], "active": True},
        {"kind": "market", "category": "Buying Process", "question": "What are the most common reasons customers choose you vs. delay or choose someone else?", "tags": ["objections", "decision"], "deliverables": ["google_ads", "meta_ads", "seo"], "active": True},
        {"kind": "market", "category": "Decision Factors", "question": "What are the top decision factors: price, speed, trust, warranties, reviews, expertise—what matters most in your area?", "tags": ["decision_factors"], "deliverables": ["seo", "gbp", "google_ads", "meta_ads"], "active": True},
        {"kind": "market", "category": "Local Market", "question": "Are there seasonal trends or local events that heavily impact demand?", "tags": ["seasonality"], "deliverables": ["seo", "google_ads", "meta_ads", "gbp"], "active": True},
        {"kind": "market", "category": "Pricing Positioning", "question": "How do you want to be positioned on price (budget, mid, premium), and do customers understand the difference?", "tags": ["pricing"], "deliverables": ["google_ads", "meta_ads", "seo"], "active": True},
    ]


def _prio_from_score(score: int) -> str:
    if score >= 6:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def _score_template(t: dict, issues: list[dict], kpi: dict, deliverables: list[str]) -> tuple[int, str]:
    q = f"{t.get('category','')} {t.get('question','')}".lower()
    score = 0
    reasons: list[str] = []

    if deliverables:
        td = [str(x).lower() for x in (t.get("deliverables") or [])]
        if any(d in td for d in deliverables):
            score += 1

    for iss in issues or []:
        txt = f"{iss.get('title','')} {iss.get('description','')}".lower()
        sev = str(iss.get("severity") or "medium").lower()
        w = 2 if sev == "high" else 1
        if any(k in q for k in ("missed call", "phone", "answer", "follow up", "follow-up", "lead")) and any(k in txt for k in ("call", "lead", "conversion", "follow")):
            score += 2 * w
            reasons.append("Ties to current client issues around lead handling")
        if any(k in q for k in ("offer", "promotion", "pricing")) and any(k in txt for k in ("cpl", "lead", "conversion", "cost", "offer")):
            score += 2 * w
            reasons.append("Ties to current client issues around offers/conversion")
        if "review" in q and any(k in txt for k in ("review", "gbp", "rating")):
            score += 2 * w
            reasons.append("Ties to reputation/reviews issues")

    gbp = (kpi or {}).get("google_business_profile") or {}
    calls = (gbp.get("calls") or {}).get("delta_pct")
    if any(k in q for k in ("missed call", "answer", "phone", "follow")) and isinstance(calls, (int, float)) and calls < 0:
        score += 2
        reasons.append("Calls are down; verify lead handling workflow")

    gads = (kpi or {}).get("google_ads") or {}
    cpl = (gads.get("cpl") or {}).get("value")
    prev_cpl = (gads.get("cpl") or {}).get("previous")
    if any(k in q for k in ("offer", "pricing", "conversion", "follow")) and isinstance(cpl, (int, float)) and isinstance(prev_cpl, (int, float)) and cpl > prev_cpl:
        score += 2
        reasons.append("CPL is rising; validate offer and conversion steps")

    recs = (gbp.get("new_reviews") or {}).get("value")
    if "review" in q and isinstance(recs, (int, float)) and recs <= 1:
        score += 2
        reasons.append("Review velocity is low; tighten review request process")

    return score, "; ".join(dict.fromkeys([r for r in reasons if r]))


@api.get("/reviews/{client_id}/goal")
async def get_review_goal(client_id: str, ctx=Depends(get_current_context)):
    doc = await db.client_review_goals.find_one({"client_id": client_id, **tenant_scope(ctx.tenant_id)})
    if not doc:
        goal = ClientReviewGoal(tenant_id=ctx.tenant_id, client_id=client_id, monthly_goal=10, updated_at=utcnow().isoformat())
        await db.client_review_goals.insert_one(goal.to_mongo())
        return goal.model_dump()
    return ClientReviewGoal.from_mongo(doc).model_dump()


@api.put("/reviews/{client_id}/goal")
async def put_review_goal(client_id: str, payload: ClientReviewGoalIn, ctx=Depends(get_current_context)):
    monthly_goal = max(0, _safe_int(payload.monthly_goal, 10))
    now = utcnow().isoformat()
    await db.client_review_goals.update_one(
        {"client_id": client_id, **tenant_scope(ctx.tenant_id)},
        {"$set": {"monthly_goal": monthly_goal, "updated_at": now}, "$setOnInsert": {"_id": new_id(), "tenant_id": ctx.tenant_id, "client_id": client_id, "created_at": now}},
        upsert=True,
    )
    doc = await db.client_review_goals.find_one({"client_id": client_id, **tenant_scope(ctx.tenant_id)})
    return ClientReviewGoal.from_mongo(doc).model_dump()


@api.post("/reviews/{client_id}/events")
async def create_review_event(client_id: str, payload: ReviewEventIn, ctx=Depends(get_current_context)):
    if payload.count is None or int(payload.count) <= 0:
        raise HTTPException(400, "count must be > 0")
    try:
        datetime.fromisoformat(payload.occurred_on)
    except Exception:
        raise HTTPException(400, "occurred_on must be ISO date (YYYY-MM-DD)")
    ev = ReviewEvent(
        tenant_id=ctx.tenant_id,
        client_id=client_id,
        kind=payload.kind,
        count=int(payload.count),
        occurred_on=payload.occurred_on,
        channel=payload.channel or "other",
        source="manual",
        notes=payload.notes,
        meeting_id=payload.meeting_id,
    )
    await db.review_events.insert_one(ev.to_mongo())
    return ev.model_dump()


@api.get("/reviews/{client_id}/events")
async def list_review_events(client_id: str, limit: int = 200, ctx=Depends(get_current_context)):
    limit = max(1, min(int(limit or 200), 1000))
    docs = await db.review_events.find({"client_id": client_id, **tenant_scope(ctx.tenant_id)}).sort("occurred_on", -1).to_list(limit)
    return [ReviewEvent.from_mongo(d).model_dump() for d in docs]


@api.get("/reviews/{client_id}/stats")
async def review_stats(client_id: str, months: int = 12, ctx=Depends(get_current_context)):
    months_list = _last_n_months(months)
    month_set = set(months_list)

    events = await db.review_events.find({"client_id": client_id, **tenant_scope(ctx.tenant_id)}).to_list(5000)
    requested_by_month: dict[str, int] = {m: 0 for m in months_list}
    for d in events:
        ev = ReviewEvent.from_mongo(d)
        if not ev:
            continue
        mk = _month_key(ev.occurred_on)
        if mk not in month_set:
            continue
        if ev.kind == "requested":
            requested_by_month[mk] = requested_by_month.get(mk, 0) + int(ev.count or 0)

    snaps = await db.review_monthly_snapshots.find({"client_id": client_id, **tenant_scope(ctx.tenant_id)}).to_list(1000)
    received_by_month: dict[str, int] = {m: 0 for m in months_list}
    rating_by_month: dict[str, Optional[float]] = {m: None for m in months_list}
    for d in snaps:
        s = ReviewMonthlySnapshot.from_mongo(d)
        if not s:
            continue
        if s.month in month_set:
            received_by_month[s.month] = max(received_by_month.get(s.month, 0), int(s.received or 0))
            if s.avg_rating is not None:
                rating_by_month[s.month] = s.avg_rating

    goal_doc = await db.client_review_goals.find_one({"client_id": client_id, **tenant_scope(ctx.tenant_id)})
    goal = (ClientReviewGoal.from_mongo(goal_doc).monthly_goal if goal_doc else 10)

    trend = []
    for m in months_list:
        req = requested_by_month.get(m, 0)
        rec = received_by_month.get(m, 0)
        missed = max(0, req - rec)
        conv = 0.0
        if req > 0:
            conv = float(rec) / float(req)
        goal_pct = 0.0
        if goal > 0:
            goal_pct = float(rec) / float(goal)
        trend.append({
            "month": m,
            "requested": req,
            "received": rec,
            "missed_opportunities": missed,
            "conversion_rate": round(conv, 4),
            "goal": goal,
            "goal_progress": round(goal_pct, 4),
            "avg_rating": rating_by_month.get(m),
        })

    cur_month = months_list[-1]
    cur_received = received_by_month.get(cur_month, 0)
    cur_requested = requested_by_month.get(cur_month, 0)
    cur_missed = max(0, cur_requested - cur_received)
    cur_conv = round((float(cur_received) / float(cur_requested)) if cur_requested > 0 else 0.0, 4)
    cur_goal_pct = round((float(cur_received) / float(goal)) if goal > 0 else 0.0, 4)

    recent = [t["received"] for t in trend[-3:] if isinstance(t.get("received"), int)]
    avg3 = int(round(sum(recent) / max(1, len(recent))))
    forecast_next = avg3

    opportunities = []
    if cur_goal_pct < 1.0:
        opportunities.append({"type": "goal_gap", "message": f"Current month is at {cur_received}/{goal} reviews. Increase request volume and follow-up to hit goal."})
    if cur_requested > 0 and cur_conv < 0.25:
        opportunities.append({"type": "low_conversion", "message": "Review request conversion rate is low. Improve script, timing, and follow-up cadence."})
    if cur_missed >= 5:
        opportunities.append({"type": "missed_opportunities", "message": "There are many requests not turning into reviews. Add a 48-hour follow-up and QR code option."})

    scripts = [
        "Quick ask (SMS): Thanks again for choosing us. If you were happy with the service, would you mind leaving a quick Google review? It helps a lot. <review link>",
        "After win: Glad we got that handled. Would you be open to leaving a short Google review about your experience? <review link>",
        "For busy customers: If you only have 30 seconds, a quick star rating and one sentence is perfect. <review link>",
    ]
    qr_recs = [
        "Place a QR code at front desk / checkout area with a short CTA: “Scan to leave a Google review”.",
        "Add QR code to invoices/receipts and job-complete emails.",
        "For field teams: add QR code on business cards or vehicle flyer.",
    ]

    return {
        "client_id": client_id,
        "goal": {"monthly_goal": goal},
        "current": {
            "month": cur_month,
            "requested": cur_requested,
            "received": cur_received,
            "missed_opportunities": cur_missed,
            "conversion_rate": cur_conv,
            "goal_progress": cur_goal_pct,
        },
        "trend": trend,
        "forecast": {"next_month_received": forecast_next, "based_on_months": 3},
        "opportunities": opportunities,
        "suggested_scripts": scripts,
        "qr_code_recommendations": qr_recs,
    }


@api.get("/discovery/library")
async def discovery_library(ctx=Depends(get_current_context)):
    docs = await db.discovery_question_templates.find(tenant_scope(ctx.tenant_id)).sort("created_at", -1).to_list(2000)
    if docs:
        items = [DiscoveryQuestionTemplate.from_mongo(d).model_dump() for d in docs]
        return {"items": items}
    return {"items": _default_discovery_templates()}


@api.post("/discovery/library")
async def discovery_library_create(payload: DiscoveryQuestionTemplateIn, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    item = DiscoveryQuestionTemplate(tenant_id=ctx.tenant_id, **payload.model_dump())
    await db.discovery_question_templates.insert_one(item.to_mongo())
    return item.model_dump()


@api.patch("/discovery/library/{template_id}")
async def discovery_library_patch(template_id: str, patch: dict, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    patch["updated_at"] = utcnow().isoformat()
    res = await db.discovery_question_templates.update_one({"_id": template_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.discovery_question_templates.find_one({"_id": template_id, **tenant_scope(ctx.tenant_id)})
    return DiscoveryQuestionTemplate.from_mongo(doc).model_dump()


@api.delete("/discovery/library/{template_id}")
async def discovery_library_delete(template_id: str, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    res = await db.discovery_question_templates.delete_one({"_id": template_id, **tenant_scope(ctx.tenant_id)})
    if res.deleted_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@api.post("/meetings/{meeting_id}/discovery/generate")
async def meeting_generate_discovery(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)

    c_doc = await db.clients.find_one({"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)})
    client = Client.from_mongo(c_doc) if c_doc else None
    services = [(s or "").lower() for s in (client.services if client else [])]
    deliverables = []
    if any("seo" in s for s in services):
        deliverables.append("seo")
    if any("gbp" in s or "google business" in s for s in services):
        deliverables.append("gbp")
        deliverables.append("google_business_profile")
    if any("google ads" in s or "ppc" in s for s in services):
        deliverables.append("google_ads")
    if any("meta" in s or "facebook" in s or "instagram" in s for s in services):
        deliverables.append("meta_ads")

    kpi = meeting.kpi_snapshot or {}
    if not kpi:
        cd = client.model_dump() if client else {"company": meeting.client_name or ""}
        kpi = await connectors.build_kpi_snapshot(ctx.tenant_id, meeting.client_id, cd.get("company", ""), user_id=ctx.user.id)

    issues = [i if isinstance(i, dict) else {} for i in (meeting.model_dump().get("issues") or [])]

    lib = await db.discovery_question_templates.find(tenant_scope(ctx.tenant_id)).to_list(2000)
    templates = [DiscoveryQuestionTemplate.from_mongo(d).model_dump() for d in lib] if lib else _default_discovery_templates()
    templates = [t for t in templates if bool(t.get("active", True))]

    ranked = []
    for t in templates:
        sc, why = _score_template(t, issues, kpi, deliverables)
        ranked.append((sc, why, t))
    ranked.sort(key=lambda x: x[0], reverse=True)

    selected = ranked[:12]
    out: list[MeetingDiscoveryQuestion] = []
    for sc, why, t in selected:
        out.append(
            MeetingDiscoveryQuestion(
                id=new_id(),
                kind=t.get("kind") or "operational",
                category=str(t.get("category") or "General"),
                question=str(t.get("question") or "").strip(),
                priority=_prio_from_score(int(sc)),
                rationale=why or None,
                status="suggested",
                notes=None,
            )
        )

    await db.meetings.update_one(
        {"_id": meeting_id, **tenant_scope(ctx.tenant_id)},
        {"$set": {"discovery_questions": [q.model_dump() for q in out], "updated_at": utcnow().isoformat()}},
    )
    doc2 = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    return {"ok": True, "meeting": Meeting.from_mongo(doc2).model_dump()}


def _iso_date(d: datetime) -> str:
    return d.date().isoformat()


def _clamp_int(v: int, lo: int, hi: int) -> int:
    try:
        v = int(v)
    except Exception:
        v = lo
    return max(lo, min(hi, v))


def _compute_current_week(start_date: str, weeks: int = 12) -> int:
    try:
        sd = datetime.fromisoformat(start_date).date()
    except Exception:
        sd = utcnow().date()
    delta_days = (utcnow().date() - sd).days
    wk = (delta_days // 7) + 1
    return _clamp_int(wk, 1, max(1, int(weeks or 12)))


async def _get_or_create_roadmap_plan(tenant_id: str, client_id: str) -> RoadmapPlan:
    doc = await db.roadmap_plans.find_one({"client_id": client_id, **tenant_scope(tenant_id)})
    if doc:
        plan = RoadmapPlan.from_mongo(doc)
        if plan:
            return plan
    plan = RoadmapPlan(tenant_id=tenant_id, client_id=client_id, start_date=_iso_date(utcnow()), weeks=12, items=[])
    await db.roadmap_plans.insert_one(plan.to_mongo())
    return plan


@api.get("/roadmap/{client_id}")
async def get_roadmap(client_id: str, ctx=Depends(get_current_context)):
    plan = await _get_or_create_roadmap_plan(ctx.tenant_id, client_id)
    today = _iso_date(utcnow())
    current_week = _compute_current_week(plan.start_date, plan.weeks)

    items = [it.model_dump() for it in (plan.items or [])]
    action_ids = [str(it.get("action_item_id") or "") for it in items if str(it.get("action_item_id") or "").strip()]
    if action_ids:
        docs = await db.action_items.find({"$and": [{"_id": {"$in": action_ids}}, tenant_scope(ctx.tenant_id)]}).to_list(2000)
        by_id = {d.get("_id"): ActionItem.from_mongo(d).model_dump() for d in docs}
        for it in items:
            aid = str(it.get("action_item_id") or "").strip()
            if not aid:
                continue
            a = by_id.get(aid)
            if not a:
                continue
            it["status"] = a.get("status") or it.get("status")
            it["due_date"] = a.get("due_date") or it.get("due_date")
            it["owner_type"] = a.get("owner_type") or it.get("owner_type")
            it["owner"] = a.get("owner") or it.get("owner")
            it["priority"] = a.get("priority") or it.get("priority")

    total = len(items)
    completed = len([it for it in items if it.get("status") == "completed"])
    pending = len([it for it in items if it.get("status") != "completed"])
    overdue = len([it for it in items if it.get("due_date") and it.get("due_date") < today and it.get("status") != "completed"])
    completion_pct = 0
    if total > 0:
        completion_pct = int(round((completed / total) * 100))

    return {
        "plan": plan.model_dump(),
        "today": today,
        "current_week": current_week,
        "counts": {
            "total_items": total,
            "completed_items": completed,
            "pending_items": pending,
            "overdue_items": overdue,
            "completion_percentage": completion_pct,
        },
        "items": items,
    }


@api.put("/roadmap/{client_id}")
async def put_roadmap(client_id: str, payload: RoadmapPlanIn, ctx=Depends(get_current_context)):
    plan = await _get_or_create_roadmap_plan(ctx.tenant_id, client_id)
    patch: dict = {"updated_at": utcnow().isoformat()}
    if payload.start_date:
        patch["start_date"] = payload.start_date
    if payload.items is not None:
        patch["items"] = [RoadmapItem.model_validate(it).model_dump() for it in (payload.items or [])]
    await db.roadmap_plans.update_one({"_id": plan.id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    doc2 = await db.roadmap_plans.find_one({"_id": plan.id, **tenant_scope(ctx.tenant_id)})
    return RoadmapPlan.from_mongo(doc2).model_dump()


@api.post("/roadmap/{client_id}/items")
async def add_roadmap_item(client_id: str, payload: RoadmapItemIn, ctx=Depends(get_current_context)):
    plan = await _get_or_create_roadmap_plan(ctx.tenant_id, client_id)
    week = _clamp_int(payload.week, 1, max(1, int(plan.weeks or 12)))

    action_item_id: Optional[str] = None
    if payload.create_action_item:
        ai_doc = ActionItem(
            tenant_id=ctx.tenant_id,
            client_id=client_id,
            meeting_id=payload.meeting_id,
            title=payload.title,
            description=payload.description,
            owner=payload.owner,
            owner_type=(payload.owner_type or "agency"),
            due_date=payload.due_date,
            priority=(payload.priority or "medium"),
            status="open",
        )
        await db.action_items.insert_one(ai_doc.to_mongo())
        action_item_id = ai_doc.id

    item = RoadmapItem(
        id=new_id(),
        week=week,
        title=payload.title,
        description=payload.description,
        owner=payload.owner,
        owner_type=(payload.owner_type or "agency"),
        due_date=payload.due_date,
        status="open",
        priority=(payload.priority or "medium"),
        action_item_id=action_item_id,
    )

    items = [it.model_dump() for it in (plan.items or [])]
    items.append(item.model_dump())
    await db.roadmap_plans.update_one(
        {"_id": plan.id, **tenant_scope(ctx.tenant_id)},
        {"$set": {"items": items, "updated_at": utcnow().isoformat()}},
    )
    return {"ok": True, "item": item.model_dump(), "action_item_id": action_item_id}


@api.patch("/roadmap/{client_id}/items/{item_id}")
async def patch_roadmap_item(client_id: str, item_id: str, payload: RoadmapItemPatch, ctx=Depends(get_current_context)):
    plan = await _get_or_create_roadmap_plan(ctx.tenant_id, client_id)
    items = [it.model_dump() for it in (plan.items or [])]
    idx = next((i for i, it in enumerate(items) if str(it.get("id") or "") == str(item_id)), -1)
    if idx < 0:
        raise HTTPException(404, "Not found")

    it = dict(items[idx])
    for k, v in payload.model_dump(exclude_unset=True).items():
        if k == "week":
            it[k] = _clamp_int(v, 1, max(1, int(plan.weeks or 12)))
        else:
            it[k] = v

    aid = str(it.get("action_item_id") or "").strip()
    if aid:
        a_patch = {}
        if payload.title is not None:
            a_patch["title"] = payload.title
        if payload.description is not None:
            a_patch["description"] = payload.description
        if payload.owner is not None:
            a_patch["owner"] = payload.owner
        if payload.owner_type is not None:
            a_patch["owner_type"] = payload.owner_type
        if payload.due_date is not None:
            a_patch["due_date"] = payload.due_date
        if payload.priority is not None:
            a_patch["priority"] = payload.priority
        if payload.status is not None:
            a_patch["status"] = payload.status
        if a_patch:
            a_patch["updated_at"] = utcnow().isoformat()
            await db.action_items.update_one({"_id": aid, **tenant_scope(ctx.tenant_id)}, {"$set": a_patch})

    items[idx] = it
    await db.roadmap_plans.update_one(
        {"_id": plan.id, **tenant_scope(ctx.tenant_id)},
        {"$set": {"items": items, "updated_at": utcnow().isoformat()}},
    )
    return {"ok": True, "item": it}

@api.post("/action-items")
async def create_action(data: ActionItemIn, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, data.client_id)
    item = ActionItem(tenant_id=ctx.tenant_id, **data.model_dump())
    await db.action_items.insert_one(item.to_mongo())
    return item.model_dump()


@api.patch("/action-items/{item_id}")
async def update_action(item_id: str, patch: dict, ctx=Depends(get_current_context)):
    doc0 = await db.action_items.find_one({"_id": item_id, **tenant_scope(ctx.tenant_id)})
    if not doc0:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc0.get("client_id") or ""))
    patch["updated_at"] = utcnow().isoformat()
    await db.action_items.update_one({"_id": item_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    doc = await db.action_items.find_one({"_id": item_id, **tenant_scope(ctx.tenant_id)})
    return ActionItem.from_mongo(doc).model_dump()


@api.delete("/action-items/{item_id}")
async def delete_action(item_id: str, ctx=Depends(get_current_context)):
    doc0 = await db.action_items.find_one({"_id": item_id, **tenant_scope(ctx.tenant_id)})
    if not doc0:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc0.get("client_id") or ""))
    await db.action_items.delete_one({"_id": item_id, **tenant_scope(ctx.tenant_id)})
    return {"ok": True}


# ===================== CONTENT CAPTURES =====================
@api.get("/content-captures")
async def list_content(client_id: Optional[str] = None, ctx=Depends(get_current_context)):
    q = {"$and": [tenant_scope(ctx.tenant_id)]}
    allowed = await _allowed_client_ids(ctx)
    if allowed is not None:
        q["$and"].append({"client_id": {"$in": allowed}})
    if client_id:
        await _require_client_access(ctx, client_id)
        q["$and"].append({"client_id": client_id})
    docs = await db.content_captures.find(q).sort("created_at", -1).to_list(500)
    return [ContentCapture.from_mongo(d).model_dump() for d in docs]


@api.post("/content-captures")
async def create_content(data: ContentCaptureIn, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, data.client_id)
    cc = ContentCapture(tenant_id=ctx.tenant_id, **data.model_dump())
    await db.content_captures.insert_one(cc.to_mongo())
    return cc.model_dump()


@api.patch("/content-captures/{cap_id}")
async def update_content(cap_id: str, patch: dict, ctx=Depends(get_current_context)):
    doc0 = await db.content_captures.find_one({"_id": cap_id, **tenant_scope(ctx.tenant_id)})
    if not doc0:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc0.get("client_id") or ""))
    patch["updated_at"] = utcnow().isoformat()
    await db.content_captures.update_one({"_id": cap_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    doc = await db.content_captures.find_one({"_id": cap_id, **tenant_scope(ctx.tenant_id)})
    return ContentCapture.from_mongo(doc).model_dump()


@api.delete("/content-captures/{cap_id}")
async def delete_content(cap_id: str, ctx=Depends(get_current_context)):
    doc0 = await db.content_captures.find_one({"_id": cap_id, **tenant_scope(ctx.tenant_id)})
    if not doc0:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc0.get("client_id") or ""))
    await db.content_captures.delete_one({"_id": cap_id, **tenant_scope(ctx.tenant_id)})
    return {"ok": True}


# ===================== INTEGRATIONS =====================
@api.get("/integrations/catalog")
async def integrations_catalog(_: User = Depends(get_current_user)):
    return list_integrations()


@api.get("/integrations")
async def integrations_status(ctx=Depends(get_current_context)):
    docs = await db.integrations.find(tenant_scope(ctx.tenant_id)).to_list(100)
    by_platform = {d["platform"]: d for d in docs}
    out = []
    for cat in list_integrations():
        plat = cat["platform"]
        stored = by_platform.get(plat)
        user_tok = None
        if plat in GOOGLE_OAUTH_PLATFORMS:
            user_tok = await db.user_oauth_tokens.find_one(
                {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "provider": "google", "platform": plat}
            )
        stored_status = (stored or {}).get("status", "not_connected")
        if plat in GOOGLE_OAUTH_PLATFORMS:
            if plat == "google_ads":
                has_dev = bool(((stored or {}).get("credentials_encrypted") or {}).get("developer_token"))
                stored_status = "connected" if (has_dev and user_tok) else "not_connected"
            else:
                stored_status = "connected" if user_tok else "not_connected"
        out.append({
            **cat,
            "status": stored_status,
            "last_synced_at": (stored or {}).get("last_synced_at") or (user_tok or {}).get("updated_at"),
            "last_error": (stored or {}).get("last_error"),
            "metadata": (stored or {}).get("metadata", {}),
            "configured_field_keys": list(((stored or {}).get("credentials_encrypted") or {}).keys()),
        })
    return out


@api.post("/integrations/{platform}/configure")
async def configure_integration(platform: str, data: IntegrationConfigureIn, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    if platform not in INTEGRATIONS:
        raise HTTPException(404, "Unknown integration")
    if platform in GOOGLE_OAUTH_PLATFORMS and platform != "google_ads":
        raise HTTPException(400, "This Google integration is connected per account manager via Connect Google.")
    if platform == "google_ads":
        drop = {"oauth_client_id", "oauth_client_secret", "refresh_token"}
        creds = {k: v for k, v in (data.credentials or {}).items() if k not in drop}
    else:
        creds = data.credentials or {}
    enc = {k: encrypt_secret(v) for k, v in creds.items() if v}
    existing = await db.integrations.find_one({"$and": [{"platform": platform}, tenant_scope(ctx.tenant_id)]})
    if existing:
        merged_creds = {**(existing.get("credentials_encrypted") or {}), **enc}
        await db.integrations.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "credentials_encrypted": merged_creds,
                "metadata": {**(existing.get("metadata") or {}), **(data.metadata or {})},
                "tenant_id": ctx.tenant_id,
                "status": "connected" if merged_creds else "not_connected",
                "updated_at": utcnow().isoformat(),
            }},
        )
    else:
        i = Integration(
            tenant_id=ctx.tenant_id,
            platform=platform,
            label=INTEGRATIONS[platform]["label"],
            status="connected" if enc else "not_connected",
            credentials_encrypted=enc,
            metadata=data.metadata or {},
        )
        await db.integrations.insert_one(i.to_mongo())
    return {"ok": True, "platform": platform, "status": "connected" if enc else "not_connected"}


@api.post("/integrations/{platform}/test")
async def test_integration(platform: str, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    if platform not in INTEGRATIONS:
        raise HTTPException(404, "Unknown integration")
    doc = await db.integrations.find_one({"$and": [{"platform": platform}, tenant_scope(ctx.tenant_id)]})
    if not doc or not doc.get("credentials_encrypted"):
        raise HTTPException(400, "No credentials configured")
    creds = {k: decrypt_secret(v) for k, v in (doc.get("credentials_encrypted", {}) or {}).items() if v}
    if not all(v is not None and str(v).strip() != "" for v in creds.values()):
        bad_keys = []
        enc_map = doc.get("credentials_encrypted", {}) or {}
        for k, v in creds.items():
            if str(v or "").strip() == "" and str(enc_map.get(k) or "").strip() != "":
                bad_keys.append(k)
        await db.integrations.update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": "error", "last_error": "Credential decryption failed", "updated_at": utcnow().isoformat()}},
        )
        detail = "Credential decryption failed. Re-enter all encrypted fields and save again."
        if bad_keys:
            detail = f"{detail} Undecryptable fields: {', '.join(sorted(set(bad_keys)))}"
        raise HTTPException(400, detail)

    if platform == "clickup":
        res = await connectors.test_clickup(ctx.tenant_id)
    elif platform == "gohighlevel":
        res = await connectors.test_gohighlevel(ctx.tenant_id)
    elif platform == "google_ads":
        res = await connectors.test_google_ads_for_user(ctx.tenant_id, ctx.user.id)
    elif platform == "google_meet":
        res = await connectors.test_google_meet_for_user(ctx.tenant_id, ctx.user.id)
    elif platform == "google_calendar":
        doc = await db.user_oauth_tokens.find_one({"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "provider": "google", "platform": "google_calendar"})
        res = {"ok": True} if doc else {"ok": False, "error": "missing_google_connection", "error_detail": "Connect Google for Google Calendar first."}
    else:
        res = {"ok": True, "note": "Credentials stored & verified. Live API sync runs on next scheduled job."}

    if not res.get("ok"):
        await db.integrations.update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": "error", "last_error": res.get("error_detail") or res.get("error") or "Integration test failed", "updated_at": utcnow().isoformat()}},
        )
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Integration test failed")

    await db.integrations.update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": "connected", "last_synced_at": utcnow().isoformat(), "last_error": None, "updated_at": utcnow().isoformat()}},
    )
    return {"ok": True, "platform": platform, "status": "connected", **res}


@api.delete("/integrations/{platform}")
async def disconnect_integration(platform: str, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    await db.integrations.delete_one({"$and": [{"platform": platform}, tenant_scope(ctx.tenant_id)]})
    return {"ok": True}


@api.get("/integrations/clickup/workspaces")
async def clickup_workspaces(ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    res = await connectors.list_clickup_workspaces(ctx.tenant_id)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
    return res


@api.get("/integrations/google_ads/customers")
async def google_ads_customers(ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        # #region debug-point H4:google-ads-customers-forbidden
        _dbg_emit("H4", "server.py:/integrations/google_ads/customers", "forbidden_non_admin", {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "role": ctx.user.role, "tenant_role": ctx.tenant_role})
        # #endregion
        raise HTTPException(403, "Admin only")
    # #region debug-point H4:google-ads-customers-entry
    _dbg_emit("H4", "server.py:/integrations/google_ads/customers", "list_google_ads_customers_entry", {"tenant_id": ctx.tenant_id, "user_id": ctx.user.id})
    # #endregion
    res = await connectors.list_google_ads_customers(ctx.tenant_id, ctx.user.id)
    if not res.get("ok"):
        # #region debug-point H4:google-ads-customers-fail
        _dbg_emit("H4", "server.py:/integrations/google_ads/customers", "list_google_ads_customers_failed", {"error": res.get("error"), "error_detail": res.get("error_detail")})
        # #endregion
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
    # #region debug-point H4:google-ads-customers-ok
    _dbg_emit("H4", "server.py:/integrations/google_ads/customers", "list_google_ads_customers_ok", {"count": len(res.get("customers") or [])})
    # #endregion
    return res


@api.get("/integrations/clickup/lists")
async def clickup_lists(team_id: Optional[str] = Query(default=None), ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    if not team_id:
        doc = await db.integrations.find_one({"$and": [{"platform": "clickup"}, tenant_scope(ctx.tenant_id)]})
        team_id = ((doc or {}).get("metadata") or {}).get("team_id")
    if not team_id:
        res = await connectors.list_clickup_workspaces(ctx.tenant_id)
        if not res.get("ok"):
            raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
        ws = (res.get("workspaces") or [])
        team_id = (ws[0] or {}).get("id") if ws else None
    if not team_id:
        raise HTTPException(400, "Missing ClickUp team_id")
    res = await connectors.list_clickup_lists(ctx.tenant_id, str(team_id))
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
    return res


@api.get("/integrations/clickup/folders")
async def clickup_folders(team_id: Optional[str] = Query(default=None), ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    if not team_id:
        doc = await db.integrations.find_one({"$and": [{"platform": "clickup"}, tenant_scope(ctx.tenant_id)]})
        team_id = ((doc or {}).get("metadata") or {}).get("team_id")
    if not team_id:
        res = await connectors.list_clickup_workspaces(ctx.tenant_id)
        if not res.get("ok"):
            raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
        ws = (res.get("workspaces") or [])
        team_id = (ws[0] or {}).get("id") if ws else None
    if not team_id:
        raise HTTPException(400, "Missing ClickUp team_id")
    res = await connectors.list_clickup_folders(ctx.tenant_id, str(team_id))
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
    return res


@api.get("/integrations/gohighlevel/locations")
async def ghl_locations(ctx=Depends(get_current_context)):
    res = await connectors.list_gohighlevel_locations(ctx.tenant_id)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
    return res


@api.get("/integrations/gohighlevel/location-tokens")
async def ghl_location_tokens(ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    docs = await db.integration_location_tokens.find({"tenant_id": ctx.tenant_id, "platform": "gohighlevel"}).to_list(2000)
    ids = sorted({str(d.get("location_id") or "") for d in (docs or []) if d.get("location_id")})
    return {"ok": True, "location_ids": ids}


@api.post("/integrations/gohighlevel/location-tokens")
async def upsert_ghl_location_token(data: GhlLocationTokenIn, ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    lid = str(data.location_id or "").strip()
    tok = str(data.token or "").strip()
    if not lid or not tok:
        raise HTTPException(400, "Missing location_id or token")
    await db.integration_location_tokens.update_one(
        {"tenant_id": ctx.tenant_id, "platform": "gohighlevel", "location_id": lid},
        {"$set": {"token_encrypted": encrypt_secret(tok), "updated_at": utcnow().isoformat()}},
        upsert=True,
    )
    return {"ok": True}


@api.delete("/integrations/gohighlevel/location-tokens")
async def delete_ghl_location_token(location_id: str = Query(...), ctx=Depends(get_current_context)):
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    lid = str(location_id or "").strip()
    if not lid:
        raise HTTPException(400, "Missing location_id")
    await db.integration_location_tokens.delete_one({"tenant_id": ctx.tenant_id, "platform": "gohighlevel", "location_id": lid})
    return {"ok": True}


# ===================== DOCS =====================
@api.get("/docs")
async def docs_list(ctx=Depends(get_current_context)):
    tdoc = await db.tenants.find_one({"_id": ctx.tenant_id})
    tslug = str((tdoc or {}).get("slug") or "")
    internal_slug = os.environ.get("INTERNAL_WIKI_TENANT_SLUG", "default").strip()
    is_internal_tenant = bool(tslug and internal_slug and tslug == internal_slug)
    is_admin_view = ctx.user.role == "admin" or ctx.tenant_role in ("owner", "admin")
    sdoc = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    settings = TenantSettings.from_mongo(sdoc) if sdoc else TenantSettings(tenant_id=ctx.tenant_id)

    def apply_template(doc: dict) -> dict:
        brand_name = str((settings.branding or {}).get("product_name") or "")
        monthly_touch = str((settings.terminology or {}).get("monthly_touch") or "Monthly Touch")
        account_manager = str((settings.terminology or {}).get("account_manager") or "Account Manager")
        rep = {
            "{{brand_name}}": brand_name,
            "{{client_singular}}": str((settings.terminology or {}).get("client_singular") or "Client"),
            "{{client_plural}}": str((settings.terminology or {}).get("client_plural") or "Clients"),
            "{{monthly_touch}}": monthly_touch,
            "{{account_manager}}": account_manager,
            "Monthly Touch OS": brand_name or "Monthly Touch OS",
            "Monthly Touch": monthly_touch,
            "Account manager": account_manager,
            "Account Manager": account_manager,
        }
        out = {**doc}
        for k in ("title", "summary", "body"):
            v = out.get(k)
            if isinstance(v, str):
                for a, b in rep.items():
                    if b:
                        v = v.replace(a, b)
                out[k] = v
        return out

    filtered = []
    for d in DOCS:
        aud = (d.get("audience") or "tenant").strip().lower()
        if aud == "internal" and not is_internal_tenant:
            continue
        if aud not in ("tenant", "internal"):
            continue
        min_role = (d.get("min_role") or "").strip().lower()
        if min_role == "admin" and not is_admin_view:
            continue
        filtered.append(apply_template(d))

    return {"items": get_docs_summary(filtered), "categories": get_categories(filtered), "wiki_type": "internal" if is_internal_tenant else "tenant"}


@api.get("/docs/{slug}")
async def docs_detail(slug: str, ctx=Depends(get_current_context)):
    d = get_doc(slug)
    if not d:
        raise HTTPException(404, "Doc not found")

    tdoc = await db.tenants.find_one({"_id": ctx.tenant_id})
    tslug = str((tdoc or {}).get("slug") or "")
    internal_slug = os.environ.get("INTERNAL_WIKI_TENANT_SLUG", "default").strip()
    is_internal_tenant = bool(tslug and internal_slug and tslug == internal_slug)
    is_admin_view = ctx.user.role == "admin" or ctx.tenant_role in ("owner", "admin")
    aud = (d.get("audience") or "tenant").strip().lower()
    if aud == "internal" and not is_internal_tenant:
        raise HTTPException(404, "Doc not found")
    min_role = (d.get("min_role") or "").strip().lower()
    if min_role == "admin" and not is_admin_view:
        raise HTTPException(404, "Doc not found")

    sdoc = await db.tenant_settings.find_one({"tenant_id": ctx.tenant_id})
    settings = TenantSettings.from_mongo(sdoc) if sdoc else TenantSettings(tenant_id=ctx.tenant_id)
    brand_name = str((settings.branding or {}).get("product_name") or "")
    monthly_touch = str((settings.terminology or {}).get("monthly_touch") or "Monthly Touch")
    account_manager = str((settings.terminology or {}).get("account_manager") or "Account Manager")
    rep = {
        "{{brand_name}}": brand_name,
        "{{client_singular}}": str((settings.terminology or {}).get("client_singular") or "Client"),
        "{{client_plural}}": str((settings.terminology or {}).get("client_plural") or "Clients"),
        "{{monthly_touch}}": monthly_touch,
        "{{account_manager}}": account_manager,
        "Monthly Touch OS": brand_name or "Monthly Touch OS",
        "Monthly Touch": monthly_touch,
        "Account manager": account_manager,
        "Account Manager": account_manager,
    }
    out = {**d}
    for k in ("title", "summary", "body"):
        v = out.get(k)
        if isinstance(v, str):
            for a, b in rep.items():
                if b:
                    v = v.replace(a, b)
            out[k] = v
    return out


# ===================== DASHBOARD =====================
@api.get("/dashboard/overview")
async def dashboard_overview(ctx=Depends(get_current_context)):
    now = utcnow()
    now_iso = now.isoformat()
    d0, d1 = _default_last_30_days()
    start_30_ts, end_30_ts = _day_bounds(d0, d1)

    total_clients = await db.clients.count_documents(tenant_scope(ctx.tenant_id))
    churn_risk_high = await db.clients.count_documents({"$and": [tenant_scope(ctx.tenant_id), {"churn_risk": "high"}]})
    churn_risk_medium = await db.clients.count_documents({"$and": [tenant_scope(ctx.tenant_id), {"churn_risk": "medium"}]})

    avg_health_score = 0
    try:
        cur = db.clients.aggregate(
            [
                {"$match": tenant_scope(ctx.tenant_id)},
                {"$group": {"_id": None, "avg": {"$avg": {"$ifNull": ["$health_score", 75]}}}},
            ]
        )
        rows = await cur.to_list(1)
        if rows and rows[0].get("avg") is not None:
            avg_health_score = round(float(rows[0]["avg"]), 1)
    except Exception:
        avg_health_score = 0

    meetings_this_month = await db.meetings.count_documents(
        {"$and": [tenant_scope(ctx.tenant_id), {"created_at": {"$gte": start_30_ts, "$lte": end_30_ts}}]}
    )

    open_action_items = await db.action_items.count_documents(
        {"$and": [tenant_scope(ctx.tenant_id), {"status": {"$in": ["open", "in_progress"]}}]}
    )
    overdue_action_items = await db.action_items.count_documents(
        {"$and": [tenant_scope(ctx.tenant_id), {"status": {"$in": ["open", "in_progress"]}}, {"due_date": {"$lt": now.date().isoformat()}}]}
    )

    content_captures_total = await db.content_captures.count_documents(tenant_scope(ctx.tenant_id))
    content_pending_routing = await db.content_captures.count_documents(
        {"$and": [tenant_scope(ctx.tenant_id), {"routed_to_marketing": {"$ne": True}}]}
    )

    review_forecast_next_month = None
    try:
        m3 = _last_n_months(3)
        snaps = await db.review_monthly_snapshots.find(
            {"$and": [tenant_scope(ctx.tenant_id), {"month": {"$in": m3}}]}
        ).to_list(5000)
        by_month = {m: 0 for m in m3}
        for d in snaps or []:
            s = ReviewMonthlySnapshot.from_mongo(d)
            if not s:
                continue
            if s.month in by_month:
                by_month[s.month] += int(s.received or 0)
        review_forecast_next_month = int(round(sum(by_month.values()) / max(1, len(by_month))))
    except Exception:
        review_forecast_next_month = None

    meeting_docs = await db.meetings.find(tenant_scope(ctx.tenant_id)).sort("created_at", -1).limit(5).to_list(5)
    recent_meetings = [Meeting.from_mongo(m).model_dump() for m in (meeting_docs or [])]

    prep_docs = await db.meetings.find(
        {
            "$and": [
                tenant_scope(ctx.tenant_id),
                {"brief_generated_at": {"$in": [None, ""]}},
                {"scheduled_at": {"$nin": [None, ""]}},
                {"scheduled_at": {"$gte": now_iso}},
            ]
        }
    ).sort("scheduled_at", 1).limit(5).to_list(5)
    prep_queue = [Meeting.from_mongo(m).model_dump() for m in (prep_docs or [])]
    prep_queue_count = await db.meetings.count_documents(
        {
            "$and": [
                tenant_scope(ctx.tenant_id),
                {"brief_generated_at": {"$in": [None, ""]}},
                {"scheduled_at": {"$nin": [None, ""]}},
                {"scheduled_at": {"$gte": now_iso}},
            ]
        }
    )

    top_health_docs = await db.clients.find(tenant_scope(ctx.tenant_id)).sort("health_score", -1).limit(5).to_list(5)
    top_health_clients = [Client.from_mongo(c).model_dump() for c in (top_health_docs or [])]

    at_risk_docs = await db.clients.find(
        {"$and": [tenant_scope(ctx.tenant_id), {"churn_risk": {"$in": ["high", "medium"]}}]}
    ).sort("health_score", 1).limit(5).to_list(5)
    at_risk_clients = [Client.from_mongo(c).model_dump() for c in (at_risk_docs or [])]

    suggestion_docs = await db.clients.find(
        {"$and": [tenant_scope(ctx.tenant_id), {"suggestions": {"$exists": True, "$ne": []}}]}
    ).sort("suggestions_generated_at", -1).limit(20).to_list(20)
    suggestions_ready_clients = len(suggestion_docs or [])
    top_suggestions = []
    pr_w = {"high": 3, "medium": 2, "low": 1}
    for c in suggestion_docs or []:
        cid = c.get("_id")
        cname = c.get("name") or c.get("company") or "Client"
        for s in (c.get("suggestions") or [])[:20]:
            if not isinstance(s, dict):
                continue
            top_suggestions.append(
                {
                    "client_id": cid,
                    "client_name": cname,
                    "category": str(s.get("category") or ""),
                    "priority": str(s.get("priority") or "medium"),
                    "confidence": float(s.get("confidence") or 0.0),
                    "title": str(s.get("title") or s.get("recommendation") or "")[:200],
                    "expected_impact": str(s.get("expected_impact") or "")[:240],
                }
            )
    top_suggestions.sort(
        key=lambda x: (
            -pr_w.get(str(x.get("priority") or "medium").lower(), 2),
            -float(x.get("confidence") or 0.0),
        )
    )
    top_suggestions = top_suggestions[:8]

    return {
        "total_clients": total_clients,
        "avg_health_score": avg_health_score,
        "churn_risk_high": churn_risk_high,
        "churn_risk_medium": churn_risk_medium,
        "meetings_this_month": meetings_this_month,
        "open_action_items": open_action_items,
        "overdue_action_items": overdue_action_items,
        "prep_queue_count": prep_queue_count,
        "prep_queue": prep_queue,
        "content_captures_total": content_captures_total,
        "content_pending_routing": content_pending_routing,
        "review_forecast_next_month": review_forecast_next_month,
        "recent_meetings": recent_meetings,
        "top_health_clients": top_health_clients,
        "at_risk_clients": at_risk_clients,
        "suggestions_ready_clients": suggestions_ready_clients,
        "top_suggestions": top_suggestions,
    }


# ===================== MODELS LIST =====================
@api.get("/ai/models")
async def ai_models(_: User = Depends(get_current_user)):
    items = []
    for key, entry in ai.MODEL_REGISTRY.items():
        provider = entry.get("provider", "unknown")
        required_env = (ai.PROVIDER_CONFIG.get(provider) or {}).get("api_key_env")
        enabled = True
        if required_env:
            enabled = bool(os.environ.get(required_env, "").strip())
        items.append(
            {
                "key": key,
                "label": entry.get("model", key),
                "provider": provider,
                "recommended": key == ai.DEFAULT_MODEL,
                "enabled": enabled,
                "required_env": required_env,
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
