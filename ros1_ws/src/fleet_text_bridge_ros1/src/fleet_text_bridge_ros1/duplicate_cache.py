from collections import deque


class DuplicateCache:
    def __init__(self, max_size=100):
        self._max_size = max(1, int(max_size))
        self._order = deque()
        self._items = set()

    def seen(self, message_id):
        if message_id in self._items:
            return True
        self._items.add(message_id)
        self._order.append(message_id)
        while len(self._order) > self._max_size:
            self._items.discard(self._order.popleft())
        return False
