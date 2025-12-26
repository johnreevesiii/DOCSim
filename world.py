from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorldState:
    """Global (cross-horse) race program state.

    This enables a "cabinet-style" continuous program where the race schedule keeps
    advancing even when the player switches horses.

    race_index is a 0-based pointer to the next race within the current round's
    6-race schedule (0..5).
    """

    current_round: int = 1  # 1..16
    cycle: int = 0          # number of times the 16-round program has completed
    race_index: int = 0     # 0..5 (next race within the round)


def load_world_state(path: Path) -> WorldState:
    if not path.exists():
        return WorldState()
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        current_round = int(data.get("current_round", 1))
        cycle = int(data.get("cycle", 0))
        race_index = int(data.get("race_index", 0))

        if current_round < 1 or current_round > 16:
            current_round = 1
        if cycle < 0:
            cycle = 0
        # Schedule has 6 races per round (index 0..5)
        if race_index < 0 or race_index > 5:
            race_index = 0

        return WorldState(current_round=current_round, cycle=cycle, race_index=race_index)
    except Exception:
        # If corrupted, fall back safely.
        return WorldState()


def save_world_state(path: Path, state: WorldState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "current_round": int(state.current_round),
        "cycle": int(state.cycle),
        "race_index": int(state.race_index),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def reset_world_state(path: Path) -> WorldState:
    state = WorldState()
    save_world_state(path, state)
    return state


def advance_world_round(state: WorldState, rounds: int = 1) -> WorldState:
    r = int(rounds)
    if r <= 0:
        return state
    for _ in range(r):
        state.current_round += 1
        state.race_index = 0
        if state.current_round > 16:
            state.current_round = 1
            state.cycle += 1
    return state
