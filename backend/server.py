"""Monthly Touch OS — FastAPI backend."""
import io
import logging
import os
import uvicorn
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
import zipfile
from urllib.parse import urlencode
from html import escape

from dotenv import load_dotenv
import httpx
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from starlette.middleware.cors import CORSMiddleware

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
STORAGE_DIR = ROOT / "storage"

GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "").strip()

from db import db, decrypt_secret, encrypt_secret, new_id, utcnow  # noqa: E402
from auth import (  # noqa: E402
    bootstrap_admin,
    create_token,
    ensure_membership,
    get_current_context,
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
    ImportGhlClientsIn,
    ClientIntegrationBinding,
    ClientIntegrationBindingIn,
    ContentCapture,
    ContentCaptureIn,
    GenerateBriefIn,
    GenerateRecapIn,
    Integration,
    IntegrationConfigureIn,
    LoginIn,
    GoogleLoginIn,
    Meeting,
    MeetingIn,
    MeetingPatch,
    QAScorecard,
    RegisterIn,
    TenantSettings,
    TenantSettingsIn,
    Ticket,
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


def tenant_scope(tenant_id: str) -> dict:
    return {"tenant_id": tenant_id}


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
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
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
async def login(data: LoginIn, _: None = Depends(require_db_ready)):
    try:
        doc = await db.users.find_one({"email": data.email})
        if not doc:
            raise HTTPException(401, "Invalid credentials")
        user = User.from_mongo(doc)
        if (user.auth_provider or "local") == "google":
            raise HTTPException(400, "This account uses Google sign-in. Use “Continue with Google”.")
        if not user.active or not verify_password(data.password, user.password_hash):
            raise HTTPException(401, "Invalid credentials")
        membership = await ensure_membership(user)
        token = create_token(user.id, user.role, membership.tenant_id, membership.role)
        return {"token": token, "user": to_public(user).model_dump(), "tenant_id": membership.tenant_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("login failed: %s", exc)
        raise HTTPException(503, "Database unavailable. Check Atlas Network Access / connection string.") from exc


@api.post("/auth/google")
async def google_login(data: GoogleLoginIn, _: None = Depends(require_db_ready)):
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
    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET or not GOOGLE_OAUTH_REDIRECT_URI:
        raise HTTPException(500, "Google OAuth is not configured on the backend")
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
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
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
    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET or not GOOGLE_OAUTH_REDIRECT_URI:
        raise HTTPException(500, "Google OAuth is not configured on the backend")

    payload = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "code": code,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data=payload)
    if resp.status_code != 200:
        await db.oauth_states.delete_one({"_id": state})
        raise HTTPException(400, f"oauth_http_{resp.status_code}: {resp.text[:300]}")
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
            analysis={"ai_default_model": ai.DEFAULT_MODEL},
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
    docs = await db.clients.find(tenant_scope(ctx.tenant_id)).sort("created_at", -1).to_list(1000)
    return [Client.from_mongo(d).model_dump() for d in docs]


@api.post("/clients")
async def create_client(data: ClientIn, ctx=Depends(get_current_context)):
    am_name = None
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
    return Client.from_mongo(doc).model_dump()


@api.patch("/clients/{client_id}")
async def update_client(client_id: str, patch: dict, ctx=Depends(get_current_context)):
    patch["updated_at"] = utcnow().isoformat()
    res = await db.clients.update_one({"_id": client_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Client not found")
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
    creds = await connectors.get_credentials(ctx.tenant_id, "gohighlevel")
    res = await connectors.list_gohighlevel_contacts(creds, location_id=location_id, query=query, limit=limit)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "GoHighLevel import failed")
    return res


@api.post("/import/gohighlevel/clients")
async def import_clients_from_gohighlevel(data: ImportGhlClientsIn, ctx=Depends(get_current_context)):
    location_id = (data.location_id or "").strip()
    if not location_id:
        raise HTTPException(400, "Missing location_id")

    selected = data.contacts or []
    if not selected and data.contact_ids:
        creds = await connectors.get_credentials(ctx.tenant_id, "gohighlevel")
        res = await connectors.list_gohighlevel_contacts(creds, location_id=location_id, query="", limit=200)
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
        created.append(new_client.model_dump())

    return {"ok": True, "created": created, "skipped": skipped}


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

    ghl_creds = await connectors.get_credentials(ctx.tenant_id, "gohighlevel")
    convs = await connectors.list_gohighlevel_conversations(ghl_creds, str(location_id), str(contact_id), limit=50)
    if not convs.get("ok"):
        raise HTTPException(400, convs.get("error_detail") or convs.get("error") or "Failed to fetch GoHighLevel conversations")
    ghl_msgs: List[dict] = []
    for c in convs.get("conversations") or []:
        cid = (c or {}).get("id")
        if not cid:
            continue
        msgs = await connectors.list_gohighlevel_messages(ghl_creds, str(location_id), str(cid), limit=100)
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
        q["$and"].append({"client_id": client_id})
    docs = await db.meetings.find(q).sort("created_at", -1).to_list(500)
    return [Meeting.from_mongo(d).model_dump() for d in docs]


@api.post("/meetings")
async def create_meeting(data: MeetingIn, ctx=Depends(get_current_context)):
    client_doc = await db.clients.find_one({"_id": data.client_id, **tenant_scope(ctx.tenant_id)})
    if not client_doc:
        raise HTTPException(404, "Client not found")
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
    client_doc = await db.clients.find_one({"_id": client_id, **tenant_scope(ctx.tenant_id)})
    if not client_doc:
        raise HTTPException(404, "Client not found")
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
async def get_meeting(meeting_id: str, ctx=Depends(get_current_context)):
    doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not doc:
        raise HTTPException(404, "Meeting not found")
    return Meeting.from_mongo(doc).model_dump()


@api.get("/meetings/{meeting_id}/export/html")
async def export_meeting_html(meeting_id: str, ctx=Depends(get_current_context)):
    doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
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
async def update_meeting(meeting_id: str, patch: MeetingPatch, ctx=Depends(get_current_context)):
    update = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None}
    update["updated_at"] = utcnow().isoformat()
    res = await db.meetings.update_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Meeting not found")
    doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    return Meeting.from_mongo(doc).model_dump()


@api.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str, ctx=Depends(get_current_context)):
    res = await db.meetings.delete_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if res.deleted_count == 0:
        raise HTTPException(404, "Meeting not found")
    await db.action_items.delete_many({"meeting_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    await db.content_captures.delete_many({"meeting_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    return {"ok": True}


@api.post("/meetings/{meeting_id}/generate-brief")
async def generate_brief(meeting_id: str, data: GenerateBriefIn, ctx=Depends(get_current_context)):
    m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await db.clients.find_one({"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)})
    client = Client.from_mongo(c_doc) if c_doc else None
    client_d = client.model_dump() if client else {"name": meeting.client_name}
    kpi = await connectors.build_kpi_snapshot(ctx.tenant_id, meeting.client_id, client_d.get("company", ""), user_id=ctx.user.id)
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
        "brief_model": data.model or ai.DEFAULT_MODEL,
        "status": "prep",
        "updated_at": utcnow().isoformat(),
    }
    await db.meetings.update_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)}, {"$set": update})
    doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    return Meeting.from_mongo(doc).model_dump()


