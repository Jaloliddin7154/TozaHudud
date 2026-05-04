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
from handlers.states import AdminAddRegion, AdminAddAdmin, AdminRemoveAdmin, AdminEditRegion
from keyboards.admin_kb import (
    admin_panel_kb,
    superadmin_panel_kb,
    region_type_kb,
    admin_manage_kb,
    report_status_kb,
    regions_list_kb,
    region_actions_kb,
    region_confirm_delete_kb,
    region_new_type_kb,
    export_district_filter_kb,
    export_format_kb,
)
from middlewares.auth import is_admin, is_superadmin, get_admin_district
from services import report as report_service
from utils.export import export_to_excel, export_to_pdf
from utils.relay import relay_map


class AdminFilter(BaseFilter):
    """Passes only when the sender is a registered admin or superadmin."""
    async def __call__(self, message: Message) -> bool:
        return await is_admin(message.from_user.id)

logger = logging.getLogger(__name__)
router = Router()

STATUS_NAMES: dict[str, str] = {
    "done": "✅ Bajarildi",
    "in_progress": "🔄 Jarayonda",
    "rejected": "❌ Rad etildi",
}


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
    panel_kb = superadmin_panel_kb() if await is_superadmin(message.from_user.id) else admin_panel_kb()
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
        district = await get_admin_district(message.from_user.id)
        stats = await report_service.get_statistics(session, district=district)

    status_lines = "\n".join(
        f"  • {k}: <b>{v}</b>" for k, v in stats["by_status"].items()
    ) or "  Yo'q"
    region_lines = "\n".join(
        f"  • {k}: <b>{v}</b>" for k, v in list(stats["by_region"].items())[:5]
    ) or "  Yo'q"

    district_label = f" — <b>{district}</b>" if district else " — barcha hududlar"
    await message.answer(
        f"📊 <b>Statistika</b>{district_label}\n\n"
        f"📋 Jami xabarlar: <b>{stats['total']}</b>\n"
        f"📅 Bugungi: <b>{stats['today']}</b>\n\n"
        f"📌 Status bo'yicha:\n{status_lines}\n\n"
        f"🗺 Hudud bo'yicha (top 5):\n{region_lines}"
    )


