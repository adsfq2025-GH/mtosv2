import asyncio

from fastapi.security import HTTPAuthorizationCredentials

import auth


class _FakeBridge:
    async def get_user_profile(self, user_id: str):
        return None


def test_get_current_user_falls_back_to_supabase_admin_user(monkeypatch):
    monkeypatch.setattr(auth, "get_runtime_bridge", lambda: _FakeBridge())
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
    assert user.role == "admin"
