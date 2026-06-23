"""JWT auth helpers."""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from models import Tenant, TenantMembership, User, UserPublic
from supabase_store import get_store
from supabase_config import get_supabase_settings, is_supabase_service_configured

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = os.environ.get("JWT_ALG", "HS256")
JWT_EXPIRES_HOURS = int(os.environ.get("JWT_EXPIRES_HOURS", "720"))

bearer = HTTPBearer(auto_error=False)
_DEFAULT_TENANT_ID: Optional[str] = None
_INTERNAL_WIKI_TENANT_ID: Optional[str] = None

APP_ROLE_ACCOUNT_MANAGER = "account_manager"
APP_ROLE_TEAM_LEAD = "team_lead"
APP_ROLE_DEPARTMENT_ADMIN = "department_admin"
APP_ROLE_SUPER_ADMIN = "super_admin"


def normalize_app_role(role: Any) -> str:
    normalized = str(role or "").strip().lower()
    if normalized in {"super_admin", "platform_admin", "system_admin"}:
        return APP_ROLE_SUPER_ADMIN
    if normalized in {"department_admin", "tenant_admin", "admin", "owner"}:
        return APP_ROLE_DEPARTMENT_ADMIN
    if normalized in {"team_lead", "lead"}:
        return APP_ROLE_TEAM_LEAD
    if normalized in {"account_manager", "manager", "member", "staff", "customer", "viewer"}:
        return APP_ROLE_ACCOUNT_MANAGER
    return APP_ROLE_ACCOUNT_MANAGER


def normalize_tenant_role(role: Any) -> str:
    normalized = str(role or "").strip().lower()
    if normalized in {"owner", "tenant_owner"}:
        return "owner"
    if normalized in {"admin", "department_admin"}:
        return "admin"
    if normalized in {"lead", "team_lead"}:
        return "lead"
    if normalized in {"viewer", "customer"}:
        return "viewer"
    return "member"


def can_manage_tenant(user_role: Any, tenant_role: Any) -> bool:
    app_role = normalize_app_role(user_role)
    membership_role = normalize_tenant_role(tenant_role)
    return app_role in {APP_ROLE_SUPER_ADMIN, APP_ROLE_DEPARTMENT_ADMIN} or membership_role in {"owner", "admin"}


def can_manage_platform(user_role: Any) -> bool:
    return normalize_app_role(user_role) == APP_ROLE_SUPER_ADMIN


def _norm_host(host: str) -> str:
    h = (host or "").strip().lower()
    if not h:
        return ""
    if "://" in h:
        h = h.split("://", 1)[1]
    if "/" in h:
        h = h.split("/", 1)[0]
    if ":" in h:
        h = h.split(":", 1)[0]
    return h


def _bridge_membership_to_model(doc: Optional[dict[str, Any]]) -> Optional[TenantMembership]:
    if not doc:
        return None
    return TenantMembership.from_mongo(doc)


def _system_role_to_app_role(system_role: Any) -> str:
    return normalize_app_role(system_role)


def _app_role_to_system_role(app_role: str) -> str:
    normalized = normalize_app_role(app_role)
    if normalized == APP_ROLE_SUPER_ADMIN:
        return "platform_admin"
    if normalized == APP_ROLE_DEPARTMENT_ADMIN:
        return "department_admin"
    if normalized == APP_ROLE_TEAM_LEAD:
        return "team_lead"
    return "customer"


def _supabase_headers(*, include_auth: bool = True) -> dict[str, str]:
    settings = get_supabase_settings()
    api_key = str(settings.get("service_role_key") or "").strip()
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }
    if include_auth:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _supabase_public_headers(access_token: str) -> dict[str, str]:
    settings = get_supabase_settings()
    api_key = str(settings.get("service_role_key") or "").strip()
    return {
        "apikey": api_key,
        "Authorization": f"Bearer {str(access_token or '').strip()}",
        "Content-Type": "application/json",
    }


