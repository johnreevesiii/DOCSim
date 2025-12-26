from __future__ import annotations
from typing import Dict, List, Literal, Tuple

from .models import Horse, TrainingResult
from .breeding import clamp_int
from .rng import RNG

# DOC-style training result scale
Grade = Literal["Perfect","Cool","Great","Good","Bad","None"]

# DOC naming conventions (10 trainings)
# Each: (name, primary stats, secondary stats)
TRAININGS: List[Tuple[str, Tuple[str,...], Tuple[str,...]]] = [
    ("Pool", ("tenacious",), ("competing",)),
    ("Solo Turf/Start", ("start",), ("oob",)),
    ("Solo Wood/Corner", ("corner",), ("competing",)),
    ("Solo Dirt/Tenacious", ("tenacious",), ("competing",)),
    ("Solo Slope/Spurt", ("spurt",), ("tenacious",)),
    ("Co-op Turf Start/Comp", ("start","competing"), ("oob",)),
    ("Co-op Dirt Ten/OTB", ("tenacious","oob"), ("competing",)),
    ("Co-op Wood Corner/OTB", ("corner","oob"), ("competing",)),
    ("Co-op Slope Spurt/Comp", ("spurt","competing"), ("tenacious",)),
    ("Rest", (), ()),
]

PACE_PLANS = ["Early Push","Even","Late Push"]

# Preferred pace plan tendencies by leg type:
# - Early types (FR/SD) do better with Early Push on Start-focused work
# - Late types (LS/SR) do better with Late Push on Spurt-focused work
# - Almighty prefers Even
def _preferred_plans(training_name: str, prim: Tuple[str,...], leg_type: str) -> List[str]:
    if leg_type == "AL":
        return ["Even"]

    early = leg_type in ("FR","SD")
    late  = leg_type in ("LS","SR")

    if "start" in prim or "oob" in prim:
        if early:
            return ["Early Push","Even"]
        if late:
            return ["Even","Late Push"]
        return ["Even"]

    if "spurt" in prim:
        if late:
            return ["Late Push","Even"]
        if early:
            return ["Even","Early Push"]
        return ["Even"]

    # default
    return ["Even"]

PREFERRED: Dict[Tuple[str,str], List[str]] = {}
for name, prim, _sec in TRAININGS:
    for lt in ("FR","SD","LS","SR","AL"):
        PREFERRED[(name, lt)] = _preferred_plans(name, prim, lt)

def _apply_delta(val: int, delta: int) -> int:
    return clamp_int(val + delta, 8, 48)


def _weighted_pick_stat(rng: RNG, items: List[str], weights: List[int]) -> str:
    """Deterministic weighted pick using the project's RNG wrapper."""
    if not items:
        raise ValueError("weighted_pick_stat: empty items")
    if len(items) != len(weights):
        raise ValueError("weighted_pick_stat: items/weights length mismatch")
    total = sum(max(0, int(w)) for w in weights)
    if total <= 0:
        # Fallback to uniform choice
        return rng.choice(items)
    r = rng.random() * total
    acc = 0.0
    for item, w in zip(items, weights):
        w = max(0, int(w))
        acc += w
        if r < acc:
            return item
    return items[-1]

