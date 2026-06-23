"""Utility helpers (ids, datetime, encryption).

The backend is Supabase-only. MongoDB has been removed completely.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from cryptography.fernet import Fernet
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


# ---------- ID / datetime helpers ----------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def _coerce_id(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


PyObjectId = Annotated[str, BeforeValidator(_coerce_id)]


# ---------- Document base ----------
class BaseDocument(BaseModel):
    """Common document base (id + timestamps)."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True, extra="ignore")

    id: str = Field(default_factory=new_id, alias="_id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def to_mongo(self) -> dict:
        """Serialize for storage. Kept as ``to_mongo`` for compatibility."""
        d = self.model_dump(by_alias=True, mode="json")
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    @classmethod
    def from_mongo(cls, doc: Optional[dict]):
        """Build from a stored doc. Kept as ``from_mongo`` for compatibility."""
        if not doc:
            return None
        d = dict(doc)
        for k in ("created_at", "updated_at"):
            val = d.get(k)
            if isinstance(val, str):
                try:
                    d[k] = datetime.fromisoformat(val)
                except Exception:
                    pass
        return cls.model_validate(d)


# ---------- Encryption for integration credentials ----------
_fernet = Fernet(os.environ["INTEGRATION_ENCRYPTION_KEY"].encode())


def encrypt_secret(value: str) -> str:
    if value is None:
        return ""
    return _fernet.encrypt(str(value).encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet.decrypt(str(value).encode()).decode()
    except Exception:
        return ""