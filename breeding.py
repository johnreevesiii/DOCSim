from __future__ import annotations
from typing import Dict, Literal, Tuple

from .rng import RNG

ExternalKey = Literal["start","corner","oob","competing","tenacious","spurt"]
MIN_V, MAX_V = 8, 48

def clamp_int(x: int, lo: int, hi: int) -> int:
    return lo if x < lo else hi if x > hi else x

def safe_get(obj, key: str) -> int:
    return int(getattr(obj, key)) if hasattr(obj, key) else int(obj[key])

def floor_avg(a: int, b: int) -> int:
    return (a + b) // 2

def breed_internals(sire, dam) -> Dict[str, int]:
    return {
        "stamina": floor_avg(int(sire.stamina), int(dam.stamina)),
        "speed":   floor_avg(int(sire.speed), int(dam.speed)),
        "sharp":   floor_avg(int(sire.sharp), int(dam.sharp)),
    }

def breed_ac(sire, dam, rng: RNG, sd: float = 18.0) -> int:
    base = (int(sire.ac) + int(dam.ac)) / 2.0
    v = int(round(base + rng.gauss(0.0, sd)))
    return clamp_int(v, 0, 255)

def compute_birth_ext_8_48_from_parents(
    sire, dam,
    rng: RNG,
    cap_sum: int = 160,
    genetic_tokens_sire: int = 0,
    genetic_tokens_dam: int = 0
) -> Dict[ExternalKey, int]:
    keys: Tuple[ExternalKey, ...] = ("start","corner","oob","competing","tenacious","spurt")
    gamma = 1.6
    sd_base = 2.2
    anom_p = 0.035
    anom_mag = 14.0

    t_total = max(0, int(genetic_tokens_sire) + int(genetic_tokens_dam))
    n_shift = 0.03 * max(0, min(t_total, 6))
    cap_sum = min(180, cap_sum + min(4 * t_total, 20))

    out: Dict[ExternalKey, int] = {}
    for k in keys:
        a0 = clamp_int(safe_get(sire, k), 0, 16)
        b0 = clamp_int(safe_get(dam, k), 0, 16)
        denom = 16 if (a0 == 16 or b0 == 16) else 15
        n = ((a0 + b0) / 2.0) / float(denom)
        n = max(0.0, min(1.0, n + n_shift))
        expected = MIN_V + (MAX_V - MIN_V) * (n ** gamma)

        noise = rng.tri_centered() * sd_base * 2.0

        if rng.random() < anom_p:
            p_pos = min(0.70, 0.50 + 0.05 * t_total)
            sign = 1.0 if (rng.random() < p_pos) else -1.0
            noise += sign * (rng.random() * anom_mag)

        v = int(expected + noise)
        out[k] = clamp_int(v, MIN_V, MAX_V)

    # cap enforcement
    def sum_ext(d: Dict[ExternalKey, int]) -> int:
        return sum(d[k] for k in keys)

    for _ in range(20):
        s = sum_ext(out)
        if s <= cap_sum:
            break
        excess = s - cap_sum
        reducibles = [(k, out[k] - MIN_V) for k in keys if out[k] > MIN_V]
        total_room = sum(r for _, r in reducibles)
        if total_room <= 0:
            break
        for k, room in reducibles:
            cut = int(round(excess * (room / total_room)))
            if cut <= 0:
                continue
            out[k] = max(MIN_V, out[k] - cut)

    while sum_ext(out) > cap_sum:
        kmax = max(keys, key=lambda kk: out[kk])
        if out[kmax] <= MIN_V:
            break
        out[kmax] -= 1

    return out


def derive_leg_type(racing_ext: Dict[ExternalKey, int]) -> str:
    """Derive DOC-style leg type from externals (excluding CORNER).

    Rules (from DOC guides):
      - Front-runner (FR): START is the highest
      - Start Dash (SD): START is 2nd highest
      - Last Spurt (LS): START is 3rd highest
      - Stretch-runner (SR): START is 4th or 5th highest
      - Almighty (AL): all compared values are very similar

    We compare: START, OOB, COMPETING, TENACIOUS, SPURT (CORNER excluded).
    """
    compare = ["start","oob","competing","tenacious","spurt"]
    vals = [racing_ext[k] for k in compare]
    if max(vals) - min(vals) <= 3:
        return "AL"

    start = racing_ext["start"]
    greater = sum(1 for k in compare if racing_ext[k] > start)
    if greater == 0:
        return "FR"
    if greater == 1:
        return "SD"
    if greater == 2:
        return "LS"
    return "SR"


def derive_style_fr_sr(racing_ext: Dict[ExternalKey, int]) -> str:
    """Backward-compatible helper. Returns the full 5-type code in v0.2.3+."""
    return derive_leg_type(racing_ext)

