import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

# Allow max 5 messages per user per 30 seconds.
_LIMIT = 5
_WINDOW = 30.0

_buckets: dict[int, list[float]] = defaultdict(list)


class RateLimitMiddleware(BaseMiddleware):
    """Throttle regular users to _LIMIT messages per _WINDOW seconds.

    Admins bypass this check (their filter runs at handler level).
    We deliberately do NOT import is_admin here to avoid a circular DB
    dependency — admin panel interactions are low-frequency by nature.
    """

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user_id: int | None = getattr(getattr(event, "from_user", None), "id", None)
        if user_id is None:
            return await handler(event, data)

        now = time.monotonic()
        bucket = _buckets[user_id]
        # Remove entries outside the window.
        bucket[:] = [t for t in bucket if now - t < _WINDOW]

        if len(bucket) >= _LIMIT:
            await event.answer(
                "⏳ Juda ko'p xabar yubordingiz. Bir oz kuting va qayta urinib ko'ring."
            )
            return None

        bucket.append(now)
        return await handler(event, data)
