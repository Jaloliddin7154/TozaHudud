from __future__ import annotations

import logging
import asyncio
import time

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select

from config import REPORTS_CHANNEL_ID
from database.db import async_session
from database.models import User
from handlers.states import UserReport, UserContactAdmin
from keyboards.admin_kb import report_status_kb
from keyboards.user_kb import main_menu_kb, request_location_kb, cancel_kb
from services import location as location_service
from services import report as report_service
from utils.relay import relay_set

logger = logging.getLogger(__name__)
perf_logger = logging.getLogger("performance")
human_logger = logging.getLogger("human")
router = Router()

# Keeps references to background tasks so asyncio doesn't GC them.
_bg_tasks: set[asyncio.Task] = set()


def _background(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _get_or_create_user(
    session, tg_id: int, username: str | None, full_name: str | None
) -> User:
    result = await session.execute(select(User).where(User.telegram_id == tg_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=tg_id, username=username, full_name=full_name)
        session.add(user)
        await session.flush()
    return user


async def _send_to_admin(
    bot: Bot,
    admin_id: int,
    photo_file_id: str,
    caption: str,
    report_id: int,
    lat: float,
    lon: float,
) -> bool:
    try:
        await bot.send_photo(
            admin_id,
            photo=photo_file_id,
            caption=caption,
            reply_markup=report_status_kb(report_id),
        )
        await bot.send_location(admin_id, latitude=lat, longitude=lon)
        return True
    except Exception as e:
        logger.error("Could not forward report to admin %s: %s", admin_id, e)
        return False


async def _send_to_channel(
    bot: Bot,
    channel_id: str,
    photo_file_id: str,
    caption: str,
    lat: float,
    lon: float,
) -> None:
    try:
        photo_msg = await bot.send_photo(chat_id=channel_id, photo=photo_file_id, caption=caption)
        await bot.send_location(
            chat_id=channel_id,
            latitude=lat,
            longitude=lon,
            reply_to_message_id=photo_msg.message_id,
        )
    except Exception as e:
        logger.error("Could not send report to channel %s: %s", channel_id, e)


async def _geocode_and_update(report_id: int, lat: float, lon: float) -> None:
    """Background task: fills in region/district/address when geocoding timed out."""
    try:
        geo = await asyncio.wait_for(
            location_service.reverse_geocode(lat, lon), timeout=15
        )
        async with async_session() as session:
            await report_service.update_report_geo(
                session,
                report_id,
                geo.get("region", ""),
                geo.get("district", ""),
                geo.get("address", ""),
            )
    except Exception as e:
        logger.error("Background geocoding failed for report_id=%s: %s", report_id, e)


# ──────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with async_session() as session:
        await _get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name,
        )
        await session.commit()

    await message.answer(
        f"👋 Salom, <b>{message.from_user.full_name}</b>!\n\n"
        "🌿 <b>Toza Hudud</b> botiga xush kelibsiz!\n\n"
        "Bu bot orqali siz:\n"
        "  📸 Chiqindi to'plangan joyni bildirishingiz\n"
        "  📍 Joylashuvni yuborishingiz\n"
        "  💬 Admin bilan bog'lanishingiz mumkin.\n\n"
        "Quyidagi tugmalardan birini tanlang:",
        reply_markup=main_menu_kb(),
    )


# ──────────────────────────────────────────────
# /help
# ──────────────────────────────────────────────
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "ℹ️ <b>Toza Hudud — Yordam</b>\n\n"
        "<b>Asosiy buyruqlar:</b>\n"
        "  /start — Botni qayta boshlash\n"
        "  /help  — Ushbu yordam xabari\n\n"
        "<b>Qanday foydalanish:</b>\n"
        "1️⃣ <b>📸 Muammo bildirish</b> tugmasini bosing\n"
        "2️⃣ Muammo joyining <b>rasmini</b> yuboring\n"
        "3️⃣ <b>📍 Lokatsiyangizni</b> yuboring\n"
        "4️⃣ Bot avtomatik ravishda tegishli adminga yuboradi\n\n"
        "<b>Admin bilan bog'lanish:</b>\n"
        "  💬 <b>Admin bilan bog'lanish</b> tugmasini bosing va xabaringizni yozing.\n\n"
        "❓ Qo'shimcha savollar uchun adminlarga yozing.",
        reply_markup=main_menu_kb(),
    )


