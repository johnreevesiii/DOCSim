from __future__ import annotations

"""Race simulation.

v0.2.8 focuses on making races *feel* more like DOC by introducing:
  - Deterministic gate draw per race (displayed in the handicapping table)
  - Stronger surface/condition preference impact (AC + going)
  - Distance/fitness fade (sharp/sprint types struggle more at long distances)
  - Simple pace + trip dynamics so externals matter in-context

This module intentionally keeps the public surface area small:
  - draw_gates(...)
  - run_race_sim(...)
"""

from dataclasses import dataclass, field
import math
from typing import Dict, List, Tuple

from .models import Condition, Horse, Surface
from .schedule import RaceMeta
from .rng import RNG, hash64
from .surfaces import surface_fit


def _get_field(obj, name: str, default):
    """Get a stat field from a dataclass or dict-like object.

    v0.2+ stores Internals/Externals as dataclasses. Older helper code used
    dict-style access. This keeps the race engine resilient.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def distance_profile(distance_m: int) -> Tuple[float, float, float]:
    """Return (sprint, mile, stayer) weights that sum to ~1."""
    if distance_m <= 1400:
        return (0.75, 0.25, 0.0)
    if distance_m <= 2000:
        return (0.30, 0.55, 0.15)
    if distance_m <= 2600:
        return (0.15, 0.35, 0.50)
    return (0.05, 0.25, 0.70)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _ext_norm(v: int) -> float:
    """Map externals 8..48 onto a 0..60-ish scale for mixing with internals."""
    vv = _clamp(float(v), 8.0, 48.0)
    return (vv - 8.0) * 1.5


def _condition_heaviness(cond: Condition) -> float:
    # Applies to both TURF and DIRT. Higher = more demanding.
    if cond == "GOOD":
        return 0.0
    if cond == "GOOD_TO_SOFT":
        return 0.35
    if cond == "SOFT":
        return 0.70
    return 1.0  # HEAVY


def _tri_noise(rng: RNG) -> float:
    """Triangular-ish noise in [-1, 1] with peak at 0."""
    return (rng.random() + rng.random() - 1.0)


def _gauss(rng: RNG, mu: float = 0.0, sigma: float = 1.0) -> float:
    """Box–Muller Gaussian using our deterministic RNG wrapper."""
    # Guard against log(0)
    u1 = max(1e-12, rng.random())
    u2 = rng.random()
    z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mu + sigma * z0


def _style_maps() -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    """Style coefficients used by the simulator.

    Returns (early_bonus, mid_bonus, late_bonus, endurance_factor).
    """
    early = {"FR": 3.0, "SD": 2.0, "AL": 0.5, "LS": -0.5, "SR": -1.0}
    mid = {"FR": 0.2, "SD": 0.4, "AL": 0.6, "LS": 0.2, "SR": 0.0}
    late = {"FR": -1.0, "SD": -0.5, "AL": 0.5, "LS": 3.0, "SR": 2.0}
    endurance = {"FR": 1.00, "SD": 0.90, "AL": 0.75, "LS": 0.55, "SR": 0.45}
    return early, mid, late, endurance


_STYLE_EARLY_BONUS, _STYLE_MID_BONUS, _STYLE_LATE_BONUS, _STYLE_ENDURANCE = _style_maps()


def _gate_ideal_pos(style: str) -> float:
    # 0 = rail, 1 = widest
    if style in ("FR", "SD"):
        return 0.22
    if style == "AL":
        return 0.50
    if style == "LS":
        return 0.65
    return 0.75  # SR and any unknown closer-like styles


def _gate_penalty(
    *,
    gate: int,
    n_runners: int,
    style: str,
    surface: Surface,
    sprint: float,
    mile: float,
    stayer: float,
    break_skill: float,
) -> float:
    """Gate penalty in score units (positive = bad; subtract from phase scores)."""
    if n_runners <= 1:
        return 0.0
    gate_pos = (gate - 1) / (n_runners - 1)
    gate_pos = _clamp(gate_pos, 0.0, 1.0)

    # Gate matters more in sprints, less in stayers.
    severity = (1.9 * sprint + 1.2 * mile + 0.7 * stayer) * (1.15 if surface == "TURF" else 1.0)

    # Style preference (inside for speed, outside-ish for closers to avoid traffic).
    ideal = _gate_ideal_pos(style)
    style_pen = abs(gate_pos - ideal) * severity * 2.3

    # Universal outside ground loss (still applies even if a closer *prefers* outside).
    outside_sev = (1.4 * sprint + 0.9 * mile + 0.5 * stayer) * (1.05 if surface == "TURF" else 1.0)
    outside_pen = gate_pos * outside_sev * 1.3

    raw = style_pen + outside_pen

    # Strong breakers (START/OOB) mitigate gate disadvantages.
    mitig = 1.0 - 0.50 * _clamp(break_skill, 0.0, 1.0)
    return raw * mitig


def _turn_penalty(
    *,
    gate: int,
    n_runners: int,
    surface: Surface,
    sprint: float,
    mile: float,
    stayer: float,
    corner_skill: float,
) -> float:
    """Extra wide-turn penalty (positive = bad; subtract from mid phase)."""
    if n_runners <= 1:
        return 0.0
    gate_pos = (gate - 1) / (n_runners - 1)
    gate_pos = _clamp(gate_pos, 0.0, 1.0)

    sev = (1.6 * sprint + 1.2 * mile + 0.9 * stayer) * (1.15 if surface == "TURF" else 1.0)
    # Low CORNER makes wide trips hurt more.
    lack = 1.0 - _clamp(corner_skill, 0.0, 1.0)
    return gate_pos * sev * lack * 1.8


def _surface_scalar(ac: int, surface: Surface, cond: Condition) -> float:
    """Performance scalar driven by AC surface preference and track condition."""
    fit = float(surface_fit(ac, surface))  # typically in [-0.4, 1.0]
    heavy = _condition_heaviness(cond)

    if fit >= 0:
        # Good fit: modest benefit.
        return 1.0 + 0.10 * fit

    # Bad fit: bigger penalty, amplified on heavier going (especially important on dirt-heavy tracks).
    return 1.0 + 0.24 * fit * (1.0 + 0.90 * heavy)


def _pace_hotness(early_potentials: List[float]) -> float:
    """0..~2 pace intensity derived from the early-speed spread in the field."""
    n = len(early_potentials)
    if n < 3:
        return 0.0

    mean = sum(early_potentials) / n
    var = sum((v - mean) ** 2 for v in early_potentials) / n
    sd = math.sqrt(var) if var > 1e-9 else 0.0
    if sd <= 1e-9:
        return 0.0

    top3 = sorted(early_potentials, reverse=True)[:3]
    top_mean = sum(top3) / 3.0
    z = (top_mean - mean) / sd
    # Small dead-zone so normal fields don't always register as "hot".
    return _clamp(z - 0.25, 0.0, 2.0)


def draw_gates(
    seed: int,
    meet_iter: int,
    race_meta: RaceMeta,
    condition: Condition,
    runners: List[Horse],
) -> Dict[str, int]:
    """Deterministically draw gates for this race."""
    base = hash64(seed, meet_iter, race_meta.course_code, race_meta.distance, race_meta.surface, condition)
    gate_rng = RNG(hash64(base, "GATE"))
    gates = list(range(1, len(runners) + 1))

    # Fisher–Yates shuffle using deterministic RNG.
    for i in range(len(gates) - 1, 0, -1):
        j = int(gate_rng.random() * (i + 1))
        gates[i], gates[j] = gates[j], gates[i]

    return {h.id: gates[i] for i, h in enumerate(runners)}


# ---------------------------
# Simulation
# ---------------------------


@dataclass
class RaceSimResult:
    scores: Dict[str, float]
    finish_order: List[Horse]
    # Payouts keyed by horse id (top-3 only).
    payouts: Dict[str, int]
    # Gate draw keyed by horse id.
    gates: Dict[str, int]
    # Payouts keyed by finishing position (1..12). Used by the race card renderer.
    payouts_by_pos: Dict[int, int] = field(default_factory=dict)


def _early_mid_late_base(
    h: Horse,
    *,
    sprint: float,
    mile: float,
    stayer: float,
    gate: int,
    n_runners: int,
    surface: Surface,
    hrng: RNG,
) -> tuple[float, float, float]:
    """Compute base early/mid/late phase scores (before pace/trip/fit scalars)."""
    st = float(_get_field(h.internals, "stamina", 0))
    sp = float(_get_field(h.internals, "speed", 0))
    sh = float(_get_field(h.internals, "sharp", 0))

    start = _ext_norm(int(_get_field(h.externals, "start", 8)))
    corner = _ext_norm(int(_get_field(h.externals, "corner", 8)))
    oob = _ext_norm(int(_get_field(h.externals, "oob", 8)))
    comp = _ext_norm(int(_get_field(h.externals, "competing", 8)))
    ten = _ext_norm(int(_get_field(h.externals, "tenacious", 8)))
    spur = _ext_norm(int(_get_field(h.externals, "spurt", 8)))

    style = str(h.style)

    # Phase cores (0..~60 scale)
    early_i = 0.60 * sp + 0.40 * sh
    early_e = 0.65 * start + 0.35 * oob
    early = 0.45 * early_i + 0.55 * early_e

    mid_i = 0.45 * sp + 0.25 * sh + 0.30 * st
    mid_e = 0.55 * comp + 0.45 * corner
    mid = 0.55 * mid_e + 0.45 * mid_i

    late_i = 0.55 * st + 0.30 * sp + 0.15 * sh
    late_e = 0.55 * spur + 0.45 * ten
    late = 0.55 * late_e + 0.45 * late_i

    # Style bias
    early += _STYLE_EARLY_BONUS.get(style, 0.0)
    mid += _STYLE_MID_BONUS.get(style, 0.0)
    late += _STYLE_LATE_BONUS.get(style, 0.0)

    # Gates: penalty (mitigated by break skill) impacts early most.
    break_skill = (0.60 * start + 0.40 * oob) / 60.0
    gp = _gate_penalty(
        gate=gate,
        n_runners=n_runners,
        style=style,
        surface=surface,
        sprint=sprint,
        mile=mile,
        stayer=stayer,
        break_skill=break_skill,
    )
    early -= gp * (0.75 * sprint + 0.40 * mile + 0.20 * stayer)
    mid -= gp * (0.25 * sprint + 0.40 * mile + 0.35 * stayer)

    # Extra wide-turn tax (outside + low CORNER).
    cp = _turn_penalty(
        gate=gate,
        n_runners=n_runners,
        surface=surface,
        sprint=sprint,
        mile=mile,
        stayer=stayer,
        corner_skill=corner / 60.0,
    )
    mid -= cp

    # Break variance (mostly affects the early picture / pace).
    early += _tri_noise(hrng) * (1.20 * sprint + 0.85 * mile + 0.60 * stayer)

    return early, mid, late


def run_race_sim(
    seed: int,
    meet_iter: int,
    race_meta: RaceMeta,
    condition: Condition,
    player: Horse,
    cpu11: List[Horse],
    *,
    gate_by_id: Dict[str, int] | None = None,
) -> RaceSimResult:
    """Simulate a race.

    The returned scores are relative "performance" values; the reporting layer converts them into
    times + margins and updates records.
    """
    runners = [player] + list(cpu11)

    # Deterministic base seed per race.
    base = hash64(seed, meet_iter, race_meta.course_code, race_meta.distance, race_meta.surface, condition)

    # Gates should be deterministic but not consume the scoring RNG stream.
    if gate_by_id is None:
        gate_by_id = draw_gates(seed, meet_iter, race_meta, condition, runners)

    sprint, mile, stayer = distance_profile(int(race_meta.distance))
    surface: Surface = race_meta.surface
    heavy = _condition_heaviness(condition)

    # Phase build-up (including gate + break variance)
    phase_by_id: Dict[str, tuple[float, float, float]] = {}
    early_pots: List[float] = []
    for h in runners:
        hrng = RNG(hash64(base, h.id, "HORSE"))
        gate = int(gate_by_id.get(h.id, 1))
        early, mid, late = _early_mid_late_base(
            h,
            sprint=sprint,
            mile=mile,
            stayer=stayer,
            gate=gate,
            n_runners=len(runners),
            surface=surface,
            hrng=hrng,
        )
        phase_by_id[h.id] = (early, mid, late)
        early_pots.append(early)

    pace_hot = _pace_hotness(early_pots)

    # Determine early rank (for pace involvement & traffic effects)
    early_order = sorted(runners, key=lambda hh: phase_by_id[hh.id][0], reverse=True)
    early_rank: Dict[str, int] = {h.id: i + 1 for i, h in enumerate(early_order)}

    scores: Dict[str, float] = {}
    for h in runners:
        hrng = RNG(hash64(base, h.id, "HORSE"))
        gate = int(gate_by_id.get(h.id, 1))
        rank = int(early_rank.get(h.id, 6))
        style = str(h.style)

        st = float(_get_field(h.internals, "stamina", 0))
        sp = float(_get_field(h.internals, "speed", 0))
        sh = float(_get_field(h.internals, "sharp", 0))

        start = _ext_norm(int(_get_field(h.externals, "start", 8)))
        oob = _ext_norm(int(_get_field(h.externals, "oob", 8)))
        comp = _ext_norm(int(_get_field(h.externals, "competing", 8)))
        ten = _ext_norm(int(_get_field(h.externals, "tenacious", 8)))

        early, mid, late = phase_by_id[h.id]

        # Trip / traffic for closers: low OOB means higher chance of getting "stuck".
        is_closer = style in ("LS", "SR") or rank >= 8
        traffic_prob = 0.12 + 0.06 * sprint + 0.08 * mile + 0.10 * stayer
        if is_closer:
            traffic_prob += 0.10
        if surface == "DIRT" and heavy >= 0.70:
            traffic_prob += 0.05  # kickback / slog
        if gate <= 4:
            traffic_prob += 0.07
        elif gate <= 8:
            traffic_prob += 0.03
        # Mitigation: OOB + competing helps navigate.
        traffic_prob -= (oob / 60.0) * 0.18
        traffic_prob -= (comp / 60.0) * 0.08
        traffic_prob = _clamp(traffic_prob, 0.0, 0.55)

        if hrng.random() < traffic_prob:
            # Stuck in traffic: hurts late kick.
            penalty = (1.5 + hrng.random() * 2.5) * (1.0 - (oob / 60.0) * 0.55)
            late -= penalty * (0.65 * sprint + 0.55 * mile + 0.45 * stayer)
            mid -= penalty * 0.25
        else:
            # Clear run / cut-through: good OOB closers occasionally get a slingshot.
            if is_closer and oob >= 45.0:
                cut_chance = 0.12 + 0.08 * mile + 0.06 * stayer
                if hrng.random() < cut_chance:
                    late += 1.0 + hrng.random() * 1.5

        # Pace fade: hot pace punishes leaders on longer trips if stamina/tenacity are lacking.
        if rank <= 2:
            pos_fac = 1.00
        elif rank <= 4:
            pos_fac = 0.85
        elif rank <= 6:
            pos_fac = 0.65
        elif rank <= 9:
            pos_fac = 0.40
        else:
            pos_fac = 0.25

        endurance = _STYLE_ENDURANCE.get(style, 0.75)
        dist_fac = 0.30 * sprint + 0.70 * mile + 1.00 * stayer

        energy = 0.55 * st + 0.45 * ten
        energy_def = max(0.0, 32.0 - energy) / 32.0
        pace_fade = pace_hot * pos_fac * endurance * dist_fac * (1.5 + 2.5 * energy_def)

        # Distance/fitness fade: sharp/sprinty builds struggle more when stayer weight is high.
        sprinter_apt = 0.55 * sp + 0.45 * sh
        mismatch = max(0.0, sprinter_apt - st)
        dist_fade = (mismatch / 40.0) * endurance * (0.20 * sprint + 0.80 * mile + 1.20 * stayer) * 2.8

        # Going handling: tenacious/stamina matter more on heavy tracks.
        handling = 0.45 * st + 0.55 * ten
        going_adj = heavy * ((handling - 30.0) / 30.0) * 2.0

        # Combine phases (distance-weighted)
        w_early = 0.45 * sprint + 0.30 * mile + 0.20 * stayer
        w_mid = 0.30 * sprint + 0.35 * mile + 0.35 * stayer
        w_late = 0.25 * sprint + 0.35 * mile + 0.45 * stayer

        score = w_early * early + w_mid * mid + w_late * late
        score += going_adj
        score -= (pace_fade + dist_fade)

        # Surface preference scalar (AC), amplified on heavier going.
        score *= _surface_scalar(int(h.ac), surface, condition)

        # Day-to-day noise: sprints are more chaotic than routes.
        sigma = 0.95 * sprint + 0.75 * mile + 0.60 * stayer
        score += _gauss(hrng, 0.0, sigma)
        score += _tri_noise(hrng) * 0.25

        scores[h.id] = score

    finish_order = sorted(runners, key=lambda hh: scores[hh.id], reverse=True)
    finish_ids = [h.id for h in finish_order]

    # Payouts (top 3). We keep both a by-horse-id map (for bookkeeping) and a by-position map
    # (for the race card renderer).
    purse = race_meta.winner_purse
    payout_list = [purse, int(purse * 0.3), int(purse * 0.2)]
    payouts_by_pos = {i + 1: payout_list[i] for i in range(len(payout_list))}
    payouts = {finish_ids[i]: payout_list[i] for i in range(min(3, len(finish_ids)))}

    return RaceSimResult(
        scores=scores,
        finish_order=finish_order,
        payouts=payouts,
        payouts_by_pos=payouts_by_pos,
        gates=gate_by_id,
    )


# ---------------------------------------------------------------------------
# Compatibility helper: base_score
# ---------------------------------------------------------------------------
#
# DOCSim v0.2.7 (and earlier) exposed a lightweight `base_score()` helper
# that some subsystems (e.g., the "Gambling Chance" fallback) still use.
# v0.2.8 refactored the race engine and removed that symbol, which breaks
# imports on startup.
#
# We restore `base_score()` here as a *compatibility* function. It is not used
# by the main simulation loop; it only needs to provide a stable, monotonic
# strength estimate for ranking horses.


def _compat_clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _compat_interp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    t = _compat_clamp(t, 0.0, 1.0)
    return y0 + (y1 - y0) * t


def _compat_distance_profile(distance_m: int) -> Tuple[float, float, float]:
    """Return (early, mid, late) weight triple that shifts with distance."""
    d = int(distance_m)
    if d <= 1200:
        return 0.40, 0.40, 0.20
    if d <= 1600:
        return 0.36, 0.34, 0.30
    if d <= 2000:
        return 0.32, 0.34, 0.34
    if d <= 2500:
        return 0.30, 0.35, 0.35
    return 0.25, 0.35, 0.40


def _compat_surface_component(ac: int, surface: Surface, condition: Condition) -> float:
    """Small additive term (+/-) for surface/condition preference based on AC."""

    a = float(_compat_clamp(float(ac), 0.0, 255.0))
    # turf_love: 0..1 where 1 = strong turf preference.
    turf_love = 1.0 - (a / 255.0)
    dirt_love = 1.0 - turf_love

    if surface == "TURF":
        base = (turf_love - 0.5) * 10.0
        cond_mult = {
            "GOOD": 1.00,
            "GOOD_TO_SOFT": 0.90,
            "SOFT": 0.80,
            "HEAVY": 0.70,
        }.get(condition, 1.0)
    else:
        base = (dirt_love - 0.5) * 10.0
        cond_mult = {
            "GOOD": 1.00,
            "GOOD_TO_SOFT": 1.05,
            "SOFT": 1.10,
            "HEAVY": 1.15,
        }.get(condition, 1.0)
    return base * cond_mult


def base_score(
    h: Horse,
    distance_m: int,
    surface: Surface = "TURF",
    condition: Condition = "GOOD",
) -> float:
    """Compatibility strength estimate used by the Gambling Chance fallback."""

    st = float(h.internals.stamina)
    sp = float(h.internals.speed)
    sh = float(h.internals.sharp)

    ex = h.externals
    start = float(ex.start)
    corner = float(ex.corner)
    oob = float(ex.oob)
    comp = float(ex.competing)
    ten = float(ex.tenacious)
    spurt = float(ex.spurt)

    early = 0.60 * start + 0.25 * oob + 0.15 * sp
    mid = 0.40 * corner + 0.25 * comp + 0.35 * ((st + sh) / 2.0)
    late = 0.55 * spurt + 0.25 * ten + 0.20 * sh

    w_e, w_m, w_l = _compat_distance_profile(int(distance_m))
    score = w_e * early + w_m * mid + w_l * late

    # Small surface/condition preference (kept modest on purpose).
    score += 0.08 * _compat_surface_component(int(h.ac), surface, condition)

    # Style tilt: front-runners benefit when early weight dominates;...
    if h.style == "FR":
        score += 0.7 * (w_e - w_l) * 10.0
    elif h.style == "SR":
        score += 0.7 * (w_l - w_e) * 10.0

    # Stamina scaling with distance (longer races reward above-average stamina).
    stamina_mod = _compat_interp(float(distance_m), 1200.0, 3000.0, 0.0, 3.0)
    score += stamina_mod * ((st - 32.0) / 32.0)

    return float(score)

