"""Copy the history somewhere safe: the raw state, a CSV per season, the article snapshots."""
import csv
import json
import shutil
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path

from .store import MatchRecord, State, by_season

COLUMNS = ["kickoff", "opponent", "venue", "competition", "worth", "brackets", "your_stage", "your_sale",
           "sold_out_at", "sold_out_noticed", "kickoff_changes"]


def _row(rec: MatchRecord) -> dict[str, str]:
    s = rec.summary
    return {
        "kickoff": rec.kickoff_iso,
        "opponent": s.get("opponent", ""),
        "venue": "home" if s.get("home") else "away",
        "competition": s.get("competition", ""),
        "worth": "" if s.get("worth") is None else str(s["worth"]),
        "brackets": " / ".join(rec.brackets),
        "your_stage": s.get("your_stage") or "",
        "your_sale": rec.your_sale or "",
        "sold_out_at": rec.sold_out_at() or "",
        "sold_out_noticed": rec.first_sold_out_seen or "",
        "kickoff_changes": "; ".join(f"{old} → {new} (noticed {seen})"
                                    for (old, _), (new, seen) in pairwise(rec.kickoffs)),
    }


def export(state: State, data_dir: Path, dest: Path) -> Path:
    out = dest / "albion-tickets"
    out.mkdir(parents=True, exist_ok=True)
    raw = asdict(state)
    raw["dismissed"] = sorted(state.dismissed)
    raw["have_tickets"] = sorted(state.have_tickets)
    (out / "state.json").write_text(json.dumps(raw, indent=1, sort_keys=True))

    for season, recs in by_season(state).items():
        with (out / f"history-{season}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(_row(r) for r in recs)

    snaps = data_dir / "snapshots"
    if snaps.is_dir():
        (out / "snapshots").mkdir(exist_ok=True)
        for f in snaps.iterdir():
            target = out / "snapshots" / f.name
            if not target.exists():  # named by content hash: an existing file is the same file
                shutil.copy2(f, target)
    return out