@api.post("/meetings/{meeting_id}/google-meet/sync-transcript")
async def sync_google_meet_transcript(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
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
    m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await db.clients.find_one({"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)})
    client = Client.from_mongo(c_doc) if c_doc else None
    analysis = await ai.analyze_transcript(
        client_name=client.name if client else (meeting.client_name or ""),
        company=client.company if client else "",
        am_name=meeting.account_manager_name or ctx.user.name,
        transcript=data.transcript,
        model_key=data.model or ai.DEFAULT_MODEL,
        session_id=f"transcript-{meeting_id}",
    )
    # persist transcript + sentiment
    await db.meetings.update_one(
        {"_id": meeting_id, **tenant_scope(ctx.tenant_id)},
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
        "created_action_items": created_actions,
        "created_content_captures": created_content,
    }


@api.post("/meetings/{meeting_id}/generate-recap")
async def generate_recap(meeting_id: str, data: GenerateRecapIn, ctx=Depends(get_current_context)):
    m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await db.clients.find_one({"_id": meeting.client_id, **tenant_scope(ctx.tenant_id)})
    client = Client.from_mongo(c_doc) if c_doc else None
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
    return recap


@api.get("/meetings/{meeting_id}/automation")
async def get_meeting_automation(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
    meeting = Meeting.from_mongo(m_doc)
    return {"ok": True, "draft": meeting.automation_draft, "generated_at": meeting.automation_draft_generated_at, "approved_at": meeting.automation_approved_at}


@api.post("/meetings/{meeting_id}/automation/generate")
async def generate_meeting_automation(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
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
    return {"ok": True, "created_action_items": created_actions, "created_tickets": created_tickets}


@api.get("/meetings/{meeting_id}/qa")
async def get_meeting_qa(meeting_id: str, ctx=Depends(get_current_context)):
    doc = await db.qa_scorecards.find_one({"$and": [{"meeting_id": meeting_id}, tenant_scope(ctx.tenant_id)]}, sort=[("created_at", -1)])
    if not doc:
        return {"ok": True, "scorecard": None}
    return {"ok": True, "scorecard": QAScorecard.from_mongo(doc).model_dump()}


@api.post("/meetings/{meeting_id}/qa/score")
async def score_meeting(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await db.meetings.find_one({"_id": meeting_id, **tenant_scope(ctx.tenant_id)})
    if not m_doc:
        raise HTTPException(404, "Meeting not found")
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
    ctx=Depends(get_current_context),
):
    q: dict = {"$and": [tenant_scope(ctx.tenant_id)]}
    if client_id:
        q["$and"].append({"client_id": client_id})
    if meeting_id:
        q["$and"].append({"meeting_id": meeting_id})
    if status:
        q["$and"].append({"status": status})
    docs = await db.action_items.find(q).sort("created_at", -1).to_list(1000)
    return [ActionItem.from_mongo(d).model_dump() for d in docs]


@api.post("/action-items")
async def create_action(data: ActionItemIn, ctx=Depends(get_current_context)):
    item = ActionItem(tenant_id=ctx.tenant_id, **data.model_dump())
    await db.action_items.insert_one(item.to_mongo())
    return item.model_dump()


@api.patch("/action-items/{item_id}")
async def update_action(item_id: str, patch: dict, ctx=Depends(get_current_context)):
    patch["updated_at"] = utcnow().isoformat()
    res = await db.action_items.update_one({"_id": item_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.action_items.find_one({"_id": item_id, **tenant_scope(ctx.tenant_id)})
    return ActionItem.from_mongo(doc).model_dump()


@api.delete("/action-items/{item_id}")
async def delete_action(item_id: str, ctx=Depends(get_current_context)):
    await db.action_items.delete_one({"_id": item_id, **tenant_scope(ctx.tenant_id)})
    return {"ok": True}


# ===================== CONTENT CAPTURES =====================
@api.get("/content-captures")
async def list_content(client_id: Optional[str] = None, ctx=Depends(get_current_context)):
    q = {"$and": [tenant_scope(ctx.tenant_id)]}
    if client_id:
        q["$and"].append({"client_id": client_id})
    docs = await db.content_captures.find(q).sort("created_at", -1).to_list(500)
    return [ContentCapture.from_mongo(d).model_dump() for d in docs]


@api.post("/content-captures")
async def create_content(data: ContentCaptureIn, ctx=Depends(get_current_context)):
    cc = ContentCapture(tenant_id=ctx.tenant_id, **data.model_dump())
    await db.content_captures.insert_one(cc.to_mongo())
    return cc.model_dump()


@api.patch("/content-captures/{cap_id}")
async def update_content(cap_id: str, patch: dict, ctx=Depends(get_current_context)):
    patch["updated_at"] = utcnow().isoformat()
    res = await db.content_captures.update_one({"_id": cap_id, **tenant_scope(ctx.tenant_id)}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    doc = await db.content_captures.find_one({"_id": cap_id, **tenant_scope(ctx.tenant_id)})
    return ContentCapture.from_mongo(doc).model_dump()


@api.delete("/content-captures/{cap_id}")
async def delete_content(cap_id: str, ctx=Depends(get_current_context)):
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
        raise HTTPException(403, "Admin only")
    res = await connectors.list_google_ads_customers(ctx.tenant_id, ctx.user.id)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
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
    if ctx.user.role != "admin" and ctx.tenant_role not in ("owner", "admin"):
        raise HTTPException(403, "Admin only")
    res = await connectors.list_gohighlevel_locations(ctx.tenant_id)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
    return res


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
async def dashboard_overview(ctx=Depends(get_current_context)):
    clients = await db.clients.find(tenant_scope(ctx.tenant_id)).to_list(2000)
    meetings = await db.meetings.find(tenant_scope(ctx.tenant_id)).to_list(2000)
    actions = await db.action_items.find(tenant_scope(ctx.tenant_id)).to_list(5000)
    content = await db.content_captures.find(tenant_scope(ctx.tenant_id)).to_list(2000)

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

    def _parse_dt(v):
        if not v:
            return None
        if isinstance(v, datetime):
            return v.replace(tzinfo=v.tzinfo or timezone.utc)
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except Exception:
                return None
        return None

    meeting_models = [Meeting.from_mongo(m).model_dump() for m in meetings]
    upcoming = []
    for m in meeting_models:
        dt = _parse_dt(m.get("scheduled_at")) or _parse_dt(m.get("created_at"))
        if dt and dt.replace(tzinfo=dt.tzinfo or timezone.utc) >= now:
            upcoming.append((dt, m))
    upcoming.sort(key=lambda x: x[0])
    prep_queue = [m for _, m in upcoming if not m.get("brief_generated_at")][:5]

    return {
        "total_clients": total_clients,
        "avg_health_score": avg_health,
        "churn_risk_high": churn_red,
        "churn_risk_medium": churn_yellow,
        "meetings_this_month": meetings_this_month,
        "open_action_items": open_actions,
        "overdue_action_items": overdue_actions,
        "prep_queue_count": len([m for _, m in upcoming if not m.get("brief_generated_at")]),
        "prep_queue": prep_queue,
        "content_captures_total": len(content),
        "content_pending_routing": sum(1 for c in content if not c.get("routed_to_marketing")),
        "recent_meetings": [
            m for _, m in sorted(
                [(_parse_dt(m.get("created_at")) or now, m) for m in meeting_models],
                key=lambda x: x[0],
                reverse=True,
            )[:5]
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
