from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .models import Horse, Condition, Surface
from .roster import ParentHorse
from .schedule import RaceMeta
from .rng import RNG, hash64


def _iget(obj, key: str, default: int = 0) -> int:
    """Get an internal stat from either a dataclass-like object or a dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        try:
            return int(obj.get(key, default))
        except Exception:
            return default
    try:
        return int(getattr(obj, key))
    except Exception:
        return default


def _eget(obj, key: str, default: int = 0) -> int:
    """Get an external stat from either a dataclass-like object or a dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        try:
            return int(obj.get(key, default))
        except Exception:
            return default
    try:
        return int(getattr(obj, key))
    except Exception:
        return default


def _surface_preference_scalar(ac: float, surface: Surface, condition: Condition) -> float:
    """
    Mirror the race_engine surface-preference scalar (but kept local to avoid import cycles).
    Higher AC favors DIRT; ~128 favors TURF. Heavy dirt punishes non-dirt types a bit more.
    """
    ac = max(0.0, min(255.0, ac))

    if surface == "TURF":
        ideal = 128.0
        diff = abs(ac - ideal) / ideal  # 0..~1
        scalar = 1.0 - 0.18 * diff
        scalar = max(0.78, scalar)
        return scalar

    # DIRT
    ideal = 255.0
    diff = abs(ac - ideal) / ideal
    scalar = 1.0 - 0.22 * diff
    if condition == "HEAVY":
        scalar -= 0.04 * diff
    elif condition == "SOFT":
        scalar -= 0.015 * diff
    scalar = max(0.78, scalar)
    return scalar


def _distance_profile_scalar(distance: int, stamina: float, sharp: float) -> float:
    """
    Mirror the race_engine distance scalar in a simplified form:
    - "Sharp" horses struggle as distance grows.
    - "Stamina" horses can lack zip on short sprints.
    """
    d = float(distance)
    sharpness = sharp - stamina

    if d >= 2400:
        if sharpness > 10:
            return max(0.85, 1.0 - 0.012 * (sharpness - 10))
    elif d >= 2000:
        if sharpness > 12:
            return max(0.88, 1.0 - 0.010 * (sharpness - 12))
    elif d <= 1400:
        dullness = stamina - sharp
        if dullness > 10:
            return max(0.90, 1.0 - 0.010 * (dullness - 10))

    return 1.0


def expected_score(h: Horse, race: RaceMeta, condition: Condition, gate: int) -> float:
    """
    A deterministic 'on paper' score (no noise), used only for commentary/expectation checks.
    """
    st = float(_iget(getattr(h, "internals", None), "stamina", 0))
    sp = float(_iget(getattr(h, "internals", None), "speed", 0))
    sh = float(_iget(getattr(h, "internals", None), "sharp", 0))

    start = float(_eget(getattr(h, "externals", None), "start", 8))
    corner = float(_eget(getattr(h, "externals", None), "corner", 8))
    oob = float(_eget(getattr(h, "externals", None), "oob", 8))
    comp = float(_eget(getattr(h, "externals", None), "competing", 8))
    ten = float(_eget(getattr(h, "externals", None), "tenacious", 8))
    spurt = float(_eget(getattr(h, "externals", None), "spurt", 8))

    # Base internal power: speed-forward, with stamina & sharp contributions
    ip = 0.46 * sp + 0.30 * st + 0.24 * sh

    # Style weighting: keep the same "feel" as race_engine
    leg = getattr(h, "leg_type", "SR") or "SR"
    if leg == "FR":
        style = 0.36 * start + 0.26 * corner + 0.14 * comp + 0.10 * ten + 0.14 * spurt
    elif leg == "SD":
        style = 0.42 * start + 0.16 * oob + 0.18 * corner + 0.10 * comp + 0.14 * spurt
    elif leg == "LS":
        style = 0.18 * start + 0.18 * oob + 0.14 * corner + 0.14 * comp + 0.36 * spurt
    else:  # SR
        style = 0.20 * start + 0.22 * corner + 0.16 * comp + 0.12 * ten + 0.30 * spurt

    style_scalar = 0.84 + (style / 48.0) * 0.22

    ac = float(getattr(h, "ac", 128))
    surface_scalar = _surface_preference_scalar(ac, race.surface, condition)
    distance_scalar = _distance_profile_scalar(race.distance, st, sh)

    # Condition scalar: light penalty on soft/heavy, more on heavy
    condition_scalar = {
        "FIRM": 1.00,
        "GOOD": 1.00,
        "SOFT": 0.985,
        "GOOD_TO_SOFT": 0.985,
        "HEAVY": 0.965,
    }.get(condition, 1.00)

    # Gate scalar: modest penalty for very wide/inside draws (handled in race_engine too)
    g = max(1, min(12, int(gate)))
    mid = 6.5
    gate_pen = abs(g - mid) / mid  # 0..~0.85
    gate_scalar = 1.0 - 0.03 * gate_pen

    return ip * style_scalar * surface_scalar * distance_scalar * condition_scalar * gate_scalar