def _supabase_auth_url(path: str) -> str:
    settings = get_supabase_settings()
    base = str(settings.get("url") or "").rstrip("/")
    return f"{base}/{path.lstrip('/')}"


async def _supabase_auth_request(
    method: str,
    path: str,
    *,
    payload: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
    include_auth: bool = True,
) -> Any:
    if not is_supabase_service_configured():
        raise RuntimeError("Supabase service role is not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(
            method.upper(),
            _supabase_auth_url(path),
            json=payload,
            params=params,
            headers=_supabase_headers(include_auth=include_auth),
        )
    response.raise_for_status()
    if not response.text.strip():
        return None
    return response.json()


async def _supabase_admin_create_user(
    *,
    email: str,
    password: str,
    name: str,
    app_role: str,
    auth_provider: str,
    avatar_url: Optional[str] = None,
    google_sub: Optional[str] = None,
) -> dict[str, Any]:
    payload = {
        "email": str(email or "").strip().lower(),
        "password": password,
        "email_confirm": True,
        "user_metadata": {
            "name": name,
            "full_name": name,
        },
        "app_metadata": {
            "provider": "google" if auth_provider == "google" else "email",
            "system_role": _app_role_to_system_role(app_role),
        },
    }
    if avatar_url:
        payload["user_metadata"]["avatar_url"] = avatar_url
        payload["user_metadata"]["picture"] = avatar_url
    if google_sub:
        payload["user_metadata"]["google_sub"] = google_sub
    result = await _supabase_auth_request("POST", "/auth/v1/admin/users", payload=payload)
    return dict(result.get("user") or result or {})


