import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..core.config import POSTGRES_URL, POSTGRES_URL_DEV


logger = logging.getLogger(__name__)


# Create async engine and session factory
engine = create_async_engine(
    POSTGRES_URL_DEV,
    echo=False,
    pool_pre_ping=True,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_postgres_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session and ensure proper cleanup."""
    session: AsyncSession = AsyncSessionLocal()
    try:
        yield session
    finally:
        try:
            await session.close()
        except Exception as e:  # pragma: no cover
            logger.warning(f"Error closing Postgres session: {e}")


async def init_postgres_models() -> None:
    """Create tables if not present. Import models locally to avoid cycles."""
    try:
        from ..models.logs import Base  # type: ignore
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("PostgreSQL models initialized (create_all executed).")
    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL models: {e}")
        # Do not raise to avoid breaking app startup in dev