def birth_comment(seed: int, sex: str, sire: ParentHorse, dam: ParentHorse) -> str:
    """
    A short DOC-style birth line. Informational only; does not affect gameplay.
    """
    # Trait hint: use parents' best average internal
    st = (_iget(sire, "stamina", 0) + _iget(dam, "stamina", 0)) / 2.0
    sp = (_iget(sire, "speed", 0) + _iget(dam, "speed", 0)) / 2.0
    sh = (_iget(sire, "sharp", 0) + _iget(dam, "sharp", 0)) / 2.0

    trait = max([("stamina", st), ("speed", sp), ("sharp", sh)], key=lambda x: x[1])[0]

    trait_hint = {
        "stamina": "Plenty of lungs in the pedigree.",
        "speed": "Speed runs deep in this family.",
        "sharp": "Quick feet and sharper instincts in the bloodline.",
    }.get(trait, "Hard to say yet—time will tell.")

    male_lines = [
        "A colt hits the ground with purpose.",
        "A colt arrives—full of swagger.",
        "A colt is born, and the barn gets louder.",
        "A colt steps out like he owns the place.",
    ]
    female_lines = [
        "A filly arrives with a steady eye.",
        "A filly is born—light on her feet.",
        "A filly arrives, calm but confident.",
        "A filly steps out and the barn goes quiet.",
    ]

    rng = RNG(hash64(seed, "birth", sire.name, dam.name, sex))
    lead = rng.choice(female_lines if sex == "F" else male_lines)
    return f"Stable note: {lead} {trait_hint}"


