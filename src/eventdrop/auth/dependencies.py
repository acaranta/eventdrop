from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import select

from eventdrop.database.engine import AsyncSessionLocal
from eventdrop.database.models import User


async def get_current_user_optional(request: Request) -> Optional[User]:
    """Return the authenticated User from session, or None if not logged in."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    return user


async def get_current_user(request: Request) -> User:
    """Return the authenticated User or raise HTTP 401."""
    user = await get_current_user_optional(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def require_admin(request: Request) -> User:
    """Return the authenticated admin User or raise HTTP 403."""
    user = await get_current_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
