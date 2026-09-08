"""Application capture barrier shared by browser sessions and screen reading.

This does not isolate the Windows account from unrelated processes. A capture
lease covers delivery as well as acquisition, so private entry cannot acknowledge
while a previously captured frame is still being delivered to a model.
"""

from contextlib import contextmanager
from threading import Condition


class CaptureBarrier:
    def __init__(self):
        self._condition = Condition()
        self._observers = 0
        self._private: set[str] = set()

    def enter(self, owner: str) -> None:
        self.block(owner)
        with self._condition:
            self._condition.wait_for(lambda: self._observers == 0)

    def block(self, owner: str) -> None:
        """Close admission synchronously before awaiting observer cancellation."""
        with self._condition:
            self._private.add(owner)

    def leave(self, owner: str) -> None:
        with self._condition:
            self._private.discard(owner)

    @property
    def blocked(self) -> bool:
        with self._condition:
            return bool(self._private)

    def owns(self, owner: str) -> bool:
        with self._condition:
            return owner in self._private

    @contextmanager
    def observe(self):
        with self._condition:
            if self._private:
                raise RuntimeError("Private browser input is active. Automated capture is paused.")
            self._observers += 1
        try:
            yield
        finally:
            with self._condition:
                self._observers -= 1
                self._condition.notify_all()


capture_barrier = CaptureBarrier()
