from sqlalchemy import select
from database.db import async_session
from database.models import Admin
from config import SUPERADMIN_ID, DEFAULT_ADMIN_IDS


def _superadmin_id() -> int | None:
    if SUPERADMIN_ID:
        return SUPERADMIN_ID
    return DEFAULT_ADMIN_IDS[0] if DEFAULT_ADMIN_IDS else None


async def is_superadmin(telegram_id: int) -> bool:
    sid = _superadmin_id()
    return sid is not None and telegram_id == sid


async def is_admin(telegram_id: int) -> bool:
    """Returns True for superadmins and DB admins."""
    if await is_superadmin(telegram_id):
        return True
    async with async_session() as session:
        stmt = select(Admin).where(Admin.telegram_id == telegram_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def get_admin_district(telegram_id: int) -> str | None:
    """Returns the assigned district for a regular admin, or None for superadmin."""
    if await is_superadmin(telegram_id):
        return None
    async with async_session() as session:
        stmt = select(Admin).where(Admin.telegram_id == telegram_id)
        result = await session.execute(stmt)
        admin = result.scalar_one_or_none()
        return admin.district if admin else None