async def _supabase_admin_update_user(
    user_id: str,
    *,
    email: Optional[str] = None,
    password: Optional[str] = None,
    name: Optional[str] = None,
    app_role: Optional[str] = None,
    auth_provider: Optional[str] = None,
    avatar_url: Optional[str] = None,
    google_sub: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if email:
        payload["email"] = str(email).strip().lower()
    if password:
        payload["password"] = password
    if name or avatar_url or google_sub:
        payload["user_metadata"] = {}
        if name:
            payload["user_metadata"]["name"] = name
            payload["user_metadata"]["full_name"] = name
        if avatar_url:
            payload["user_metadata"]["avatar_url"] = avatar_url
            payload["user_metadata"]["picture"] = avatar_url
        if google_sub:
            payload["user_metadata"]["google_sub"] = google_sub
    if app_role or auth_provider:
        payload["app_metadata"] = {}
        if auth_provider:
            payload["app_metadata"]["provider"] = "google" if auth_provider == "google" else "email"
        if app_role:
            payload["app_metadata"]["system_role"] = _app_role_to_system_role(app_role)
    result = await _supabase_auth_request("PUT", f"/auth/v1/admin/users/{user_id}", payload=payload)
    return dict(result.get("user") or result or {})


async def _supabase_admin_get_user(user_id: str) -> Optional[dict[str, Any]]:
    uid = str(user_id or "").strip()
    if not uid:
        return None
    try:
        result = await _supabase_auth_request("GET", f"/auth/v1/admin/users/{uid}")
    except Exception:
        return None
    user = dict((result or {}).get("user") or result or {})
    return user or None


async def _supabase_password_login(email: str, password: str) -> Optional[dict[str, Any]]:
    session = await _supabase_password_login_session(email, password)
    if not session:
        return None
    user = dict((session or {}).get("user") or {})
    return user or None


async def _supabase_password_login_session(email: str, password: str) -> Optional[dict[str, Any]]:
    try:
        result = await _supabase_auth_request(
            "POST",
            "/auth/v1/token",
            payload={"email": str(email or "").strip().lower(), "password": password},
            params={"grant_type": "password"},
            include_auth=False,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401):
            return None
        raise
    data = dict(result or {})
    return data or None


async def login_password_session(email: str, password: str) -> Optional[dict[str, Any]]:
    return await _supabase_password_login_session(email, password)


async def login_google_session(
    id_token: str,
    *,
    access_token: Optional[str] = None,
    nonce: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    payload: dict[str, Any] = {
        "provider": "google",
        "id_token": str(id_token or "").strip(),
    }
    if access_token:
        payload["access_token"] = str(access_token).strip()
    if nonce:
        payload["nonce"] = str(nonce).strip()
    try:
        result = await _supabase_auth_request(
            "POST",
            "/auth/v1/token",
            params={"grant_type": "id_token"},
            payload=payload,
        )
    except httpx.HTTPStatusError:
        raise
    return dict(result or {})


async def _supabase_get_user_from_access_token(access_token: str) -> Optional[dict[str, Any]]:
    token = str(access_token or "").strip()
    if not token or not is_supabase_service_configured():
        return None
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            _supabase_auth_url("/auth/v1/user"),
            headers=_supabase_public_headers(token),
        )
    if response.status_code in (401, 403):
        return None
    response.raise_for_status()
    if not response.text.strip():
        return None
    data = response.json() or {}
    return dict(data or {})


def _decode_unverified_jwt(token: str) -> dict[str, Any]:
    try:
        return dict(jwt.decode(token, options={"verify_signature": False, "verify_exp": False, "verify_aud": False}) or {})
    except Exception:
        return {}


def _supabase_claim_role_to_app_role(claim_role: Any) -> str:
    return normalize_app_role(claim_role)


def _supabase_claim_role_to_tenant_role(claim_role: Any) -> str:
    normalized = str(claim_role or "").strip().lower()
    if normalized in {"tenant_owner", "owner"}:
        return "owner"
    if normalized in {"platform_admin", "system_admin", "department_admin", "admin"}:
        return "admin"
    if normalized in {"team_lead", "lead"}:
        return "lead"
    if normalized in {"staff", "customer", "manager", "account_manager"}:
        return "member"
    return ""


def _supabase_auth_user_to_user(auth_user: Optional[dict[str, Any]], *, token_claims: Optional[dict[str, Any]] = None) -> Optional[User]:
    if not auth_user:
        return None
    claims = dict(token_claims or {})
    email = str(auth_user.get("email") or "").strip().lower()
    meta = dict(auth_user.get("user_metadata") or {})
    app_meta = dict(auth_user.get("app_metadata") or {})
    name = str(meta.get("name") or meta.get("full_name") or "").strip() or (email.split("@", 1)[0] if email else "User")
    claim_role = claims.get("user_role") or claims.get("role")
    role = _supabase_claim_role_to_app_role(claim_role or app_meta.get("system_role"))
    provider = str(app_meta.get("provider") or meta.get("provider") or "").strip().lower()
    return User(
        _id=str(auth_user.get("id") or ""),
        email=email,
        name=name,
        role=role,
        password_hash="",
        avatar_url=meta.get("avatar_url") or meta.get("picture"),
        active=True,
        auth_provider="google" if provider == "google" else "local",
    )


def supabase_session_to_user(session: Optional[dict[str, Any]]) -> Optional[User]:
    data = dict(session or {})
    auth_user = dict(data.get("user") or {})
    claims = _decode_unverified_jwt(str(data.get("access_token") or "").strip())
    return _supabase_auth_user_to_user(auth_user, token_claims=claims)


async def update_supabase_user(
    user_id: str,
    *,
    name: Optional[str] = None,
    app_role: Optional[str] = None,
    auth_provider: Optional[str] = None,
    avatar_url: Optional[str] = None,
    google_sub: Optional[str] = None,
) -> dict[str, Any]:
    return await _supabase_admin_update_user(
        user_id,
        name=name,
        app_role=app_role,
        auth_provider=auth_provider,
        avatar_url=avatar_url,
        google_sub=google_sub,
    )


async def _resolve_authenticated_request(token: str) -> tuple[User, dict[str, Any], str]:
    raw_token = str(token or "").strip()
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = decode_token(raw_token)
        user_id = payload.get("sub")
        token_role = payload.get("role")
        bridged_user = _runtime_profile_to_user(await get_store().get_user_profile(str(user_id or "")))
        if bridged_user:
            return bridged_user, dict(payload or {}), "legacy"
        supabase_user = await _supabase_admin_get_user(str(user_id or ""))
        user = _supabase_auth_user_to_user(supabase_user, token_claims={"role": token_role})
        if user:
            return user, dict(payload or {}), "legacy"
    except jwt.PyJWTError:
        pass

    supabase_user = await _supabase_get_user_from_access_token(raw_token)
    if not supabase_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    claims = _decode_unverified_jwt(raw_token)
    user = _supabase_auth_user_to_user(supabase_user, token_claims=claims)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if str(user.id or "") != str(supabase_user.get("id") or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    return user, claims, "supabase"


async def authenticate_password_user(email: str, password: str) -> Optional[User]:
    if not is_supabase_service_configured():
        return None
    normalized_email = str(email or "").strip().lower()
    profile = await get_store().get_user_profile_by_email(normalized_email)
    if profile and str(profile.get("auth_provider") or "").strip().lower() == "google":
        raise HTTPException(status_code=400, detail='This account uses Google sign-in. Use "Continue with Google".')
    auth_user = await _supabase_password_login(normalized_email, password)
    if not auth_user:
        return None
    bridged_user = _runtime_profile_to_user(
        await get_store().get_user_profile(str(auth_user.get("id") or ""))
        or await get_store().get_user_profile_by_email(normalized_email)
    )
    if bridged_user:
        return bridged_user
    return User(
        _id=str(auth_user.get("id") or ""),
        email=str(auth_user.get("email") or normalized_email or "").strip().lower(),
        name=str((((auth_user.get("user_metadata") or {}).get("name")) or normalized_email.split("@", 1)[0] or "User")).strip(),
        role=_system_role_to_app_role(((auth_user.get("app_metadata") or {}).get("system_role"))),
        password_hash="",
        avatar_url=((auth_user.get("user_metadata") or {}).get("avatar_url")),
        active=True,
        auth_provider="local",
    )


async def register_identity(email: str, name: str, password: str, *, app_role: str) -> User:
    normalized_email = str(email or "").strip().lower()
    existing = await get_store().get_user_profile_by_email(normalized_email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    auth_user = await _supabase_admin_create_user(
        email=normalized_email,
        password=password,
        name=name,
        app_role=app_role,
        auth_provider="local",
    )
    bridged_user = _runtime_profile_to_user(
        await get_store().get_user_profile(str(auth_user.get("id") or ""))
        or await get_store().get_user_profile_by_email(normalized_email)
    )
    if bridged_user:
        return bridged_user
    return User(
        _id=str(auth_user.get("id") or ""),
        email=normalized_email,
        name=name,
        role=app_role,
        password_hash="",
        avatar_url=None,
        active=True,
        auth_provider="local",
    )


async def sync_google_identity(email: str, name: str, *, picture: Optional[str] = None, google_sub: Optional[str] = None) -> User:
    normalized_email = str(email or "").strip().lower()
    bridge = get_store()
    existing = await bridge.get_user_profile_by_email(normalized_email)
    if existing:
        app_role = _system_role_to_app_role(existing.get("role"))
        await _supabase_admin_update_user(
            str(existing.get("_id") or existing.get("id") or ""),
            email=normalized_email,
            name=name,
            app_role=app_role,
            auth_provider="google",
            avatar_url=picture,
            google_sub=google_sub,
        )
    else:
        is_first_user = not await bridge.has_user_profiles()
        app_role = APP_ROLE_SUPER_ADMIN if is_first_user else APP_ROLE_ACCOUNT_MANAGER
        await _supabase_admin_create_user(
            email=normalized_email,
            password=secrets.token_urlsafe(24),
            name=name,
            app_role=app_role,
            auth_provider="google",
            avatar_url=picture,
            google_sub=google_sub,
        )
    bridged_user = _runtime_profile_to_user(await bridge.get_user_profile_by_email(normalized_email))
    if not bridged_user:
        raise HTTPException(status_code=500, detail="Google sign-in profile sync failed")
    return bridged_user


async def list_runtime_users(*, limit: int = 500) -> list[dict[str, Any]]:
    if is_supabase_service_configured():
        profiles = await get_store().list_user_profiles(limit=limit)
        return [
            {
                "id": item.get("id"),
                "email": item.get("email"),
                "name": item.get("name"),
                "role": _system_role_to_app_role(item.get("role")),
                "avatar_url": item.get("avatar_url"),
                "active": True,
            }
            for item in profiles
        ]
    return []


async def resolve_tenant_id_from_host(host: str) -> Optional[str]:
    h = _norm_host(host)
    if not h:
        return None

    bridge_tenant_id = await get_store().resolve_tenant_legacy_id_from_host(h)
    if bridge_tenant_id:
        return bridge_tenant_id
    if is_supabase_service_configured():
        return None
    raise RuntimeError("Supabase service configuration is required for tenant host resolution")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user_id: str, role: str, tenant_id: Optional[str] = None, tenant_role: Optional[str] = None) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "tenant_id": tenant_id,
        "trole": tenant_role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRES_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])


