import asyncio

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials

import auth


class _FakeBridge:
    async def get_user_profile(self, user_id: str):
        return None

    async def get_user_profile_by_email(self, email: str):
        return None


def test_get_current_user_falls_back_to_supabase_admin_user(monkeypatch):
    monkeypatch.setattr(auth, "get_store", lambda: _FakeBridge())
    async def fake_supabase_admin_get_user(user_id: str):
        return {
            "id": user_id,
            "email": "owner@example.com",
            "user_metadata": {"full_name": "Owner Name"},
            "app_metadata": {"provider": "email", "system_role": "system_admin"},
        }
    monkeypatch.setattr(
        auth,
        "_supabase_admin_get_user",
        fake_supabase_admin_get_user,
    )
    token = auth.create_token("user-123", "admin", "tenant-1", "owner")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = asyncio.run(auth.get_current_user(creds))
    assert user.id == "user-123"
    assert user.email == "owner@example.com"
    assert user.role == "department_admin"


def test_get_current_context_accepts_supabase_style_claims(monkeypatch):
    async def fake_supabase_get_user_from_access_token(token: str):
        return {
            "id": "supabase-user-1",
            "email": "manager@example.com",
            "user_metadata": {"full_name": "Manager Name"},
            "app_metadata": {"provider": "email", "system_role": "customer"},
        }

    async def fake_resolve_tenant_id_from_host(host: str):
        return None

    monkeypatch.setattr(auth, "_supabase_get_user_from_access_token", fake_supabase_get_user_from_access_token)
    monkeypatch.setattr(
        auth,
        "_decode_unverified_jwt",
        lambda token: {"sub": "supabase-user-1", "tenant_id": "tenant-123", "user_role": "manager"},
    )
    monkeypatch.setattr(auth, "resolve_tenant_id_from_host", fake_resolve_tenant_id_from_host)

    scope = {"type": "http", "headers": [(b"host", b"localhost")]}
    request = Request(scope)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="supabase-token")
    ctx = asyncio.run(auth.get_current_context(request, creds))

    assert ctx.user.id == "supabase-user-1"
    assert ctx.user.role == "account_manager"
    assert ctx.tenant_id == "tenant-123"
    assert ctx.tenant_role == "member"


def test_supabase_session_to_user_uses_claim_role():
    session = {
        "access_token": auth.create_token("ignored", "admin", "tenant-1", "owner"),
        "user": {
            "id": "supabase-google-user",
            "email": "google@example.com",
            "user_metadata": {"name": "Google User", "picture": "https://example.com/a.png"},
            "app_metadata": {"provider": "google", "system_role": "customer"},
        },
    }

    user = auth.supabase_session_to_user(session)

    assert user is not None
    assert user.id == "supabase-google-user"
    assert user.email == "google@example.com"
    assert user.role == "department_admin"
    assert user.auth_provider == "google"


def test_authenticate_password_user_uses_supabase_password_session(monkeypatch):
    monkeypatch.setattr(auth, "get_store", lambda: _FakeBridge())
    monkeypatch.setattr(auth, "is_supabase_service_configured", lambda: True)

    async def fake_supabase_password_login(email: str, password: str):
        assert email == "manager@example.com"
        assert password == "secret123"
        return {
            "id": "supabase-user-2",
            "email": email,
            "user_metadata": {"name": "Manager Name"},
            "app_metadata": {"provider": "email", "system_role": "customer"},
        }

    monkeypatch.setattr(auth, "_supabase_password_login", fake_supabase_password_login)

    user = asyncio.run(auth.authenticate_password_user("manager@example.com", "secret123"))

    assert user is not None
    assert user.id == "supabase-user-2"
    assert user.email == "manager@example.com"
    assert user.role == "account_manager"
    assert user.auth_provider == "local"


def test_role_normalization_and_admin_capabilities():
    assert auth.normalize_app_role("platform_admin") == "super_admin"
    assert auth.normalize_app_role("admin") == "department_admin"
    assert auth.normalize_app_role("manager") == "account_manager"
    assert auth.normalize_tenant_role("team_lead") == "lead"
    assert auth.can_manage_tenant("department_admin", "member") is True
    assert auth.can_manage_tenant("account_manager", "member") is False
