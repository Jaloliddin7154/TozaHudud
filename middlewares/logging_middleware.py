from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware

logger = logging.getLogger(__name__)
perf_logger = logging.getLogger("performance")
human_logger = logging.getLogger("human")


def _extract_user_chat(event: Any) -> tuple[int | None, int | None]:
    """Pull user_id and chat_id from the innermost Update sub-event."""
    inner = (
        getattr(event, "message", None)
        or getattr(event, "callback_query", None)
        or getattr(event, "edited_message", None)
        or getattr(event, "channel_post", None)
    )
    user_id = getattr(getattr(inner, "from_user", None), "id", None)
    chat_id = getattr(getattr(inner, "chat", None), "id", None)
    return user_id, chat_id


class UpdateLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        started = time.perf_counter()
        user_id, chat_id = _extract_user_chat(event)
        event_type = event.__class__.__name__

        try:
            result = await handler(event, data)
            elapsed_ms = (time.perf_counter() - started) * 1000

            if elapsed_ms > 1000:
                perf_logger.warning(
                    "slow_update type=%s user_id=%s chat_id=%s elapsed_ms=%.1f",
                    event_type, user_id, chat_id, elapsed_ms,
                )
                human_logger.warning(
                    "Sekin so'rov: turi=%s, foydalanuvchi=%s, chat=%s, vaqt=%.0f ms",
                    event_type, user_id, chat_id, elapsed_ms,
                )
            else:
                perf_logger.info(
                    "update type=%s user_id=%s chat_id=%s elapsed_ms=%.1f",
                    event_type, user_id, chat_id, elapsed_ms,
                )
                human_logger.info(
                    "So'rov bajarildi: turi=%s, foydalanuvchi=%s, vaqt=%.0f ms",
                    event_type, user_id, elapsed_ms,
                )
            return result
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "update_error type=%s user_id=%s chat_id=%s elapsed_ms=%.1f",
                event_type, user_id, chat_id, elapsed_ms,
            )
            human_logger.error(
                "Xatolik yuz berdi: turi=%s, foydalanuvchi=%s, chat=%s, vaqt=%.0f ms",
                event_type, user_id, chat_id, elapsed_ms,
            )
            raise
