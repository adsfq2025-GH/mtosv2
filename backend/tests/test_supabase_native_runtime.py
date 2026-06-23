import asyncio

from auth import RequestContext
from models import User
import supabase_native_runtime as runtime


class _FakeRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def list(self, table, *, filters=None, order=None):
        self.calls.append(
            {
                "table": table,
                "filters": dict(filters or {}),
                "order": order,
            }
        )
        return list(self.rows)


def _ctx(*, user_id: str, role: str = "manager", tenant_role: str = "member", token_kind=None, access_token=None):
    return RequestContext(
        user=User(_id=user_id, email=f"{user_id}@example.com", name=user_id, role=role, password_hash=""),
        tenant_id="tenant-1",
        tenant_role=tenant_role,
        token_kind=token_kind,
        access_token=access_token,
    )


def test_list_clients_filters_to_current_account_manager(monkeypatch):
    repo = _FakeRepo(
        [
            {"id": "client-1", "tenant_id": "tenant-1", "name": "Acme", "account_manager_user_id": "am-1", "is_deleted": False},
            {"id": "client-2", "tenant_id": "tenant-1", "name": "Beta", "account_manager_user_id": "am-2", "is_deleted": False},
        ]
    )
    monkeypatch.setattr(runtime, "_repo_for_ctx", lambda ctx: repo)

    docs = asyncio.run(runtime.list_clients(_ctx(user_id="am-1"), limit=25))

    assert [doc["_id"] for doc in docs] == ["client-1"]
    assert repo.calls[0]["table"] == "clients"
    assert repo.calls[0]["filters"]["tenant_id"] == "eq.tenant-1"
    assert repo.calls[0]["filters"]["is_deleted"] == "eq.false"
    assert repo.calls[0]["filters"]["limit"] == "25"


def test_list_clients_keeps_all_rows_for_admin(monkeypatch):
    repo = _FakeRepo(
        [
            {"id": "client-1", "tenant_id": "tenant-1", "name": "Acme", "account_manager_user_id": "am-1", "is_deleted": False},
            {"id": "client-2", "tenant_id": "tenant-1", "name": "Beta", "account_manager_user_id": "am-2", "is_deleted": False},
        ]
    )
    monkeypatch.setattr(runtime, "_repo_for_ctx", lambda ctx: repo)

    docs = asyncio.run(runtime.list_clients(_ctx(user_id="admin-1", role="admin", tenant_role="owner")))

    assert [doc["_id"] for doc in docs] == ["client-1", "client-2"]


def test_repo_for_ctx_uses_user_scoped_repository_for_supabase_tokens(monkeypatch):
    captured = {}

    class _RepoFactory:
        def __init__(self):
            captured["base_created"] = captured.get("base_created", 0) + 1

        def for_user(self, token: str):
            captured["token"] = token
            return "user-scoped-repo"

    monkeypatch.setattr(runtime, "SupabaseNativeRepository", _RepoFactory)

    repo = runtime._repo_for_ctx(
        _ctx(user_id="am-1", token_kind="supabase", access_token="supabase-access-token")
    )

    assert repo == "user-scoped-repo"
    assert captured["base_created"] == 1
    assert captured["token"] == "supabase-access-token"