def _runtime_profile_to_user(profile: Optional[dict]) -> Optional[User]:
    if not profile:
        return None
    app_role = _system_role_to_app_role(profile.get("role"))
    auth_provider = str(profile.get("auth_provider") or "local").strip().lower() or "local"
    return User(
        _id=str(profile.get("id") or profile.get("_id") or ""),
        email=str(profile.get("email") or "").strip().lower(),
        name=str(profile.get("name") or "").strip() or str(profile.get("email") or "").split("@", 1)[0] or "User",
        role=app_role,
        password_hash="",
        avatar_url=profile.get("avatar_url"),
        active=True,
        auth_provider="google" if auth_provider == "google" else "local",
    )


async def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> User:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    user, _, _ = await _resolve_authenticated_request(creds.credentials)
    return user


class RequestContext(BaseModel):
    user: User
    tenant_id: str
    tenant_role: str
    access_token: Optional[str] = None
    token_kind: Optional[str] = None


async def ensure_default_tenant() -> str:
    global _DEFAULT_TENANT_ID
    if _DEFAULT_TENANT_ID:
        return _DEFAULT_TENANT_ID
    bridge = get_store()
    if is_supabase_service_configured():
        doc = await bridge.get_tenant_by_slug("default")
        if not doc:
            doc = await bridge.create_tenant(slug="default", name="Default")
        if doc:
            _DEFAULT_TENANT_ID = str(doc.get("_id") or doc.get("id") or "default")
            return _DEFAULT_TENANT_ID
        raise RuntimeError("Unable to resolve default tenant from Supabase")
    raise RuntimeError("Supabase service configuration is required for tenant bootstrap")


