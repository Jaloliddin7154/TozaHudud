from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from sqlalchemy import select

from database.db import async_session
from database.models import Admin, Region, User
from handlers.states import (
    AdminAddRegion,
    AdminAddAdmin,
    AdminRemoveAdmin,
    AdminEditRegion,
    AdminSetChannel,
)
from keyboards.admin_kb import (
    admin_panel_kb,
    region_admin_panel_kb,
    superadmin_panel_kb,
    region_type_kb,
    admin_manage_kb,
    report_status_kb,
    regions_list_kb,
    region_actions_kb,
    region_confirm_delete_kb,
    region_new_type_kb,
    export_period_kb,
    export_district_filter_kb,
    export_format_kb,
)
from database.models import ReportStatus
from middlewares.auth import is_admin, is_superadmin, get_admin_scope
from services import report as report_service
from utils.export import export_to_excel, export_to_pdf
from utils.relay import relay_get, relay_set


class AdminFilter(BaseFilter):
    """Passes only when the sender is a registered admin or superadmin."""
    async def __call__(self, message: Message) -> bool:
        return await is_admin(message.from_user.id)

logger = logging.getLogger(__name__)
router = Router()

STATUS_NAMES: dict[str, str] = {
    ReportStatus.DONE:        "✅ Bajarildi",
    ReportStatus.IN_PROGRESS: "🔄 Jarayonda",
    ReportStatus.REJECTED:    "❌ Rad etildi",
}

STATUS_UZ: dict[str, str] = {
    ReportStatus.NEW:         "Yangi",
    ReportStatus.IN_PROGRESS: "Jarayonda",
    ReportStatus.DONE:        "Bajarildi",
    ReportStatus.REJECTED:    "Rad etildi",
}


def _parse_tg_id(text: str) -> int | None:
    """Parse a Telegram ID string. Returns None if invalid."""
    try:
        return int(text.strip())
    except ValueError:
        return None


def _is_admin_manager(scope: dict) -> bool:
    return bool(scope.get("is_superadmin") or scope.get("role") == "region_admin")


def _panel_from_scope(scope: dict):
    if scope.get("is_superadmin"):
        return superadmin_panel_kb()
    if scope.get("role") == "region_admin":
        return region_admin_panel_kb()
    return admin_panel_kb()


def _actor_scope_from_state(data: dict) -> dict:
    return {
        "is_superadmin": bool(data.get("creator_is_superadmin")),
        "role": data.get("creator_role"),
        "region": data.get("creator_region"),
    }


def _can_manage_target(actor_scope: dict, target: Admin) -> bool:
    """True if actor can manage target admin account."""
    if actor_scope.get("is_superadmin"):
        return True
    if actor_scope.get("role") != "region_admin":
        return False
    actor_region = actor_scope.get("region")
    # Region admin can manage only district-level admins in own region.
    if target.role in {"superadmin", "region_admin"}:
        return False
    return bool(actor_region and target.region == actor_region)