def race_insight_lines(
    seed: int,
    horse: Horse,
    race: RaceMeta,
    condition: Condition,
    *,
    expected_rank: int,
    actual_pos: int,
    gate: int,
) -> List[str]:
    """
    Post-race commentary meant to hint at hidden modifiers (surface, distance, gate, style traffic).
    Only triggers when the horse underperforms vs expectation.
    """
    field_size = 12  # DOCSim always runs 12-horse fields today

    # We want these comments to show up often enough to be helpful (without spamming).
    #
    # "Underperformed" = finished meaningfully worse than the on-paper expectation.
    # Keeping this threshold moderately low makes it more likely the player sees feedback
    # about surface/distance/gate/style mismatches during normal play.
    underperformed = (actual_pos - expected_rank) >= 2 or (expected_rank <= 4 and actual_pos >= 6)


    # Gather basics
    ac = float(getattr(horse, "ac", 128))
    st = float(_iget(getattr(horse, "internals", None), "stamina", 0))
    sh = float(_iget(getattr(horse, "internals", None), "sharp", 0))
    sharpness = sh - st

    oob = float(_eget(getattr(horse, "externals", None), "oob", 8))
    ten = float(_eget(getattr(horse, "externals", None), "tenacious", 8))
    start = float(_eget(getattr(horse, "externals", None), "start", 8))
    leg = getattr(horse, "leg_type", "SR") or "SR"

    # Compute scalars (roughly mirroring race_engine)
    surf_scalar = _surface_preference_scalar(ac, race.surface, condition)
    dist_scalar = _distance_profile_scalar(race.distance, st, sh)

    # Trigger rules:
    # - Underperformed vs on-paper expectation, OR
    # - Finished poorly AND a strong surface/distance mismatch was present (to hint hidden modifiers)
    # Even if the horse was expected to be poor on paper, we still want to hint at why.
    # If the horse finishes mid-pack or worse AND has a notable mismatch, show a comment.
    mismatch_trigger = (actual_pos >= 5) and (surf_scalar <= 0.93 or dist_scalar <= 0.95)
    if not (underperformed or mismatch_trigger):
        return []


    # Preference text
    pref_surface = "DIRT" if ac >= 200 else ("TURF" if ac <= 160 else "MIXED")
    surf_name = "dirt" if race.surface == "DIRT" else "turf"

    reasons: List[Tuple[float, str]] = []

    # Surface mismatch
    if pref_surface != "MIXED" and pref_surface != race.surface and surf_scalar <= 0.93:
        want = "dirt" if pref_surface == "DIRT" else "turf"
        lines = [
            f"Trainer's note: That looked like a {want} runner on {surf_name}.",
            f"Track talk: Surface matters—{want} types can struggle on {surf_name}.",
        ]
        reasons.append((1.00 + (0.93 - surf_scalar) * 2.0, RNG(hash64(seed, 'c_surf', horse.id, race.name)).choice(lines)))

    # Heavy/soft going
    if condition in ("HEAVY", "SOFT", "GOOD_TO_SOFT"):
        # If they're already mismatched, we don't need to double-dip.
        if surf_scalar <= 0.96:
            lines = [
                f"The going was deep—{condition.lower().replace('_', ' ')} {surf_name} can punish the wrong type.",
                f"Not a clean trip in that footing. {condition.title().replace('_', ' ')} tracks can sap a runner.",
            ]
            reasons.append((0.70 + (1.0 - surf_scalar) * 1.0, RNG(hash64(seed, 'c_going', horse.id, race.name)).choice(lines)))

    # Distance mismatch for sharp horses on stamina courses
    if race.distance >= 2400 and sharpness > 8 and dist_scalar < 0.98:
        lines = [
            "That was a stamina course—sharp types can fade when the trip stretches.",
            "Long trip, sharp build. More stamina (or a shorter race) usually helps.",
        ]
        reasons.append((0.90 + (0.98 - dist_scalar) * 3.0, RNG(hash64(seed, 'c_trip', horse.id, race.name)).choice(lines)))

    # Sprint dullness for stamina horses
    if race.distance <= 1400 and (st - sh) > 10 and dist_scalar < 0.98:
        lines = [
            "Too sharp a sprint for a stayer—needed more early zip.",
            "Short trip, big lungs. Sprinters get first run here.",
        ]
        reasons.append((0.80 + (0.98 - dist_scalar) * 3.0, RNG(hash64(seed, 'c_sprint', horse.id, race.name)).choice(lines)))

    # Gate trouble (outside)
    if gate in (11, 12) and actual_pos >= 7:
        lines = [
            f"Bad draw: gate {gate} can force a wide trip.",
            f"Gate {gate} meant extra ground—hard to make it up.",
        ]
        reasons.append((0.55, RNG(hash64(seed, 'c_gate', horse.id, race.name)).choice(lines)))

    # Style/traffic hints for closers
    if leg in ("LS", "SR"):
        if oob <= 18 and actual_pos >= 7:
            lines = [
                "Traffic trouble: needed more Out of the Box to find daylight.",
                "Got bottled up—Out of the Box helps you cut through the pack.",
            ]
            reasons.append((0.75, RNG(hash64(seed, 'c_traffic', horse.id, race.name)).choice(lines)))

    # Front-runner fade hints
    if leg == "FR":
        if ten <= 18 and race.distance >= 1800:
            lines = [
                "Went forward early, but the finish asked for more Tenacious.",
                "Led them up—and then the long run home bit back. Tenacious helps you hold.",
            ]
            reasons.append((0.60, RNG(hash64(seed, 'c_fade', horse.id, race.name)).choice(lines)))
        if start <= 16:
            lines = [
                "Slow away from the gate—Start matters when you're meant to go forward.",
                "Missed the jump. A front-runner wants a cleaner break.",
            ]
            reasons.append((0.55, RNG(hash64(seed, 'c_break', horse.id, race.name)).choice(lines)))

    if not reasons:
        # Generic underperformance line
        rng = RNG(hash64(seed, "c_generic", horse.id, race.name))
        return [
            rng.choice(
                [
                    "Didn't find a rhythm today—sometimes it's just not their day.",
                    "That one never got comfortable. Keep tuning the build and try again.",
                    "A puzzling run—might have been the trip, might have been the day.",
                ]
            )
        ]

    # Pick the best reason (highest score), but keep deterministic ordering
    reasons.sort(key=lambda x: x[0], reverse=True)
    return [reasons[0][1]]


