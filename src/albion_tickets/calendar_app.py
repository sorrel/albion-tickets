"""Putting notices into the "Albion tickets" calendar (synced to the phone through iCloud).

MacCalendar runs calendar.js (EventKit, through osascript) once per batch of
changes, passing them as JSON on stdin. The script reports each change on its
own line as soon as it is done, so a batch cut short still says what it
finished: a created event is never lost (and later duplicated) because a
later one stalled. FakeCalendar is the in-memory stand-in every test uses.
"""
import json
import os
import selectors
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote
from typing import Protocol

from .notices import Notice

SCRIPT = Path(__file__).with_name("calendar.js")
BASE_TIMEOUT_S = 150  # covers macOS's one-off "allow calendar access?" prompt
PER_CHANGE_S = 10
MARK = "albion-tickets:"  # each event's URL: this, then its notice key (see calendar.js)


class CalendarError(Exception):
    pass


@dataclass(frozen=True)
class Change:
    """One calendar change: an upsert (notice set) or a removal (notice None)."""
    uid: str | None
    notice: Notice | None = None


@dataclass(frozen=True)
class Event:
    """An event found in the calendar, by both its IDs (older records hold the local one)."""
    uid: str
    local: str
    title: str
    start: datetime
    key: str  # the notice key it carries, "" for events written before keys were kept


class Calendar(Protocol):
    def apply(self, changes: list[Change]) -> list[str | CalendarError]: ...
    def check_ready(self) -> str | None: ...
    def listing(self, start: datetime, end: datetime) -> list[Event]: ...


def alarm_minutes(n: Notice) -> list[int]:
    return [round((a - n.start).total_seconds() / 60) for a in n.alarms]


def upsert(cal: Calendar, n: Notice, uid: str | None) -> str:
    result = cal.apply([Change(uid, n)])[0]
    if isinstance(result, CalendarError):
        raise result
    return result


def remove(cal: Calendar, uid: str) -> None:
    result = cal.apply([Change(uid)])[0]
    if isinstance(result, CalendarError):
        raise result


class FakeCalendar:
    def __init__(self) -> None:
        self.events: dict[str, Notice] = {}
        self.calls: list[tuple[str, str]] = []
        self.batches: list[int] = []

    def apply(self, changes: list[Change]) -> list[str | CalendarError]:
        self.batches.append(len(changes))
        out: list[str | CalendarError] = []
        for c in changes:
            if c.notice is None:
                self.calls.append(("remove", c.uid))
                self.events.pop(c.uid, None)
                out.append(c.uid)
                continue
            # As calendar.js: the given ID, else an event already carrying this key, else a new one.
            same_key = next((u for u, n in self.events.items() if n and n.key == c.notice.key), None)
            uid = c.uid if c.uid in self.events else same_key or uuid.uuid4().hex
            self.events[uid] = c.notice
            self.calls.append(("upsert", c.notice.key))
            out.append(uid)
        return out

    def check_ready(self) -> str | None:
        return None

    def listing(self, start: datetime, end: datetime) -> list[Event]:
        return [Event(uid, uid, n.title, n.start, n.key) for uid, n in self.events.items() if n and start <= n.start < end]


def _payload(c: Change) -> dict:
    if c.notice is None:
        return {"op": "remove", "uid": c.uid}
    n = c.notice
    return {
        "op": "upsert", "uid": c.uid, "key": n.key, "title": n.title, "notes": n.notes,
        "start": int(n.start.timestamp() * 1000), "end": int(n.end.timestamp() * 1000),
        "alarms": alarm_minutes(n), "location": n.location, "geo": list(n.geo) if n.geo else None,
    }


class MacCalendar:
    def __init__(self, name: str, command: list[str] | None = None) -> None:
        self.name = name
        self.command = command or ["osascript", "-l", "JavaScript", str(SCRIPT)]  # tests swap in a stand-in

    def _run(self, ops: list[dict]) -> list[dict]:
        """Results line by line; stops at the deadline with what has arrived."""
        limit = BASE_TIMEOUT_S + PER_CHANGE_S * len(ops)
        deadline = time.monotonic() + limit
        proc = subprocess.Popen(self.command, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.stdin.write(json.dumps({"calendar": self.name, "ops": ops}).encode())
        proc.stdin.close()
        results: list[dict] = []
        buf = b""
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        try:
            while len(results) < len(ops):
                left = deadline - time.monotonic()
                if left <= 0 or not sel.select(timeout=left):
                    break
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                results.extend(json.loads(line) for line in lines if line.strip())
        finally:
            sel.close()
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        if len(results) < len(ops):
            why = proc.stderr.read().decode().strip() if proc.returncode not in (0, -9) else ""
            stop = why or f"the calendar did not finish within {limit} s"
            results.extend({"ok": False, "error": stop} for _ in range(len(ops) - len(results)))
        proc.stderr.close()
        proc.stdout.close()
        return results

    def apply(self, changes: list[Change]) -> list[str | CalendarError]:
        if not changes:
            return []
        out: list[str | CalendarError] = []
        for r in self._run([_payload(c) for c in changes]):
            if r.get("ok") and (r.get("uid") or "") != "":
                out.append(r["uid"])
            else:
                out.append(CalendarError(r.get("error") or "no event ID came back"))
        return out

    def listing(self, start: datetime, end: datetime) -> list[Event]:
        result = self._run([{"op": "list", "from": start.timestamp(), "to": end.timestamp()}])[0]
        if not result.get("ok"):
            raise CalendarError(result.get("error") or "couldn't list the calendar")
        return [Event(e["uid"], e["local"], e["title"], datetime.fromtimestamp(e["start"], UTC),
                      unquote(e["mark"].removeprefix(MARK))) for e in result["events"]]

    def check_ready(self) -> str | None:
        result = self._run([{"op": "check"}])[0]
        if result.get("ok"):
            return None
        if result.get("error") == "missing":
            return f'Calendar "{self.name}" not found — create it in Calendar.app under your iCloud account'
        return f"Calendar not reachable: {result.get('error')}"