def _scale_delta_for_diminishing(val: int, delta: int) -> int:
    # Diminishing returns (externals are clamped to 8..48).
    # We keep progression lively through mid-career and taper close to cap.
    if delta == 0:
        return 0
    mag = abs(delta)
    sign = 1 if delta > 0 else -1
    if val >= 46:
        mag = max(1, mag // 4)
    elif val >= 42:
        mag = max(1, mag // 2)
    return sign * mag

def _weighted_choice(rng: RNG, weights: List[Tuple[Grade, float]]) -> Grade:
    r = rng.random()
    acc = 0.0
    for g, w in weights:
        acc += w
        if r <= acc:
            return g
    return weights[-1][0]

def grade_from_minigame(rng: RNG, player_choice: str, preferred: List[str]) -> Grade:
    # Desired distribution:
    # - Perfect and Bad: rare, similar
    # - Good most common; Great > Cool; Cool still meaningful
    if player_choice in preferred:
        weights: List[Tuple[Grade,float]] = [
            ("Perfect", 0.05),
            ("Cool",    0.15),
            ("Great",   0.25),
            ("Good",    0.50),
            ("Bad",     0.05),
        ]
    else:
        weights = [
            ("Perfect", 0.05),
            ("Cool",    0.10),
            ("Great",   0.20),
            ("Good",    0.60),
            ("Bad",     0.05),
        ]
    return _weighted_choice(rng, weights)

def apply_training(player: Horse, training_index: int, grade: Grade, rng: RNG) -> TrainingResult:
    name, prim, sec = TRAININGS[training_index]
    deltas: Dict[str, int] = {k: 0 for k in ["start","corner","oob","competing","tenacious","spurt"]}

    if grade == "None":
        return TrainingResult(training_id=training_index, training_name=name, grade="None", deltas=deltas)

    e = player.externals

    # Rest training: mostly neutral, but can slightly recover/decline
    if name == "Rest":
        if grade in ("Perfect","Cool"):
            stat = rng.choice(["competing","tenacious","oob","corner"])
            cur = getattr(e, stat)
            adj = _scale_delta_for_diminishing(cur, 1)
            new_val = _apply_delta(cur, adj)
            setattr(e, stat, new_val)
            deltas[stat] += (new_val - cur)
        elif grade == "Bad":
            stat = rng.choice(["competing","tenacious","oob","corner"])
            cur = getattr(e, stat)
            adj = _scale_delta_for_diminishing(cur, -1)
            new_val = _apply_delta(cur, adj)
            setattr(e, stat, new_val)
            deltas[stat] += (new_val - cur)
        return TrainingResult(training_id=training_index, training_name=name, grade=grade, deltas=deltas)

    # ------------------------------
    # DOC-like external stat growth
    # ------------------------------
    # Instead of rolling independent deltas per stat (which can feel "chunky"),
    # we spend a small per-session point budget and allocate it across the
    # training's primary/secondary stats using weighted picks.

    budget_ranges = {
        "Perfect": (7, 11),
        "Cool":    (6, 10),
        "Great":   (5, 8),
        "Good":    (3, 6),
    }

    if grade in budget_ranges:
        lo, hi = budget_ranges[grade]
        budget = rng.randint(lo, hi)
        sign = 1
    else:  # Bad
        budget = rng.randint(1, 5)
        sign = -1

    # Weighted target pool: primaries dominate secondaries.
    weight_map: Dict[str, int] = {}
    for s in prim:
        weight_map[s] = weight_map.get(s, 0) + 4
    for s in sec:
        weight_map[s] = weight_map.get(s, 0) + 2

    targets = list(weight_map.keys())
    weights = list(weight_map.values())
    if not targets:
        targets = list(deltas.keys())
        weights = [1] * len(targets)

    # Spend the budget in mostly +1/+2 packets (occasional +2 feels DOC-like).
    p2_by_grade = {
        "Perfect": 0.55,
        "Cool":    0.45,
        "Great":   0.35,
        "Good":    0.20,
        "Bad":     0.25,
    }
    p2 = p2_by_grade.get(grade, 0.25)

    remaining = budget
    while remaining > 0:
        stat = _weighted_pick_stat(rng, targets, weights)
        cur = getattr(e, stat)

        # Force 2-point packets near the diminishing threshold so "budget" is
        # still spent even when the scaled gain becomes smaller.
        if remaining >= 2 and cur >= 42:
            packet = 2
        else:
            packet = 2 if (remaining >= 2 and rng.random() < p2) else 1

        raw = sign * packet
        adj = _scale_delta_for_diminishing(cur, raw)
        new_val = _apply_delta(cur, adj)
        setattr(e, stat, new_val)
        deltas[stat] += (new_val - cur)
        remaining -= packet

    # Breakthrough: small chance of an extra burst on a primary stat.
    if grade in ("Good", "Great", "Cool", "Perfect") and prim:
        bt_chance = {
            "Good": 0.08,
            "Great": 0.12,
            "Cool": 0.15,
            "Perfect": 0.18,
        }.get(grade, 0.0)
        if rng.random() < bt_chance:
            stat = rng.choice(list(prim))
            extra = rng.randint(2, 4) if grade in ("Cool", "Perfect") else rng.randint(2, 3)
            cur = getattr(e, stat)
            adj = _scale_delta_for_diminishing(cur, extra)
            new_val = _apply_delta(cur, adj)
            setattr(e, stat, new_val)
            deltas[stat] += (new_val - cur)

    # Spillover: occasional small tick to a non-target stat.
    non_targets = [k for k in deltas.keys() if k not in set(prim + sec)]
    if non_targets:
        if grade != "Bad":
            so_chance = {
                "Good": 0.20,
                "Great": 0.25,
                "Cool": 0.30,
                "Perfect": 0.35,
            }.get(grade, 0.20)
            if rng.random() < so_chance:
                other = rng.choice(non_targets)
                cur = getattr(e, other)
                adj = _scale_delta_for_diminishing(cur, 1)
                new_val = _apply_delta(cur, adj)
                setattr(e, other, new_val)
                deltas[other] += (new_val - cur)
        else:
            # Bad training: small extra random penalty to emphasize risk.
            if rng.random() < 0.35:
                other = rng.choice(non_targets)
                cur = getattr(e, other)
                adj = _scale_delta_for_diminishing(cur, -1)
                new_val = _apply_delta(cur, adj)
                setattr(e, other, new_val)
                deltas[other] += (new_val - cur)

    return TrainingResult(training_id=training_index, training_name=name, grade=grade, deltas=deltas)

def primary_secondary_for_training(training_index: int) -> Tuple[Tuple[str,...], Tuple[str,...]]:
    return TRAININGS[training_index][1], TRAININGS[training_index][2]