def retirement_poem_lines(seed: int, horse: Horse) -> List[str]:
    """
    A DOC-inspired retirement poem (original text). The tier is based on career results.
    """
    earnings = int(getattr(horse, "earnings", 0) or 0)
    races = int(getattr(horse, "races", 0) or 0)
    g1 = int(getattr(horse, "g1_wins", 0) or 0)

    # Simple career tiering
    if g1 >= 3 or earnings >= 5_000_000:
        tier = "legend"
    elif g1 >= 1 or earnings >= 1_500_000:
        tier = "star"
    elif earnings >= 250_000 or races >= 10:
        tier = "fighter"
    else:
        tier = "quiet"

    rng = RNG(hash64(seed, "retire", horse.id, horse.name, tier))

    legend = [
        [
            "A champion steps away from the rail,",
            "and the crowd finally exhales.",
            "From gate to wire, you answered every call—",
            "the clock remembers your name.",
            "Rest now. The field will chase your echo.",
            "Tomorrow, a new hope is born.",
        ],
        [
            "The banners come down slowly,",
            "but the story stays.",
            "You ran with steel in your stride,",
            "and left the track a little quieter behind you.",
            "Hold your head high in the paddock of legends.",
            "The next generation is watching.",
        ],
    ]

    star = [
        [
            "Not every career is a crown—",
            "some are a steady flame.",
            "You found big moments under bright lights,",
            "and proved you belonged.",
            "Walk out proud. The barn knows what you did.",
        ],
        [
            "A good horse leaves a mark",
            "without needing a statue.",
            "You showed heart when it counted,",
            "and taught the stable to believe.",
            "Retire with respect—and a full feed tub.",
        ],
    ]

    fighter = [
        [
            "Some horses win by inches,",
            "some by stubborn will.",
            "You kept showing up,",
            "and that matters.",
            "Rest those legs—your work is done.",
        ],
        [
            "No easy roads,",
            "no easy fields.",
            "But you fought for every length,",
            "and earned your keep.",
            "That's a career worth saluting.",
        ],
    ]

    quiet = [
        [
            "The track doesn't love everyone loudly,",
            "but it remembers the honest ones.",
            "You tried. You learned. You ran.",
            "That's enough for a good ending.",
            "Rest now—your next chapter is quieter.",
        ],
        [
            "Not every dream ends in a trophy,",
            "but every run writes a line.",
            "Thank you for the miles.",
            "Thank you for the effort.",
            "Time to come home.",
        ],
    ]

    bank = {
        "legend": legend,
        "star": star,
        "fighter": fighter,
        "quiet": quiet,
    }[tier]

    poem = rng.choice(bank)
    # Add a tiny stat-aware signature line.
    if g1 > 0:
        poem = poem + [f"({g1} G1 win{'s' if g1 != 1 else ''} | ${earnings:,} earned)"]
    else:
        poem = poem + [f"(${earnings:,} earned | {races} race{'s' if races != 1 else ''})"]
    return poem
