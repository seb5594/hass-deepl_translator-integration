"""A small in-memory cache that keeps repeated translations from using up the quota."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable
from typing import Generic, TypeVar

ValueT = TypeVar("ValueT")


class TranslationCache(Generic[ValueT]):
    """Least-recently-used cache; a size of zero turns it off."""

    def __init__(self, max_size: int) -> None:
        self._max_size = max(0, max_size)
        self._entries: OrderedDict[Hashable, ValueT] = OrderedDict()

    @property
    def enabled(self) -> bool:
        """Whether the cache stores anything at all."""
        return self._max_size > 0

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: Hashable) -> ValueT | None:
        """Return the cached value and mark it as recently used."""
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key: Hashable, value: ValueT) -> None:
        """Store a value, dropping the least recently used one when the cache is full."""
        if not self.enabled:
            return
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_size:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """Forget everything."""
        self._entries.clear()