# ──────────────────────────────────────────────
# Report flow: photo → location
# ──────────────────────────────────────────────
@router.message(F.text == "📸 Muammo bildirish")
async def start_report(message: Message, state: FSMContext) -> None:
    await state.set_state(UserReport.waiting_photo)
    await message.answer(
        "📸 Iltimos, muammo joylashgan yerning <b>rasmini</b> yuboring:",
        reply_markup=cancel_kb(),
    )


@router.message(UserReport.waiting_photo, F.photo)
async def process_photo(message: Message, state: FSMContext) -> None:
    # Store only the Telegram file_id — no download, no disk I/O.
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(UserReport.waiting_location)
    await message.answer(
        "✅ Rasm qabul qilindi!\n\n"
        "📍 Endi <b>joylashuvingizni</b> yuboring:",
        reply_markup=request_location_kb(),
    )


@router.message(UserReport.waiting_photo, ~F.photo)
async def process_photo_invalid(message: Message, state: FSMContext) -> None:
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=main_menu_kb())
        return
    await message.answer("⚠️ Iltimos, faqat rasm yuboring.")


@router.message(UserReport.waiting_location, F.location)
async def process_location(message: Message, state: FSMContext, bot: Bot) -> None:
    started_at = time.perf_counter()
    lat = message.location.latitude
    lon = message.location.longitude

    data = await state.get_data()
    photo_file_id: str = data.get("photo_file_id", "")

    # Free FSM state immediately — user is not blocked during processing.
    await state.clear()

    if not photo_file_id:
        await message.answer(
            "⚠️ Rasm topilmadi. Iltimos, <b>📸 Muammo bildirish</b> tugmasini bosib qaytadan boshlang.",
            reply_markup=main_menu_kb(),
        )
        return

    try:
        await message.answer("⏳ Manzil aniqlanmoqda...")
    except Exception as e:
        logger.error("Could not send waiting message to user %s: %s", message.from_user.id, e)

    try:
        # ── 1. Geocode (wait up to 4 s — usually <1 s on cache hit) ──────────
        geo: dict | None = None
        try:
            geo = await asyncio.wait_for(
                location_service.reverse_geocode(lat, lon), timeout=4
            )
        except asyncio.TimeoutError:
            logger.info("Geocoding timed out for user_id=%s", message.from_user.id)

        unknown = "Noma'lum"
        region   = geo.get("region",  "")       if geo else ""
        district = geo.get("district","")       if geo else ""
        address  = geo.get("address", unknown)  if geo else unknown
        region_display   = region   or unknown
        district_display = district or unknown

        # ── 2. Save report + resolve who to notify ────────────────────────────
        async with async_session() as session:
            user = await _get_or_create_user(
                session,
                message.from_user.id,
                message.from_user.username,
                message.from_user.full_name,
            )
            report = await report_service.create_report(
                session,
                user.id,
                photo_file_id,   # Telegram file_id stored in image_path field
                lat, lon,
                region, district, address,
            )
            report_id = report.id
            admin_ids, channel_ids = await report_service.get_delivery_targets(
                session, region, district
            )

        # If geocoding timed out, fill address in background without blocking user.
        if geo is None:
            _background(_geocode_and_update(report_id, lat, lon))

        # ── 3. Build captions ─────────────────────────────────────────────────
        gps = f"{lat:.6f}, {lon:.6f}"

        admin_caption = (
            f"🚨 <b>Yangi muammo #{report_id}</b>\n\n"
            f"👤 {message.from_user.full_name}\n"
            f"🗺 Viloyat: <b>{region_display}</b>\n"
            f"🏙 Tuman/Shahar: <b>{district_display}</b>\n"
            f"📌 Manzil: {address}\n"
            f"📡 Koordinatasi: {gps}"
        )
        channel_caption = (
            f"📢 <b>Yangi muammo #{report_id}</b>\n\n"
            f"📌 {address}\n"
            f"📡 Koordinatasi: {gps}"
        )

        # ── 4. Send to scoped admins + scoped channels concurrently ───────────
        tasks = [
            _send_to_admin(bot, aid, photo_file_id, admin_caption, report_id, lat, lon)
            for aid in admin_ids
        ]
        for channel_id in channel_ids:
            tasks.append(
                _send_to_channel(bot, channel_id, photo_file_id, channel_caption, lat, lon)
            )

        # Optional global fallback channel (kept for backward compatibility).
        if REPORTS_CHANNEL_ID and REPORTS_CHANNEL_ID not in channel_ids:
            tasks.append(_send_to_channel(bot, REPORTS_CHANNEL_ID, photo_file_id, channel_caption, lat, lon))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        sent_count = sum(1 for r in results[: len(admin_ids)] if r is True)

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        perf_logger.info(
            "report_done user_id=%s report_id=%s admins=%s sent=%s elapsed_ms=%.1f",
            message.from_user.id, report_id, len(admin_ids), sent_count, elapsed_ms,
        )

        # ── 5. Confirmation to user ───────────────────────────────────────────
        location_line = (
            f"🗺 Viloyat: <b>{region_display}</b>\n"
            f"🏙 Tuman/Shahar: <b>{district_display}</b>\n"
            f"📌 Manzil: {address}\n\n"
            if (region or district)
            else ""
        )
        await message.answer(
            f"✅ <b>Xabaringiz muvaffaqiyatli yuborildi!</b>\n\n"
            f"🆔 Xabar raqami: <b>#{report_id}</b>\n"
            f"{location_line}"
            "📋 Mas'ul xizmat tez orada muammoni ko'rib chiqadi.\n\n"
            "🌿 Rahmat! Sizning faolligingiz shaharni toza saqlashga yordam beradi.",
            reply_markup=main_menu_kb(),
        )
        human_logger.info(
            "Yangi xabar: user=%s report_id=%s hudud=%s/%s adminlar=%s %.0fms",
            message.from_user.id, report_id,
            region_display, district_display,
            sent_count, elapsed_ms,
        )

    except Exception:
        logger.exception("process_location failed for user_id=%s", message.from_user.id)
        try:
            await message.answer(
                "⚠️ Xabarni qayta ishlashda xatolik bo'ldi. Iltimos, qaytadan urinib ko'ring.",
                reply_markup=main_menu_kb(),
            )
        except Exception:
            pass