@router.message(Command("clearcache"))
async def cmd_clear_cache(message: Message) -> None:
    """Superadmin-only: remove all __pycache__ directories in the project."""
    if not await is_superadmin(message.from_user.id):
        await message.answer("⛔ Bu buyruq faqat superadmin uchun.")
        return

    project_root = Path(__file__).resolve().parents[1]
    cache_dirs = [p for p in project_root.rglob("__pycache__") if p.is_dir()]

    if not cache_dirs:
        await message.answer("✅ __pycache__ papkalar topilmadi.")
        return

    removed = 0
    for cache_dir in sorted(cache_dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            shutil.rmtree(cache_dir)
            removed += 1
        except Exception as e:
            logger.warning("Could not remove cache directory %s: %s", cache_dir, e)

    await message.answer(
        f"🧹 Tozalash yakunlandi.\n"
        f"O'chirilgan __pycache__ papkalar: <b>{removed}</b>"
    )


# ──────────────────────────────────────────────
# /admin — panel entry
# ──────────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ Sizda admin huquqi yo'q.")
        return
    await state.clear()
    scope = await get_admin_scope(message.from_user.id)
    panel_kb = _panel_from_scope(scope)
    await message.answer(
        "🛠 <b>Admin panelga xush kelibsiz!</b>\n"
        "Quyidagi bo'limlardan birini tanlang:",
        reply_markup=panel_kb,
    )


# ──────────────────────────────────────────────
# Statistics
# ──────────────────────────────────────────────
@router.message(F.text == "📊 Statistika")
async def show_stats(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return

    async with async_session() as session:
        scope = await get_admin_scope(message.from_user.id)
        district = scope.get("district")
        region = scope.get("region")
        stats = await report_service.get_statistics(session, district=district, region=region)
        user_stats = await report_service.get_user_report_counts(
            session, district=district, region=region, limit=5
        )
        loc_stats = await report_service.get_location_hotspots(
            session, district=district, region=region, limit=3
        )

    status_lines = "\n".join(
        f"  • {STATUS_UZ.get(k, k)}: <b>{v}</b>" for k, v in stats["by_status"].items()
    ) or "  Yo'q"
    region_lines = "\n".join(
        f"  • {k}: <b>{v}</b>" for k, v in list(stats["by_region"].items())[:5]
    ) or "  Yo'q"

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    user_lines = "\n".join(
        f"  {medals[i]} {u['full_name']} — <b>{u['count']}</b> ta"
        for i, u in enumerate(user_stats)
    ) or "  Yo'q"

    no_address = "Manzil yo'q"
    hot_lines = "\n".join(
        f"  🔴 {loc['address'] or no_address} ({loc['district'] or '?'}) — <b>{loc['count']}</b> marta"
        for loc in loc_stats
    ) or "  Yo'q"

    area_name = district or region
    district_label = f" — <b>{area_name}</b>" if area_name else " — barcha hududlar"
    await message.answer(
        f"📊 <b>Statistika</b>{district_label}\n\n"
        f"📋 Jami xabarlar: <b>{stats['total']}</b>\n"
        f"📅 Bugungi: <b>{stats['today']}</b>\n\n"
        f"📌 Status bo'yicha:\n{status_lines}\n\n"
        f"🗺 Hudud bo'yicha (top 5):\n{region_lines}\n\n"
        f"👥 Eng faol foydalanuvchilar:\n{user_lines}\n\n"
        f"🔥 Eng ko'p murojaat qilingan joylar:\n{hot_lines}"
    )


# ──────────────────────────────────────────────
# Reports list
# ──────────────────────────────────────────────
@router.message(F.text == "📋 Xabarlar ro'yxati")
async def list_reports(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return

    async with async_session() as session:
        scope = await get_admin_scope(message.from_user.id)
        district = scope.get("district")
        region = scope.get("region")
        reports = await report_service.get_all_reports(session, district=district, region=region)

    if not reports:
        await message.answer("📭 Hozircha xabarlar yo'q.")
        return

    status_emoji = {"new": "🆕", "in_progress": "🔄", "done": "✅", "rejected": "❌"}
    lines = []
    unknown = "Noma'lum"
    for r in reports[:20]:
        emoji = status_emoji.get(r.status or "", "❓")
        date_str = r.created_at.strftime("%d.%m.%Y") if r.created_at else "N/A"
        lines.append(
            f"{emoji} <b>#{r.id}</b> | {date_str}\n"
            f"   📍 {r.region or unknown} / {r.district or unknown}"
        )

    area_name = district or region
    district_label = f" ({area_name})" if area_name else " (barcha)"
    await message.answer(f"📋 <b>So'nggi 20 xabar{district_label}:</b>\n\n" + "\n\n".join(lines))


# ──────────────────────────────────────────────
# Export — Step 1: period selection
# ──────────────────────────────────────────────
@router.message(F.text == "📥 Hisobot yuklash")
async def download_report_menu(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "📅 <b>Qaysi davr bo'yicha hisobot kerak?</b>",
        reply_markup=export_period_kb(),
    )


# ── Step 2: period chosen → district (superadmin) or format (regular admin) ─
_PERIOD_LABELS = {
    "today": "Bugungi",
    "month": "Joriy oy",
    "year":  "Joriy yil",
    "all":   "Barchasi",
}


@router.callback_query(F.data.startswith("xper:"))
async def export_period_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    period = callback.data[len("xper:"):]
    await state.update_data(export_period=period)
    period_label = _PERIOD_LABELS.get(period, period)

    if await is_superadmin(callback.from_user.id):
        async with async_session() as session:
            districts = await report_service.get_distinct_districts(session)
        if not districts:
            await callback.message.edit_text("📭 Hozircha eksport qilish uchun ma'lumot yo'q.")
            await callback.answer()
            return
        await callback.message.edit_text(
            f"✅ Davr: <b>{period_label}</b>\n\n"
            "🗺 Qaysi hudud bo'yicha hisobot?",
            reply_markup=export_district_filter_kb(districts),
        )
    else:
        await callback.message.edit_text(
            f"✅ Davr: <b>{period_label}</b>\n\n"
            "📄 Hisobot formatini tanlang:",
            reply_markup=export_format_kb(),
        )
    await callback.answer()


# ── Step 3 (superadmin only): district chosen → format ─────────────────────
@router.callback_query(F.data.startswith("xfilt:"))
async def export_filter_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    selected = callback.data[len("xfilt:"):]
    district = None if selected == "__all__" else selected
    await state.update_data(export_district=district)
    label = district or "Barchasi"
    data = await state.get_data()
    period_label = _PERIOD_LABELS.get(data.get("export_period", "all"), "Barchasi")
    await callback.message.edit_text(
        f"✅ Davr: <b>{period_label}</b>   |   Hudud: <b>{label}</b>\n\n"
        "📄 Hisobot formatini tanlang:",
        reply_markup=export_format_kb(),
    )
    await callback.answer()


# ── Step 4: format chosen → generate & send ────────────────────────────────
@router.callback_query(F.data.startswith("xfmt:"))
async def export_format_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    fmt = callback.data[len("xfmt:"):]

    fsm_data = await state.get_data()
    period: str = fsm_data.get("export_period", "all")

    if await is_superadmin(callback.from_user.id):
        district: str | None = fsm_data.get("export_district")
        region: str | None = None
    else:
        scope = await get_admin_scope(callback.from_user.id)
        district = scope.get("district")
        region = scope.get("region")

    await state.clear()

    period_label = _PERIOD_LABELS.get(period, period)
    area_name = district or region or "Barchasi"
    await callback.answer(f"⏳ {period_label} / {area_name} — tayyorlanmoqda...")

    async with async_session() as session:
        reports = await report_service.get_reports_filtered(
            session, period, district=district, region=region
        )
        stats = await report_service.get_statistics(session, district=district, region=region)
        user_stats = await report_service.get_user_report_counts(
            session, district=district, region=region
        )
        location_stats = await report_service.get_location_hotspots(
            session, district=district, region=region
        )
        daily_stats = await report_service.get_daily_stats(session, district=district, region=region)
        monthly_stats = await report_service.get_monthly_stats(session, district=district, region=region)
        yearly_stats = await report_service.get_yearly_stats(session, district=district, region=region)

    if fmt == "excel":
        file_bytes = await asyncio.to_thread(
            export_to_excel,
            reports, period_label, stats,
            user_stats, location_stats,
            daily_stats, monthly_stats, yearly_stats,
            area_name,
        )
        safe_name = area_name.replace(" ", "_")
        filename = f"toza_hudud_{safe_name}_{period}.xlsx"
        file = BufferedInputFile(file_bytes, filename=filename)
        await callback.message.answer_document(
            file,
            caption=(
                f"📊 <b>Excel hisobot</b>\n"
                f"📅 Davr: <b>{period_label}</b>\n"
                f"🗺 Hudud: <b>{area_name}</b>\n"
                f"📋 Xabarlar: <b>{len(reports)}</b> ta\n"
                f"📑 Varaqlar: Umumiy · Xabarlar · Kunlik · Oylik · Yillik · Faollik"
            ),
        )
    else:
        file_bytes = await asyncio.to_thread(export_to_pdf, reports, stats)
        safe_name = area_name.replace(" ", "_")
        filename = f"toza_hudud_{safe_name}_{period}.pdf"
        file = BufferedInputFile(file_bytes, filename=filename)
        await callback.message.answer_document(
            file,
            caption=f"📄 PDF hisobot — <b>{period_label}</b> / <b>{area_name}</b>",
        )


# ──────────────────────────────────────────────
# Report status update
# ──────────────────────────────────────────────
@router.callback_query(F.data.startswith("status:"))
async def update_status_cb(callback: CallbackQuery, bot: Bot) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    _, new_status, report_id_str = callback.data.split(":", 2)
    if new_status not in ReportStatus.__members__.values():
        await callback.answer("⚠️ Noma'lum status", show_alert=True)
        return
    report_id = int(report_id_str)

    async with async_session() as session:
        report = await report_service.update_report_status(session, report_id, new_status)
        if not report:
            await callback.answer("⚠️ Xabar topilmadi", show_alert=True)
            return

        user_stmt = select(User).where(User.id == report.user_id)
        user_result = await session.execute(user_stmt)
        user = user_result.scalar_one_or_none()

    # Notify user
    if user:
        status_text = {
            ReportStatus.DONE:        "✅ Muammo hal qilindi",
            ReportStatus.IN_PROGRESS: "🔄 Muammo ko'rib chiqilmoqda",
            ReportStatus.REJECTED:    "❌ Xabar rad etildi",
        }.get(new_status, new_status)
        try:
            await bot.send_message(
                user.telegram_id,
                f"📢 <b>Xabaringiz holati yangilandi!</b>\n\n"
                f"🆔 Xabar #{report_id}\n"
                f"📌 Holat: {status_text}",
            )
        except Exception as e:
            logger.error("Could not notify user %s: %s", user.telegram_id, e)

    label = STATUS_NAMES.get(new_status, new_status)
    await callback.answer(f"Status: {label}", show_alert=False)

    # Update caption — replace existing status line or append; always keep keyboard.
    try:
        original_caption = callback.message.caption or ""
        status_line = f"\n\n📌 Status: {label}"
        if "📌 Status:" in original_caption:
            new_caption = re.sub(r"\n\n📌 Status:.*", status_line, original_caption)
        else:
            new_caption = original_caption + status_line
        await callback.message.edit_caption(
            caption=new_caption,
            reply_markup=report_status_kb(report_id),
        )
    except Exception:
        pass  # Caption unchanged or message too old


# ──────────────────────────────────────────────
# Region management
# ──────────────────────────────────────────────
@router.message(F.text == "🗺 Hudud qo'shish")
async def add_region_start(message: Message, state: FSMContext) -> None:
    if not await is_superadmin(message.from_user.id):
        return
    await state.set_state(AdminAddRegion.waiting_name)
    await message.answer("🗺 Yangi hudud nomini kiriting (masalan: Samarqand viloyati):")


@router.message(AdminAddRegion.waiting_name, AdminFilter(), F.text)
async def add_region_name(message: Message, state: FSMContext) -> None:
    await state.update_data(region_name=message.text.strip())
    await state.set_state(AdminAddRegion.waiting_type)
    await message.answer("Hudud turini tanlang:", reply_markup=region_type_kb())


@router.callback_query(F.data.startswith("region_type:"))
async def add_region_type_cb(callback: CallbackQuery, state: FSMContext) -> None:
    region_type = callback.data.split(":")[1]
    data = await state.get_data()
    region_name: str = data.get("region_name", "")

    async with async_session() as session:
        region = Region(name=region_name, type=region_type)
        session.add(region)
        await session.commit()

    await state.clear()
    await callback.message.edit_text(
        f"✅ Hudud muvaffaqiyatli qo'shildi!\n\n"
        f"📍 Nomi: <b>{region_name}</b>\n"
        f"🏷 Turi: <b>{region_type}</b>"
    )
    await callback.answer()
    await callback.message.answer("Admin panelga qaytish:", reply_markup=superadmin_panel_kb())


# ──────────────────────────────────────────────
# Regions management (list / edit / delete)
# ──────────────────────────────────────────────
async def _send_regions_list(target, session) -> None:
    result = await session.execute(select(Region).order_by(Region.type, Region.name))
    regions = list(result.scalars().all())
    if not regions:
        await target.answer("📭 Hozircha hududlar yo'q.")
        return
    await target.answer(
        f"🗺 <b>Hududlar ro'yxati</b> ({len(regions)} ta)\n"
        "Tahrirlash yoki o'chirish uchun tanlang:",
        reply_markup=regions_list_kb(regions),
    )


@router.message(F.text == "📝 Hududlar boshqaruvi")
async def regions_manage_menu(message: Message) -> None:
    if not await is_superadmin(message.from_user.id):
        return
    async with async_session() as session:
        await _send_regions_list(message, session)


@router.callback_query(F.data == "regions_back")
async def regions_back_cb(callback: CallbackQuery) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    async with async_session() as session:
        result = await session.execute(select(Region).order_by(Region.type, Region.name))
        regions = list(result.scalars().all())
    if not regions:
        await callback.message.edit_text("📭 Hozircha hududlar yo'q.")
    else:
        await callback.message.edit_text(
            f"🗺 <b>Hududlar ro'yxati</b> ({len(regions)} ta)\n"
            "Tahrirlash yoki o'chirish uchun tanlang:",
            reply_markup=regions_list_kb(regions),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("region_manage:"))
async def region_manage_cb(callback: CallbackQuery) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    region_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        region = await session.get(Region, region_id)
    if not region:
        await callback.answer("⚠️ Hudud topilmadi", show_alert=True)
        return
    await callback.message.edit_text(
        f"🗺 <b>{region.name}</b>\n"
        f"🏷 Turi: <b>{region.type}</b>\n\n"
        "Amalni tanlang:",
        reply_markup=region_actions_kb(region_id),
    )
    await callback.answer()


# --- Edit name ---
@router.callback_query(F.data.startswith("region_edit_name:"))
async def region_edit_name_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    region_id = int(callback.data.split(":")[1])
    await state.set_state(AdminEditRegion.waiting_new_name)
    await state.update_data(edit_region_id=region_id)
    await callback.message.answer("✏️ Yangi hudud nomini kiriting:")
    await callback.answer()


@router.message(AdminEditRegion.waiting_new_name, AdminFilter(), F.text)
async def region_save_new_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    region_id: int = data["edit_region_id"]
    new_name = message.text.strip()
    async with async_session() as session:
        region = await session.get(Region, region_id)
        if not region:
            await message.answer("⚠️ Hudud topilmadi.")
            await state.clear()
            return
        old_name = region.name
        region.name = new_name
        await session.commit()
    await state.clear()
    await message.answer(
        f"✅ Hudud nomi yangilandi!\n\n"
        f"<s>{old_name}</s> → <b>{new_name}</b>",
        reply_markup=superadmin_panel_kb(),
    )


# --- Edit type ---
@router.callback_query(F.data.startswith("region_edit_type:"))
async def region_edit_type_cb(callback: CallbackQuery) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    region_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "🔄 Yangi turni tanlang:",
        reply_markup=region_new_type_kb(region_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("region_set_type:"))
async def region_set_type_cb(callback: CallbackQuery) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    _, region_id_str, new_type = callback.data.split(":", 2)
    region_id = int(region_id_str)
    async with async_session() as session:
        region = await session.get(Region, region_id)
        if not region:
            await callback.answer("⚠️ Hudud topilmadi", show_alert=True)
            return
        region.type = new_type
        await session.commit()
        region_name = region.name
    await callback.message.edit_text(
        f"✅ <b>{region_name}</b> turi <b>{new_type}</b> ga o'zgartirildi!"
    )
    await callback.answer()
    await callback.message.answer("Admin panelga qaytish:", reply_markup=superadmin_panel_kb())


# --- Delete ---
@router.callback_query(F.data.startswith("region_delete:"))
async def region_delete_cb(callback: CallbackQuery) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    region_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        region = await session.get(Region, region_id)
    if not region:
        await callback.answer("⚠️ Hudud topilmadi", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚠️ <b>{region.name}</b> hududini o'chirishni tasdiqlaysizmi?\n"
        "Bu amalni qaytarib bo'lmaydi.",
        reply_markup=region_confirm_delete_kb(region_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("region_delete_confirm:"))
async def region_delete_confirm_cb(callback: CallbackQuery) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    region_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        region = await session.get(Region, region_id)
        if not region:
            await callback.answer("⚠️ Hudud topilmadi", show_alert=True)
            return
        region_name = region.name
        await session.delete(region)
        await session.commit()
    await callback.message.edit_text(f"🗑 <b>{region_name}</b> o'chirildi.")
    await callback.answer()
    await callback.message.answer("Admin panelga qaytish:", reply_markup=superadmin_panel_kb())


# ──────────────────────────────────────────────
# Admin management
# ──────────────────────────────────────────────
@router.message(F.text == "👥 Admin boshqaruvi")
async def admin_manage_menu(message: Message) -> None:
    scope = await get_admin_scope(message.from_user.id)
    if not _is_admin_manager(scope):
        return
    region = scope.get("region")
    area = f"<b>{region}</b>" if region else "barcha hududlar"
    await message.answer(
        f"👥 Admin boshqaruvi ({area}):",
        reply_markup=admin_manage_kb(),
    )


@router.callback_query(F.data == "admin_add")
async def add_admin_start(callback: CallbackQuery, state: FSMContext) -> None:
    scope = await get_admin_scope(callback.from_user.id)
    if not _is_admin_manager(scope):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.update_data(
        creator_is_superadmin=bool(scope.get("is_superadmin")),
        creator_role=scope.get("role"),
        creator_region=scope.get("region"),
    )
    await state.set_state(AdminAddAdmin.waiting_telegram_id)
    await callback.message.answer(
        "➕ <b>Yangi admin qo'shish</b>\n\nYangi adminning Telegram ID sini kiriting:"
    )
    await callback.answer()


@router.message(AdminAddAdmin.waiting_telegram_id, AdminFilter(), F.text)
async def add_admin_get_id(message: Message, state: FSMContext) -> None:
    tg_id = _parse_tg_id(message.text)
    if tg_id is None:
        await message.answer("⚠️ Telegram ID faqat raqamlardan iborat bo'lishi kerak. Qayta kiriting:")
        return
    await state.update_data(new_admin_tg_id=tg_id)

    data = await state.get_data()
    if data.get("creator_role") == "region_admin":
        # Region admin can create only district admins in own region.
        await state.update_data(new_admin_role="admin", new_admin_region=data.get("creator_region"))
        await state.set_state(AdminAddAdmin.waiting_district)
        await message.answer(
            "Yangi admin uchun <b>tuman/shahar</b> kiriting.\n"
            "Masalan: <i>Yunusobod tumani</i>"
        )
        return

    await state.set_state(AdminAddAdmin.waiting_role)
    await message.answer(
        "Admin rolini kiriting:\n"
        "  • <b>superadmin</b> — to'liq ruxsat\n"
        "  • <b>region_admin</b> — viloyat bo'yicha\n"
        "  • <b>admin</b> — tuman/shahar bo'yicha"
    )


@router.message(AdminAddAdmin.waiting_role, AdminFilter(), F.text)
async def add_admin_get_role(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("creator_role") == "region_admin":
        await state.clear()
        await message.answer("⚠️ Siz uchun rol avtomatik: <b>admin</b> (tuman darajasi).")
        return

    role = message.text.strip().lower()
    if role not in {"superadmin", "region_admin", "admin", "district_admin"}:
        await message.answer("⚠️ Rol noto'g'ri. Faqat: superadmin, region_admin yoki admin")
        return

    if role == "superadmin":
        normalized_role = "superadmin"
    elif role == "region_admin":
        normalized_role = "region_admin"
    else:
        normalized_role = "admin"
    await state.update_data(new_admin_role=normalized_role)
    await state.set_state(AdminAddAdmin.waiting_region)
    await message.answer(
        "Bu adminning <b>viloyatini</b> kiriting.\n"
        "Masalan: <i>Toshkent viloyati</i>"
    )


@router.message(AdminAddAdmin.waiting_region, AdminFilter(), F.text)
async def add_admin_get_region(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("creator_role") == "region_admin":
        await state.clear()
        await message.answer("⚠️ Viloyat siz uchun avtomatik belgilanadi.")
        return

    region = message.text.strip()
    if not region:
        await message.answer("⚠️ Viloyat nomini kiriting.")
        return
    await state.update_data(new_admin_region=region)

    data = await state.get_data()
    role = data.get("new_admin_role", "admin")
    if role in {"region_admin", "superadmin"}:
        await state.update_data(new_admin_district=None)
        await state.set_state(AdminAddAdmin.waiting_channel)
        await message.answer(
            "Viloyat adminining <b>kanal ID</b> sini kiriting.\n"
            "Masalan: <code>-1001234567890</code>"
        )
        return

    await state.set_state(AdminAddAdmin.waiting_district)
    await message.answer(
        "Bu adminning <b>tuman/shahar nomini</b> kiriting.\n"
        "Masalan: <i>Yunusobod tumani</i>"
    )


@router.message(AdminAddAdmin.waiting_district, AdminFilter(), F.text)
async def add_admin_get_district(message: Message, state: FSMContext) -> None:
    district = message.text.strip()
    if not district:
        await message.answer("⚠️ Tuman/shahar nomini kiriting.")
        return
    await state.update_data(new_admin_district=district)
    await state.set_state(AdminAddAdmin.waiting_channel)
    await message.answer(
        "Bu adminning <b>kanal ID</b> sini kiriting.\n"
        "Masalan: <code>-1001234567890</code>"
    )


@router.message(AdminAddAdmin.waiting_channel, AdminFilter(), F.text)
async def add_admin_get_channel(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    new_tg_id: int = data["new_admin_tg_id"]
    role: str = data.get("new_admin_role", "admin")
    region: str | None = data.get("new_admin_region")
    district: str | None = data.get("new_admin_district")
    channel_id = message.text.strip()

    if not channel_id:
        await message.answer("⚠️ Kanal ID bo'sh bo'lmasligi kerak.")
        return

    async with async_session() as session:
        stmt = select(Admin).where(Admin.telegram_id == new_tg_id)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            await message.answer(f"⚠️ Bu admin allaqachon mavjud (ID: <code>{new_tg_id}</code>).")
        else:
            # Region admin cannot create region-level/superadmin accounts.
            if data.get("creator_role") == "region_admin" and role != "admin":
                await message.answer("⛔ Region admin faqat tuman adminini qo'sha oladi.")
                await state.clear()
                return

            admin = Admin(
                telegram_id=new_tg_id,
                role=role,
                region=region,
                district=district,
                channel_id=channel_id,
            )
            session.add(admin)
            await session.commit()

            area_text = f"{region or '-'} / {district or '-'}"
            await message.answer(
                f"✅ Admin muvaffaqiyatli qo'shildi!\n\n"
                f"🆔 Telegram ID: <code>{new_tg_id}</code>\n"
                f"👤 Rol: <b>{role}</b>\n"
                f"📍 Hudud: <b>{area_text}</b>\n"
                f"📢 Kanal: <code>{channel_id}</code>"
            )

    await state.clear()
    scope = await get_admin_scope(message.from_user.id)
    panel = _panel_from_scope(scope)
    await message.answer("Admin panelga qaytish:", reply_markup=panel)


@router.callback_query(F.data == "admin_remove")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext) -> None:
    scope = await get_admin_scope(callback.from_user.id)
    if not _is_admin_manager(scope):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.update_data(
        creator_is_superadmin=bool(scope.get("is_superadmin")),
        creator_role=scope.get("role"),
        creator_region=scope.get("region"),
    )
    await state.set_state(AdminRemoveAdmin.waiting_telegram_id)
    await callback.message.answer(
        "🗑 O'chiriladigan adminning Telegram ID sini kiriting:"
    )
    await callback.answer()


@router.message(AdminRemoveAdmin.waiting_telegram_id, AdminFilter(), F.text)
async def remove_admin_by_id(message: Message, state: FSMContext) -> None:
    tg_id = _parse_tg_id(message.text)
    if tg_id is None:
        await message.answer("⚠️ Telegram ID raqam bo'lishi kerak. Qayta kiriting:")
        return
    data = await state.get_data()
    actor_scope = _actor_scope_from_state(data)

    async with async_session() as session:
        stmt = select(Admin).where(Admin.telegram_id == tg_id)
        result = await session.execute(stmt)
        admin = result.scalar_one_or_none()

        if admin:
            if not _can_manage_target(actor_scope, admin):
                await message.answer("⛔ Siz bu adminni o'chira olmaysiz (hudud/rol cheklovi).")
                await state.clear()
                return
            await session.delete(admin)
            await session.commit()
            await message.answer(f"✅ Admin o'chirildi (ID: <code>{tg_id}</code>).")
        else:
            await message.answer(f"⚠️ ID <code>{tg_id}</code> bo'yicha admin topilmadi.")

    await state.clear()
    scope = await get_admin_scope(message.from_user.id)
    panel = _panel_from_scope(scope)
    await message.answer("Admin panelga qaytish:", reply_markup=panel)


@router.callback_query(F.data == "admin_list")
async def list_admins_cb(callback: CallbackQuery) -> None:
    scope = await get_admin_scope(callback.from_user.id)
    if not _is_admin_manager(scope):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    async with async_session() as session:
        stmt = select(Admin)
        if scope.get("role") == "region_admin":
            stmt = stmt.where(Admin.region == scope.get("region"))
        result = await session.execute(stmt)
        admins = result.scalars().all()

    if not admins:
        await callback.message.answer("📭 Bazada hech qanday admin yo'q.")
    else:
        lines = []
        for i, a in enumerate(admins, 1):
            lines.append(
                f"{i}. 🆔 <code>{a.telegram_id}</code>\n"
                f"   👤 Rol: {a.role}\n"
                f"   📍 Viloyat: {a.region or '—'} | Tuman: {a.district or '—'}\n"
                f"   📢 Kanal: <code>{a.channel_id or '—'}</code>"
            )
        await callback.message.answer(
            "👥 <b>Adminlar ro'yxati:</b>\n\n" + "\n\n".join(lines)
        )
    await callback.answer()


@router.callback_query(F.data == "admin_set_channel")
async def set_channel_start(callback: CallbackQuery, state: FSMContext) -> None:
    scope = await get_admin_scope(callback.from_user.id)
    if not _is_admin_manager(scope):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    await state.update_data(
        creator_is_superadmin=bool(scope.get("is_superadmin")),
        creator_role=scope.get("role"),
        creator_region=scope.get("region"),
    )
    await state.set_state(AdminSetChannel.waiting_telegram_id)
    await callback.message.answer("🔗 Kanal biriktiriladigan admin Telegram ID sini kiriting:")
    await callback.answer()


@router.message(AdminSetChannel.waiting_telegram_id, AdminFilter(), F.text)
async def set_channel_get_admin_id(message: Message, state: FSMContext) -> None:
    tg_id = _parse_tg_id(message.text)
    if tg_id is None:
        await message.answer("⚠️ Telegram ID raqam bo'lishi kerak. Qayta kiriting:")
        return
    data = await state.get_data()
    actor_scope = _actor_scope_from_state(data)

    async with async_session() as session:
        result = await session.execute(select(Admin).where(Admin.telegram_id == tg_id))
        admin = result.scalar_one_or_none()
        if not admin:
            await message.answer("⚠️ Bunday admin topilmadi.")
            return
        can_manage = _can_manage_target(actor_scope, admin)
        if actor_scope.get("role") == "region_admin" and admin.telegram_id == message.from_user.id:
            can_manage = True
        if not can_manage:
            await message.answer("⛔ Siz bu admin uchun kanalni o'zgartira olmaysiz.")
            await state.clear()
            return

    await state.update_data(target_admin_tg_id=tg_id)
    await state.set_state(AdminSetChannel.waiting_channel)
    await message.answer("Yangi kanal ID kiriting (masalan: <code>-1001234567890</code>):")


@router.message(AdminSetChannel.waiting_channel, AdminFilter(), F.text)
async def set_channel_save(message: Message, state: FSMContext) -> None:
    channel_id = message.text.strip()
    if not channel_id:
        await message.answer("⚠️ Kanal ID bo'sh bo'lmasligi kerak.")
        return

    data = await state.get_data()
    tg_id = data.get("target_admin_tg_id")
    if not tg_id:
        await state.clear()
        await message.answer("⚠️ Sessiya tugagan, qayta urinib ko'ring.")
        return

    async with async_session() as session:
        result = await session.execute(select(Admin).where(Admin.telegram_id == tg_id))
        admin = result.scalar_one_or_none()
        if not admin:
            await state.clear()
            await message.answer("⚠️ Admin topilmadi.")
            return
        admin.channel_id = channel_id
        await session.commit()

    await state.clear()
    scope = await get_admin_scope(message.from_user.id)
    panel = _panel_from_scope(scope)
    await message.answer(
        f"✅ Admin <code>{tg_id}</code> uchun kanal yangilandi: <code>{channel_id}</code>",
        reply_markup=panel,
    )


# ──────────────────────────────────────────────
# Relay: admin replies to forwarded user message
# ──────────────────────────────────────────────
@router.message(AdminFilter(), F.reply_to_message)
async def relay_admin_reply(message: Message, bot: Bot) -> None:
    original_msg_id = message.reply_to_message.message_id
    user_tg_id = await relay_get(original_msg_id)

    if not user_tg_id:
        return  # Not a tracked relay message

    try:
        await bot.send_message(
            user_tg_id,
            f"💬 <b>Admin javobi:</b>\n\n{message.text or '[Media]'}",
        )
    except Exception as e:
        logger.error("Relay reply failed for user %s: %s", user_tg_id, e)
        await message.answer("⚠️ Foydalanuvchiga xabar yuborishda xatolik yuz berdi.")
        return

    try:
        await message.react([])  # Acknowledge with empty reaction (aiogram 3.4+)
    except Exception:
        pass  # Non-critical: reaction may fail if bot lacks permission
