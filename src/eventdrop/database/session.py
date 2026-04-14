from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from eventdrop.database.engine import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
