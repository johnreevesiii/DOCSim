from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, List

from .rng import RNG, hash64
from .models import Horse
from .race_engine import base_score

@dataclass
class GamblingChanceResult:
    picked_horse_id: str
    winner_horse_id: str
    won: bool
    payout: int
    odds_by_horse: Dict[str, float]

def softmax(scores: List[float], T: float) -> List[float]:
    mx = max(scores)
    exps = [math.exp((s - mx) / T) for s in scores]
    Z = sum(exps)
    return [e / Z for e in exps]

def run_gambling_chance(
    global_seed: int,
    meet_iteration: int,
    round_num: int,
    slot: str,
    cpu_field: List[Horse],
    picked_horse_id: str,
    stake: int = 25_000,
    house_edge: float = 0.15,
    temp: float = 12.0,
    round_unit: int = 10_000
) -> GamblingChanceResult:
    rng = RNG(hash64(global_seed, "GAMBLE", round_num, slot, meet_iteration))

    ids = [h.id for h in cpu_field]
    raw = [base_score(h, 1600) + rng.gauss(0.0, 2.0) + rng.gauss(0.0, 1.0) for h in cpu_field]
    ps = softmax(raw, temp)

    odds: Dict[str, float] = {}
    for hid, p in zip(ids, ps):
        p = max(1e-6, p)
        odds[hid] = (1.0 / p) * (1.0 - house_edge)

    # sample winner
    r = rng.random()
    acc = 0.0
    winner = ids[-1]
    for hid, p in zip(ids, ps):
        acc += p
        if r <= acc:
            winner = hid
            break

    won = (picked_horse_id == winner)
    payout = 0
    if won:
        payout = int(round((stake * odds[picked_horse_id]) / round_unit) * round_unit)

    return GamblingChanceResult(
        picked_horse_id=picked_horse_id,
        winner_horse_id=winner,
        won=won,
        payout=payout,
        odds_by_horse=odds
    )
