import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from datetime import timedelta

from app.database.database import get_db
from app.schemas.schemas import UserCreate, UserLogin, TokenResponse, UserResponse
from app.services.auth_service import (
    authenticate_user, create_user, create_access_token,
    get_user_by_email, get_current_user
)
from app.config import settings
from app.limiter import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/register", response_model=TokenResponse)
@limiter.limit("5/minute")
async def register(request: Request, user_data: UserCreate, db: Session = Depends(get_db)):
    existing = get_user_by_email(db, user_data.email)
    if existing:
        logger.warning(f"Registration attempt with existing email: {user_data.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    user = create_user(db, user_data.email, user_data.name, user_data.password)
    logger.info(f"New user registered successfully: {user.email} (id: {user.id})")
    token = create_access_token(
        {"sub": user.id},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes)
    )
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user)
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, credentials: UserLogin, db: Session = Depends(get_db)):
    user = authenticate_user(db, credentials.email, credentials.password)
    if not user:
        logger.warning(f"Failed login attempt for: {credentials.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    logger.info(f"User logged in successfully: {user.email}")
    token = create_access_token(
        {"sub": user.id},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes)
    )
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user)
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user=Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
