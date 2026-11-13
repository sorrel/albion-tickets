import plistlib
from pathlib import Path

PLIST = Path(__file__).parents[1] / "launchd" / "com.albion-tickets.check.plist"


def test_plist_has_no_machine_paths_and_nine_slots():
    text = PLIST.read_text()
    assert "/Users/" not in text and "__REPO_DIR__" in text
    data = plistlib.loads(text.encode())
    hours = [slot["Hour"] for slot in data["StartCalendarInterval"]]
    assert hours == [7, 9, 11, 13, 15, 17, 19, 21, 22]
    assert all(slot["Minute"] == 0 for slot in data["StartCalendarInterval"])
    assert data["ProgramArguments"] == ["__REPO_DIR__/.venv/bin/albion", "check"]
    assert "KeepAlive" not in data
