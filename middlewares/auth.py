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
    if sid is not None and telegram_id == sid:
        return True

    async with async_session() as session:
        stmt = select(Admin).where(
            (Admin.telegram_id == telegram_id) & (Admin.role == "superadmin")
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def is_admin(telegram_id: int) -> bool:
    """Returns True for superadmins and DB admins."""
    if await is_superadmin(telegram_id):
        return True
    async with async_session() as session:
        stmt = select(Admin).where(Admin.telegram_id == telegram_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def get_admin_scope(telegram_id: int) -> dict[str, str | bool | None]:
    """Returns scope used for filtering reports and stats.

    - superadmin: full access (region=None, district=None)
    - region_admin: region-wide access
    - admin/district_admin: district-only access
    """
    if await is_superadmin(telegram_id):
        return {
            "is_superadmin": True,
            "role": "superadmin",
            "region": None,
            "district": None,
        }

    async with async_session() as session:
        stmt = select(Admin).where(Admin.telegram_id == telegram_id)
        result = await session.execute(stmt)
        admin = result.scalar_one_or_none()
        if not admin:
            return {
                "is_superadmin": False,
                "role": None,
                "region": None,
                "district": None,
            }

        role = (admin.role or "admin").strip().lower()
        if role == "region_admin":
            return {
                "is_superadmin": False,
                "role": role,
                "region": admin.region,
                "district": None,
            }

        return {
            "is_superadmin": False,
            "role": role,
            "region": admin.region,
            "district": admin.district,
        }


async def is_region_admin(telegram_id: int) -> bool:
    scope = await get_admin_scope(telegram_id)
    return bool(scope.get("role") == "region_admin")