async def ensure_internal_wiki_tenant_id() -> str:
    global _INTERNAL_WIKI_TENANT_ID
    if _INTERNAL_WIKI_TENANT_ID:
        return _INTERNAL_WIKI_TENANT_ID
    slug = os.environ.get("INTERNAL_WIKI_TENANT_SLUG", "default").strip()
    bridge = get_store()
    if is_supabase_service_configured():
        doc = await bridge.get_tenant_by_slug(slug)
        if not doc:
            doc = await bridge.create_tenant(slug=slug, name="Internal")
        if doc:
            _INTERNAL_WIKI_TENANT_ID = str(doc.get("_id") or doc.get("id") or slug)
            return _INTERNAL_WIKI_TENANT_ID
        raise RuntimeError("Unable to resolve internal wiki tenant from Supabase")
    raise RuntimeError("Supabase service configuration is required for tenant bootstrap")


async def ensure_membership_for_tenant(user: User, tenant_id: str, role_if_create: Optional[str] = None) -> TenantMembership:
    bridge = get_store()
    if is_supabase_service_configured():
        doc = await bridge.get_user_membership(str(tenant_id), user.id)
        membership = _bridge_membership_to_model(doc)
        if membership and membership.status == "active":
            return membership
        role = normalize_tenant_role(role_if_create or ("owner" if can_manage_tenant(user.role, "owner") else "member"))
        created = await bridge.create_tenant_membership(str(tenant_id), user.id, role=role, status="active")
        membership = _bridge_membership_to_model(created)
        if membership:
            return membership
        raise RuntimeError("Unable to resolve tenant membership from Supabase")
    raise RuntimeError("Supabase service configuration is required for tenant membership resolution")


