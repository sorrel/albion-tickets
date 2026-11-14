"""A single status line for a person watching a check run.

Each step overwrites the line. Once a step has run for `quiet_after`
seconds, the line ticks its elapsed seconds, so a slow fetch or a waiting
Calendar.app is visibly still alive. `close()` clears the line, leaving the
terminal for the summary.
"""
from __future__ import annotations

import shutil
import threading
import time
from typing import TextIO

CLEAR = "\r\x1b[K"


class Progress:
    def __init__(self, stream: TextIO, quiet_after: float = 2.0, tick: float = 1.0,
                 width: int | None = None) -> None:
        self._stream = stream
        self._quiet_after = quiet_after
        self._tick = tick
        self._width = width or shutil.get_terminal_size().columns
        self._lock = threading.Lock()
        self._message = ""
        self._started = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()

    def _show(self, text: str) -> None:
        limit = self._width - 1  # a wrapped line can't be overwritten
        if len(text) > limit:
            text = text[: limit - 1] + "…"
        self._stream.write(CLEAR + text)
        self._stream.flush()

    def __call__(self, message: str) -> None:
        with self._lock:
            self._message = message
            self._started = time.monotonic()
            self._show(message)

    def _beat(self) -> None:
        while not self._stop.wait(self._tick):
            with self._lock:
                waited = time.monotonic() - self._started
                if self._message and waited >= self._quiet_after:
                    self._show(f"{self._message} ({round(waited)}s)")

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
        with self._lock:
            self._stream.write(CLEAR)
            self._stream.flush()
