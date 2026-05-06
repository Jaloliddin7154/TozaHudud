from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Report, User, Admin, ReportStatus
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
        status=ReportStatus.NEW,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def get_delivery_targets(
    session: AsyncSession,
    region: str,
    district: str,
) -> tuple[list[int], list[str]]:
    """Resolve recipient admins and channels for a report location.

    Rules:
    - district admins get only their district
    - region_admin gets all reports in their region
    - channels attached to matching admins also receive the report
    - config superadmin is always included in admin_ids
    """
    admin_ids: set[int] = set()
    channel_ids: set[str] = set()

    if SUPERADMIN_ID:
        admin_ids.add(SUPERADMIN_ID)
    elif DEFAULT_ADMIN_IDS:
        admin_ids.add(DEFAULT_ADMIN_IDS[0])

    db_superadmins = await session.execute(select(Admin).where(Admin.role == "superadmin"))
    for a in db_superadmins.scalars():
        admin_ids.add(a.telegram_id)
        if a.channel_id:
            channel_ids.add(a.channel_id)

    if district:
        district_stmt = select(Admin).where(Admin.district == district)
        district_rows = await session.execute(district_stmt)
        for a in district_rows.scalars():
            admin_ids.add(a.telegram_id)
            if a.channel_id:
                channel_ids.add(a.channel_id)

    if region:
        region_stmt = select(Admin).where(
            (Admin.region == region) & (Admin.role.in_(["region_admin", "superadmin"]))
        )
        region_rows = await session.execute(region_stmt)
        for a in region_rows.scalars():
            admin_ids.add(a.telegram_id)
            if a.channel_id:
                channel_ids.add(a.channel_id)

    if not admin_ids:
        fallback_rows = await session.execute(select(Admin))
        for a in fallback_rows.scalars():
            admin_ids.add(a.telegram_id)
            if a.channel_id:
                channel_ids.add(a.channel_id)

    return list(admin_ids), list(channel_ids)


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
    from sqlalchemy.orm import joinedload
    stmt = (
        select(Report)
        .options(joinedload(Report.user))
        .where(Report.id == report_id)
    )
    result = await session.execute(stmt)
    report = result.unique().scalar_one_or_none()
    if not report:
        return None, None
    return report, report.user


def _apply_scope(stmt, region: str | None, district: str | None):
    if district:
        return stmt.where(Report.district == district)
    if region:
        return stmt.where(Report.region == region)
    return stmt


async def get_statistics(
    session: AsyncSession,
    district: str | None = None,
    region: str | None = None,
) -> dict:
    today = datetime.now(timezone.utc).date()

    total_stmt = _apply_scope(select(func.count(Report.id)), region, district)
    total = await session.scalar(total_stmt) or 0

    today_count = (
        await session.scalar(
            _apply_scope(
                select(func.count(Report.id)).where(
                    func.date(Report.created_at) == str(today),
                ),
                region,
                district,
            )
        )
        or 0
    )

    status_rows = await session.execute(
        _apply_scope(
            select(Report.status, func.count(Report.id)).group_by(Report.status),
            region,
            district,
        )
    )
    region_rows = await session.execute(
        _apply_scope(
            select(Report.region, func.count(Report.id))
            .group_by(Report.region)
            .order_by(desc(func.count(Report.id)))
            .limit(10),
            region,
            district,
        )
    )

    return {
        "total": total,
        "today": today_count,
        "by_status": {row[0] or "unknown": row[1] for row in status_rows.all()},
        "by_region": {row[0] or "Noma'lum": row[1] for row in region_rows.all()},
    }


async def get_all_reports(
    session: AsyncSession,
    district: str | None = None,
    region: str | None = None,
) -> list[Report]:
    stmt = select(Report).order_by(desc(Report.created_at))
    stmt = _apply_scope(stmt, region, district)
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


# ── Period-filtered reports ────────────────────────────────────────────────


