from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eventdrop.database.models import AppSettings

DEFAULTS = {
    "allow_registration": "false",
}


async def get_setting(db: AsyncSession, key: str) -> str:
    result = await db.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return DEFAULTS.get(key, "")
    return row.value


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        row = AppSettings(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    await db.flush()


async def is_registration_allowed(db: AsyncSession) -> bool:
    val = await get_setting(db, "allow_registration")
    return val.lower() == "true"
