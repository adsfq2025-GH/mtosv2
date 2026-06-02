"""JWT auth helpers."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from db import db
from models import Tenant, TenantMembership, User, UserPublic

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = os.environ.get("JWT_ALG", "HS256")
JWT_EXPIRES_HOURS = int(os.environ.get("JWT_EXPIRES_HOURS", "720"))

bearer = HTTPBearer(auto_error=False)
_DEFAULT_TENANT_ID: Optional[str] = None


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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
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


async def ensure_membership(user: User) -> TenantMembership:
    doc = await db.tenant_memberships.find_one({"user_id": user.id, "status": "active"})
    if doc:
        return TenantMembership.from_mongo(doc)
    tenant_id = await ensure_default_tenant()
    role = "owner" if user.role == "admin" else "member"
    m = TenantMembership(tenant_id=tenant_id, user_id=user.id, role=role, status="active")
    await db.tenant_memberships.insert_one(m.to_mongo())
    return m


async def get_current_context(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> RequestContext:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = decode_token(creds.credentials)
        user_id = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    doc = await db.users.find_one({"_id": user_id})
    if not doc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    user = User.from_mongo(doc)
    tenant_id = payload.get("tenant_id")
    tenant_role = payload.get("trole")
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
