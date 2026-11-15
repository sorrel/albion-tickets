"""Putting notices into Calendar.app (which syncs to the phone through iCloud).

MacCalendar runs a small JXA script per call, passing the notice as JSON on
stdin. FakeCalendar is the in-memory stand-in every test uses.
"""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Protocol

from .notices import Notice

SCRIPT = Path(__file__).with_name("calendar.js")


class CalendarError(Exception):
    pass


class Calendar(Protocol):
    def upsert(self, n: Notice, uid: str | None) -> str: ...
    def remove(self, uid: str) -> None: ...
    def check_ready(self) -> str | None: ...


def alarm_minutes(n: Notice) -> list[int]:
    return [round((a - n.start).total_seconds() / 60) for a in n.alarms]


class FakeCalendar:
    def __init__(self) -> None:
        self.events: dict[str, Notice] = {}
        self.calls: list[tuple[str, str]] = []

    def upsert(self, n: Notice, uid: str | None) -> str:
        if uid is None or uid not in self.events:
            uid = uuid.uuid4().hex
        self.events[uid] = n
        self.calls.append(("upsert", n.key))
        return uid

    def remove(self, uid: str) -> None:
        self.calls.append(("remove", uid))
        self.events.pop(uid, None)

    def check_ready(self) -> str | None:
        return None


class MacCalendar:
    def __init__(self, name: str) -> None:
        self.name = name

    def _call(self, payload: dict) -> str:
        payload = {"calendar": self.name, **payload}
        try:
            done = subprocess.run(
                ["osascript", "-l", "JavaScript", str(SCRIPT)],
                input=json.dumps(payload), capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise CalendarError("Calendar.app did not answer within 30 s") from exc
        if done.returncode != 0:
            raise CalendarError(done.stderr.strip() or f"osascript exited {done.returncode}")
        return done.stdout.strip()

    def check_ready(self) -> str | None:
        try:
            result = self._call({"op": "check"})
        except CalendarError as exc:
            return f"Calendar.app not reachable: {exc}"
        if result == "missing":
            return f'Calendar "{self.name}" not found — create it in Calendar.app under your iCloud account'
        return None

    def upsert(self, n: Notice, uid: str | None) -> str:
        result = self._call({
            "op": "upsert", "uid": uid, "title": n.title, "notes": n.notes,
            "start": int(n.start.timestamp() * 1000), "end": int(n.end.timestamp() * 1000),
            "alarms": alarm_minutes(n), "location": n.location,
        })
        if not result or result == "missing":
            raise CalendarError(f"upsert of {n.key} failed: {result!r}")
        return result

    def remove(self, uid: str) -> None:
        self._call({"op": "remove", "uid": uid})
