from __future__ import annotations
import math
from typing import List, Tuple

from .models import Horse

def ext_sum(h: Horse) -> int:
    e = h.externals
    return e.start + e.corner + e.oob + e.competing + e.tenacious + e.spurt

def int_sum(h: Horse) -> int:
    i = h.internals
    return i.stamina + i.speed + i.sharp

def compute_pool_int_stats(horses: List[Horse]) -> Tuple[float, float]:
    vals = [int_sum(h) for h in horses]
    mu = sum(vals) / max(1, len(vals))
    var = sum((v - mu) ** 2 for v in vals) / max(1, len(vals))
    sd = math.sqrt(var) if var > 1e-9 else 1.0
    return mu, sd

def compute_rating(h: Horse, pool_int_mean: float, pool_int_sd: float) -> float:
    en = (ext_sum(h) - 48) / (288 - 48) * 100.0
    z = (int_sum(h) - pool_int_mean) / pool_int_sd
    inn = z * 15.0 + 50.0
    return 0.55 * en + 0.45 * inn
