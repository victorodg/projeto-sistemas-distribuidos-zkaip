import threading


class LamportClock:
    def __init__(self):
        self._clock = 0
        self._lock = threading.Lock()

    def tick(self):
        with self._lock:
            self._clock += 1
            return self._clock

    def update(self, received):
        with self._lock:
            self._clock = max(self._clock, received) + 1
            return self._clock

    @property
    def value(self):
        with self._lock:
            return self._clock
