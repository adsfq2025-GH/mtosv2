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
import jwt
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
CLICKUP_OAUTH_CLIENT_ID = str(os.environ.get("CLICKUP_OAUTH_CLIENT_ID") or os.environ.get("CLICKUP_CLIENT_ID") or "").strip()
CLICKUP_OAUTH_CLIENT_SECRET = str(os.environ.get("CLICKUP_OAUTH_CLIENT_SECRET") or os.environ.get("CLICKUP_CLIENT_SECRET") or "").strip()
CLICKUP_OAUTH_REDIRECT_URI = str(os.environ.get("CLICKUP_OAUTH_REDIRECT_URI") or os.environ.get("CLICKUP_REDIRECT_URI") or "").strip()


def _clean_oauth_str(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    for _ in range(3):
        s2 = s.strip()
        if len(s2) >= 2 and (
            (s2[0] == "`" and s2[-1] == "`")
            or (s2[0] == '"' and s2[-1] == '"')
            or (s2[0] == "'" and s2[-1] == "'")
        ):
            s = s2[1:-1].strip()
            continue
        s = s2
        break
    s = s.replace("`", "").strip()
    return s


async def _google_oauth_config(tenant_id: str) -> Dict[str, str]:
    out = {
        "client_id": _clean_oauth_str(GOOGLE_OAUTH_CLIENT_ID),
        "client_secret": _clean_oauth_str(GOOGLE_OAUTH_CLIENT_SECRET),
        "redirect_uri": _clean_oauth_str(GOOGLE_OAUTH_REDIRECT_URI),
    }
    try:
        doc = await _get_integration_runtime_doc(tenant_id, "google_oauth")
        if doc:
            meta = doc.get("metadata") or {}
            enc = doc.get("credentials_encrypted") or {}
            mid = _clean_oauth_str(meta.get("client_id"))
            mru = _clean_oauth_str(meta.get("redirect_uri"))
            if mid:
                out["client_id"] = mid
            if mru:
                out["redirect_uri"] = mru
            if str(enc.get("client_secret") or "").strip():
                out["client_secret"] = _clean_oauth_str(decrypt_secret(enc.get("client_secret")))
    except Exception:
        return out
    return out


async def _clickup_oauth_config(tenant_id: str) -> Dict[str, str]:
    out = {
        "client_id": _clean_oauth_str(CLICKUP_OAUTH_CLIENT_ID),
        "client_secret": _clean_oauth_str(CLICKUP_OAUTH_CLIENT_SECRET),
        "redirect_uri": _clean_oauth_str(CLICKUP_OAUTH_REDIRECT_URI),
    }
    try:
        doc = await _get_integration_runtime_doc(tenant_id, "clickup")
        if doc:
            meta = doc.get("metadata") or {}
            enc = doc.get("credentials_encrypted") or {}
            mid = _clean_oauth_str(meta.get("client_id"))
            mru = _clean_oauth_str(meta.get("redirect_uri"))
            if mid:
                out["client_id"] = mid
            if mru:
                out["redirect_uri"] = mru
            if str(enc.get("client_secret") or "").strip():
                out["client_secret"] = _clean_oauth_str(decrypt_secret(enc.get("client_secret")))
    except Exception:
        return out
    return out


async def _google_login_client_id() -> str:
    cid = _clean_oauth_str(GOOGLE_OAUTH_CLIENT_ID)
    if cid:
        return cid
    return ""
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "").strip()

from db import decrypt_secret, encrypt_secret, new_id, utcnow  # noqa: E402
from auth import (  # noqa: E402
    authenticate_password_user,
    bootstrap_admin,
    can_manage_tenant,
    create_token,
    ensure_membership,
    ensure_membership_for_tenant,
    get_current_context,
    get_current_user,
    login_google_session,
    login_password_session,
    list_runtime_users,
    register_identity,
    require_admin,
    resolve_tenant_id_from_host,
    supabase_session_to_user,
    to_public,
    update_supabase_user,
)
from supabase_native_runtime import (  # noqa: E402
    get_action_item as sb_get_action_item,
    get_client_for_tenant as sb_get_client_for_tenant,
    get_client as sb_get_client,
    get_meeting as sb_get_meeting,
    list_action_items as sb_list_action_items,
    list_clients_for_tenant as sb_list_clients_for_tenant,
    list_clients as sb_list_clients,
    list_meetings as sb_list_meetings,
    list_action_items_for_tenant as sb_list_action_items_for_tenant,
    list_meetings_for_tenant as sb_list_meetings_for_tenant,
    soft_delete_action_items_for_client as sb_soft_delete_action_items_for_client,
    soft_delete_action_items_for_meeting as sb_soft_delete_action_items_for_meeting,
    upsert_meeting_for_tenant as sb_upsert_meeting_for_tenant,
    upsert_client_for_tenant as sb_upsert_client_for_tenant,
    soft_delete_action_item as sb_soft_delete_action_item,
    soft_delete_client as sb_soft_delete_client,
    soft_delete_meetings_for_client as sb_soft_delete_meetings_for_client,
    soft_delete_meeting as sb_soft_delete_meeting,
    upsert_action_item as sb_upsert_action_item,
    upsert_client as sb_upsert_client,
    upsert_meeting as sb_upsert_meeting,
)
from supabase_native_repository import SupabaseNativeRepository, SupabaseRepositoryError  # noqa: E402
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
from oauth_runtime import (
    build_clickup_oauth_state,
    build_google_oauth_state,
    clear_google_oauth_token,
    decode_clickup_oauth_state,
    decode_google_oauth_state,
    get_google_oauth_runtime_doc,
    write_google_oauth_token,
)
from supabase_store import store as bridge, get_store, SupabaseStore  # noqa: E402
from supabase_config import get_runtime_bridge_env_summary, is_supabase_native_only_mode, is_supabase_service_configured
import ai
import ai_visibility
import ai_territory_intelligence
import connectors
import monthly_touch
import clickup_client_sync
import ownership_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mtos")

app = FastAPI(title="Monthly Touch OS")
api = APIRouter(prefix="/api")
DB_READY = False


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


def _default_tenant_settings(tenant_id: str) -> TenantSettings:
    return TenantSettings(
        tenant_id=tenant_id,
        branding={"product_name": "Monthly Touch OS"},
        terminology={"monthly_touch": "Monthly Touch", "client_singular": "Client", "client_plural": "Clients"},
        workflows={"meeting_types": [{"key": "monthly_touch", "label": "Monthly Touch", "wins_count": 3, "issues_count": 2}]},
        analysis={"ai_default_model": ai.DEFAULT_MODEL, "ai_territory_scan_frequency_hours": 24, "ai_territory_max_prompts": 60},
    )


def _tenant_settings_default_doc(tenant_id: str) -> dict[str, Any]:
    return _default_tenant_settings(tenant_id).to_mongo()


def _normalize_tenant_settings_doc(tenant_id: str, doc: Optional[dict[str, Any]]) -> dict[str, Any]:
    base = _tenant_settings_default_doc(tenant_id)
    source = dict(doc or {})
    normalized = {**base, **source}
    normalized["tenant_id"] = tenant_id
    normalized["branding"] = dict(source.get("branding") or base.get("branding") or {})
    normalized["terminology"] = dict(source.get("terminology") or base.get("terminology") or {})
    normalized["workflows"] = dict(source.get("workflows") or base.get("workflows") or {})
    normalized["analysis"] = dict(source.get("analysis") or base.get("analysis") or {})
    normalized["created_at"] = source.get("created_at") or base.get("created_at")
    normalized["updated_at"] = source.get("updated_at") or base.get("updated_at")
    normalized.pop("id", None)
    return normalized


async def _get_tenant_settings_doc(tenant_id: str, *, ensure_exists: bool = False) -> dict[str, Any]:
    bridge = get_store()
    bridge_doc = await bridge.get_tenant_settings(tenant_id) if bridge.is_enabled_for("settings") else None
    if bridge_doc:
        return _normalize_tenant_settings_doc(tenant_id, bridge_doc)

    default_doc = _tenant_settings_default_doc(tenant_id)
    if ensure_exists and bridge.service_configured:
        upserted = await bridge.upsert_tenant_settings(tenant_id, default_doc)
        if upserted:
            return _normalize_tenant_settings_doc(tenant_id, upserted)
    return _normalize_tenant_settings_doc(tenant_id, default_doc)


async def _mirror_tenant_settings_doc(tenant_id: str, doc: dict[str, Any], *, reason: str) -> dict[str, Any]:
    normalized = _normalize_tenant_settings_doc(tenant_id, doc)
    bridge = get_store()
    mirror_status = {"attempted": False, "ok": False, "reason": "disabled"}
    if bridge.is_mirror_enabled_for("settings"):
        mirror_status = await bridge.safe_mirror_tenant_settings(tenant_id, normalized, reason=reason)
    return {"doc": normalized, "mirror": mirror_status}


async def _write_tenant_settings_patch(
    tenant_id: str,
    patch: dict[str, Any],
    *,
    reason: str,
    upsert: bool = True,
) -> dict[str, Any]:
    baseline = await _get_tenant_settings_doc(tenant_id)
    next_doc = _normalize_tenant_settings_doc(tenant_id, {**baseline, **dict(patch or {})})
    bridge = get_store()
    final_doc = _normalize_tenant_settings_doc(tenant_id, next_doc)
    upserted = await bridge.upsert_tenant_settings(tenant_id, final_doc) if bridge.service_configured and upsert else None
    if upserted:
        final_doc = _normalize_tenant_settings_doc(tenant_id, upserted)
    mirror_status = {"attempted": bool(upserted), "ok": bool(upserted), "reason": reason, "mode": "supabase_primary"}
    return {"doc": final_doc, "mirror": mirror_status}