async def ensure_membership(user: User) -> TenantMembership:
    bridge = get_store()
    if is_supabase_service_configured():
        memberships = [item for item in await bridge.list_user_memberships(user.id, limit=50) if str((item or {}).get("status") or "") == "active"]
        if memberships:
            default_doc = next((item for item in memberships if bool((item or {}).get("is_default"))), memberships[0])
            membership = _bridge_membership_to_model(default_doc)
            if membership:
                return membership
        tenant_id = await ensure_default_tenant()
        created = await bridge.create_tenant_membership(
            tenant_id,
            user.id,
            role="owner" if can_manage_tenant(user.role, "owner") else "member",
            status="active",
            is_default=True,
        )
        membership = _bridge_membership_to_model(created)
        if membership:
            return membership
        raise RuntimeError("Unable to create default tenant membership from Supabase")
    raise RuntimeError("Supabase service configuration is required for tenant membership resolution")


async def get_current_context(request: Request, creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> RequestContext:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    raw_access_token = str(creds.credentials or "").strip()
    user, payload, token_kind = await _resolve_authenticated_request(raw_access_token)
    tenant_id = payload.get("tenant_id")
    tenant_role = payload.get("trole") if token_kind == "legacy" else _supabase_claim_role_to_tenant_role(payload.get("user_role"))
    host_tenant_id = await resolve_tenant_id_from_host(request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
    if host_tenant_id and str(host_tenant_id) != str(tenant_id or ""):
        m = None
        if is_supabase_service_configured():
            m = _bridge_membership_to_model(await get_store().get_user_membership(str(host_tenant_id), user.id))
        if not m:
            raise HTTPException(status_code=403, detail="Not a member of this tenant")
        tenant_id = m.tenant_id
        tenant_role = normalize_tenant_role(m.role)
    if not tenant_id or not tenant_role:
        membership = await ensure_membership(user)
        tenant_id = membership.tenant_id
        tenant_role = normalize_tenant_role(membership.role)
    return RequestContext(
        user=user,
        tenant_id=str(tenant_id),
        tenant_role=normalize_tenant_role(tenant_role),
        access_token=raw_access_token,
        token_kind=token_kind,
    )


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not can_manage_tenant(user.role, "admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def to_public(user: User) -> UserPublic:
    return UserPublic(id=user.id, email=user.email, name=user.name, role=user.role, avatar_url=user.avatar_url)


async def bootstrap_admin():
    """Create initial admin from env if it doesn't exist."""
    email = os.environ.get("ADMIN_BOOTSTRAP_EMAIL")
    pw = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD")
    if not email or not pw:
        return
    normalized_email = str(email).strip().lower()
    if is_supabase_service_configured():
        existing = await get_store().get_user_profile_by_email(normalized_email)
        if existing:
            return
        await _supabase_admin_create_user(
            email=normalized_email,
            password=pw,
            name="System Admin",
            app_role=APP_ROLE_SUPER_ADMIN,
            auth_provider="local",
        )
        return
    raise RuntimeError("Supabase service configuration is required for admin bootstrap")
