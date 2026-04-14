from typing import Optional

from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from eventdrop.database.session import get_db
from eventdrop.database.models import User


async def get_current_user_optional(request: Request, db: AsyncSession = Depends(get_db)) -> Optional[User]:
    """Returns current user from session, or None if not logged in."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Returns current user, raises 302 redirect to login if not logged in."""
    user = await get_current_user_optional(request, db)
    if user is None:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    return user


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Returns current user, raises 403 if not admin."""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
