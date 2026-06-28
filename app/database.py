from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models import Base


def make_engine(settings: Settings):
    return create_async_engine(settings.database_url, echo=False)


def make_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(make_engine(settings), expire_on_commit=False)


async def init_db(session_factory: async_sessionmaker[AsyncSession]) -> None:
    engine = session_factory.kw["bind"]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            await conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN IF NOT EXISTS playoff_bonus_cents INTEGER NOT NULL DEFAULT 0"
                )
            )
        elif engine.dialect.name == "sqlite":
            columns = await conn.execute(text("PRAGMA table_info(users)"))
            column_names = {row[1] for row in columns}
            if "playoff_bonus_cents" not in column_names:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN playoff_bonus_cents INTEGER NOT NULL DEFAULT 0")
                )
        if engine.dialect.name == "postgresql":
            for value in ("btts", "double_chance", "to_qualify"):
                await conn.execute(
                    text(f"ALTER TYPE markettype ADD VALUE IF NOT EXISTS '{value}'")
                )
