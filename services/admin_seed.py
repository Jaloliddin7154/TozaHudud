import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Admin

logger = logging.getLogger(__name__)


def _parse_assignments(raw: str) -> list[dict]:
    """Parse ADMIN_ASSIGNMENTS env value.

    Format:
    tg_id|role|region|district|channel_id;tg_id2|role|region|district|channel_id2

    Notes:
    - role: superadmin | region_admin | admin
    - Use '-' for empty region or district.
    """
    items: list[dict] = []
    if not raw:
        return items

    for idx, chunk in enumerate(raw.split(";"), 1):
        part = chunk.strip()
        if not part:
            continue

        fields = [x.strip() for x in part.split("|")]
        if len(fields) != 5:
            logger.warning("ADMIN_ASSIGNMENTS format xato (qism %s): %s", idx, part)
            continue

        tg_id_s, role, region, district, channel_id = fields
        if not tg_id_s.lstrip("-").isdigit():
            logger.warning("ADMIN_ASSIGNMENTS tg_id xato (qism %s): %s", idx, tg_id_s)
            continue

        role = role.lower()
        if role not in {"superadmin", "region_admin", "admin"}:
            logger.warning("ADMIN_ASSIGNMENTS role xato (qism %s): %s", idx, role)
            continue

        items.append(
            {
                "telegram_id": int(tg_id_s),
                "role": role,
                "region": None if region in {"", "-"} else region,
                "district": None if district in {"", "-"} else district,
                "channel_id": channel_id,
            }
        )

    return items


async def seed_admin_assignments(session: AsyncSession, raw: str) -> tuple[int, int]:
    """Upsert admins from ADMIN_ASSIGNMENTS.

    Returns: (created_count, updated_count)
    """
    entries = _parse_assignments(raw)
    if not entries:
        return 0, 0

    created = 0
    updated = 0

    for e in entries:
        stmt = select(Admin).where(Admin.telegram_id == e["telegram_id"])
        result = await session.execute(stmt)
        admin = result.scalar_one_or_none()

        if admin is None:
            session.add(
                Admin(
                    telegram_id=e["telegram_id"],
                    role=e["role"],
                    region=e["region"],
                    district=e["district"],
                    channel_id=e["channel_id"],
                )
            )
            created += 1
        else:
            admin.role = e["role"]
            admin.region = e["region"]
            admin.district = e["district"]
            admin.channel_id = e["channel_id"]
            updated += 1

    await session.commit()
    return created, updated
