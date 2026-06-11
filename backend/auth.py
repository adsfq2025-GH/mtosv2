"""JWT auth helpers."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from db import db
from models import Tenant, TenantMembership, User, UserPublic
from runtime_bridge import get_runtime_bridge

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = os.environ.get("JWT_ALG", "HS256")
JWT_EXPIRES_HOURS = int(os.environ.get("JWT_EXPIRES_HOURS", "720"))

bearer = HTTPBearer(auto_error=False)
_DEFAULT_TENANT_ID: Optional[str] = None
_INTERNAL_WIKI_TENANT_ID: Optional[str] = None


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


async def resolve_tenant_id_from_host(host: str) -> Optional[str]:
    h = _norm_host(host)
    if not h:
        return None

    bridge_tenant_id = await get_runtime_bridge().resolve_tenant_legacy_id_from_host(h)
    if bridge_tenant_id:
        return bridge_tenant_id

    base_domain = os.environ.get("BASE_DOMAIN", "mapranking.com").strip().lower()
    if base_domain and h.endswith("." + base_domain):
        slug = h[: -(len(base_domain) + 1)].split(".", 1)[0].strip()
        if slug:
            doc = await db.tenants.find_one({"slug": slug, "status": "active"})
            if doc:
                return str(doc.get("_id"))

    doc = await db.tenant_domains.find_one({"domain": h})
    if doc:
        return str(doc.get("tenant_id"))
    return None


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
    system_role = str(profile.get("role") or "").strip().lower()
    app_role = "admin" if system_role == "platform_admin" else "manager"
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
    try:
        payload = decode_token(creds.credentials)
        user_id = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    doc = await db.users.find_one({"_id": user_id})
    if not doc:
        bridged_user = _runtime_profile_to_user(await get_runtime_bridge().get_user_profile(str(user_id or "")))
        if not bridged_user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return bridged_user
    return User.from_mongo(doc)


class RequestContext(BaseModel):
    user: User
    tenant_id: str
    tenant_role: str


async def ensure_default_tenant() -> str:
    global _DEFAULT_TENANT_ID
    if _DEFAULT_TENANT_ID:
        return _DEFAULT_TENANT_ID
    doc = await db.tenants.find_one({"slug": "default"})
    if not doc:
        t = Tenant(slug="default", name="Default")
        await db.tenants.insert_one(t.to_mongo())
        _DEFAULT_TENANT_ID = t.id
        return _DEFAULT_TENANT_ID
    _DEFAULT_TENANT_ID = doc.get("_id")
    return _DEFAULT_TENANT_ID


async def ensure_internal_wiki_tenant_id() -> str:
    global _INTERNAL_WIKI_TENANT_ID
    if _INTERNAL_WIKI_TENANT_ID:
        return _INTERNAL_WIKI_TENANT_ID
    slug = os.environ.get("INTERNAL_WIKI_TENANT_SLUG", "default").strip()
    doc = await db.tenants.find_one({"slug": slug})
    if not doc:
        t = Tenant(slug=slug, name="Internal")
        await db.tenants.insert_one(t.to_mongo())
        _INTERNAL_WIKI_TENANT_ID = t.id
        return _INTERNAL_WIKI_TENANT_ID
    _INTERNAL_WIKI_TENANT_ID = str(doc.get("_id"))
    return _INTERNAL_WIKI_TENANT_ID


async def ensure_membership_for_tenant(user: User, tenant_id: str, role_if_create: Optional[str] = None) -> TenantMembership:
    doc = await db.tenant_memberships.find_one({"user_id": user.id, "tenant_id": str(tenant_id), "status": "active"})
    if doc:
        return TenantMembership.from_mongo(doc)
    role = role_if_create or ("owner" if user.role == "admin" else "member")
    m = TenantMembership(tenant_id=str(tenant_id), user_id=user.id, role=role, status="active")
    await db.tenant_memberships.insert_one(m.to_mongo())
    return m


async def ensure_membership(user: User) -> TenantMembership:
    doc = await db.tenant_memberships.find_one({"user_id": user.id, "status": "active"})
    if doc:
        return TenantMembership.from_mongo(doc)
    tenant_id = await ensure_default_tenant()
    role = "owner" if user.role == "admin" else "member"
    m = TenantMembership(tenant_id=tenant_id, user_id=user.id, role=role, status="active")
    await db.tenant_memberships.insert_one(m.to_mongo())
    return m


async def get_current_context(request: Request, creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> RequestContext:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = decode_token(creds.credentials)
        user_id = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    doc = await db.users.find_one({"_id": user_id})
    user = User.from_mongo(doc) if doc else _runtime_profile_to_user(await get_runtime_bridge().get_user_profile(str(user_id or "")))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    tenant_id = payload.get("tenant_id")
    tenant_role = payload.get("trole")
    host_tenant_id = await resolve_tenant_id_from_host(request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
    if host_tenant_id and str(host_tenant_id) != str(tenant_id or ""):
        mdoc = await db.tenant_memberships.find_one({"user_id": user.id, "tenant_id": str(host_tenant_id), "status": "active"})
        if not mdoc:
            raise HTTPException(status_code=403, detail="Not a member of this tenant")
        m = TenantMembership.from_mongo(mdoc)
        tenant_id = m.tenant_id
        tenant_role = m.role
    if not tenant_id or not tenant_role:
        membership = await ensure_membership(user)
        tenant_id = membership.tenant_id
        tenant_role = membership.role
    return RequestContext(user=user, tenant_id=str(tenant_id), tenant_role=str(tenant_role))


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
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
    existing = await db.users.find_one({"email": email})
    if existing:
        return
    user = User(
        email=email,
        name="System Admin",
        role="admin",
        password_hash=hash_password(pw),
    )
    await db.users.insert_one(user.to_mongo())
