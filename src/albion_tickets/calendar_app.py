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
from pathlib import Path
from typing import Protocol

from .notices import Notice

SCRIPT = Path(__file__).with_name("calendar.js")
BASE_TIMEOUT_S = 150  # covers macOS's one-off "allow calendar access?" prompt
PER_CHANGE_S = 10


class CalendarError(Exception):
    pass


@dataclass(frozen=True)
class Change:
    """One calendar change: an upsert (notice set) or a removal (notice None)."""
    uid: str | None
    notice: Notice | None = None


class Calendar(Protocol):
    def apply(self, changes: list[Change]) -> list[str | CalendarError]: ...
    def check_ready(self) -> str | None: ...


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
            uid = c.uid if c.uid in self.events else uuid.uuid4().hex
            self.events[uid] = c.notice
            self.calls.append(("upsert", c.notice.key))
            out.append(uid)
        return out

    def check_ready(self) -> str | None:
        return None


def _payload(c: Change) -> dict:
    if c.notice is None:
        return {"op": "remove", "uid": c.uid}
    n = c.notice
    return {
        "op": "upsert", "uid": c.uid, "title": n.title, "notes": n.notes,
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

    def check_ready(self) -> str | None:
        result = self._run([{"op": "check"}])[0]
        if result.get("ok"):
            return None
        if result.get("error") == "missing":
            return f'Calendar "{self.name}" not found — create it in Calendar.app under your iCloud account'
        return f"Calendar not reachable: {result.get('error')}"
