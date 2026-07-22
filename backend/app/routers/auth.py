from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, get_current_user, verify_password
from app.database import get_db
from app.models import Organization, User
from app.redis_client import (
    sync_redis_client,
    login_attempts_key,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_LOCKOUT_SECONDS,
)
from app.schemas import LoginIn, MeOut, Token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)):
    attempts_key = login_attempts_key(payload.email)
    attempts = sync_redis_client.get(attempts_key)
    if attempts and int(attempts) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again in a few minutes.",
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        pipe = sync_redis_client.pipeline()
        pipe.incr(attempts_key)
        pipe.expire(attempts_key, LOGIN_LOCKOUT_SECONDS)
        pipe.execute()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    sync_redis_client.delete(attempts_key)

    token = create_access_token(subject=str(user.id), role=user.role, org_id=str(user.org_id))
    return Token(access_token=token, role=user.role)


@router.get("/me", response_model=MeOut)
async def me(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = result.scalar_one_or_none()
    return MeOut(
        email=user.email,
        role=user.role,
        organization_name=org.name if org else "Unknown Organization",
        organization_id=user.org_id,
    )
