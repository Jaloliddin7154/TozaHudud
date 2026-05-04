from datetime import datetime
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Report, User, Admin
from config import SUPERADMIN_ID, DEFAULT_ADMIN_IDS


async def create_report(
    session: AsyncSession,
    user_id: int,
    image_path: str,
    lat: float,
    lon: float,
    region: str,
    district: str,
    address: str,
) -> Report:
    report = Report(
        user_id=user_id,
        image_path=image_path,
        latitude=lat,
        longitude=lon,
        region=region,
        district=district,
        address=address,
        status="new",
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def get_notify_admin_ids(
    session: AsyncSession, region: str, district: str
) -> list[int]:
    """Returns deduplicated telegram_ids to notify for a new report.

    Always includes the config-level superadmin, DB superadmins, and any
    admin whose assigned region/district matches the report location.
    Falls back to all admins if nothing is configured.
    """
    ids: set[int] = set()

    # Config-level superadmin is always notified regardless of DB state.
    if SUPERADMIN_ID:
        ids.add(SUPERADMIN_ID)
    elif DEFAULT_ADMIN_IDS:
        ids.add(DEFAULT_ADMIN_IDS[0])

    # DB superadmins.
    res = await session.execute(select(Admin).where(Admin.role == "superadmin"))
    for a in res.scalars():
        ids.add(a.telegram_id)

    # District/region-matched admins (only when location is resolved).
    if region or district:
        stmt = select(Admin).where(
            (Admin.region == region) | (Admin.district == district)
        )
        res = await session.execute(stmt)
        for a in res.scalars():
            ids.add(a.telegram_id)

    # Fallback: if no one configured, notify all admins.
    if not ids:
        res = await session.execute(select(Admin))
        for a in res.scalars():
            ids.add(a.telegram_id)

    return list(ids)


async def get_default_admins(session: AsyncSession) -> list[Admin]:
    """Returns superadmins, or all admins if none set as superadmin."""
    stmt = select(Admin).where(Admin.role == "superadmin")
    result = await session.execute(stmt)
    admins = list(result.scalars().all())
    if not admins:
        stmt = select(Admin)
        result = await session.execute(stmt)
        admins = list(result.scalars().all())
    return admins


async def update_report_status(
    session: AsyncSession, report_id: int, status: str
) -> Report | None:
    stmt = select(Report).where(Report.id == report_id)
    result = await session.execute(stmt)
    report = result.scalar_one_or_none()
    if report:
        report.status = status
        await session.commit()
        await session.refresh(report)
    return report


async def update_report_geo(
    session: AsyncSession,
    report_id: int,
    region: str,
    district: str,
    address: str,
) -> None:
    result = await session.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if report:
        report.region = region
        report.district = district
        report.address = address
        await session.commit()


async def get_report_with_user(
    session: AsyncSession, report_id: int
) -> tuple[Report | None, User | None]:
    stmt = select(Report).where(Report.id == report_id)
    result = await session.execute(stmt)
    report = result.scalar_one_or_none()
    if not report:
        return None, None
    user_stmt = select(User).where(User.id == report.user_id)
    user_result = await session.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    return report, user


async def get_statistics(session: AsyncSession, district: str | None = None) -> dict:
    today = datetime.utcnow().date()

    filters = [Report.district == district] if district else []

    total = await session.scalar(
        select(func.count(Report.id)).where(*filters)
    ) or 0

    today_count = (
        await session.scalar(
            select(func.count(Report.id)).where(
                *filters,
                func.date(Report.created_at) == str(today),
            )
        )
        or 0
    )

    status_rows = await session.execute(
        select(Report.status, func.count(Report.id))
        .where(*filters)
        .group_by(Report.status)
    )
    region_rows = await session.execute(
        select(Report.region, func.count(Report.id))
        .where(*filters)
        .group_by(Report.region)
        .order_by(desc(func.count(Report.id)))
        .limit(10)
    )

    return {
        "total": total,
        "today": today_count,
        "by_status": {row[0] or "unknown": row[1] for row in status_rows.all()},
        "by_region": {row[0] or "Noma'lum": row[1] for row in region_rows.all()},
    }


async def get_all_reports(
    session: AsyncSession, district: str | None = None
) -> list[Report]:
    stmt = select(Report).order_by(desc(Report.created_at))
    if district:
        stmt = stmt.where(Report.district == district)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_distinct_districts(session: AsyncSession) -> list[str]:
    """Returns distinct districts that have at least one report."""
    rows = await session.execute(
        select(Report.district)
        .where(Report.district.isnot(None))
        .distinct()
        .order_by(Report.district)
    )
    return [r[0] for r in rows.all() if r[0]]
