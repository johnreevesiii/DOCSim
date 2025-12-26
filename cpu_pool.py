from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Tuple

from .rng import RNG, hash64
from .models import Externals, Horse, Internals
from .breeding import compute_birth_ext_8_48_from_parents, breed_internals, derive_style_fr_sr, clamp_int, breed_ac
from .rating import compute_pool_int_stats, compute_rating
from .names import load_name_pool, build_round_names

Slot = Literal["1R","2R","3R","4R","5R","G1"]

BANDS: Dict[Slot, Tuple[float, float]] = {
    "1R": (0.20, 0.80),
    "2R": (0.25, 0.85),
    "3R": (0.50, 0.95),
    "4R": (0.30, 0.85),
    "5R": (0.40, 0.90),
    "G1": (0.65, 1.00),
}

@dataclass
class RoundPool:
    round_num: int
    seed: int
    horses: List[Horse]
    sorted_ids: List[str]
    used_by_slot: Dict[Slot, set]


def count_player_wins(player: Horse) -> int:
    """Total career wins for the player horse.

    We intentionally derive this from the persisted career log (rather than adding
    a new save field) so old saves remain compatible.
    """

    wins = 0
    for entry in getattr(player, "career_log", []) or []:
        if getattr(entry, "player_pos", None) == 1:
            wins += 1
    return wins


def player_rating_percentile(player: Horse, pool_horses: List[Horse]) -> float:
    """Percentile rank of the player horse's rating within the current round pool.

    Returns a value in [0, 1]. Uses `rating_base` when present on pool horses.
    """

    if not pool_horses:
        return 0.50

    pool_int_mu, pool_int_sd = compute_pool_int_stats(pool_horses)
    pr = compute_rating(player, pool_int_mu, pool_int_sd)

    ratings: List[float] = []
    for h in pool_horses:
        if getattr(h, "rating_base", None) is None:
            ratings.append(compute_rating(h, pool_int_mu, pool_int_sd))
        else:
            ratings.append(float(h.rating_base))

    if not ratings:
        return 0.50

    le = sum(1 for r in ratings if r <= pr)
    return le / float(len(ratings))


def compute_1r_handicap_band_shift(player: Horse, pool_horses: List[Horse]) -> Tuple[float, int, float]:
    """Compute an additional band shift for slot 1R.

    Design intent:
      - Stronger/More successful horses should draw tougher 1R fields.
      - We keep the shift bounded and modest so it doesn't invalidate the
        round difficulty curve.

    Returns:
      (shift, wins, percentile)
    """

    wins = count_player_wins(player)
    pct = player_rating_percentile(player, pool_horses)

    # Wins-driven scaling (primary). ~0.12 max.
    shift_wins = min(0.12, wins * 0.008)  # 10 wins => 0.08

    # G1 wins provide a smaller nudge. ~0.06 max.
    g1_wins = int(getattr(player, "g1_wins", 0) or 0)
    shift_g1 = min(0.06, g1_wins * 0.02)

    # If the player is in the top 30% of the pool, nudge upward. ~0.06 max.
    shift_pct = 0.0
    if pct > 0.70:
        shift_pct = min(0.06, (pct - 0.70) * 0.20)  # pct=1.0 => +0.06

    shift = min(0.18, shift_wins + shift_g1 + shift_pct)
    return (shift, wins, pct)

def round_mean_multiplier(round_num: int) -> float:
    return 1.00 + (round_num - 1) * (0.35 / 15.0)

def _scale_external(v: int, rm: float) -> int:
    mid = 28
    scaled = mid + (v - mid) * rm
    return clamp_int(int(round(scaled)), 8, 48)

def _scale_internals(i: Dict[str, int], rm: float) -> Dict[str, int]:
    mult = 0.95 + 0.05 * rm
    return {k: int(round(v * mult)) for k, v in i.items()}

def build_round_pool(global_seed: int, round_num: int, sires, dams, data_dir: str, pool_size: int = 36) -> RoundPool:
    seed = hash64(global_seed, "ROUND", round_num)
    rng = RNG(seed)
    rm = round_mean_multiplier(round_num)

    # naming
    base_names = load_name_pool(Path(data_dir))
    names = build_round_names(global_seed, round_num, pool_size, base_names)

    horses: List[Horse] = []
    for idx in range(pool_size):
        sire = rng.choice(sires)
        dam  = rng.choice(dams)
        ext = compute_birth_ext_8_48_from_parents(sire, dam, rng, cap_sum=160)
        ints = breed_internals(sire, dam)
        ac = breed_ac(sire, dam, rng)

        ext2 = {k: _scale_external(ext[k], rm) for k in ext}
        ints2 = _scale_internals(ints, rm)

        style = derive_style_fr_sr(ext2)

        horses.append(Horse(
            id=f"CPU-R{round_num:02d}-{idx:02d}",
            name=names[idx],
            sex=rng.choice(["M", "F"]),
            style=style,
            ac=ac,
            internals=Internals(**ints2),
            externals=Externals(**ext2),
        ))

    mu, sd = compute_pool_int_stats(horses)
    for h in horses:
        h.rating_base = compute_rating(h, mu, sd)

    sorted_ids = [h.id for h in sorted(horses, key=lambda x: float(x.rating_base or 0.0))]
    used_by_slot = {slot: set() for slot in BANDS.keys()}
    return RoundPool(round_num=round_num, seed=seed, horses=horses, sorted_ids=sorted_ids, used_by_slot=used_by_slot)

def select_cpu_field(
    global_seed: int,
    pool: RoundPool,
    slot: Slot,
    meet_iteration: int,
    field_size: int = 11,
    band_shift: float = 0.0
) -> List[Horse]:
    lo_p, hi_p = BANDS[slot]
    lo_p = max(0.0, min(1.0, lo_p + band_shift))
    hi_p = max(0.0, min(1.0, hi_p + band_shift))
    if hi_p < lo_p:
        hi_p = lo_p

    ids = pool.sorted_ids
    n = len(ids)
    lo = int(n * lo_p)
    hi = max(lo, int(n * hi_p) - 1)
    candidates = ids[lo:hi+1]

    rng = RNG(hash64(global_seed, "FIELD", pool.round_num, slot, meet_iteration))
    candidates = candidates[:]  # copy
    rng.shuffle(candidates)

    used = pool.used_by_slot[slot]
    chosen: List[str] = []
    for hid in candidates:
        if hid not in used:
            chosen.append(hid)
        if len(chosen) == field_size:
            break

    if len(chosen) < field_size:
        for hid in candidates:
            if hid not in chosen:
                chosen.append(hid)
            if len(chosen) == field_size:
                break

    used.update(chosen)
    m = {h.id: h for h in pool.horses}
    return [m[i] for i in chosen if i in m]
