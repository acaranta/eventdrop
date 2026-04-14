from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from eventdrop.database.models import User
from eventdrop.auth.passwords import hash_password, verify_password
import uuid


async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_oidc_subject(db: AsyncSession, sub: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.oidc_subject == sub))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, username: str, password: Optional[str] = None,
                      email: Optional[str] = None, is_admin: bool = False,
                      oidc_subject: Optional[str] = None) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        password_hash=hash_password(password) if password else None,
        is_admin=is_admin,
        oidc_subject=oidc_subject,
    )
    db.add(user)
    await db.flush()
    return user


async def update_user_password(db: AsyncSession, user: User, new_password: str) -> User:
    user.password_hash = hash_password(new_password)
    await db.flush()
    return user


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def delete_user(db: AsyncSession, user_id: str) -> bool:
    user = await get_user_by_id(db, user_id)
    if user:
        await db.delete(user)
        await db.flush()
        return True
    return False
