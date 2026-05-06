import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram_sqlite_storage.sqlitestore import SQLStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from config import BOT_TOKEN, SUPERADMIN_ID, DEFAULT_ADMIN_IDS, ADMIN_ASSIGNMENTS
from database.db import init_db, async_session
from handlers.admin import router as admin_router
from handlers.user import router as user_router
from middlewares.logging_middleware import UpdateLoggingMiddleware
from middlewares.rate_limit import RateLimitMiddleware
from services.admin_seed import seed_admin_assignments
from utils.logging_setup import setup_logging
from utils.relay import relay_cleanup_old

setup_logging()
logger = logging.getLogger(__name__)


async def main() -> None:
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN topilmadi! .env faylini tekshiring.")
        sys.exit(1)

    if not SUPERADMIN_ID and not DEFAULT_ADMIN_IDS:
        logger.warning(
            "SUPERADMIN_ID va DEFAULT_ADMIN_IDS ikkalasi ham bo'sh — "
            "yangi xabarlar hech kimga yuborilmaydi."
        )

    await init_db()
    logger.info("Ma'lumotlar bazasi tayyor.")

    deleted = await relay_cleanup_old()
    if deleted:
        logger.info("Relay cleanup: %d eski yozuv o'chirildi.", deleted)

    if ADMIN_ASSIGNMENTS:
        async with async_session() as session:
            created, updated = await seed_admin_assignments(session, ADMIN_ASSIGNMENTS)
            logger.info(
                "ADMIN_ASSIGNMENTS qo'llandi: created=%s updated=%s",
                created,
                updated,
            )

    bot = Bot(
        token=BOT_TOKEN,
        session=AiohttpSession(timeout=15),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=SQLStorage("fsm_storage.db"))
    dp.update.outer_middleware(UpdateLoggingMiddleware())
    dp.message.outer_middleware(RateLimitMiddleware())

    # Admin router MUST be registered first (higher priority for shared filters)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # Set bot commands visible in Telegram UI
    user_commands = [
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="help",  description="Foydalanish bo'yicha yordam"),
    ]
    admin_commands = user_commands + [
        BotCommand(command="admin", description="Admin panelni ochish"),
    ]
    superadmin_commands = admin_commands + [
        BotCommand(command="clearcache", description="Kesh (__pycache__) fayllarni o'chirish"),
    ]

    # Default commands for all users
    await bot.set_my_commands(user_commands, scope=BotCommandScopeAllPrivateChats())

    # Extended commands for each configured admin
    notify_ids: set[int] = set(DEFAULT_ADMIN_IDS)
    if SUPERADMIN_ID:
        notify_ids.add(SUPERADMIN_ID)

    for uid in notify_ids:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=uid))
        except Exception as e:
            logger.warning("Admin %s uchun komandalar o'rnatilmadi: %s", uid, e)

    if SUPERADMIN_ID:
        try:
            await bot.set_my_commands(
                superadmin_commands,
                scope=BotCommandScopeChat(chat_id=SUPERADMIN_ID),
            )
        except Exception as e:
            logger.warning("Superadmin komandalarini o'rnatib bo'lmadi: %s", e)

    # Notify superadmin on startup
    if SUPERADMIN_ID:
        try:
            await bot.send_message(SUPERADMIN_ID, "🤖 <b>Toza Hudud boti ishga tushdi!</b>")
        except Exception:
            pass

    logger.info("Bot polling boshlandi...")
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