@router.message(UserReport.waiting_location)
async def process_location_invalid(message: Message, state: FSMContext) -> None:
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=main_menu_kb())
        return
    await message.answer("⚠️ Iltimos, faqat lokatsiya yuboring (📍 tugmasi orqali).")


# ──────────────────────────────────────────────
# Cancel
# ──────────────────────────────────────────────
@router.message(F.text == "❌ Bekor qilish")
async def cancel_action(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=main_menu_kb())


# ──────────────────────────────────────────────
# Contact admin flow
# ──────────────────────────────────────────────
@router.message(F.text == "💬 Admin bilan bog'lanish")
async def contact_admin_start(message: Message, state: FSMContext) -> None:
    await state.set_state(UserContactAdmin.waiting_message)
    await message.answer(
        "💬 Adminga yubormoqchi bo'lgan xabaringizni yozing:",
        reply_markup=cancel_kb(),
    )


@router.message(UserContactAdmin.waiting_message, F.text)
async def contact_admin_send(message: Message, state: FSMContext, bot: Bot) -> None:
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=main_menu_kb())
        return

    async with async_session() as session:
        admins = await report_service.get_default_admins(session)
        admin_ids = [a.telegram_id for a in admins]

    user_text = (
        f"💬 <b>Foydalanuvchi xabari</b>\n\n"
        f"👤 {message.from_user.full_name}\n"
        f"🆔 <code>{message.from_user.id}</code>\n\n"
        f"📝 {message.text}\n\n"
        f"<i>Javob berish uchun ushbu xabarga reply qiling.</i>"
    )

    sent = 0
    for admin_id in admin_ids:
        try:
            sent_msg = await bot.send_message(admin_id, user_text)
            await relay_set(sent_msg.message_id, message.from_user.id)
            sent += 1
        except Exception as e:
            logger.error("Error sending contact message to admin %s: %s", admin_id, e)

    await state.clear()
    if sent > 0:
        await message.answer("✅ Xabaringiz adminga yuborildi!", reply_markup=main_menu_kb())
        human_logger.info(
            "Foydalanuvchi xabari yuborildi: user=%s adminlar=%s",
            message.from_user.id, sent,
        )
    else:
        await message.answer(
            "⚠️ Xabar yuborishda xatolik yuz berdi. Keyinroq urinib ko'ring.",
            reply_markup=main_menu_kb(),
        )
        human_logger.warning("Foydalanuvchi xabari yuborilmadi: user=%s", message.from_user.id)
