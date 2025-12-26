from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from .models import Horse, RaceLogEntry, RaceRunnerResult, Externals, Internals

def horse_to_dict(h: Horse) -> Dict[str, Any]:
    d = {
        "id": h.id,
        "name": h.name,
        "sex": h.sex,
        "style": h.style,
        "ac": h.ac,
        "internals": asdict(h.internals),
        "externals": asdict(h.externals),
        "extras": getattr(h, "extras", {}),
        "genetic_tokens": h.genetic_tokens,
        "g1_wins": h.g1_wins,
        "pending_g1_superfood": getattr(h, "pending_g1_superfood", False),
        "career_log": [],
    }

    # Optional pedigree/breeding-card metadata (used for retirement display and
    # breeding pool). These keys are additive and remain backward-compatible.
    pedigree: Dict[str, Any] = {}
    for k in ("sire_name", "dam_name", "sire_ext", "dam_ext", "breeding_ext"):
        v = getattr(h, k, None)
        if v is not None:
            pedigree[k] = v
    if pedigree:
        d["pedigree"] = pedigree
    for e in h.career_log:
        d["career_log"].append({
            "round_num": e.round_num,
            "slot": e.slot,
            "race_name": e.race_name,
            "track": e.track,
            "course_code": e.course_code,
            "surface": e.surface,
            "condition": e.condition,
            "distance": e.distance,
            "winner_time": e.winner_time,
            "player_pos": e.player_pos,
            "player_time": e.player_time,
            "player_lengths": e.player_lengths,
            "payout": e.payout,
            "earnings_total_after": e.earnings_total_after,
            "field": [asdict(r) for r in e.field],
        })
    return d

def horse_from_dict(d: Dict[str, Any]) -> Horse:
    h = Horse(
        id=d["id"],
        name=d["name"],
        sex=d["sex"],
        style=d["style"],
        ac=int(d.get("ac", 128)),
        internals=Internals(**d["internals"]),
        externals=Externals(**d["externals"]),
        extras=(d.get("extras") if isinstance(d.get("extras"), dict) else {}),
    )
    h.genetic_tokens = int(d.get("genetic_tokens", 0))
    h.g1_wins = int(d.get("g1_wins", 0))
    h.pending_g1_superfood = bool(d.get("pending_g1_superfood", False))

    pedigree = d.get("pedigree") or {}
    if isinstance(pedigree, dict):
        for k in ("sire_name", "dam_name", "sire_ext", "dam_ext", "breeding_ext"):
            if k in pedigree:
                setattr(h, k, pedigree.get(k))
    for e in d.get("career_log", []):
        field = [RaceRunnerResult(**rr) for rr in e.get("field", [])]
        h.career_log.append(RaceLogEntry(
            round_num=e["round_num"],
            slot=e["slot"],
            race_name=e["race_name"],
            track=e["track"],
            course_code=e["course_code"],
            surface=e["surface"],
            condition=e["condition"],
            distance=e["distance"],
            winner_time=e["winner_time"],
            player_pos=e["player_pos"],
            player_time=e["player_time"],
            player_lengths=e["player_lengths"],
            payout=e["payout"],
            earnings_total_after=e["earnings_total_after"],
            field=field,
        ))
    return h

def save_game(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")

def load_game(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
