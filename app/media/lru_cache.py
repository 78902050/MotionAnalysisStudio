"""Small bounded LRU cache for decoded video frames."""

from collections import OrderedDict
from threading import RLock
from typing import Generic, TypeVar


Key = TypeVar("Key")
Value = TypeVar("Value")


class LruFrameCache(Generic[Key, Value]):
    def __init__(self, capacity: int) -> None:
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self._items: OrderedDict[Key, Value] = OrderedDict()
        self._lock = RLock()

    def get(self, key: Key) -> Value | None:
        with self._lock:
            if key not in self._items:
                return None
            value = self._items.pop(key)
            self._items[key] = value
            return value

    def put(self, key: Key, value: Value) -> None:
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = value
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
