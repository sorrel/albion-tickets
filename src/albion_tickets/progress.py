"""Progress lines for a person watching a check run.

Each step prints a line. If nothing has been printed for `quiet_after`
seconds, a heartbeat says the current step is still going, so a slow fetch
or a waiting Calendar.app is never silent for long.
"""
from __future__ import annotations

import threading
import time
from typing import Callable


class Progress:
    def __init__(self, write: Callable[[str], None], quiet_after: float = 5.0) -> None:
        self._write = write
        self._quiet_after = quiet_after
        self._lock = threading.Lock()
        self._step = ""
        self._step_started = time.monotonic()
        self._last = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()

    def __call__(self, message: str) -> None:
        with self._lock:
            self._step = message.strip().rstrip("…").rstrip(".")
            self._step_started = self._last = time.monotonic()
            self._write(message)

    def _beat(self) -> None:
        while not self._stop.wait(self._quiet_after / 5):
            with self._lock:
                now = time.monotonic()
                if self._step and now - self._last >= self._quiet_after:
                    waited = round(now - self._step_started)
                    step = self._step[0].lower() + self._step[1:]
                    self._write(f"  …still {step} ({waited}s)")
                    self._last = now

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
