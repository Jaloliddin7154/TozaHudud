from collections import OrderedDict


class _BoundedRelay:
    """Maps bot_message_id -> user_telegram_id, capped at _MAX entries (oldest dropped first)."""

    _MAX = 1000

    def __init__(self) -> None:
        self._data: OrderedDict[int, int] = OrderedDict()

    def get(self, key: int, default: int | None = None) -> int | None:
        return self._data.get(key, default)

    def __setitem__(self, key: int, value: int) -> None:
        self._data[key] = value
        if len(self._data) > self._MAX:
            self._data.popitem(last=False)

    def __getitem__(self, key: int) -> int:
        return self._data[key]


relay_map: _BoundedRelay = _BoundedRelay()
