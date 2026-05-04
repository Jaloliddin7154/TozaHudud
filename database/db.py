from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.models import Base
from config import DB_PATH

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        # SQLite tuning: improves write/read throughput for bot workload.
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA synchronous=NORMAL"))
        await conn.execute(text("PRAGMA temp_store=MEMORY"))
        await conn.execute(text("PRAGMA cache_size=-20000"))

        await conn.run_sync(Base.metadata.create_all)

        # Ensure indexes exist for hot query paths.
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_reports_district ON reports(district)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_reports_region ON reports(region)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_admins_district ON admins(district)")
        )
