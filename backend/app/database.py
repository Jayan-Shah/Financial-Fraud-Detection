from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# --- FIX FOR ASYNCPG SSL ARGUMENT ---
# asyncpg expects 'ssl=' instead of 'sslmode='
async_db_url = settings.database_url
if async_db_url and "sslmode=" in async_db_url:
    async_db_url = async_db_url.replace("sslmode=", "ssl=")
# ------------------------------------

engine = create_async_engine(async_db_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()