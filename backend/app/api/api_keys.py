from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.models import User
from app.schemas.schemas import ApiKeyCreate, ApiKeyResponse, ApiKeyCreatedResponse
from app.services.auth_service import get_current_user
from app.services.api_key_service import (
    create_api_key, list_api_keys, revoke_api_key
)

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_key(
    data: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    api_key, full_key = create_api_key(db, current_user.id, data.name)
    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        key=full_key,
        status=api_key.status,
        created_at=api_key.created_at,
    )


@router.get("", response_model=List[ApiKeyResponse])
async def get_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    keys = list_api_keys(db, current_user.id)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/{key_id}")
async def delete_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    success = revoke_api_key(db, key_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"message": "API key revoked successfully"}
