import secrets
import hashlib
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.models.models import ApiKey, ApiKeyStatus, User


def generate_api_key() -> Tuple[str, str, str]:
    """
    Generate a new API key.
    Returns (full_key, prefix, key_hash)
    """
    random_part = secrets.token_urlsafe(24)
    full_key = f"wha_live_{random_part}"
    prefix = full_key[:16]
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, prefix, key_hash


def create_api_key(db: Session, user_id: str, name: str) -> Tuple[ApiKey, str]:
    """Create a new API key. Returns (api_key_record, full_key)."""
    full_key, prefix, key_hash = generate_api_key()

    api_key = ApiKey(
        user_id=user_id,
        name=name,
        key_hash=key_hash,
        prefix=prefix,
        status=ApiKeyStatus.active,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key, full_key


def list_api_keys(db: Session, user_id: str):
    return (
        db.query(ApiKey)
        .filter(ApiKey.user_id == user_id, ApiKey.status == ApiKeyStatus.active)
        .order_by(ApiKey.created_at.desc())
        .all()
    )


def revoke_api_key(db: Session, key_id: str, user_id: str) -> bool:
    key = db.query(ApiKey).filter(
        ApiKey.id == key_id, ApiKey.user_id == user_id
    ).first()
    if not key:
        return False
    key.status = ApiKeyStatus.revoked
    db.commit()
    return True


def validate_api_key(db: Session, raw_key: str) -> Optional[ApiKey]:
    """Validate an API key and return the record if valid."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = db.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.status == ApiKeyStatus.active,
    ).first()

    if api_key:
        api_key.last_used_at = datetime.now(timezone.utc)
        db.commit()

    return api_key
