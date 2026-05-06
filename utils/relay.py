import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, delete

from database.db import async_session
from database.models import RelayMessage

logger = logging.getLogger(__name__)

_TTL_DAYS = 7


async def relay_set(bot_message_id: int, user_telegram_id: int) -> None:
    """Persist a bot_message_id → user_telegram_id mapping."""
    async with async_session() as session:
        result = await session.execute(
            select(RelayMessage).where(RelayMessage.bot_message_id == bot_message_id)
        )
        relay = result.scalar_one_or_none()
        if relay:
            relay.user_telegram_id = user_telegram_id
        else:
            session.add(
                RelayMessage(
                    bot_message_id=bot_message_id,
                    user_telegram_id=user_telegram_id,
                )
            )
        await session.commit()


async def relay_get(bot_message_id: int) -> int | None:
    """Return the user_telegram_id for a given bot_message_id, or None."""
    async with async_session() as session:
        result = await session.execute(
            select(RelayMessage).where(RelayMessage.bot_message_id == bot_message_id)
        )
        relay = result.scalar_one_or_none()
        return relay.user_telegram_id if relay else None


async def relay_cleanup_old(days: int = _TTL_DAYS) -> int:
    """Delete relay entries older than *days* days. Returns deleted row count."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with async_session() as session:
        result = await session.execute(
            delete(RelayMessage).where(RelayMessage.created_at < cutoff)
        )
        await session.commit()
        deleted = result.rowcount
        if deleted:
            logger.info("relay_cleanup: %d eski yozuv o'chirildi", deleted)
        return deleted
