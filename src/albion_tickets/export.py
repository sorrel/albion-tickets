"""Copy the history somewhere safe: the raw state, a CSV per season, the article snapshots."""
from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from .store import State

COLUMNS = ["kickoff", "opponent", "venue", "competition", "worth", "brackets", "your_stage", "your_sale",
           "sold_out_at", "sold_out_noticed", "kickoff_changes"]


def _row(rec) -> dict[str, str]:
    s = rec.summary
    stages = sorted(s.get("stages", []), key=lambda st: st["opens"])
    yours = next((st for st in stages if st["label"] == s.get("your_stage")), None)
    return {
        "kickoff": rec.kickoffs[-1][0] if rec.kickoffs else "",
        "opponent": s.get("opponent", ""),
        "venue": "home" if s.get("home") else "away",
        "competition": s.get("competition", ""),
        "worth": "" if s.get("worth") is None else str(s["worth"]),
        "brackets": " / ".join(f"{st['min_points']}+" for st in stages if st.get("min_points") is not None),
        "your_stage": s.get("your_stage") or "",
        "your_sale": yours["opens"] if yours else "",
        "sold_out_at": s.get("sold_out_stage") or "",
        "sold_out_noticed": rec.first_sold_out_seen or "",
        "kickoff_changes": "; ".join(f"{old} → {new} (noticed {seen})"
                                    for (old, _), (new, seen) in zip(rec.kickoffs, rec.kickoffs[1:])),
    }


def export(state: State, data_dir: Path, dest: Path) -> Path:
    out = dest / "albion-tickets"
    out.mkdir(parents=True, exist_ok=True)
    raw = asdict(state)
    raw["dismissed"] = sorted(state.dismissed)
    raw["have_tickets"] = sorted(state.have_tickets)
    (out / "state.json").write_text(json.dumps(raw, indent=1, sort_keys=True))

    seasons: dict[str, list] = {}
    for key, rec in state.matches.items():
        seasons.setdefault(key[:7], []).append(rec)
    for season, recs in seasons.items():
        recs.sort(key=lambda r: r.kickoffs[-1][0] if r.kickoffs else "")
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
