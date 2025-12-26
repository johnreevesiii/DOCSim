from __future__ import annotations
from typing import Dict, List

from .rng import RNG, hash64
from .models import Horse
from .schedule import RaceMeta

def apply_post_race_growth(global_seed: int, meet_iteration: int, race: RaceMeta, player: Horse, finish_pos: int) -> Dict[str, int]:
    rng = RNG(hash64(global_seed, "GROW", race.round_num, race.slot, meet_iteration))
    is_feature = (race.slot == "3R")
    is_g1 = (race.slot == "G1")

    if is_g1:
        p = 0.60 if finish_pos == 1 else 0.35 if finish_pos == 2 else 0.25 if finish_pos == 3 else 0.10
        extra_p = 0.20 if finish_pos == 1 else 0.0
    elif is_feature:
        p = 0.40 if finish_pos == 1 else 0.25 if finish_pos == 2 else 0.20 if finish_pos == 3 else 0.08
        extra_p = 0.0
    else:
        p = 0.25 if finish_pos == 1 else 0.15 if finish_pos == 2 else 0.10 if finish_pos == 3 else 0.05
        extra_p = 0.0

    applied = {"stamina": 0, "speed": 0, "sharp": 0}
    keys = ["stamina","speed","sharp"]

    if rng.random() < p:
        k = rng.choice(keys)
        setattr(player.internals, k, getattr(player.internals, k) + 1)
        applied[k] += 1

    if extra_p and rng.random() < extra_p:
        k = rng.choice(keys)
        setattr(player.internals, k, getattr(player.internals, k) + 1)
        applied[k] += 1

    return applied

def apply_g1_win_rewards(player: Horse, finish_pos: int) -> Dict[str,int]:
    # update g1 wins and genetic token opportunities (handled via feeding specials)
    eff = {"g1_wins_added": 0}
    if finish_pos == 1:
        player.g1_wins += 1
        player.pending_g1_superfood = True
        eff["g1_wins_added"] = 1
    return eff
