from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


def get_async_url(url: str):
    """
    Normalize a PostgreSQL URL for asyncpg:
    - Converts postgres:// and postgresql:// to postgresql+asyncpg://
    - Strips sslmode= and ssl= from the query string entirely
    - Returns (url, connect_args) where connect_args carries the ssl setting
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Split URL into base and query string manually — urlparse can mishandle
    # the non-standard postgresql+asyncpg:// scheme in older Python builds.
    if "?" in url:
        base, query = url.split("?", 1)
    else:
        base, query = url, ""

    # Parse query params by hand to avoid any urlparse scheme whitelist issues
    params = {}
    if query:
        for part in query.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k] = v
            elif part:
                params[part] = ""

    sslmode = params.pop("sslmode", None)
    ssl_param = params.pop("ssl", None)

    # Determine effective ssl setting
    ssl_value = sslmode or ssl_param
    needs_ssl = ssl_value in ("require", "verify-ca", "verify-full", "true", "True", "1")

    connect_args = {"ssl": needs_ssl}

    # Rebuild URL without SSL params
    new_query = "&".join(f"{k}={v}" for k, v in params.items())
    final_url = f"{base}?{new_query}" if new_query else base

    return final_url, connect_args


import sys

_raw_url = settings.database_url
if not _raw_url:
    print("BMM-POS FATAL: DATABASE_URL is empty or not set", file=sys.stderr, flush=True)
    raise RuntimeError("DATABASE_URL is not configured")

_url, _connect_args = get_async_url(_raw_url)
print(f"BMM-POS: DB scheme={_url.split('://')[0] if '://' in _url else 'unknown'}", file=sys.stderr, flush=True)
engine = create_async_engine(
    _url,
    echo=False,
    connect_args=_connect_args,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=10,
    max_overflow=10,
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
