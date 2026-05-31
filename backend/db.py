"""DB + utility helpers (Mongo, encryption, datetime, ids)."""
import os
from datetime import datetime, timezone
from typing import Annotated, Any, Optional
import uuid

from bson import ObjectId
from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


# ---------- Mongo client ----------
_mongo_url = os.environ["MONGO_URL"]
_db_name = os.environ["DB_NAME"]
_client = AsyncIOMotorClient(_mongo_url)
db = _client[_db_name]


# ---------- ObjectId support ----------
def _to_str(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    return str(v)


PyObjectId = Annotated[str, BeforeValidator(_to_str)]


class BaseDocument(BaseModel):
    """Common doc base with id <-> _id mapping."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True, extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo(self) -> dict:
        d = self.model_dump(by_alias=True)
        # store datetimes as ISO strings for JSON safety
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    @classmethod
    def from_mongo(cls, doc: Optional[dict]):
        if not doc:
            return None
        d = dict(doc)
        for k in ("created_at", "updated_at"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = datetime.fromisoformat(d[k])
                except Exception:
                    pass
        return cls.model_validate(d)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


# ---------- Encryption for integration credentials ----------
_fernet = Fernet(os.environ["INTEGRATION_ENCRYPTION_KEY"].encode())


def encrypt_secret(value: str) -> str:
    if value is None:
        return ""
    return _fernet.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception:
        return ""