# ──────────────────────────────────────────────
# Reports list
# ──────────────────────────────────────────────
@router.message(F.text == "📋 Xabarlar ro'yxati")
async def list_reports(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return

    async with async_session() as session:
        district = await get_admin_district(message.from_user.id)
        reports = await report_service.get_all_reports(session, district=district)

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

    district_label = f" ({district})" if district else " (barcha)"
    await message.answer(f"📋 <b>So'nggi 20 xabar{district_label}:</b>\n\n" + "\n\n".join(lines))


# ──────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────
@router.message(F.text == "📥 Hisobot yuklash")
async def download_report_menu(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        return
    if await is_superadmin(message.from_user.id):
        # Superadmin: first choose district filter
        async with async_session() as session:
            districts = await report_service.get_distinct_districts(session)
        if not districts:
            await message.answer("📭 Hozircha eksport qilish uchun ma'lumot yo'q.")
            return
        await message.answer(
            "🗺 Qaysi hudud bo'yicha hisobot?\n"
            "\"Barchasi\" ni tanlasangiz — barcha hududlar:",
            reply_markup=export_district_filter_kb(districts),
        )
    else:
        # Regular admin: directly choose format for their own district
        district = await get_admin_district(message.from_user.id)
        await message.answer(
            f"📥 <b>{district or 'Tuman'}</b> bo'yicha hisobot turini tanlang:",
            reply_markup=export_format_kb(),
        )


# Superadmin selects district filter
@router.callback_query(F.data.startswith("xfilt:"))
async def export_filter_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    selected = callback.data[len("xfilt:"):]
    district = None if selected == "__all__" else selected
    await state.update_data(export_district=district)
    label = district or "Barchasi"
    await callback.message.edit_text(
        f"✅ Tanlandi: <b>{label}</b>\n\nHisobot formatini tanlang:",
        reply_markup=export_format_kb(),
    )
    await callback.answer()


# Both superadmin (via FSM) and regular admin (direct) hit this handler
@router.callback_query(F.data.startswith("xfmt:"))
async def export_format_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    fmt = callback.data[len("xfmt:"):]  # "excel" or "pdf"

    if await is_superadmin(callback.from_user.id):
        data = await state.get_data()
        district: str | None = data.get("export_district")
    else:
        district = await get_admin_district(callback.from_user.id)

    await state.clear()

    district_label = district or "Barchasi"
    await callback.answer(f"⏳ {district_label} bo'yicha tayyorlanmoqda...")

    async with async_session() as session:
        reports = await report_service.get_all_reports(session, district=district)
        stats = await report_service.get_statistics(session, district=district)

    if fmt == "excel":
        file_bytes = await asyncio.to_thread(export_to_excel, reports)
        filename = f"toza_hudud_{district or 'barcha'}.xlsx"
        file = BufferedInputFile(file_bytes, filename=filename)
        await callback.message.answer_document(
            file,
            caption=f"📊 Excel hisobot — <b>{district_label}</b>",
        )
    else:
        file_bytes = await asyncio.to_thread(export_to_pdf, reports, stats)
        filename = f"toza_hudud_{district or 'barcha'}.pdf"
        file = BufferedInputFile(file_bytes, filename=filename)
        await callback.message.answer_document(
            file,
            caption=f"📄 PDF hisobot — <b>{district_label}</b>",
        )


# ──────────────────────────────────────────────
# Report status update
# ──────────────────────────────────────────────
@router.callback_query(F.data.startswith("status:"))
async def update_status_cb(callback: CallbackQuery, bot: Bot) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    _, new_status, report_id_str = callback.data.split(":")
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
            "done": "✅ Muammo hal qilindi",
            "in_progress": "🔄 Muammo ko'rib chiqilmoqda",
            "rejected": "❌ Xabar rad etildi",
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


@router.message(AdminAddRegion.waiting_name, F.text)
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


@router.message(AdminEditRegion.waiting_new_name, F.text)
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
    _, region_id_str, new_type = callback.data.split(":")
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
    if not await is_superadmin(message.from_user.id):
        return
    await message.answer("👥 Admin boshqaruvi:", reply_markup=admin_manage_kb())


@router.callback_query(F.data == "admin_add")
async def add_admin_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(AdminAddAdmin.waiting_telegram_id)
    await callback.message.answer(
        "➕ <b>Yangi admin qo'shish</b>\n\nYangi adminning Telegram ID sini kiriting:"
    )
    await callback.answer()


@router.message(AdminAddAdmin.waiting_telegram_id, F.text)
async def add_admin_get_id(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.lstrip("-").isdigit():
        await message.answer("⚠️ Telegram ID faqat raqamlardan iborat bo'lishi kerak. Qayta kiriting:")
        return
    await state.update_data(new_admin_tg_id=int(text))
    await state.set_state(AdminAddAdmin.waiting_district)
    await message.answer(
        "Bu adminning <b>tuman nomini</b> kiriting.\n"
        "Masalan: <i>Yunusobod tumani</i>"
    )


@router.message(AdminAddAdmin.waiting_district, F.text)
async def add_admin_get_district(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    new_tg_id: int = data["new_admin_tg_id"]
    district = message.text.strip()

    async with async_session() as session:
        stmt = select(Admin).where(Admin.telegram_id == new_tg_id)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            await message.answer(f"⚠️ Bu admin allaqachon mavjud (ID: <code>{new_tg_id}</code>).")
        else:
            admin = Admin(telegram_id=new_tg_id, district=district, role="admin")
            session.add(admin)
            await session.commit()
            await message.answer(
                f"✅ Admin muvaffaqiyatli qo'shildi!\n\n"
                f"🆔 Telegram ID: <code>{new_tg_id}</code>\n"
                f"📍 Tuman: <b>{district}</b>"
            )

    await state.clear()
    await message.answer("Admin panelga qaytish:", reply_markup=superadmin_panel_kb())


@router.callback_query(F.data == "admin_remove")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_superadmin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(AdminRemoveAdmin.waiting_telegram_id)
    await callback.message.answer(
        "🗑 O'chiriladigan adminning Telegram ID sini kiriting:"
    )
    await callback.answer()


@router.message(AdminRemoveAdmin.waiting_telegram_id, F.text)
async def remove_admin_by_id(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.lstrip("-").isdigit():
        await message.answer("⚠️ Telegram ID raqam bo'lishi kerak. Qayta kiriting:")
        return

    tg_id = int(text)
    async with async_session() as session:
        stmt = select(Admin).where(Admin.telegram_id == tg_id)
        result = await session.execute(stmt)
        admin = result.scalar_one_or_none()

        if admin:
            await session.delete(admin)
            await session.commit()
            await message.answer(f"✅ Admin o'chirildi (ID: <code>{tg_id}</code>).")
        else:
            await message.answer(f"⚠️ ID <code>{tg_id}</code> bo'yicha admin topilmadi.")

    await state.clear()
    await message.answer("Admin panelga qaytish:", reply_markup=superadmin_panel_kb())


@router.callback_query(F.data == "admin_list")
async def list_admins_cb(callback: CallbackQuery) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(select(Admin))
        admins = result.scalars().all()

    if not admins:
        await callback.message.answer("📭 Bazada hech qanday admin yo'q.")
    else:
        lines = []
        for i, a in enumerate(admins, 1):
            lines.append(
                f"{i}. 🆔 <code>{a.telegram_id}</code>\n"
                f"   📍 Tuman: {a.district or '—'} | 👤 Rol: {a.role}"
            )
        await callback.message.answer(
            "👥 <b>Adminlar ro'yxati:</b>\n\n" + "\n\n".join(lines)
        )
    await callback.answer()


# ──────────────────────────────────────────────
# Relay: admin replies to forwarded user message
# ──────────────────────────────────────────────
@router.message(AdminFilter(), F.reply_to_message)
async def relay_admin_reply(message: Message, bot: Bot) -> None:
    original_msg_id = message.reply_to_message.message_id
    user_tg_id = relay_map.get(original_msg_id)

    if not user_tg_id:
        return  # Not a tracked relay message

    try:
        await bot.send_message(
            user_tg_id,
            f"💬 <b>Admin javobi:</b>\n\n{message.text or '[Media]'}",
        )
        await message.react([])  # Acknowledge (aiogram 3.4+)
    except Exception as e:
        logger.error("Relay reply failed for user %s: %s", user_tg_id, e)
        await message.answer("⚠️ Foydalanuvchiga xabar yuborishda xatolik yuz berdi.")