async def get_reports_filtered(
    session: AsyncSession,
    period: str,
    district: str | None = None,
    region: str | None = None,
) -> list[Report]:
    """Return reports filtered by time period.
    period: 'today' | 'month' | 'year' | 'all'
    """
    now = datetime.now(timezone.utc)
    stmt = select(Report).order_by(desc(Report.created_at))
    stmt = _apply_scope(stmt, region, district)
    if period == "today":
        day_str = now.strftime("%Y-%m-%d")
        stmt = stmt.where(func.strftime("%Y-%m-%d", Report.created_at) == day_str)
    elif period == "month":
        month_str = now.strftime("%Y-%m")
        stmt = stmt.where(func.strftime("%Y-%m", Report.created_at) == month_str)
    elif period == "year":
        year_str = now.strftime("%Y")
        stmt = stmt.where(func.strftime("%Y", Report.created_at) == year_str)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ── Aggregate time-series stats ────────────────────────────────────────────


async def get_daily_stats(
    session: AsyncSession,
    district: str | None = None,
    region: str | None = None,
    days: int = 30,
) -> list[dict]:
    """Report count per day for the last *days* days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    stmt = (
        select(
            func.strftime("%Y-%m-%d", Report.created_at).label("day"),
            func.count(Report.id).label("cnt"),
        )
        .where(func.strftime("%Y-%m-%d", Report.created_at) >= cutoff)
        .group_by("day")
        .order_by("day")
    )
    stmt = _apply_scope(stmt, region, district)
    rows = await session.execute(stmt)
    return [{"label": r.day, "count": r.cnt} for r in rows.all()]


async def get_monthly_stats(
    session: AsyncSession,
    district: str | None = None,
    region: str | None = None,
    months: int = 12,
) -> list[dict]:
    """Report count per month for the last *months* months."""
    cutoff_date = datetime.now(timezone.utc).replace(day=1) - timedelta(days=30 * months)
    cutoff = cutoff_date.strftime("%Y-%m")
    stmt = (
        select(
            func.strftime("%Y-%m", Report.created_at).label("month"),
            func.count(Report.id).label("cnt"),
        )
        .where(func.strftime("%Y-%m", Report.created_at) >= cutoff)
        .group_by("month")
        .order_by("month")
    )
    stmt = _apply_scope(stmt, region, district)
    rows = await session.execute(stmt)
    return [{"label": r.month, "count": r.cnt} for r in rows.all()]


async def get_yearly_stats(
    session: AsyncSession,
    district: str | None = None,
    region: str | None = None,
) -> list[dict]:
    """Report count per year (all time)."""
    stmt = (
        select(
            func.strftime("%Y", Report.created_at).label("year"),
            func.count(Report.id).label("cnt"),
        )
        .group_by("year")
        .order_by("year")
    )
    stmt = _apply_scope(stmt, region, district)
    rows = await session.execute(stmt)
    return [{"label": r.year, "count": r.cnt} for r in rows.all()]


# ── User & location stats ──────────────────────────────────────────────────


async def get_user_report_counts(
    session: AsyncSession,
    district: str | None = None,
    region: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Top users by number of submitted reports."""
    stmt = (
        select(
            User.telegram_id,
            User.full_name,
            User.username,
            func.count(Report.id).label("cnt"),
        )
        .join(User, Report.user_id == User.id)
        .group_by(User.id)
        .order_by(desc("cnt"))
        .limit(limit)
    )
    stmt = _apply_scope(stmt, region, district)
    rows = await session.execute(stmt)
    return [
        {
            "telegram_id": r.telegram_id,
            "full_name": r.full_name or r.username or str(r.telegram_id),
            "count": r.cnt,
        }
        for r in rows.all()
    ]


async def get_location_hotspots(
    session: AsyncSession,
    district: str | None = None,
    region: str | None = None,
    limit: int = 15,
) -> list[dict]:
    """Most frequently reported locations (coordinates rounded to ~110 m)."""
    stmt = (
        select(
            func.round(Report.latitude, 3).label("lat"),
            func.round(Report.longitude, 3).label("lon"),
            func.count(Report.id).label("cnt"),
            func.max(Report.address).label("address"),
            func.max(Report.district).label("district"),
        )
        .where(Report.latitude.isnot(None))
        .where(Report.longitude.isnot(None))
        .group_by("lat", "lon")
        .order_by(desc("cnt"))
        .limit(limit)
    )
    stmt = _apply_scope(stmt, region, district)
    rows = await session.execute(stmt)
    return [
        {
            "lat": r.lat,
            "lon": r.lon,
            "count": r.cnt,
            "address": r.address or "",
            "district": r.district or "",
        }
        for r in rows.all()
    ]
