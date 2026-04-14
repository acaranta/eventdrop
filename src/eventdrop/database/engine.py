from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from eventdrop.config import settings

engine = create_async_engine(
    settings.get_database_url(),
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
