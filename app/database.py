from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


def get_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    sslmode = params.pop("sslmode", [None])[0]
    if sslmode in ("require", "verify-ca", "verify-full"):
        params["ssl"] = ["true"]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    url = urlunparse(parsed._replace(query=new_query))
    return url


engine = create_async_engine(get_async_url(settings.database_url), echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