def _merge_runtime_integration_docs(mongo_doc: Optional[dict[str, Any]], bridge_doc: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Compatibility shim: only the bridge (Supabase) doc is used now."""
    return dict(bridge_doc or mongo_doc or {}) if (bridge_doc or mongo_doc) else None


async def _get_integration_runtime_doc(tenant_id: str, platform: str) -> Optional[dict[str, Any]]:
    return await get_store().get_tenant_integration(tenant_id, platform)


async def _mirror_tenant_integration_doc(tenant_id: str, doc: dict[str, Any], *, reason: str) -> dict[str, Any]:
    platform = str((doc or {}).get("platform") or "").strip().lower()
    if not platform:
        return {"attempted": False, "ok": False, "reason": "missing_platform"}
    return await get_store().mirror_tenant_integration(tenant_id, platform, doc)


async def _soft_delete_tenant_integration_doc(tenant_id: str, platform: str, *, reason: str) -> dict[str, Any]:
    return await get_store().safe_soft_delete_tenant_integration(tenant_id, platform)


async def _get_user_oauth_runtime_doc(tenant_id: str, user_id: str, provider: str, platform: str) -> Optional[dict[str, Any]]:
    if str(provider or "").strip().lower() == "google":
        return await get_google_oauth_runtime_doc(tenant_id, user_id, platform)
    return await get_store().get_user_oauth_account(tenant_id, user_id, provider, platform)


async def _mirror_user_oauth_account_doc(
    tenant_id: str,
    user_id: str,
    doc: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    return await get_store().mirror_user_oauth_account(tenant_id, user_id, doc, reason=reason)


async def _soft_delete_user_oauth_account_doc(
    tenant_id: str,
    user_id: str,
    provider: str,
    platform: str,
    *,
    reason: str,
) -> dict[str, Any]:
    return await get_store().safe_soft_delete_user_oauth_account(
        tenant_id, user_id, provider, platform, reason=reason
    )


async def _require_client_access(ctx, client_id: str) -> dict:
    doc = await sb_get_client(ctx, str(client_id))
    if not doc:
        raise HTTPException(404, "Client not found")
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        if str(doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    return doc


async def _require_meeting_access(ctx, meeting_id: str) -> dict:
    doc = await sb_get_meeting(ctx, str(meeting_id))
    if not doc:
        raise HTTPException(404, "Meeting not found")
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        if str(doc.get("account_manager_id") or "") != str(ctx.user.id):
            raise HTTPException(403, "Forbidden")
    return doc


async def _allowed_client_ids(ctx) -> Optional[List[str]]:
    if can_manage_tenant(ctx.user.role, ctx.tenant_role):
        return None
    docs = [
        doc
        for doc in await sb_list_clients(ctx, limit=5000)
        if str((doc or {}).get("account_manager_id") or "") == str(ctx.user.id)
    ]
    return [str(d.get("_id")) for d in (docs or []) if str(d.get("_id") or "").strip()]


async def _list_action_item_docs(
    tenant_id: str,
    *,
    client_id: Optional[str] = None,
    meeting_id: Optional[str] = None,
    status: Optional[str] = None,
    owner_type: Optional[str] = None,
    due_before: Optional[str] = None,
    due_after: Optional[str] = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    return await sb_list_action_items_for_tenant(
        str(tenant_id),
        client_id=client_id,
        meeting_id=meeting_id,
        status=status,
        owner_type=owner_type,
        due_before=due_before,
        due_after=due_after,
        limit=limit,
    )


async def _list_meeting_docs(
    tenant_id: str,
    *,
    client_id: Optional[str] = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    return await sb_list_meetings_for_tenant(str(tenant_id), client_id=client_id, limit=limit)


async def _upsert_meeting_doc(tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    stored = await sb_upsert_meeting_for_tenant(str(tenant_id), dict(doc or {}))
    return stored or dict(doc or {})


async def _upsert_client_doc(tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    stored = await sb_upsert_client_for_tenant(str(tenant_id), dict(doc or {}))
    return stored or dict(doc or {})


async def _bg_publish_clickup_brief(tenant_id: str, meeting_id: str) -> None:
    try:
        bridge = get_store()
        m_doc = await bridge.get_meeting(tenant_id, meeting_id) if bridge.is_enabled_for("meetings") else None
        if not m_doc:
            return
        c_doc = await bridge.get_client(tenant_id, str(m_doc.get("client_id") or "")) if bridge.is_enabled_for("clients") else None
        res = await connectors.publish_clickup_meeting_brief(tenant_id, m_doc, c_doc or {})
        if not res.get("ok"):
            return
        task_id = str(res.get("task_id") or "").strip()
        task_url = str(res.get("url") or "").strip()
        if not task_id:
            return
        meeting_patch = {**dict(m_doc or {})}
        clickup_client_book = dict(meeting_patch.get("clickup_client_book") or {})
        clickup_client_book["brief_task_id"] = task_id
        clickup_client_book["brief_task_url"] = task_url
        meeting_patch["clickup_client_book"] = clickup_client_book
        meeting_patch["updated_at"] = utcnow().isoformat()
        if bridge.is_enabled_for("meetings"):
            await bridge.upsert_meeting(tenant_id, meeting_patch)
    except Exception as exc:
        logger.error("clickup brief publish failed: %s", exc)


async def _bg_publish_clickup_summary(tenant_id: str, meeting_id: str) -> None:
    try:
        bridge = get_store()
        m_doc = await bridge.get_meeting(tenant_id, meeting_id) if bridge.is_enabled_for("meetings") else None
        if not m_doc:
            return
        if not str(m_doc.get("recap_email") or "").strip():
            return
        if not str(m_doc.get("automation_approved_at") or "").strip():
            return
        c_doc = await bridge.get_client(tenant_id, str(m_doc.get("client_id") or "")) if bridge.is_enabled_for("clients") else None
        if bridge.is_enabled_for("action_items"):
            actions = await bridge.list_action_items(tenant_id, meeting_legacy_id=meeting_id, limit=500)
        else:
            actions = []
        if bridge.is_enabled_for("tickets"):
            tickets = await bridge.list_tickets(tenant_id, meeting_legacy_id=meeting_id, limit=500)
        else:
            tickets = []
        res = await connectors.publish_clickup_meeting_summary(tenant_id, m_doc, c_doc or {}, actions or [], tickets or [])
        if not res.get("ok"):
            return
        task_id = str(res.get("task_id") or "").strip()
        task_url = str(res.get("url") or "").strip()
        if not task_id:
            return
        meeting_patch = {**dict(m_doc or {})}
        clickup_client_book = dict(meeting_patch.get("clickup_client_book") or {})
        clickup_client_book["summary_task_id"] = task_id
        clickup_client_book["summary_task_url"] = task_url
        meeting_patch["clickup_client_book"] = clickup_client_book
        meeting_patch["updated_at"] = utcnow().isoformat()
        if bridge.is_enabled_for("meetings"):
            await bridge.upsert_meeting(tenant_id, meeting_patch)
    except Exception as exc:
        logger.error("clickup summary publish failed: %s", exc)


async def _bg_publish_clickup_tickets(tenant_id: str, meeting_id: str) -> None:
    try:
        bridge = get_store()
        m_doc = await bridge.get_meeting(tenant_id, meeting_id) if bridge.is_enabled_for("meetings") else None
        if not m_doc:
            return
        if bridge.is_enabled_for("tickets"):
            tickets = await bridge.list_tickets(tenant_id, meeting_legacy_id=meeting_id, limit=1000)
        else:
            tickets = []
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
                if bridge.is_enabled_for("tickets"):
                    doc0 = await bridge.get_ticket(tenant_id, tid)
                    if doc0:
                        await bridge.upsert_ticket(
                            tenant_id,
                            {**dict(doc0), "external_id": task_id, "external_url": url, "updated_at": utcnow().isoformat()},
                        )
    except Exception as exc:
        logger.error("clickup tickets publish failed: %s", exc)


async def _bg_send_client_recap_email(tenant_id: str, meeting_id: str, user_id: str) -> None:
    try:
        bridge = get_store()
        m_doc = await bridge.get_meeting(tenant_id, meeting_id) if bridge.is_enabled_for("meetings") else None
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
        c_doc = await bridge.get_client(tenant_id, client_id) if bridge.is_enabled_for("clients") else None
        to_addr = str((c_doc or {}).get("email") or "").strip()
        if not to_addr:
            return
        res = await connectors.send_gmail_plain_email(tenant_id, user_id, to_addr, subject, plain)
        if not res.get("ok"):
            return
        meeting_patch = {
            **dict(m_doc or {}),
            "recap_subject": subject,
            "recap_email": plain,
            "recap_sent_at": utcnow().isoformat(),
            "updated_at": utcnow().isoformat(),
        }
        if bridge.is_enabled_for("meetings"):
            await bridge.upsert_meeting(tenant_id, meeting_patch)
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
    if is_supabase_service_configured():
        try:
            repo = SupabaseNativeRepository.from_env()
            await repo.list("tenants", select="id", limit=1)
            DB_READY = True
            return True
        except SupabaseRepositoryError as exc:
            logger.error("Supabase native readiness check failed: %s", exc)
            return False
        except Exception as exc:
            logger.error("Unexpected Supabase readiness failure: %s", exc)
            return False
    logger.error("Supabase service configuration is required")
    return False


async def require_db_ready():
    ok = await _ensure_db_ready()
    if not ok:
        raise HTTPException(503, "Database unavailable. Check Supabase service configuration.")

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
        "supabase_native_only_mode": is_supabase_native_only_mode(),
        "google_login_configured": bool(GOOGLE_OAUTH_CLIENT_ID),
        "google_oauth_configured": bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REDIRECT_URI),
    }


# ===================== AUTH =====================
@api.post("/auth/register")
async def register(request: Request, data: RegisterIn, _: None = Depends(require_db_ready)):
    # First user becomes super admin; later users default to account manager.
    try:
        role = "super_admin" if not await get_store().has_user_profiles() else "account_manager"
        user = await register_identity(data.email, data.name, data.password, app_role=role)
        host_tenant_id = await resolve_tenant_id_from_host(request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
        if host_tenant_id:
            existing_count = await get_store().count_active_members_for_tenant(str(host_tenant_id))
            role_if_create = "owner" if existing_count == 0 else "member"
            membership = await ensure_membership_for_tenant(user, str(host_tenant_id), role_if_create=role_if_create)
        else:
            membership = await ensure_membership(user)
        settings_doc = await get_store().get_tenant_settings(membership.tenant_id)
        if not settings_doc:
            await _write_tenant_settings_patch(
                membership.tenant_id,
                _tenant_settings_default_doc(membership.tenant_id),
                reason="auth_register_bootstrap",
            )
        session = await login_password_session(data.email, data.password)
        token = str((session or {}).get("access_token") or "").strip()
        if not token:
            token = create_token(user.id, user.role, membership.tenant_id, membership.role)
        return {
            "token": token,
            "refresh_token": (session or {}).get("refresh_token"),
            "expires_in": (session or {}).get("expires_in"),
            "user": to_public(user).model_dump(),
            "tenant_id": membership.tenant_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("register failed: %s", exc)
        raise HTTPException(503, "Registration failed. Check Supabase auth configuration or database connectivity.") from exc


@api.post("/auth/login")
async def login(request: Request, data: LoginIn, _: None = Depends(require_db_ready)):
    try:
        user = await authenticate_password_user(data.email, data.password)
        if not user:
            raise HTTPException(401, "Invalid credentials")
        host_tenant_id = await resolve_tenant_id_from_host(request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
        if host_tenant_id:
            membership_doc = await get_store().get_user_membership(str(host_tenant_id), user.id)
            if not membership_doc:
                raise HTTPException(403, "Not a member of this tenant")
            membership = TenantMembership.from_mongo(membership_doc)
        else:
            membership = await ensure_membership(user)
        session = await login_password_session(data.email, data.password)
        token = str((session or {}).get("access_token") or "").strip()
        if not token:
            token = create_token(user.id, user.role, membership.tenant_id, membership.role)
        return {
            "token": token,
            "refresh_token": (session or {}).get("refresh_token"),
            "expires_in": (session or {}).get("expires_in"),
            "user": to_public(user).model_dump(),
            "tenant_id": membership.tenant_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("login failed: %s", exc)
        raise HTTPException(503, "Login failed. Check Supabase auth configuration or database connectivity.") from exc


@api.post("/auth/google")
async def google_login(request: Request, data: GoogleLoginIn, _: None = Depends(require_db_ready)):
    cred = (data.credential or "").strip()
    if not cred:
        raise HTTPException(400, "Missing credential")
    # #region debug-point B:google-login-tokeninfo
    _dbg_emit("B", "server.py:/auth/google", "google_login_tokeninfo", {
        "credential_length": len(cred),
    })
    # #endregion
    try:
        session = await login_google_session(cred)
    except httpx.HTTPStatusError as exc:
        detail = "Google sign-in failed"
        try:
            payload = exc.response.json() or {}
            detail = str(payload.get("msg") or payload.get("message") or payload.get("error_description") or payload.get("error") or detail)
        except Exception:
            if exc.response.text:
                detail = exc.response.text[:300]
        status_code = exc.response.status_code if exc.response is not None else 400
        raise HTTPException(status_code if status_code < 500 else 400, detail) from exc

    user = supabase_session_to_user(session)
    if not user:
        raise HTTPException(400, "Supabase Google session did not return a user")

    profiles = await get_store().list_user_profiles(limit=2)
    if len(profiles) == 1 and str((profiles[0] or {}).get("email") or "").strip().lower() == str(user.email or "").strip().lower():
        await update_supabase_user(
            user.id,
            name=user.name,
            app_role="super_admin",
            auth_provider="google",
            avatar_url=user.avatar_url,
        )
        session = await login_google_session(cred)
        user = supabase_session_to_user(session) or user

    host_tenant_id = await resolve_tenant_id_from_host(request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
    if host_tenant_id:
        mdoc = await get_store().get_user_membership(str(host_tenant_id), user.id)
        if mdoc:
            membership = TenantMembership.from_mongo(mdoc)
        else:
            existing_count = await get_store().count_active_members_for_tenant(str(host_tenant_id))
            role_if_create = "owner" if existing_count == 0 else "member"
            membership = await ensure_membership_for_tenant(user, str(host_tenant_id), role_if_create=role_if_create)
    else:
        membership = await ensure_membership(user)
    # #region debug-point B:google-login-success
    _dbg_emit("B", "server.py:/auth/google", "google_login_success", {
        "user_id": str(user.id),
        "email": user.email,
        "tenant_id": membership.tenant_id,
    })
    # #endregion
    token = str((session or {}).get("access_token") or "").strip()
    if not token:
        token = create_token(user.id, user.role, membership.tenant_id, membership.role)
    return {
        "token": token,
        "refresh_token": (session or {}).get("refresh_token"),
        "expires_in": (session or {}).get("expires_in"),
        "user": to_public(user).model_dump(),
        "tenant_id": membership.tenant_id,
    }


@api.get("/auth/me")
async def me(user: User = Depends(get_current_user)):
    # #region debug-point D:auth-me
    _dbg_emit("D", "server.py:/auth/me", "auth_me_ok", {"user_id": str(user.id), "email": user.email})
    # #endregion
    payload = to_public(user).model_dump()
    profile = await get_store().get_user_profile(user.id)
    if profile:
        payload["email"] = profile.get("email") or payload.get("email")
        payload["name"] = profile.get("name") or payload.get("name")
        payload["avatar_url"] = profile.get("avatar_url") or payload.get("avatar_url")
    return payload


@api.get("/users")
async def list_users(_: User = Depends(require_admin)):
    return await list_runtime_users(limit=500)


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
    # #region debug-point GO1:oauth-config-source
    try:
        doc = await _get_integration_runtime_doc(ctx.tenant_id, "google_oauth")
        meta = (doc or {}).get("metadata") or {}
        enc = (doc or {}).get("credentials_encrypted") or {}
        _dbg_emit(
            "GO1",
            "server.py:/oauth/google/start",
            "oauth_config",
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user.id,
                "platform": platform,
                "has_env_client_id": bool(GOOGLE_OAUTH_CLIENT_ID),
                "has_env_secret": bool(GOOGLE_OAUTH_CLIENT_SECRET),
                "has_env_redirect_uri": bool(GOOGLE_OAUTH_REDIRECT_URI),
                "has_meta_client_id": bool(str(meta.get("client_id") or "").strip()),
                "has_meta_redirect_uri": bool(str(meta.get("redirect_uri") or "").strip()),
                "has_enc_secret": bool(str(enc.get("client_secret") or "").strip()),
                "redirect_uri": str(cfg.get("redirect_uri") or "")[:180],
            },
        )
    except Exception:
        pass
    # #endregion
    state = build_google_oauth_state(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        platform=platform,
        scopes=scopes,
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
    doc = await _get_user_oauth_runtime_doc(ctx.tenant_id, ctx.user.id, "google", platform)
    if not doc:
        return {"ok": True, "connected": False}
    refresh_token = await connectors.get_google_refresh_token(ctx.tenant_id, ctx.user.id, platform)
    if not refresh_token:
        return {"ok": True, "connected": False}
    return {"ok": True, "connected": True, "platform": platform, "scopes": doc.get("scopes") or [], "updated_at": doc.get("updated_at")}


@api.post("/oauth/google/disconnect")
async def oauth_google_disconnect(platform: str = Query(...), ctx=Depends(get_current_context)):
    runtime_doc = await _get_user_oauth_runtime_doc(ctx.tenant_id, ctx.user.id, "google", platform)
    disconnect_result = await clear_google_oauth_token(
        ctx.tenant_id,
        ctx.user.id,
        platform,
        account_email=(runtime_doc or {}).get("account_email"),
        scopes=list((runtime_doc or {}).get("scopes") or []),
        updated_at=utcnow().isoformat(),
    )
    if not disconnect_result.get("ok"):
        raise HTTPException(503, "OAuth disconnect could not be completed safely. Token state remains unchanged.")
    return {"ok": True}


@api.get("/oauth/google/callback")
async def oauth_google_callback(code: str = Query(...), state: str = Query(...)):
    try:
        st = decode_google_oauth_state(state)
    except jwt.PyJWTError:
        raise HTTPException(400, "Invalid OAuth state")
    tenant_id = str(st.get("tenant_id") or "").strip()
    user_id = str(st.get("user_id") or "").strip()
    platform = str(st.get("platform") or "").strip()
    scopes = [str(scope).strip() for scope in (st.get("scopes") or []) if str(scope).strip()]
    cfg = await _google_oauth_config(str(tenant_id))
    if not cfg.get("client_id") or not cfg.get("client_secret") or not cfg.get("redirect_uri"):
        raise HTTPException(500, "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET/GOOGLE_OAUTH_REDIRECT_URI on the backend or configure Integrations → Google OAuth.")
    # #region debug-point GO2:oauth-callback-config
    try:
        doc = await _get_integration_runtime_doc(str(tenant_id), "google_oauth")
        meta = (doc or {}).get("metadata") or {}
        enc = (doc or {}).get("credentials_encrypted") or {}
        _dbg_emit(
            "GO2",
            "server.py:/oauth/google/callback",
            "oauth_callback_config",
            {
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "platform": platform,
                "has_env_client_id": bool(GOOGLE_OAUTH_CLIENT_ID),
                "has_env_secret": bool(GOOGLE_OAUTH_CLIENT_SECRET),
                "has_env_redirect_uri": bool(GOOGLE_OAUTH_REDIRECT_URI),
                "has_meta_client_id": bool(str(meta.get("client_id") or "").strip()),
                "has_meta_redirect_uri": bool(str(meta.get("redirect_uri") or "").strip()),
                "has_enc_secret": bool(str(enc.get("client_secret") or "").strip()),
                "redirect_uri": str(cfg.get("redirect_uri") or "")[:180],
            },
        )
    except Exception:
        pass
    # #endregion

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
        detail = resp.text[:300]
        try:
            j = resp.json() or {}
            if isinstance(j, dict) and (j.get("error") or j.get("error_description")):
                detail = f"{j.get('error') or 'oauth_error'}: {j.get('error_description') or ''}".strip()
        except Exception:
            pass
        # #region debug-point GO3:oauth-token-error
        try:
            _dbg_emit(
                "GO3",
                "server.py:/oauth/google/callback",
                "oauth_token_exchange_failed",
                {
                    "tenant_id": str(tenant_id),
                    "user_id": str(user_id),
                    "platform": platform,
                    "http_status": resp.status_code,
                    "detail": str(detail)[:220],
                    "redirect_uri": str(cfg.get("redirect_uri") or "")[:180],
                },
            )
        except Exception:
            pass
        # #endregion
        raise HTTPException(400, f"oauth_http_{resp.status_code}: {detail}")
    data = resp.json() or {}
    refresh_token = data.get("refresh_token") or ""
    if not str(refresh_token).strip():
        raise HTTPException(400, "Google did not return a refresh_token. Re-run Connect and ensure prompt=consent is forced.")

    now = utcnow().isoformat()
    user_doc = await get_store().get_user_profile(str(user_id))
    write_result = await write_google_oauth_token(
        str(tenant_id),
        str(user_id),
        str(platform or "").strip(),
        str(refresh_token),
        scopes,
        account_email=(user_doc or {}).get("email"),
        updated_at=now,
    )
    if not write_result.get("ok"):
        raise HTTPException(503, "OAuth token storage is unavailable. Connection was not finalized safely.")

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


@api.get("/oauth/clickup/start")
async def oauth_clickup_start(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    cfg = await _clickup_oauth_config(ctx.tenant_id)
    if not cfg.get("client_id") or not cfg.get("client_secret") or not cfg.get("redirect_uri"):
        raise HTTPException(
            500,
            "ClickUp OAuth is not configured. Add ClickUp client_id, client_secret, and redirect_uri in Integrations -> ClickUp or backend env vars.",
        )
    state = build_clickup_oauth_state(tenant_id=ctx.tenant_id, user_id=ctx.user.id)
    params = {
        "client_id": cfg.get("client_id"),
        "redirect_uri": cfg.get("redirect_uri"),
        "state": state,
    }
    url = "https://app.clickup.com/api?" + urlencode(params)
    return {"ok": True, "url": url}


@api.get("/oauth/clickup/status")
async def oauth_clickup_status(ctx=Depends(get_current_context)):
    token = await connectors.get_clickup_access_token(ctx.tenant_id)
    doc = await _get_integration_runtime_doc(ctx.tenant_id, "clickup")
    return {
        "ok": True,
        "connected": bool(token),
        "updated_at": (doc or {}).get("updated_at"),
        "last_synced_at": (doc or {}).get("last_synced_at"),
    }


@api.post("/oauth/clickup/disconnect")
async def oauth_clickup_disconnect(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    await _soft_delete_tenant_integration_doc(ctx.tenant_id, "clickup", reason="disconnect_clickup_oauth")
    return {"ok": True}


@api.get("/oauth/clickup/callback")
async def oauth_clickup_callback(code: str = Query(...), state: str = Query(...)):
    try:
        st = decode_clickup_oauth_state(state)
    except jwt.PyJWTError:
        raise HTTPException(400, "Invalid OAuth state")

    tenant_id = str(st.get("tenant_id") or "").strip()
    user_id = str(st.get("user_id") or "").strip()
    cfg = await _clickup_oauth_config(tenant_id)
    if not cfg.get("client_id") or not cfg.get("client_secret") or not cfg.get("redirect_uri"):
        raise HTTPException(
            500,
            "ClickUp OAuth is not configured. Add ClickUp client_id, client_secret, and redirect_uri in Integrations -> ClickUp or backend env vars.",
        )

    payload = {
        "client_id": cfg.get("client_id"),
        "client_secret": cfg.get("client_secret"),
        "code": code,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://api.clickup.com/api/v2/oauth/token", json=payload)
    if resp.status_code != 200:
        detail = _safe_err_detail(resp)
        raise HTTPException(400, f"clickup_oauth_http_{resp.status_code}: {detail}")

    data = resp.json() or {}
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(400, "ClickUp did not return an access_token.")

    now = utcnow().isoformat()
    bridge = get_store()
    existing = await bridge.get_tenant_integration(tenant_id, "clickup")
    if existing:
        merged_creds = {
            **dict(existing.get("credentials_encrypted") or {}),
            "access_token": encrypt_secret(access_token),
        }
        merged_metadata = {
            **dict(existing.get("metadata") or {}),
            "client_id": cfg.get("client_id"),
            "redirect_uri": cfg.get("redirect_uri"),
            "oauth_connected_by_user_id": user_id,
        }
        await bridge.upsert_tenant_integration(tenant_id, "clickup", {
            "id": existing.get("id") or existing.get("_id"),
            "tenant_id": tenant_id,
            "platform": "clickup",
            "label": existing.get("label") or INTEGRATIONS["clickup"]["label"],
            "status": "connected",
            "last_synced_at": now,
            "last_error": None,
            "credentials_encrypted": merged_creds,
            "metadata": merged_metadata,
            "updated_at": now,
        })
        mirror_doc = {
            "platform": "clickup",
            "label": existing.get("label") or INTEGRATIONS["clickup"]["label"],
            "status": "connected",
            "last_synced_at": now,
            "last_error": None,
            "metadata": merged_metadata,
        }
    else:
        integration = Integration(
            tenant_id=tenant_id,
            platform="clickup",
            label=INTEGRATIONS["clickup"]["label"],
            status="connected",
            last_synced_at=now,
            last_error=None,
            credentials_encrypted={"access_token": encrypt_secret(access_token)},
            metadata={
                "client_id": cfg.get("client_id"),
                "redirect_uri": cfg.get("redirect_uri"),
                "oauth_connected_by_user_id": user_id,
            },
        )
        payload = integration.to_mongo()
        if payload.get("_id"):
            payload["id"] = payload.pop("_id")
        await bridge.upsert_tenant_integration(tenant_id, "clickup", payload)
        mirror_doc = {
            "platform": "clickup",
            "label": integration.label,
            "status": "connected",
            "last_synced_at": now,
            "last_error": None,
            "metadata": integration.metadata,
        }

    await _mirror_tenant_integration_doc(tenant_id, mirror_doc, reason="clickup_oauth_callback")

    html = """<!doctype html><html><head><meta charset="utf-8"></head>
<body><script>
try {
  if (window.opener) {
    window.opener.postMessage({ type: "clickup_oauth_success", platform: "clickup" }, "*");
  }
} catch (e) {}
window.close();
</script>
<div style="font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 20px;">
  ClickUp connected. You can close this window.
</div>
</body></html>"""
    return Response(content=html, media_type="text/html")


@api.get("/settings")
async def get_settings(ctx=Depends(get_current_context)):
    doc = await _get_tenant_settings_doc(ctx.tenant_id, ensure_exists=True)
    return TenantSettings.from_mongo(doc).model_dump()


@api.put("/settings")
async def put_settings(data: TenantSettingsIn, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    patch = {
        "branding": data.branding or {},
        "terminology": data.terminology or {},
        "workflows": data.workflows or {},
        "analysis": data.analysis or {},
        "updated_at": utcnow().isoformat(),
    }
    result = await _write_tenant_settings_patch(ctx.tenant_id, patch, reason="settings_put")
    doc = result["doc"]
    return TenantSettings.from_mongo(doc).model_dump()


def _default_prompt_text(key: str) -> str:
    catalog = _prompt_template_catalog()
    meta = catalog.get(str(key or "").strip())
    return str((meta or {}).get("default_text") or "")


def _prompt_template_catalog() -> dict[str, dict[str, str]]:
    return {
        "brief_prompt": {
            "label": "Brief Prompt",
            "category": "pre_meeting",
            "description": "Controls Monthly Touch brief generation, strategic talking points, wins, issues, and next-step framing.",
            "default_text": (
                "Generate a retention-focused Monthly Touch brief. Prioritize business outcomes, client value, growth blockers, and concrete next-step recommendations."
            ),
        },
        "monthly_touch_analysis": {
            "label": "Audit Prompt",
            "category": "post_meeting",
            "description": "Controls transcript analysis, sentiment, risks, action items, and relationship insights.",
            "default_text": (
                "Analyze the transcript and produce a structured Monthly Touch analysis.\n"
                "Focus on:\n"
                "- Client personality and decision-making style\n"
                "- Trust issues, frustrations, and relationship opportunities\n"
                "- Business goals, growth goals, and hidden risks\n"
                "- Operational bottlenecks that affect lead handling, sales, fulfillment, retention\n"
                "- Clear action items with owner_type (agency|client) and suggested priority\n"
                "Be specific and evidence-based. Do not invent facts."
            ),
        },
        "ticket_prompt": {
            "label": "Ticket Prompt",
            "category": "post_meeting",
            "description": "Shapes how department tickets are derived from the meeting workflow and follow-up planning.",
            "default_text": "Create only operationally necessary department tickets. Keep them accountable, client-relevant, and specific enough for cross-team execution.",
        },
        "email_prompt": {
            "label": "Email Prompt",
            "category": "post_meeting",
            "description": "Controls client-facing recap email tone, structure, and next-step clarity.",
            "default_text": "Write recap emails that are concise, strategic, client-facing, and explicit about progress, blockers, ownership, and the next Monthly Touch.",
        },
        "qa_prompt": {
            "label": "QA Prompt",
            "category": "coaching",
            "description": "Controls scoring and feedback for Monthly Touch quality assurance.",
            "default_text": "Score the Monthly Touch as a strategic retention meeting. Reward clarity, business discovery, trust-building, follow-through, and concrete next-step ownership.",
        },
        "coaching_prompt": {
            "label": "Coaching Prompt",
            "category": "coaching",
            "description": "Controls coaching tone and improvement guidance for Account Managers.",
            "default_text": "Give coaching feedback that is direct, constructive, and focused on improving future Monthly Touch quality, strategic depth, and client confidence.",
        },
        "retention_prompt": {
            "label": "Retention Prompt",
            "category": "strategy",
            "description": "Controls churn-risk, relationship health, and retention-oriented interpretation inside AI workflows.",
            "default_text": "Prioritize churn-risk detection, trust repair opportunities, proof-of-value communication, and strategic recommendations that improve client retention.",
        },
    }


def _prompt_template_payload(tenant_id: str, key: str, text: str, *, updated_at: Optional[str] = None) -> dict[str, Any]:
    meta = dict(_prompt_template_catalog().get(str(key or "").strip()) or {})
    default_text = str(meta.get("default_text") or "")
    current_text = str(text or "")
    return {
        "tenant_id": tenant_id,
        "key": str(key or "").strip(),
        "label": str(meta.get("label") or str(key or "").strip()),
        "category": str(meta.get("category") or "custom"),
        "description": str(meta.get("description") or ""),
        "text": current_text,
        "default_text": default_text,
        "is_customized": current_text.strip() != default_text.strip(),
        "updated_at": updated_at,
    }


def _prompt_template_doc(tenant_id: str, key: str, text: str, *, updated_at: Optional[str] = None) -> dict[str, Any]:
    return PromptTemplate(
        tenant_id=tenant_id,
        key=str(key),
        text=str(text or ""),
        updated_at=updated_at,
    ).to_mongo()


async def _get_prompt_template_doc(tenant_id: str, key: str) -> Optional[dict[str, Any]]:
    normalized_key = str(key or "").strip()
    settings_doc = await _get_tenant_settings_doc(tenant_id)
    analysis = dict((settings_doc or {}).get("analysis") or {})
    prompt_templates = dict(analysis.get("prompt_templates") or {})
    if normalized_key in prompt_templates:
        return _prompt_template_doc(
            tenant_id,
            normalized_key,
            str(prompt_templates.get(normalized_key) or ""),
            updated_at=str((settings_doc or {}).get("updated_at") or ""),
        )
    return None


async def _write_prompt_template_doc(tenant_id: str, key: str, text: str) -> dict[str, Any]:
    normalized_key = str(key or "").strip()
    next_text = str(text or "")
    settings_doc = await _get_tenant_settings_doc(tenant_id)
    analysis = dict((settings_doc or {}).get("analysis") or {})
    prompt_templates = dict(analysis.get("prompt_templates") or {})
    prompt_templates[normalized_key] = next_text
    analysis["prompt_templates"] = prompt_templates
    result = await _write_tenant_settings_patch(
        tenant_id,
        {
            "analysis": analysis,
            "updated_at": utcnow().isoformat(),
        },
        reason=f"prompt_template:{normalized_key}",
    )
    final_doc = _prompt_template_doc(
        tenant_id,
        normalized_key,
        next_text,
        updated_at=str((result.get("doc") or {}).get("updated_at") or ""),
    )
    return final_doc


async def _list_prompt_templates(tenant_id: str) -> list[dict[str, Any]]:
    catalog = _prompt_template_catalog()
    items: list[dict[str, Any]] = []
    for key in catalog.keys():
        doc = await _get_prompt_template_doc(tenant_id, key)
        text = PromptTemplate.from_mongo(doc).text if doc else _default_prompt_text(key)
        updated_at = str((doc or {}).get("updated_at") or "")
        items.append(_prompt_template_payload(tenant_id, key, text, updated_at=updated_at))
    return items


async def _get_prompt_template_text(tenant_id: str, key: str) -> str:
    doc = await _get_prompt_template_doc(tenant_id, key)
    if doc:
        return str(PromptTemplate.from_mongo(doc).text or "")
    return _default_prompt_text(key)


def _prompt_instruction_bundle(*parts: str) -> str:
    cleaned = [str(part or "").strip() for part in parts if str(part or "").strip()]
    return "\n\n".join(cleaned)


@api.get("/prompts")
async def list_prompt_templates(ctx=Depends(get_current_context)):
    return {"ok": True, "items": await _list_prompt_templates(ctx.tenant_id)}


@api.get("/prompts/{key}")
async def get_prompt_template(key: str, ctx=Depends(get_current_context)):
    normalized_key = str(key or "").strip()
    doc = await _get_prompt_template_doc(ctx.tenant_id, normalized_key)
    if not doc:
        return {"ok": True, **_prompt_template_payload(ctx.tenant_id, normalized_key, _default_prompt_text(normalized_key))}
    prompt = PromptTemplate.from_mongo(doc)
    return {"ok": True, **_prompt_template_payload(ctx.tenant_id, normalized_key, prompt.text, updated_at=prompt.updated_at)}


@api.put("/prompts/{key}")
async def put_prompt_template(key: str, data: PromptTemplateIn, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    normalized_key = str(key or "").strip()
    doc = await _write_prompt_template_doc(ctx.tenant_id, normalized_key, str(data.text or ""))
    prompt = PromptTemplate.from_mongo(doc)
    return {"ok": True, **_prompt_template_payload(ctx.tenant_id, normalized_key, prompt.text, updated_at=prompt.updated_at)}


async def _is_internal_tenant_id(tenant_id: str) -> bool:
    tdoc = await get_store().get_tenant(tenant_id)
    tslug = str((tdoc or {}).get("slug") or "")
    internal_slug = os.environ.get("INTERNAL_WIKI_TENANT_SLUG", "default").strip()
    return bool(tslug and internal_slug and tslug == internal_slug)


async def _ai_visibility_entitlement(ctx) -> dict:
    if can_manage_tenant(ctx.user.role, ctx.tenant_role):
        return {"enabled": True, "trial_expires_at": None, "reason": "global_admin"}
    if await _is_internal_tenant_id(ctx.tenant_id):
        return {"enabled": True, "trial_expires_at": None, "reason": "internal_tenant"}

    sdoc = await _get_tenant_settings_doc(ctx.tenant_id)
    settings = TenantSettings.from_mongo(sdoc)
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
    can_manage = can_manage_tenant(ctx.user.role, ctx.tenant_role)
    return {"ok": True, **ent, "can_manage": can_manage}


@api.post("/super/ai-visibility/grant")
async def super_grant_ai_visibility(
    tenant_id: str = Query(...),
    enabled: bool = Query(True),
    trial_days: int = Query(14, ge=1, le=365),
    user: User = Depends(get_current_user),
):
    if not can_manage_tenant(user.role, "admin"):
        raise HTTPException(403, "Admin only")
    tdoc = await get_store().get_tenant(tenant_id)
    if not tdoc:
        raise HTTPException(404, "Tenant not found")

    sdoc = await _get_tenant_settings_doc(tenant_id)
    settings = TenantSettings.from_mongo(sdoc)
    analysis = dict(settings.analysis or {})
    ent = dict((analysis.get("entitlements") or {}) if isinstance(analysis, dict) else {})
    ent["ai_visibility"] = bool(enabled)
    analysis["entitlements"] = ent
    if enabled:
        analysis["ai_visibility_trial_expires_at"] = (utcnow() + timedelta(days=int(trial_days))).isoformat()
    else:
        analysis.pop("ai_visibility_trial_expires_at", None)

    patch = {"analysis": analysis, "updated_at": utcnow().isoformat()}
    await _write_tenant_settings_patch(tenant_id, patch, reason="ai_visibility_admin_set")
    return {"ok": True}


async def _get_ai_visibility_config_doc(
    tenant_id: str,
    *,
    client_id: Optional[str] = None,
    config_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    bridge = get_store()
    if not bridge.is_enabled_for("ai_visibility"):
        return None
    if str(config_id or "").strip():
        return await bridge.get_ai_visibility_config(tenant_id, str(config_id))
    if str(client_id or "").strip():
        return await bridge.get_ai_visibility_config_for_client(tenant_id, str(client_id))
    return None


async def _list_ai_visibility_configs_docs(tenant_id: str, client_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    bridge = get_store()
    if not bridge.is_enabled_for("ai_visibility"):
        return []
    return await bridge.list_ai_visibility_configs(tenant_id, client_legacy_id=str(client_id), limit=limit)


async def _list_ai_visibility_runs_docs(
    tenant_id: str,
    config_id: str,
    *,
    scan_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    bridge = get_store()
    if not bridge.is_enabled_for("ai_visibility"):
        return []
    return await bridge.list_ai_visibility_runs(tenant_id, str(config_id), scan_id=scan_id, limit=limit)


async def _list_ai_visibility_scans_docs(
    tenant_id: str,
    config_id: str,
    *,
    client_id: Optional[str] = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    bridge = get_store()
    if not bridge.is_enabled_for("ai_visibility"):
        return []
    return await bridge.list_ai_visibility_scans(
        tenant_id,
        str(config_id),
        client_legacy_id=str(client_id) if client_id else None,
        limit=limit,
    )


async def _get_latest_ai_visibility_scan_doc(
    tenant_id: str,
    config_id: str,
    client_id: str,
) -> Optional[dict[str, Any]]:
    bridge = get_store()
    if not bridge.is_enabled_for("ai_visibility"):
        return None
    return await bridge.get_latest_ai_visibility_scan(tenant_id, str(config_id), str(client_id))


async def _list_ai_territory_events_docs(tenant_id: str, client_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    bridge = get_store()
    if not bridge.is_enabled_for("ai_visibility"):
        return []
    return await bridge.list_ai_territory_events(tenant_id, str(client_id), limit=limit)


@api.get("/ai-visibility/configs")
async def list_ai_visibility_configs(
    client_id: str = Query(...),
    ctx=Depends(_require_ai_visibility),
):
    docs = await _list_ai_visibility_configs_docs(ctx.tenant_id, client_id, limit=200)
    client_doc = await _require_client_access(ctx, client_id)
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
    existing = await _get_ai_visibility_config_doc(ctx.tenant_id, client_id=client_id)
    if existing:
        return {"ok": True, "config": AiVisibilityConfig.from_mongo(existing).model_dump()}

    client_doc = await _require_client_access(ctx, client_id)

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
    stored = await ai_territory_intelligence._upsert_ai_visibility_config_doc(ctx.tenant_id, cfg.to_mongo())
    return {
        "ok": True,
        "config": AiVisibilityConfig.from_mongo(stored).model_dump(),
        "prompt_intelligence": {"themes": intel.get("themes") or [], "prompts_total": intel.get("prompts_total") or 0},
    }


@api.patch("/ai-visibility/configs/{config_id}")
async def update_ai_visibility_config(
    config_id: str,
    data: Dict[str, Any] = Body(default_factory=dict),
    ctx=Depends(_require_ai_visibility),
):
    cfg_doc = await _get_ai_visibility_config_doc(ctx.tenant_id, config_id=config_id)
    if not cfg_doc:
        raise HTTPException(404, "Config not found")
    cfg = AiVisibilityConfig.from_mongo(cfg_doc)
    client_doc = await _require_client_access(ctx, cfg.client_id)
    if not isinstance(data, dict):
        raise HTTPException(400, "Invalid payload")

    patch: Dict[str, Any] = {"updated_at": utcnow().isoformat()}

    if not data:
        intel = await ai_visibility.generate_prompt_intelligence(client_doc or {})
        patch["market"] = str(intel.get("market") or "").strip()
        doc = await ai_territory_intelligence._upsert_ai_visibility_config_doc(
            ctx.tenant_id,
            {**dict(cfg_doc or {}), **patch},
        )
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

    doc = await ai_territory_intelligence._upsert_ai_visibility_config_doc(
        ctx.tenant_id,
        {**dict(cfg_doc or {}), **patch},
    )
    return {"ok": True, "config": AiVisibilityConfig.from_mongo(doc).model_dump()}


@api.get("/ai-visibility/configs/{config_id}/runs")
async def list_ai_visibility_runs(
    config_id: str,
    limit: int = Query(100, ge=1, le=500),
    scan_id: Optional[str] = Query(None),
    ctx=Depends(_require_ai_visibility),
):
    cfg_doc = await _get_ai_visibility_config_doc(ctx.tenant_id, config_id=config_id)
    if not cfg_doc:
        raise HTTPException(404, "Config not found")
    await _require_client_access(ctx, str(cfg_doc.get("client_id") or ""))
    docs = await _list_ai_visibility_runs_docs(ctx.tenant_id, config_id, scan_id=scan_id, limit=int(limit))
    return {"ok": True, "runs": [AiVisibilityRun.from_mongo(d).model_dump() for d in (docs or [])]}


@api.get("/ai-visibility/configs/{config_id}/scans")
async def list_ai_visibility_scans(
    config_id: str,
    limit: int = Query(30, ge=1, le=200),
    ctx=Depends(_require_ai_visibility),
):
    cfg_doc = await _get_ai_visibility_config_doc(ctx.tenant_id, config_id=config_id)
    if not cfg_doc:
        raise HTTPException(404, "Config not found")
    await _require_client_access(ctx, str(cfg_doc.get("client_id") or ""))
    docs = await _list_ai_visibility_scans_docs(
        ctx.tenant_id,
        config_id,
        client_id=str(cfg_doc.get("client_id") or ""),
        limit=int(limit),
    )
    return {"ok": True, "scans": [AiVisibilityScan.from_mongo(d).model_dump() for d in (docs or [])]}


@api.post("/ai-visibility/configs/{config_id}/run")
async def run_ai_visibility_scan(config_id: str, ctx=Depends(_require_ai_visibility)):
    cfg_doc = await _get_ai_visibility_config_doc(ctx.tenant_id, config_id=config_id)
    if not cfg_doc:
        raise HTTPException(404, "Config not found")
    cfg = AiVisibilityConfig.from_mongo(cfg_doc)
    if not cfg.enabled:
        raise HTTPException(400, "Config is disabled")

    client_doc = await _require_client_access(ctx, cfg.client_id)

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
                stored_run = await ai_territory_intelligence._create_ai_visibility_run_doc(ctx.tenant_id, run.to_mongo())
                created += 1
                if bool((stored_run or {}).get("hit")):
                    hit_count += 1
                    per_provider[p]["hits"] += 1
                runs_for_metrics.append(AiVisibilityRun.from_mongo(stored_run).model_dump())
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
    stored_scan = await ai_territory_intelligence._create_ai_visibility_scan_doc(ctx.tenant_id, scan.to_mongo())
    await ai_territory_intelligence._upsert_ai_visibility_config_doc(
        ctx.tenant_id,
        {**dict(cfg_doc or {}), "market": market, "updated_at": utcnow().isoformat()},
    )

    return {
        "ok": True,
        "scan_id": scan_id,
        "scan": AiVisibilityScan.from_mongo(stored_scan).model_dump(),
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
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    sdoc = await _get_tenant_settings_doc(ctx.tenant_id)
    settings = TenantSettings.from_mongo(sdoc)
    return {"ok": True, **_ai_territory_settings(settings)}


@api.put("/ai-territory/settings")
async def put_ai_territory_settings(
    scan_frequency_hours: int = Query(24, ge=1, le=168),
    max_prompts: int = Query(60, ge=10, le=200),
    ctx=Depends(get_current_context),
):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    sdoc = await _get_tenant_settings_doc(ctx.tenant_id)
    settings = TenantSettings.from_mongo(sdoc)
    analysis = dict(settings.analysis or {}) if isinstance(settings.analysis, dict) else {}
    analysis["ai_territory_scan_frequency_hours"] = int(scan_frequency_hours)
    analysis["ai_territory_max_prompts"] = int(max_prompts)
    await _write_tenant_settings_patch(
        ctx.tenant_id,
        {"analysis": analysis, "updated_at": utcnow().isoformat()},
        reason="ai_territory_settings_put",
    )
    return {"ok": True}


@api.get("/ai-territory/{client_id}/latest")
async def ai_territory_latest(client_id: str, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, client_id)
    cfg = await _get_ai_visibility_config_doc(ctx.tenant_id, client_id=client_id)
    if not cfg:
        return {"ok": True, "scan": None, "events": []}
    scan = await _get_latest_ai_visibility_scan_doc(ctx.tenant_id, str(cfg.get("_id") or ""), client_id)
    events = await _list_ai_territory_events_docs(ctx.tenant_id, client_id, limit=50)
    return {"ok": True, "scan": AiVisibilityScan.from_mongo(scan).model_dump() if scan else None, "events": events}


@api.get("/ai-territory/{client_id}/history")
async def ai_territory_history(client_id: str, limit: int = 30, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, client_id)
    limit = max(1, min(int(limit or 30), 200))
    cfg = await _get_ai_visibility_config_doc(ctx.tenant_id, client_id=client_id)
    if not cfg:
        return {"ok": True, "scans": []}
    docs = await _list_ai_visibility_scans_docs(
        ctx.tenant_id,
        str(cfg.get("_id") or ""),
        client_id=client_id,
        limit=limit,
    )
    return {"ok": True, "scans": [AiVisibilityScan.from_mongo(d).model_dump() for d in (docs or [])]}


@api.post("/ai-territory/{client_id}/run")
async def ai_territory_run_now(client_id: str, ctx=Depends(get_current_context)):
    c_doc = await _require_client_access(ctx, client_id)
    sdoc = await _get_tenant_settings_doc(ctx.tenant_id)
    settings = TenantSettings.from_mongo(sdoc)
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
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    bridge = get_store()
    tdoc = await bridge.get_tenant(ctx.tenant_id)
    slug = (tdoc or {}).get("slug") or ""
    base_domain = os.environ.get("BASE_DOMAIN", "mapranking.com").strip().lower()
    default_subdomain = f"{slug}.{base_domain}" if slug and base_domain else ""
    bridge_docs = await bridge.list_tenant_domains(ctx.tenant_id, limit=200)
    docs = bridge_docs
    custom_domains = sorted({str(d.get("domain") or "").strip().lower() for d in (docs or []) if d.get("domain")})
    return {"ok": True, "default_subdomain": default_subdomain, "custom_domains": custom_domains}


@api.post("/white-label/domains")
async def add_white_label_domain(domain: str = Query(...), ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    d = str(domain or "").strip().lower()
    if not d or "." not in d:
        raise HTTPException(400, "Invalid domain")
    if ":" in d or "/" in d:
        raise HTTPException(400, "Invalid domain")
    bridge = get_store()
    existing_bridge = await bridge.get_tenant_domain(d)
    if existing_bridge and str(existing_bridge.get("tenant_id")) != str(ctx.tenant_id):
        raise HTTPException(409, "Domain already in use by another tenant")
    if bridge.is_enabled_for("domains"):
        bridged_doc = await bridge.upsert_tenant_domain(ctx.tenant_id, d)
        if not bridged_doc:
            raise HTTPException(503, "Unable to store domain in Supabase")
    return {"ok": True}


@api.delete("/white-label/domains")
async def delete_white_label_domain(domain: str = Query(...), ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    d = str(domain or "").strip().lower()
    if not d:
        raise HTTPException(400, "Invalid domain")
    bridge = get_store()
    if bridge.is_enabled_for("domains"):
        deleted = await bridge.delete_tenant_domain(ctx.tenant_id, d)
        if not deleted:
            raise HTTPException(503, "Unable to delete domain from Supabase")
    return {"ok": True}


@api.get("/white-label/uploads")
async def list_white_label_uploads(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    bridge = get_store()
    if bridge.is_enabled_for("tenant_files"):
        docs = await bridge.list_tenant_files(ctx.tenant_id, limit=200)
    else:
        docs = []
    return [{"id": d.get("_id"), "filename": d.get("filename"), "mime_type": d.get("mime_type"), "size_bytes": d.get("size_bytes"), "created_at": d.get("created_at"), "extracted_chars": d.get("extracted_chars", 0)} for d in docs]


@api.post("/white-label/uploads")
async def upload_white_label_doc(
    file: UploadFile = File(...),
    purpose: str = Form("documentation"),
    ctx=Depends(get_current_context),
):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
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
    bridge = get_store()
    if bridge.is_enabled_for("tenant_files"):
        await bridge.create_tenant_file(ctx.tenant_id, doc)
    else:
        pass
    return {"ok": True, "file": {"id": file_id, "filename": file.filename, "mime_type": file.content_type, "size_bytes": len(raw), "extracted_chars": len(extracted_text or "")}}


@api.post("/white-label/analyze")
async def analyze_white_label(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")

    bridge = get_store()
    if bridge.is_enabled_for("tenant_files"):
        files = await bridge.list_tenant_files(ctx.tenant_id, limit=50)
    else:
        files = []
    corpus = "\n\n".join([(f.get("extracted_text") or "") for f in files if (f.get("extracted_text") or "").strip()])[:80_000]
    if not corpus.strip():
        raise HTTPException(400, "No extractable text found in uploads")

    sdoc = await _get_tenant_settings_doc(ctx.tenant_id)
    settings = TenantSettings.from_mongo(sdoc)
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
    result = await _write_tenant_settings_patch(ctx.tenant_id, next_doc, reason="white_label_ai_generate")
    doc2 = result["doc"]
    return {"ok": True, "settings": TenantSettings.from_mongo(doc2).model_dump()}


# ===================== CLIENTS =====================
@api.get("/clients")
async def list_clients(ctx=Depends(get_current_context)):
    docs = await sb_list_clients(ctx, limit=1000)
    return [Client.from_mongo(d).model_dump() for d in docs]


@api.post("/clients")
async def create_client(data: ClientIn, ctx=Depends(get_current_context)):
    am_name = None
    bridge = get_store()
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        data.account_manager_id = ctx.user.id
    if data.account_manager_id:
        profile = await bridge.get_user_profile(str(data.account_manager_id))
        if profile:
            am_name = profile.get("name")
    c = Client(tenant_id=ctx.tenant_id, **data.model_dump(), account_manager_name=am_name)
    stored = await sb_upsert_client(ctx, c.to_mongo())
    return Client.from_mongo(stored).model_dump()


@api.get("/clients/{client_id}")
async def get_client(client_id: str, ctx=Depends(get_current_context)):
    doc = await _require_client_access(ctx, client_id)
    return Client.from_mongo(doc).model_dump()


@api.get("/clients/{client_id}/suggestions")
async def get_client_suggestions(client_id: str, ctx=Depends(get_current_context)):
    doc = await _require_client_access(ctx, client_id)
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
    c_doc = await _require_client_access(ctx, client_id)
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
    next_doc = {**dict(c_doc or {}), **patch}
    doc2 = await sb_upsert_client(ctx, next_doc)
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
    existing = await _require_client_access(ctx, client_id)
    patch["updated_at"] = utcnow().isoformat()
    next_doc = {**dict(existing or {}), **dict(patch or {})}
    doc = await sb_upsert_client(ctx, next_doc)
    return Client.from_mongo(doc).model_dump()


@api.delete("/clients/{client_id}")
async def delete_client(client_id: str, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    await _require_client_access(ctx, client_id)
    await sb_soft_delete_client(ctx, client_id)
    await sb_soft_delete_meetings_for_client(ctx, client_id)
    await sb_soft_delete_action_items_for_client(ctx, client_id)
    bridge = get_store()
    if bridge.is_enabled_for("content_captures"):
        await bridge.soft_delete_content_captures_for_client(ctx.tenant_id, client_id)
    if bridge.is_enabled_for("tickets"):
        await bridge.soft_delete_tickets_for_client(ctx.tenant_id, client_id)
    if bridge.is_enabled_for("qa_scorecards"):
        await bridge.soft_delete_qa_scorecards_for_client(ctx.tenant_id, client_id)
    return {"ok": True}


@api.get("/clients/{client_id}/bindings")
async def list_client_bindings(client_id: str, ctx=Depends(get_current_context)):
    bridge = get_store()
    if bridge.is_enabled_for("client_bindings"):
        docs = await bridge.list_client_bindings(ctx.tenant_id, client_id, limit=100)
        return [ClientIntegrationBinding.from_mongo(d).model_dump() for d in docs]
    return []


@api.get("/admin/runtime-bridge/smoke")
async def runtime_bridge_smoke(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    bridge = get_store()
    return {
        "ok": True,
        "bridge_ready": bridge.service_configured(),
        "config": get_runtime_bridge_env_summary(),
        "smoke": await bridge.smoke_check(ctx.tenant_id),
        "store": "supabase",
        "mongo_fallback_preserved": False,
        "auth_cutover": "disabled",
    }


@api.put("/clients/{client_id}/bindings/{platform}")
async def upsert_client_binding(
    client_id: str,
    platform: str,
    data: ClientIntegrationBindingIn,
    ctx=Depends(get_current_context),
):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    if platform not in INTEGRATIONS:
        raise HTTPException(404, "Unknown integration")
    bridge = get_store()
    update = {
        "enabled": bool(data.enabled),
        "external_ids": data.external_ids or {},
        "config": data.config or {},
        "tenant_id": ctx.tenant_id,
        "updated_at": utcnow().isoformat(),
    }
    binding = ClientIntegrationBinding(client_id=client_id, platform=platform, **update)
    if not bridge.is_enabled_for("client_bindings"):
        raise HTTPException(503, "Client bindings runtime is not enabled")
    stored = await bridge.upsert_client_binding(ctx.tenant_id, client_id, binding.to_mongo())
    return ClientIntegrationBinding.from_mongo(stored or binding.to_mongo()).model_dump()


@api.delete("/clients/{client_id}/bindings/{platform}")
async def delete_client_binding(client_id: str, platform: str, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    bridge = get_store()
    if not bridge.is_enabled_for("client_bindings"):
        raise HTTPException(503, "Client bindings runtime is not enabled")
    await bridge.soft_delete_client_binding(ctx.tenant_id, client_id, platform)
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


@api.post("/import/gohighlevel/clients")
async def import_clients_from_gohighlevel(data: ImportGhlClientsIn, ctx=Depends(get_current_context)):
    raise HTTPException(410, "GoHighLevel contact import has been replaced by ClickUp Client Assignment Sync.")


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
    if user_id and can_manage_tenant(ctx.user.role, ctx.tenant_role):
        target_user_id = user_id
    await _dbg_emit("H1", "status:begin", {"tenant_id": ctx.tenant_id, "user_id": str(target_user_id)})
    bridge = get_store()
    doc = await bridge.get_clickup_client_sync_state(ctx.tenant_id, str(target_user_id)) if bridge.is_enabled_for("clickup_sync") else None
    state = doc or {"tenant_id": ctx.tenant_id, "user_id": str(target_user_id), "last_success_at": None, "last_error": None}
    await _dbg_emit("H1", "status:ok", {"state": state})
    last_run_id = str((state or {}).get("last_run_id") or "").strip()
    last_run = None
    if last_run_id:
        last_run = await bridge.get_clickup_client_sync_log(ctx.tenant_id, str(target_user_id), last_run_id) if bridge.is_enabled_for("clickup_sync") else None
        if last_run:
            last_run = {k: v for k, v in last_run.items() if k not in ("tenant_id", "user_id")}
    return {"ok": True, "state": state, "last_run": last_run}


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
            await clickup_client_sync._save_clickup_integration_metadata(
                ctx.tenant_id,
                {
                    "last_synced_at": utcnow().isoformat(),
                    "last_error": None,
                    "status": "connected",
                },
            )
        else:
            await clickup_client_sync._save_clickup_integration_metadata(
                ctx.tenant_id,
                {
                    "last_error": res.get("error"),
                    "status": "error",
                },
            )
        return res

    asyncio.create_task(_run())
    return {"ok": True, "queued": True}


@api.post("/import/clickup/clients/sync/all")
async def clickup_client_sync_all(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    return await clickup_client_sync.sync_assigned_clients_for_all_users(tenant_id=ctx.tenant_id)


@api.get("/v1/integrations/clickup/status")
async def clickup_status_v1(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    config = await ownership_sync._get_clickup_config(ctx.tenant_id)
    summary = await ownership_sync.get_ownership_summary(ctx.tenant_id)
    return {
        "ok": True,
        **ownership_sync.get_clickup_status_payload(config),
        "ownership_summary": summary,
    }


@api.post("/v1/integrations/clickup/ping")
async def clickup_ping_v1(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    result = await ownership_sync.ping_clickup(ctx.tenant_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("detail") or "ClickUp ping failed")
    return result


@api.get("/v1/ownership/summary")
async def ownership_summary_v1(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    return {"ok": True, **(await ownership_sync.get_ownership_summary(ctx.tenant_id))}


@api.get("/v1/ownership/exceptions")
async def ownership_exceptions_v1(limit: int = Query(default=50), ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    capped_limit = max(1, min(int(limit or 50), 50))
    rows = await ownership_sync.list_open_exceptions(ctx.tenant_id, limit=capped_limit)
    return {"ok": True, "items": rows, "count": len(rows)}


@api.post("/v1/ownership/sync")
async def ownership_sync_v1(ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    result = await ownership_sync.run_clickup_ownership_sync(ctx.tenant_id, ctx.user.id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("detail") or "Ownership sync failed")
    return result


@api.post("/v1/integrations/clickup/ownership-sync")
async def ownership_sync_alias_v1(ctx=Depends(get_current_context)):
    return await ownership_sync_v1(ctx)


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
    binding = await connectors.get_client_binding(ctx.tenant_id, str(client.get("id") or ""), "gohighlevel")
    location_id = ((binding or {}).get("external_ids") or {}).get("location_id") or ((binding or {}).get("config") or {}).get("location_id")
    contact_id = ((binding or {}).get("external_ids") or {}).get("contact_id") or ((binding or {}).get("config") or {}).get("contact_id")
    if not location_id or not contact_id:
        raise HTTPException(400, "Client is missing GoHighLevel mapping (location_id/contact_id). Import from GHL or set mapping first.")

    convs = await connectors.list_gohighlevel_conversations(ctx.tenant_id, str(location_id), str(contact_id), limit=100)
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
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    doc = await _require_client_access(ctx, client_id)
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
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    doc = await _require_client_access(ctx, client_id)
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
    if client_id:
        await _require_client_access(ctx, client_id)
    docs = await sb_list_meetings(ctx, client_id=client_id, limit=500)
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
    stored = await sb_upsert_meeting(ctx, m.to_mongo())
    return Meeting.from_mongo(stored).model_dump()


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
    doc = await _require_meeting_access(ctx, meeting_id)
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
    doc = await _require_meeting_access(ctx, meeting_id)
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
    doc0 = await _require_meeting_access(ctx, meeting_id)
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
    doc = await _upsert_meeting_doc(ctx.tenant_id, {**dict(doc0 or {}), **update})
    if updated_feedback:
        meeting = Meeting.from_mongo(doc)
        m_docs = [
            d for d in await _list_meeting_docs(ctx.tenant_id, client_id=meeting.client_id, limit=2000)
            if isinstance((d or {}).get("feedback"), dict) and (d or {}).get("feedback")
        ]
        m_docs.sort(key=lambda d: str((d or {}).get("updated_at") or ""), reverse=True)
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
        client_doc = await sb_get_client_for_tenant(ctx.tenant_id, meeting.client_id)
        if client_doc:
            await _upsert_client_doc(
                ctx.tenant_id,
                {
                    **dict(client_doc),
                    "feedback_last_submitted_at": (feedback_payload or {}).get("submitted_at"),
                    "feedback_alert": alert,
                    "feedback_alert_level": level,
                    "feedback_alert_reason": reason,
                    "feedback_rolling_avg": rolling,
                    "updated_at": utcnow().isoformat(),
                },
            )
    if updated_health:
        meeting = Meeting.from_mongo(doc)
        m_docs = [
            d for d in await _list_meeting_docs(ctx.tenant_id, client_id=meeting.client_id, limit=2000)
            if (d or {}).get("nps_score") is not None or str((d or {}).get("sentiment_classification") or "").strip()
        ]
        m_docs.sort(key=lambda d: str((d or {}).get("updated_at") or ""), reverse=True)
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
        client_doc = await sb_get_client_for_tenant(ctx.tenant_id, meeting.client_id)
        if client_doc:
            await _upsert_client_doc(
                ctx.tenant_id,
                {
                    **dict(client_doc),
                    "health_last_submitted_at": utcnow().isoformat(),
                    "health_alert": alert,
                    "health_alert_level": level,
                    "health_alert_reason": reason,
                    "churn_risk_score": churn_score,
                    "churn_risk_indicators": indicators,
                    "nps_rolling_avg": roll.get("nps_avg"),
                    "sentiment_rolling": roll.get("sentiment_counts") or {},
                    "updated_at": utcnow().isoformat(),
                },
            )
    return Meeting.from_mongo(doc).model_dump()


@api.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str, ctx=Depends(get_current_context)):
    await _require_meeting_access(ctx, meeting_id)
    await sb_soft_delete_meeting(ctx, meeting_id)
    await sb_soft_delete_action_items_for_meeting(ctx, meeting_id)
    bridge = get_store()
    if bridge.is_enabled_for("content_captures"):
        await bridge.soft_delete_content_captures_for_meeting(ctx.tenant_id, meeting_id)
    if bridge.is_enabled_for("tickets"):
        await bridge.soft_delete_tickets_for_meeting(ctx.tenant_id, meeting_id)
    if bridge.is_enabled_for("qa_scorecards"):
        await bridge.soft_delete_qa_scorecards_for_meeting(ctx.tenant_id, meeting_id)
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
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    c_doc = await sb_get_client_for_tenant(ctx.tenant_id, meeting.client_id)
    client = Client.from_mongo(c_doc) if c_doc else None
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
    onboarding_support = await monthly_touch.build_first_90_day_brief_support(ctx.tenant_id, client_d, kpi)
    brief_prompt = await _get_prompt_template_text(ctx.tenant_id, "brief_prompt")
    retention_prompt = await _get_prompt_template_text(ctx.tenant_id, "retention_prompt")
    try:
        brief = await ai.generate_meeting_brief(
            client=client_d,
            kpi_snapshot=kpi_for_ai,
            extra_context=monthly_touch.merge_brief_extra_context(data.extra_context, (onboarding_support or {}).get("extra_context")),
            model_key=data.model or ai.DEFAULT_MODEL,
            session_id=f"brief-{meeting_id}",
            system_prompt_override=_prompt_instruction_bundle(brief_prompt, retention_prompt),
        )
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
    brief = monthly_touch.apply_first_90_day_brief_support(brief, onboarding_support)
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
    doc = await _upsert_meeting_doc(ctx.tenant_id, {**meeting.model_dump(), **update})
    await monthly_touch.upsert_review_snapshot_from_kpi(ctx.tenant_id, meeting.client_id, kpi)
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
    doc = await _upsert_meeting_doc(ctx.tenant_id, {**meeting.model_dump(), **patch})
    return Meeting.from_mongo(doc).model_dump()


@api.post("/meetings/{meeting_id}/analyze-transcript")
async def analyze_transcript(meeting_id: str, data: AnalyzeTranscriptIn, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    bridge = get_store()
    c_doc = await sb_get_client_for_tenant(ctx.tenant_id, meeting.client_id)
    client = Client.from_mongo(c_doc) if c_doc else None

    pdoc = await _get_prompt_template_doc(ctx.tenant_id, "monthly_touch_analysis")
    instructions = (PromptTemplate.from_mongo(pdoc).text if pdoc else _default_prompt_text("monthly_touch_analysis"))
    workflow_prompt = _prompt_instruction_bundle(
        await _get_prompt_template_text(ctx.tenant_id, "ticket_prompt"),
        await _get_prompt_template_text(ctx.tenant_id, "email_prompt"),
        await _get_prompt_template_text(ctx.tenant_id, "coaching_prompt"),
        await _get_prompt_template_text(ctx.tenant_id, "retention_prompt"),
    )

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
            system_prompt_override=workflow_prompt,
        )
    )
    analysis_results, automation_draft = await asyncio.gather(asyncio.gather(*analysis_tasks), automation_task)
    analysis_by_model = {models[i]: analysis_results[i] for i in range(len(models))}
    analysis = analysis_results[0] if analysis_results else {}
    await _upsert_meeting_doc(
        ctx.tenant_id,
        {
            **meeting.model_dump(),
            "transcript": data.transcript,
            "transcript_analyzed_at": utcnow().isoformat(),
            "sentiment": analysis.get("sentiment", "neutral"),
            "sentiment_summary": analysis.get("sentiment_summary", ""),
            "transcript_analysis": analysis,
            "transcript_analysis_by_model": analysis_by_model,
            "automation_draft": automation_draft,
            "automation_draft_generated_at": utcnow().isoformat(),
            "updated_at": utcnow().isoformat(),
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
        stored = await sb_upsert_action_item(ctx, item.to_mongo())
        if stored:
            item = ActionItem.from_mongo(stored)
        created_actions.append(item.model_dump())
    # create content captures
    created_content: List[dict] = []
    for co in analysis.get("content_opportunities", []) or []:
        capture_type = str(co.get("type", "quote") or "quote").strip() or "quote"
        route_to_marketing = capture_type in {"testimonial_video", "testimonial_written", "quote", "case_study_lead", "clip"}
        capture_notes = str(co.get("why_strong") or "").strip()
        if route_to_marketing:
            capture_notes = (capture_notes + "\n\nAUTO-ROUTING: Marketing follow-up recommended. Notify Luisa and attach transcript context for review.").strip()
        cc = ContentCapture(
            tenant_id=ctx.tenant_id,
            meeting_id=meeting_id,
            client_id=meeting.client_id,
            type=capture_type,
            content=co.get("content", ""),
            notes=capture_notes,
            received=True,
            requested=True,
            routed_to_marketing=route_to_marketing,
        )
        if not bridge.is_enabled_for("content_captures"):
            raise HTTPException(503, "Content captures runtime is not enabled")
        stored = await bridge.upsert_content_capture(ctx.tenant_id, cc.to_mongo())
        saved_capture = ContentCapture.model_validate(stored or cc.model_dump())
        created_content.append(saved_capture.model_dump())
        if route_to_marketing:
            follow_up_item = ActionItem(
                tenant_id=ctx.tenant_id,
                meeting_id=meeting_id,
                client_id=meeting.client_id,
                title=f"Marketing follow-up: {capture_type.replace('_', ' ')}",
                description=(
                    f"Review captured content for {meeting.client_name or 'client'} and route to Luisa / marketing.\n\n"
                    f"Captured content: {saved_capture.content}\n\n"
                    f"Context: {capture_notes or 'Marketing-worthy client moment identified during transcript analysis.'}"
                ).strip(),
                owner=meeting.account_manager_name or "Marketing",
                owner_type="agency",
                priority="medium",
            )
            stored_task = await sb_upsert_action_item(ctx, follow_up_item.to_mongo())
            created_actions.append(ActionItem.from_mongo(stored_task or follow_up_item.to_mongo()).model_dump())
    # update client health & sentiment
    if client:
        new_health = analysis.get("health_score_suggestion")
        client_update = {"sentiment": analysis.get("sentiment", "neutral")}
        if isinstance(new_health, (int, float)):
            client_update["health_score"] = int(new_health)
            client_update["churn_risk"] = "high" if new_health < 50 else ("medium" if new_health < 70 else "low")
        await _upsert_client_doc(ctx.tenant_id, {**client.model_dump(), **client_update, "updated_at": utcnow().isoformat()})

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
    c_doc = await sb_get_client_for_tenant(ctx.tenant_id, meeting.client_id)
    client = Client.from_mongo(c_doc) if c_doc else None
    if client and _is_ads_client_services(client.services):
        fb = meeting.model_dump().get("feedback") or {}
        if not isinstance(fb, dict):
            fb = {}
        required = ("lead_quality", "campaign_quality", "satisfaction", "results")
        ok = all((k in fb and isinstance(fb.get(k), int) and 1 <= int(fb.get(k)) <= 5) for k in required)
        if not ok:
            raise HTTPException(400, "Client feedback (Lead Quality, Campaign Quality, Satisfaction, Results) is required for Ads clients before completing the meeting.")
    actions = await _list_action_item_docs(ctx.tenant_id, meeting_id=meeting_id, limit=100)
    actions_p = [ActionItem.from_mongo(a).model_dump() for a in actions]
    email_prompt = await _get_prompt_template_text(ctx.tenant_id, "email_prompt")
    retention_prompt = await _get_prompt_template_text(ctx.tenant_id, "retention_prompt")
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
            system_prompt_override=_prompt_instruction_bundle(email_prompt, retention_prompt),
        )
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
    await _upsert_meeting_doc(
        ctx.tenant_id,
        {
            **meeting.model_dump(),
            "recap_html": recap["html"],
            "recap_email": recap["plain"],
            "status": "completed",
            "updated_at": utcnow().isoformat(),
        },
    )
    asyncio.create_task(_bg_publish_clickup_summary(ctx.tenant_id, meeting_id))
    return recap


@api.get("/feedback/{client_id}/trend")
async def feedback_trend(client_id: str, limit: int = 24, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, client_id)
    limit = max(1, min(int(limit or 24), 60))
    m_docs = [
        d for d in await _list_meeting_docs(ctx.tenant_id, client_id=client_id, limit=2000)
        if isinstance((d or {}).get("feedback"), dict) and (d or {}).get("feedback")
    ]
    m_docs.sort(key=lambda d: str((d or {}).get("updated_at") or ""), reverse=True)
    m_docs = m_docs[:limit]
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
    m_docs = [
        d for d in await _list_meeting_docs(ctx.tenant_id, client_id=client_id, limit=2000)
        if (d or {}).get("nps_score") is not None or str((d or {}).get("sentiment_classification") or "").strip()
    ]
    m_docs.sort(key=lambda d: str((d or {}).get("updated_at") or ""), reverse=True)
    m_docs = m_docs[:limit]
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
    if client_id:
        await _require_client_access(ctx, client_id)
    docs = [
        d for d in await _list_meeting_docs(ctx.tenant_id, client_id=client_id or None, limit=5000)
        if (d or {}).get("wins_library")
        and start_ts <= str((d or {}).get("brief_generated_at") or "") <= end_ts
    ]
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        docs = [d for d in docs if str((d or {}).get("account_manager_id") or "") == str(ctx.user.id)]
    elif account_manager_id:
        docs = [d for d in docs if str((d or {}).get("account_manager_id") or "") == str(account_manager_id)]
    docs.sort(key=lambda d: str((d or {}).get("brief_generated_at") or ""), reverse=True)
    docs = docs[:limit]
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
    if client_id:
        await _require_client_access(ctx, client_id)
    docs = [
        d for d in await _list_meeting_docs(ctx.tenant_id, client_id=client_id or None, limit=5000)
        if (d or {}).get("issues_library")
        and start_ts <= str((d or {}).get("brief_generated_at") or "") <= end_ts
    ]
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        docs = [d for d in docs if str((d or {}).get("account_manager_id") or "") == str(ctx.user.id)]
    elif account_manager_id:
        docs = [d for d in docs if str((d or {}).get("account_manager_id") or "") == str(account_manager_id)]
    docs.sort(key=lambda d: str((d or {}).get("brief_generated_at") or ""), reverse=True)
    docs = docs[:limit]
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
    c_doc = await sb_get_client_for_tenant(ctx.tenant_id, meeting.client_id)
    client = Client.from_mongo(c_doc) if c_doc else None
    workflow_prompt = _prompt_instruction_bundle(
        await _get_prompt_template_text(ctx.tenant_id, "ticket_prompt"),
        await _get_prompt_template_text(ctx.tenant_id, "email_prompt"),
        await _get_prompt_template_text(ctx.tenant_id, "coaching_prompt"),
        await _get_prompt_template_text(ctx.tenant_id, "retention_prompt"),
    )
    try:
        draft = await ai.generate_meeting_workflow(
            client_name=client.name if client else (meeting.client_name or ""),
            company=client.company if client else "",
            title=meeting.title,
            transcript=meeting.transcript or "",
            model_key=ai.DEFAULT_MODEL,
            session_id=f"automation-{meeting_id}",
            system_prompt_override=workflow_prompt,
        )
    except ai.AIProviderError as e:
        raise HTTPException(400, str(e))
    await _upsert_meeting_doc(
        ctx.tenant_id,
        {**meeting.model_dump(), "automation_draft": draft, "automation_draft_generated_at": utcnow().isoformat(), "updated_at": utcnow().isoformat()},
    )
    return {"ok": True, "draft": draft}


@api.post("/meetings/{meeting_id}/automation/approve")
async def approve_meeting_automation(meeting_id: str, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    m_doc = await _require_meeting_access(ctx, meeting_id)
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
        stored = await sb_upsert_action_item(ctx, item.to_mongo())
        if stored:
            item = ActionItem.from_mongo(stored)
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
        bridge = get_store()
        if not bridge.is_enabled_for("tickets"):
            raise HTTPException(503, "Tickets runtime is not enabled")
        stored = await bridge.upsert_ticket(ctx.tenant_id, ticket.to_mongo())
        if stored:
            ticket = Ticket.model_validate(stored)
        created_tickets.append(ticket.model_dump())

    bridge = get_store()
    meeting_patch = {**meeting.model_dump(), "automation_approved_at": utcnow().isoformat(), "updated_at": utcnow().isoformat()}
    await _upsert_meeting_doc(ctx.tenant_id, meeting_patch)
    asyncio.create_task(_bg_publish_clickup_tickets(ctx.tenant_id, meeting_id))
    asyncio.create_task(_bg_send_client_recap_email(ctx.tenant_id, meeting_id, meeting.account_manager_id or ctx.user.id))
    asyncio.create_task(_bg_publish_clickup_summary(ctx.tenant_id, meeting_id))
    return {"ok": True, "created_action_items": created_actions, "created_tickets": created_tickets}


@api.get("/meetings/{meeting_id}/qa")
async def get_meeting_qa(meeting_id: str, ctx=Depends(get_current_context)):
    await _require_meeting_access(ctx, meeting_id)
    bridge = get_store()
    doc = await bridge.get_latest_qa_scorecard(ctx.tenant_id, meeting_id) if bridge.is_enabled_for("qa_scorecards") else None
    if not doc:
        return {"ok": True, "scorecard": None}
    return {
        "ok": True,
        "scorecard": (
            QAScorecard.model_validate(doc).model_dump()
            if bridge.is_enabled_for("qa_scorecards")
            else QAScorecard.from_mongo(doc).model_dump()
        ),
    }


@api.post("/meetings/{meeting_id}/qa/score")
async def score_meeting(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    if not (meeting.transcript or "").strip():
        raise HTTPException(400, "Missing transcript")
    bridge = get_store()
    c_doc = await sb_get_client_for_tenant(ctx.tenant_id, meeting.client_id)
    client = Client.from_mongo(c_doc) if c_doc else None
    qa_prompt = await _get_prompt_template_text(ctx.tenant_id, "qa_prompt")
    coaching_prompt = await _get_prompt_template_text(ctx.tenant_id, "coaching_prompt")
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
            system_prompt_override=_prompt_instruction_bundle(qa_prompt, coaching_prompt),
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
    if bridge.is_enabled_for("qa_scorecards"):
        stored = await bridge.create_qa_scorecard(ctx.tenant_id, card.to_mongo())
        meeting_patch = {**meeting.model_dump(), "meeting_score": card.total_score, "updated_at": utcnow().isoformat()}
        if bridge.is_enabled_for("meetings"):
            await bridge.upsert_meeting(ctx.tenant_id, meeting_patch)
        return {"ok": True, "scorecard": QAScorecard.model_validate(stored or card.model_dump()).model_dump()}
    raise HTTPException(503, "QA runtime is not enabled")


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
    allowed = await _allowed_client_ids(ctx)
    if client_id:
        await _require_client_access(ctx, client_id)
    docs = await _list_action_item_docs(
        ctx.tenant_id,
        client_id=client_id,
        meeting_id=meeting_id,
        status=status,
        owner_type=owner_type,
        due_before=due_before,
        due_after=due_after,
        limit=1000,
    )
    if allowed is not None:
        docs = [doc for doc in docs if str((doc or {}).get("client_id") or "") in set(allowed)]
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

    allowed = await _allowed_client_ids(ctx)
    if client_id:
        await _require_client_access(ctx, client_id)
    active_statuses = {"open", "in_progress", "blocked"}
    docs = await _list_action_item_docs(ctx.tenant_id, client_id=client_id, meeting_id=meeting_id, limit=2000)
    docs = [doc for doc in docs if str((doc or {}).get("status") or "") in active_statuses]
    docs.sort(key=lambda item: (str(item.get("due_date") or "9999-12-31"), str(item.get("created_at") or "")), reverse=False)
    if allowed is not None:
        allowed_set = set(allowed)
        docs = [doc for doc in docs if str((doc or {}).get("client_id") or "") in allowed_set]
    items = [ActionItem.from_mongo(d).model_dump() for d in docs]

    client_ids = {it.get("client_id") for it in items if it.get("client_id")}
    meeting_ids = {it.get("meeting_id") for it in items if it.get("meeting_id")}

    clients_docs = [doc for doc in await sb_list_clients_for_tenant(ctx.tenant_id, limit=5000) if str((doc or {}).get("_id") or "") in client_ids]
    meetings_docs = [doc for doc in await sb_list_meetings_for_tenant(ctx.tenant_id, limit=5000) if str((doc or {}).get("_id") or "") in meeting_ids]

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
    doc = await sb_get_action_item(ctx, item_id)
    if not doc:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc.get("client_id") or ""))
    item = ActionItem.from_mongo(doc)
    doc2 = await sb_upsert_action_item(
        ctx,
        {
            **item.model_dump(),
            "last_reminded_at": now,
            "reminder_count": int((item.reminder_count or 0) + 1),
            "updated_at": now,
        },
    )
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
    bridge = get_store()
    doc = await bridge.get_client_review_goal(ctx.tenant_id, client_id)
    if doc:
        return doc
    goal = ClientReviewGoal(tenant_id=ctx.tenant_id, client_id=client_id, monthly_goal=10, updated_at=utcnow().isoformat())
    payload = goal.to_mongo()
    if payload.get("_id"):
        payload["id"] = payload.pop("_id")
    bridged = await bridge.upsert_client_review_goal(ctx.tenant_id, client_id, payload)
    return bridged or goal.model_dump()


@api.put("/reviews/{client_id}/goal")
async def put_review_goal(client_id: str, payload: ClientReviewGoalIn, ctx=Depends(get_current_context)):
    monthly_goal = max(0, _safe_int(payload.monthly_goal, 10))
    now = utcnow().isoformat()
    bridge = get_store()
    doc = await bridge.upsert_client_review_goal(
        ctx.tenant_id,
        client_id,
        {
            "tenant_id": ctx.tenant_id,
            "client_id": client_id,
            "monthly_goal": monthly_goal,
            "updated_at": now,
        },
    )
    return doc or {"tenant_id": ctx.tenant_id, "client_id": client_id, "monthly_goal": monthly_goal, "updated_at": now}


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
    bridge = get_store()
    ev_payload = ev.to_mongo()
    if ev_payload.get("_id"):
        ev_payload["id"] = ev_payload.pop("_id")
    doc = await bridge.create_review_event(ctx.tenant_id, client_id, ev_payload)
    return doc or ev.model_dump()


@api.get("/reviews/{client_id}/events")
async def list_review_events(client_id: str, limit: int = 200, ctx=Depends(get_current_context)):
    limit = max(1, min(int(limit or 200), 1000))
    return await get_store().list_review_events(ctx.tenant_id, client_id=client_id, limit=limit)


@api.get("/reviews/{client_id}/stats")
async def review_stats(client_id: str, months: int = 12, ctx=Depends(get_current_context)):
    months_list = _last_n_months(months)
    month_set = set(months_list)
    bridge = get_store()
    events = await bridge.list_review_events(ctx.tenant_id, client_id=client_id, limit=5000)
    requested_by_month: dict[str, int] = {m: 0 for m in months_list}
    for d in events:
        ev = ReviewEvent.model_validate(d) if d else None
        if not ev:
            continue
        mk = _month_key(ev.occurred_on)
        if mk not in month_set:
            continue
        if ev.kind == "requested":
            requested_by_month[mk] = requested_by_month.get(mk, 0) + int(ev.count or 0)
    snaps = await bridge.list_review_monthly_snapshots(ctx.tenant_id, client_id=client_id, limit=1000)
    received_by_month: dict[str, int] = {m: 0 for m in months_list}
    rating_by_month: dict[str, Optional[float]] = {m: None for m in months_list}
    for d in snaps:
        s = ReviewMonthlySnapshot.model_validate(d) if d else None
        if not s:
            continue
        if s.month in month_set:
            received_by_month[s.month] = max(received_by_month.get(s.month, 0), int(s.received or 0))
            if s.avg_rating is not None:
                rating_by_month[s.month] = s.avg_rating
    goal_doc = await bridge.get_client_review_goal(ctx.tenant_id, client_id)
    goal = (
        ClientReviewGoal.model_validate(goal_doc).monthly_goal
        if goal_doc
        else 10
    )

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
    items = await get_store().list_discovery_question_templates(ctx.tenant_id, limit=2000)
    if items:
        return {"items": items}
    return {"items": _default_discovery_templates()}


@api.post("/discovery/library")
async def discovery_library_create(payload: DiscoveryQuestionTemplateIn, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    item = DiscoveryQuestionTemplate(tenant_id=ctx.tenant_id, **payload.model_dump())
    payload_dict = item.to_mongo()
    if payload_dict.get("_id"):
        payload_dict["id"] = payload_dict.pop("_id")
    return await get_store().upsert_discovery_question_template(ctx.tenant_id, payload_dict) or item.model_dump()


@api.patch("/discovery/library/{template_id}")
async def discovery_library_patch(template_id: str, patch: dict, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    bridge = get_store()
    existing = await bridge.get_discovery_question_template(ctx.tenant_id, template_id)
    if not existing:
        raise HTTPException(404, "Not found")
    merged = dict(existing)
    merged.update(patch or {})
    if "_id" in merged:
        merged["id"] = merged.pop("_id")
    return await bridge.upsert_discovery_question_template(ctx.tenant_id, merged) or merged


@api.delete("/discovery/library/{template_id}")
async def discovery_library_delete(template_id: str, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    ok = await get_store().soft_delete_discovery_question_template(ctx.tenant_id, template_id)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@api.post("/meetings/{meeting_id}/discovery/generate")
async def meeting_generate_discovery(meeting_id: str, ctx=Depends(get_current_context)):
    m_doc = await _require_meeting_access(ctx, meeting_id)
    meeting = Meeting.from_mongo(m_doc)
    client_doc = await sb_get_client_for_tenant(ctx.tenant_id, meeting.client_id)
    client = Client.from_mongo(client_doc) if client_doc else None
    bridge = get_store()
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

    templates = await bridge.list_discovery_question_templates(ctx.tenant_id, limit=2000)
    if not templates:
        templates = _default_discovery_templates()
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

    meeting_patch = meeting.model_dump()
    meeting_patch["discovery_questions"] = [q.model_dump() for q in out]
    meeting_patch["updated_at"] = utcnow().isoformat()
    doc2 = await bridge.upsert_meeting(ctx.tenant_id, meeting_patch)
    return {"ok": True, "meeting": doc2 or meeting_patch}


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
    bridge = get_store()
    doc = await bridge.get_roadmap_plan(tenant_id, client_id)
    if doc:
        try:
            return RoadmapPlan.model_validate(doc)
        except Exception:
            pass
    plan = RoadmapPlan(tenant_id=tenant_id, client_id=client_id, start_date=_iso_date(utcnow()), weeks=12, items=[])
    payload = plan.to_mongo()
    if payload.get("_id"):
        payload["id"] = payload.pop("_id")
    stored = await bridge.upsert_roadmap_plan(tenant_id, client_id, payload)
    try:
        return RoadmapPlan.model_validate(stored or payload)
    except Exception:
        return plan


@api.get("/roadmap/{client_id}")
async def get_roadmap(client_id: str, ctx=Depends(get_current_context)):
    plan = await _get_or_create_roadmap_plan(ctx.tenant_id, client_id)
    today = _iso_date(utcnow())
    current_week = _compute_current_week(plan.start_date, plan.weeks)

    items = [it.model_dump() for it in (plan.items or [])]
    action_ids = [str(it.get("action_item_id") or "") for it in items if str(it.get("action_item_id") or "").strip()]
    if action_ids:
        docs = [doc for doc in await sb_list_action_items(ctx, limit=2000) if str((doc or {}).get("_id") or "") in set(action_ids)]
        by_id = {
            d.get("_id"): ActionItem.from_mongo(d).model_dump()
            for d in docs
        }
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
    next_doc = {**plan.model_dump(), **patch}
    stored = await get_store().upsert_roadmap_plan(ctx.tenant_id, client_id, next_doc)
    return stored or next_doc


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
        stored = await sb_upsert_action_item(ctx, ai_doc.to_mongo())
        action_item_id = str((stored or {}).get("_id") or ai_doc.id)

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
    next_doc = {**plan.model_dump(), "items": items, "updated_at": utcnow().isoformat()}
    stored = await get_store().upsert_roadmap_plan(ctx.tenant_id, client_id, next_doc)
    next_plan = stored or next_doc
    return {"ok": True, "item": item.model_dump(), "action_item_id": action_item_id, "plan": next_plan}


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
            doc0 = await sb_get_action_item(ctx, aid)
            if doc0:
                await sb_upsert_action_item(ctx, {**dict(doc0), **a_patch})

    items[idx] = it
    next_doc = {**plan.model_dump(), "items": items, "updated_at": utcnow().isoformat()}
    stored = await get_store().upsert_roadmap_plan(ctx.tenant_id, client_id, next_doc)
    next_plan = stored or next_doc
    return {"ok": True, "item": it, "plan": next_plan}

@api.post("/action-items")
async def create_action(data: ActionItemIn, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, data.client_id)
    item = ActionItem(tenant_id=ctx.tenant_id, **data.model_dump())
    stored = await sb_upsert_action_item(ctx, item.to_mongo())
    return ActionItem.from_mongo(stored).model_dump()


@api.patch("/action-items/{item_id}")
async def update_action(item_id: str, patch: dict, ctx=Depends(get_current_context)):
    doc0 = await sb_get_action_item(ctx, item_id)
    if not doc0:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc0.get("client_id") or ""))
    patch["updated_at"] = utcnow().isoformat()
    next_doc = {**dict(doc0 or {}), **dict(patch or {})}
    doc = await sb_upsert_action_item(ctx, next_doc)
    return ActionItem.from_mongo(doc).model_dump()


@api.delete("/action-items/{item_id}")
async def delete_action(item_id: str, ctx=Depends(get_current_context)):
    doc0 = await sb_get_action_item(ctx, item_id)
    if not doc0:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc0.get("client_id") or ""))
    await sb_soft_delete_action_item(ctx, item_id)
    return {"ok": True}


# ===================== CONTENT CAPTURES =====================
@api.get("/content-captures")
async def list_content(client_id: Optional[str] = None, ctx=Depends(get_current_context)):
    allowed = await _allowed_client_ids(ctx)
    if client_id:
        await _require_client_access(ctx, client_id)
    docs = await get_store().list_content_captures(ctx.tenant_id, client_id=client_id, limit=500)
    if allowed is not None:
        docs = [doc for doc in docs if str((doc or {}).get("client_id") or "") in set(allowed)]
    return [ContentCapture.model_validate(d).model_dump() for d in docs if d]


@api.post("/content-captures")
async def create_content(data: ContentCaptureIn, ctx=Depends(get_current_context)):
    await _require_client_access(ctx, data.client_id)
    cc = ContentCapture(tenant_id=ctx.tenant_id, **data.model_dump())
    payload = cc.to_mongo()
    if payload.get("_id"):
        payload["id"] = payload.pop("_id")
    stored = await get_store().upsert_content_capture(ctx.tenant_id, payload)
    return ContentCapture.model_validate(stored or payload).model_dump()


@api.patch("/content-captures/{cap_id}")
async def update_content(cap_id: str, patch: dict, ctx=Depends(get_current_context)):
    bridge = get_store()
    doc0 = await bridge.get_content_capture(ctx.tenant_id, cap_id)
    if not doc0:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc0.get("client_id") or ""))
    patch["updated_at"] = utcnow().isoformat()
    next_doc = {**dict(doc0 or {}), **dict(patch or {})}
    if "_id" in next_doc:
        next_doc["id"] = next_doc.pop("_id")
    doc = await bridge.upsert_content_capture(ctx.tenant_id, next_doc)
    return ContentCapture.model_validate(doc or next_doc).model_dump()


@api.delete("/content-captures/{cap_id}")
async def delete_content(cap_id: str, ctx=Depends(get_current_context)):
    bridge = get_store()
    doc0 = await bridge.get_content_capture(ctx.tenant_id, cap_id)
    if not doc0:
        raise HTTPException(404, "Not found")
    await _require_client_access(ctx, str(doc0.get("client_id") or ""))
    deleted = await bridge.soft_delete_content_capture(ctx.tenant_id, cap_id)
    if not deleted:
        raise HTTPException(404, "Not found")
    return {"ok": True}


# ===================== INTEGRATIONS =====================
@api.get("/integrations/catalog")
async def integrations_catalog(_: User = Depends(get_current_user)):
    return list_integrations()


@api.get("/integrations")
async def integrations_status(ctx=Depends(get_current_context)):
    google_oauth_cfg = await _google_oauth_config(ctx.tenant_id)
    google_oauth_app_configured = all(
        bool(str(google_oauth_cfg.get(key) or "").strip())
        for key in ("client_id", "client_secret", "redirect_uri")
    )
    google_user_connections: dict[str, dict[str, Any]] = {}
    for google_platform in GOOGLE_OAUTH_PLATFORMS:
        runtime_doc = await _get_user_oauth_runtime_doc(ctx.tenant_id, ctx.user.id, "google", google_platform)
        google_user_connections[google_platform] = {
            "runtime_doc": runtime_doc,
            "has_refresh_token": bool(await connectors.get_google_refresh_token(ctx.tenant_id, ctx.user.id, google_platform)),
        }
    out = []
    for cat in list_integrations():
        plat = cat["platform"]
        stored = await _get_integration_runtime_doc(ctx.tenant_id, plat)
        user_tok = None
        has_refresh_token = False
        if plat in GOOGLE_OAUTH_PLATFORMS:
            google_conn = google_user_connections.get(plat) or {}
            user_tok = google_conn.get("runtime_doc")
            has_refresh_token = bool(google_conn.get("has_refresh_token"))
        stored_status = (stored or {}).get("status", "not_connected")
        if plat in GOOGLE_OAUTH_PLATFORMS:
            if plat == "google_ads":
                has_dev = bool(((stored or {}).get("credentials_encrypted") or {}).get("developer_token"))
                stored_status = "connected" if (has_dev and has_refresh_token) else "not_connected"
            else:
                stored_status = "connected" if has_refresh_token else "not_connected"
        row = {
            **cat,
            "status": stored_status,
            "last_synced_at": (stored or {}).get("last_synced_at") or (user_tok or {}).get("updated_at"),
            "last_error": (stored or {}).get("last_error"),
            "metadata": (stored or {}).get("metadata", {}),
            "configured_field_keys": list(((stored or {}).get("credentials_encrypted") or {}).keys()),
        }
        if plat == "google_oauth":
            connected_google_platforms = sorted(
                platform
                for platform, conn in google_user_connections.items()
                if conn.get("has_refresh_token")
            )
            row.update(
                {
                    "app_configured": google_oauth_app_configured,
                    "google_account_connected": bool(connected_google_platforms),
                    "google_account_connected_platforms": connected_google_platforms,
                }
            )
        out.append(row)
    return out


@api.get("/diagnostics/integrations")
async def diagnostics_integrations(ctx=Depends(get_current_context)):
    bridge = get_store()
    bridge_docs = await bridge.list_tenant_integrations(ctx.tenant_id, limit=200)
    safe = []
    for bridge_doc in bridge_docs:
        safe.append({k: v for k, v in dict(bridge_doc or {}).items() if k not in ("credentials_encrypted",)})

    safe_user_google = []
    for plat in sorted(GOOGLE_OAUTH_PLATFORMS):
        runtime_doc = await _get_user_oauth_runtime_doc(ctx.tenant_id, ctx.user.id, "google", plat)
        if runtime_doc:
            safe_user_google.append(
                {
                    "provider": "google",
                    "platform": plat,
                    "scopes": runtime_doc.get("scopes") or [],
                    "account_email": runtime_doc.get("account_email"),
                    "updated_at": runtime_doc.get("updated_at"),
                    "last_synced_at": runtime_doc.get("last_synced_at"),
                }
            )
    return {"ok": True, "tenant_id": ctx.tenant_id, "user_id": ctx.user.id, "integrations": safe, "user_google_tokens": safe_user_google}


@api.get("/diagnostics/google-oauth")
async def diagnostics_google_oauth(ctx=Depends(get_current_context)):
    doc = await _get_integration_runtime_doc(ctx.tenant_id, "google_oauth")
    meta = (doc or {}).get("metadata") or {}
    enc = (doc or {}).get("credentials_encrypted") or {}
    secret_decrypt_ok = False
    try:
        if str(enc.get("client_secret") or "").strip():
            secret_decrypt_ok = bool(str(decrypt_secret(enc.get("client_secret")) or "").strip())
    except Exception:
        secret_decrypt_ok = False
    cfg = await _google_oauth_config(ctx.tenant_id)
    cid = str(cfg.get("client_id") or "").strip()
    rid = str(cfg.get("redirect_uri") or "").strip()
    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "has_env": {
            "client_id": bool(GOOGLE_OAUTH_CLIENT_ID),
            "client_secret": bool(GOOGLE_OAUTH_CLIENT_SECRET),
            "redirect_uri": bool(GOOGLE_OAUTH_REDIRECT_URI),
        },
        "has_integration": {
            "client_id": bool(str(meta.get("client_id") or "").strip()),
            "client_secret_encrypted": bool(str(enc.get("client_secret") or "").strip()),
            "client_secret_decrypt_ok": secret_decrypt_ok,
            "redirect_uri": bool(str(meta.get("redirect_uri") or "").strip()),
        },
        "effective": {
            "client_id_tail": cid[-10:] if cid else "",
            "redirect_uri": rid,
            "client_id_source": "integration" if cid and str(meta.get("client_id") or "").strip() == cid else ("env" if cid else "missing"),
            "redirect_uri_source": "integration" if rid and str(meta.get("redirect_uri") or "").strip() == rid else ("env" if rid else "missing"),
            "client_secret_source": "integration" if secret_decrypt_ok else ("env" if bool(GOOGLE_OAUTH_CLIENT_SECRET) else "missing"),
        },
    }


@api.get("/diagnostics/client/{client_id}")
async def diagnostics_client(client_id: str, ctx=Depends(get_current_context)):
    bridge = get_store()
    cdoc = await _require_client_access(ctx, client_id)
    if not cdoc:
        raise HTTPException(404, "Client not found")
    bindings = await bridge.list_client_bindings(ctx.tenant_id, client_id, limit=200)
    safe_bindings = []
    for b in bindings:
        bb = dict(b or {})
        if bb.get("_id") and not isinstance(bb["_id"], str):
            bb["_id"] = str(bb["_id"])
        safe_bindings.append(bb)
    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "user_id": ctx.user.id,
        "client": {
            "id": str(cdoc.get("_id")),
            "company": cdoc.get("company"),
            "name": cdoc.get("name"),
            "website": cdoc.get("website"),
            "location": cdoc.get("location"),
            "services": cdoc.get("services") or [],
            "gbp_data": cdoc.get("gbp_data") or {},
            "crm_data": cdoc.get("crm_data") or {},
        },
        "bindings": safe_bindings,
    }


@api.get("/diagnostics/meeting/{meeting_id}")
async def diagnostics_meeting(meeting_id: str, ctx=Depends(get_current_context)):
    bridge = get_store()
    doc = await bridge.get_meeting(ctx.tenant_id, meeting_id)
    if not doc:
        raise HTTPException(404, "Meeting not found")
    client_id = str(doc.get("client_id") or "").strip()
    if client_id:
        await _require_client_access(ctx, client_id)
    m = Meeting.model_validate(doc).model_dump()
    kpi = (m or {}).get("kpi_snapshot") or {}
    return {
        "ok": True,
        "tenant_id": ctx.tenant_id,
        "user_id": ctx.user.id,
        "meeting": {
            "id": meeting_id,
            "client_id": client_id,
            "brief_generated_at": m.get("brief_generated_at"),
            "brief_model": m.get("brief_model"),
            "wins_count": len(m.get("wins") or []),
            "issues_count": len(m.get("issues") or []),
            "recommendations_count": len(m.get("strategic_recommendations") or []),
        },
        "kpi_availability": (kpi or {}).get("_availability") or {},
    }


@api.post("/integrations/{platform}/configure")
async def configure_integration(platform: str, data: IntegrationConfigureIn, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
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
    now = utcnow().isoformat()
    existing = await get_store().get_tenant_integration(ctx.tenant_id, platform)
    if existing:
        merged_creds = {**(existing.get("credentials_encrypted") or {}), **enc}
        merged_metadata = {**(existing.get("metadata") or {}), **(data.metadata or {})}
        if platform == "clickup":
            status_value = "connected" if (merged_creds.get("api_token") or merged_creds.get("access_token")) else "not_connected"
        else:
            status_value = "connected" if merged_creds else "not_connected"
        mirror_doc = {
            "id": existing.get("id") or existing.get("_id"),
            "tenant_id": ctx.tenant_id,
            "platform": platform,
            "label": existing.get("label") or INTEGRATIONS[platform]["label"],
            "status": status_value,
            "last_synced_at": existing.get("last_synced_at"),
            "last_error": existing.get("last_error"),
            "credentials_encrypted": merged_creds,
            "metadata": merged_metadata,
            "updated_at": now,
        }
        await get_store().upsert_tenant_integration(ctx.tenant_id, platform, mirror_doc)
        mirror_doc = {
            "platform": platform,
            "label": mirror_doc["label"],
            "status": status_value,
            "last_synced_at": mirror_doc["last_synced_at"],
            "last_error": mirror_doc["last_error"],
            "metadata": merged_metadata,
        }
    else:
        i = Integration(
            tenant_id=ctx.tenant_id,
            platform=platform,
            label=INTEGRATIONS[platform]["label"],
            status=(
                "connected"
                if (platform != "clickup" and bool(enc))
                or (platform == "clickup" and bool(enc.get("api_token") or enc.get("access_token")))
                else "not_connected"
            ),
            credentials_encrypted=enc,
            metadata=data.metadata or {},
        )
        i_payload = i.to_mongo()
        if i_payload.get("_id"):
            i_payload["id"] = i_payload.pop("_id")
        await get_store().upsert_tenant_integration(ctx.tenant_id, platform, i_payload)
        mirror_doc = {
            "platform": platform,
            "label": i.label,
            "status": i.status,
            "last_synced_at": i.last_synced_at,
            "last_error": i.last_error,
            "metadata": i.metadata,
        }
    await _mirror_tenant_integration_doc(ctx.tenant_id, mirror_doc, reason="configure_integration")
    return {"ok": True, "platform": platform, "status": mirror_doc["status"]}


@api.post("/integrations/{platform}/test")
async def test_integration(platform: str, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    if platform not in INTEGRATIONS:
        raise HTTPException(404, "Unknown integration")
    doc = await _get_integration_runtime_doc(ctx.tenant_id, platform)
    if not doc or not doc.get("credentials_encrypted"):
        raise HTTPException(400, "No credentials configured")
    creds = {k: decrypt_secret(v) for k, v in (doc.get("credentials_encrypted", {}) or {}).items() if v}
    if not all(v is not None and str(v).strip() != "" for v in creds.values()):
        bad_keys = []
        enc_map = doc.get("credentials_encrypted", {}) or {}
        for k, v in creds.items():
            if str(v or "").strip() == "" and str(enc_map.get(k) or "").strip() != "":
                bad_keys.append(k)
        await _mirror_tenant_integration_doc(
            ctx.tenant_id,
            {
                "id": doc.get("id") or doc.get("_id"),
                "tenant_id": ctx.tenant_id,
                "platform": platform,
                "label": (doc or {}).get("label") or INTEGRATIONS[platform]["label"],
                "status": "error",
                "last_synced_at": (doc or {}).get("last_synced_at"),
                "last_error": "Credential decryption failed",
                "metadata": dict((doc or {}).get("metadata") or {}),
                "credentials_encrypted": doc.get("credentials_encrypted") or {},
                "updated_at": utcnow().isoformat(),
            },
            reason="test_integration_decrypt_failed",
        )
        detail = "Credential decryption failed. Re-enter all encrypted fields and save again."
        if bad_keys:
            detail = f"{detail} Undecryptable fields: {', '.join(sorted(set(bad_keys)))}"
        raise HTTPException(400, detail)

    if platform == "clickup" and not connectors._clickup_token_from_creds(creds):
        raise HTTPException(400, "ClickUp OAuth app saved. Finish Connect ClickUp or add a personal API token before testing.")

    if platform == "clickup":
        res = await connectors.test_clickup(ctx.tenant_id)
    elif platform == "gohighlevel":
        res = await connectors.test_gohighlevel(ctx.tenant_id)
    elif platform == "google_ads":
        res = await connectors.test_google_ads_for_user(ctx.tenant_id, ctx.user.id)
    elif platform == "google_meet":
        res = await connectors.test_google_meet_for_user(ctx.tenant_id, ctx.user.id)
    elif platform == "google_calendar":
        google_doc = await _get_user_oauth_runtime_doc(ctx.tenant_id, ctx.user.id, "google", "google_calendar")
        res = {"ok": True} if google_doc else {"ok": False, "error": "missing_google_connection", "error_detail": "Connect Google for Google Calendar first."}
    else:
        res = {"ok": True, "note": "Credentials stored & verified. Live API sync runs on next scheduled job."}

    if not res.get("ok"):
        await _mirror_tenant_integration_doc(
            ctx.tenant_id,
            {
                "id": doc.get("id") or doc.get("_id"),
                "tenant_id": ctx.tenant_id,
                "platform": platform,
                "label": (doc or {}).get("label") or INTEGRATIONS[platform]["label"],
                "status": "error",
                "last_synced_at": (doc or {}).get("last_synced_at"),
                "last_error": res.get("error_detail") or res.get("error") or "Integration test failed",
                "metadata": dict((doc or {}).get("metadata") or {}),
                "credentials_encrypted": doc.get("credentials_encrypted") or {},
                "updated_at": utcnow().isoformat(),
            },
            reason="test_integration_failed",
        )
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Integration test failed")

    synced_at = utcnow().isoformat()
    await _mirror_tenant_integration_doc(
        ctx.tenant_id,
        {
            "id": doc.get("id") or doc.get("_id"),
            "tenant_id": ctx.tenant_id,
            "platform": platform,
            "label": (doc or {}).get("label") or INTEGRATIONS[platform]["label"],
            "status": "connected",
            "last_synced_at": synced_at,
            "last_error": None,
            "metadata": dict((doc or {}).get("metadata") or {}),
            "credentials_encrypted": doc.get("credentials_encrypted") or {},
            "updated_at": synced_at,
        },
        reason="test_integration_success",
    )
    return {"ok": True, "platform": platform, "status": "connected", **res}


@api.delete("/integrations/{platform}")
async def disconnect_integration(platform: str, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    await _soft_delete_tenant_integration_doc(ctx.tenant_id, platform, reason="disconnect_integration")
    return {"ok": True}


@api.get("/integrations/clickup/workspaces")
async def clickup_workspaces(ctx=Depends(get_current_context)):
    if str(ctx.tenant_role or "") == "viewer":
        raise HTTPException(403, "Forbidden")
    res = await connectors.list_clickup_workspaces(ctx.tenant_id)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
    return res


@api.get("/integrations/google_ads/customers")
async def google_ads_customers(ctx=Depends(get_current_context)):
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


@api.get("/integrations/google_business_profile/locations")
async def google_business_profile_locations(ctx=Depends(get_current_context)):
    res = await connectors.list_gbp_locations_for_user(ctx.tenant_id, ctx.user.id)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error_detail") or res.get("error") or "Failed")
    return res


@api.get("/integrations/clickup/lists")
async def clickup_lists(team_id: Optional[str] = Query(default=None), ctx=Depends(get_current_context)):
    if str(ctx.tenant_role or "") == "viewer":
        raise HTTPException(403, "Forbidden")
    if not team_id:
        doc = await _get_integration_runtime_doc(ctx.tenant_id, "clickup")
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
    if str(ctx.tenant_role or "") == "viewer":
        raise HTTPException(403, "Forbidden")
    if not team_id:
        doc = await _get_integration_runtime_doc(ctx.tenant_id, "clickup")
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
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    ids = await connectors.list_gohighlevel_location_token_ids(ctx.tenant_id)
    return {"ok": True, "location_ids": ids}


@api.post("/integrations/gohighlevel/location-tokens")
async def upsert_ghl_location_token(data: GhlLocationTokenIn, ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    lid = str(data.location_id or "").strip()
    tok = str(data.token or "").strip()
    if not lid or not tok:
        raise HTTPException(400, "Missing location_id or token")
    ok = await connectors.upsert_gohighlevel_location_token(ctx.tenant_id, lid, tok)
    if not ok:
        raise HTTPException(503, "Unable to store location token")
    return {"ok": True}


@api.delete("/integrations/gohighlevel/location-tokens")
async def delete_ghl_location_token(location_id: str = Query(...), ctx=Depends(get_current_context)):
    if not can_manage_tenant(ctx.user.role, ctx.tenant_role):
        raise HTTPException(403, "Admin only")
    lid = str(location_id or "").strip()
    if not lid:
        raise HTTPException(400, "Missing location_id")
    ok = await connectors.delete_gohighlevel_location_token(ctx.tenant_id, lid)
    if not ok:
        raise HTTPException(503, "Unable to delete location token")
    return {"ok": True}


# ===================== DOCS =====================
@api.get("/docs")
async def docs_list(ctx=Depends(get_current_context)):
    is_internal_tenant = await _is_internal_tenant_id(ctx.tenant_id)
    is_admin_view = can_manage_tenant(ctx.user.role, ctx.tenant_role)
    sdoc = await _get_tenant_settings_doc(ctx.tenant_id)
    settings = TenantSettings.from_mongo(sdoc)

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

    is_internal_tenant = await _is_internal_tenant_id(ctx.tenant_id)
    is_admin_view = can_manage_tenant(ctx.user.role, ctx.tenant_role)
    aud = (d.get("audience") or "tenant").strip().lower()
    if aud == "internal" and not is_internal_tenant:
        raise HTTPException(404, "Doc not found")
    min_role = (d.get("min_role") or "").strip().lower()
    if min_role == "admin" and not is_admin_view:
        raise HTTPException(404, "Doc not found")

    sdoc = await _get_tenant_settings_doc(ctx.tenant_id)
    settings = TenantSettings.from_mongo(sdoc)
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
    bridge = get_store()
    clients_docs = await bridge.list_clients(ctx.tenant_id, limit=5000) if bridge.is_enabled_for("clients") else []
    meetings_docs = await _list_meeting_docs(ctx.tenant_id, limit=5000)
    action_docs = await _list_action_item_docs(ctx.tenant_id, limit=5000)
    content_docs = await bridge.list_content_captures(ctx.tenant_id, limit=5000) if bridge.is_enabled_for("content_captures") else []

    total_clients = len(clients_docs)
    churn_risk_high = sum(1 for doc in clients_docs if str((doc or {}).get("churn_risk") or "").strip().lower() == "high")
    churn_risk_medium = sum(1 for doc in clients_docs if str((doc or {}).get("churn_risk") or "").strip().lower() == "medium")

    health_scores = [float((doc or {}).get("health_score", 75) or 75) for doc in clients_docs]
    avg_health_score = round(sum(health_scores) / len(health_scores), 1) if health_scores else 0

    meetings_this_month = sum(
        1 for doc in meetings_docs
        if start_30_ts <= str((doc or {}).get("created_at") or "") <= end_30_ts
    )

    open_action_items = sum(1 for doc in action_docs if str((doc or {}).get("status") or "") in {"open", "in_progress"})
    overdue_action_items = sum(
        1
        for doc in action_docs
        if str((doc or {}).get("status") or "") in {"open", "in_progress"}
        and str((doc or {}).get("due_date") or "") < now.date().isoformat()
    )

    content_captures_total = len(content_docs)
    content_pending_routing = sum(1 for doc in content_docs if not bool((doc or {}).get("routed_to_marketing", False)))

    review_forecast_next_month = None
    try:
        m3 = _last_n_months(3)
        snaps = await bridge.list_review_monthly_snapshots(ctx.tenant_id, months=m3, limit=5000) if bridge.is_enabled_for("reviews") else []
        by_month = {m: 0 for m in m3}
        for d in snaps or []:
            s = ReviewMonthlySnapshot.model_validate(d)
            if not s:
                continue
            if s.month in by_month:
                by_month[s.month] += int(s.received or 0)
        review_forecast_next_month = int(round(sum(by_month.values()) / max(1, len(by_month))))
    except Exception:
        review_forecast_next_month = None

    meeting_docs = sorted(meetings_docs, key=lambda m: str((m or {}).get("created_at") or ""), reverse=True)[:5]
    recent_meetings = [Meeting.from_mongo(m).model_dump() for m in (meeting_docs or [])]

    prep_docs = [
        m for m in meetings_docs
        if str((m or {}).get("brief_generated_at") or "") in {"", "None"}
        and str((m or {}).get("scheduled_at") or "").strip()
        and str((m or {}).get("scheduled_at") or "") >= now_iso
    ]
    prep_docs.sort(key=lambda m: str((m or {}).get("scheduled_at") or ""))
    prep_queue = [Meeting.from_mongo(m).model_dump() for m in prep_docs[:5]]
    prep_queue_count = len(prep_docs)

    top_health_docs = sorted(clients_docs, key=lambda c: float((c or {}).get("health_score") or 0), reverse=True)[:5]
    top_health_clients = [Client.from_mongo(c).model_dump() for c in (top_health_docs or [])]

    at_risk_docs = [
        c for c in clients_docs
        if str((c or {}).get("churn_risk") or "").strip().lower() in {"high", "medium"}
    ]
    at_risk_docs.sort(key=lambda c: float((c or {}).get("health_score") or 0))
    at_risk_clients = [Client.from_mongo(c).model_dump() for c in at_risk_docs[:5]]

    suggestion_docs = [c for c in clients_docs if list((c or {}).get("suggestions") or [])]
    suggestion_docs.sort(key=lambda c: str((c or {}).get("suggestions_generated_at") or ""), reverse=True)
    suggestion_docs = suggestion_docs[:20]
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
    if not await _ensure_db_ready():
        raise RuntimeError("Supabase database is not ready. Check SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and bootstrap SQL.")
    try:
        await bootstrap_admin()
    except Exception as exc:
        logger.error("bootstrap_admin failed: %s", exc)
    try:
        enabled = (os.environ.get("CLICKUP_AUTO_SYNC_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
        hours = float(os.environ.get("CLICKUP_AUTO_SYNC_HOURS", "24") or "24")
        if enabled and hours > 0:
            interval_s = max(300, int(hours * 3600))

            async def _clickup_loop():
                await asyncio.sleep(20)
                while True:
                    try:
                        await clickup_client_sync.sync_all_tenants()
                    except Exception as exc:
                        logger.error("clickup auto sync failed: %s", exc)
                    await asyncio.sleep(interval_s)

            asyncio.create_task(_clickup_loop())
    except Exception as exc:
        logger.error("clickup auto sync init failed: %s", exc)
    logger.info("Monthly Touch OS API ready")


# ===================== PRODUCTION ENTRYPOINT =====================
# Ensures Render binds natively to the host infrastructure via Python execution fallback.
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
