from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Literal, Tuple

from .models import FeedingResult, Horse
from .rng import RNG, hash64
from .breeding import clamp_int
from .training import Grade

Stat = Literal["start","corner","oob","competing","tenacious","spurt"]

EXTERNAL_KEYS: Tuple[Stat, ...] = ("start","corner","oob","competing","tenacious","spurt")

@dataclass(frozen=True)
class FoodItem:
    name: str
    tier: Literal["basic","standard","premium","special"]
    # optional bias stats: (primary, secondary)
    bias: Tuple[Tuple[Stat,...], Tuple[Stat,...]] = ((),())

# A compact nostalgic catalog (expand later)
FOODS: List[FoodItem] = [
    FoodItem("Vegetable Salad", "standard"),
    FoodItem("Camembert Cheese", "premium"),
    FoodItem("Chinese Herbal Dumplings (Regular)", "standard"),
    FoodItem("Apple", "basic"),
    FoodItem("Large Apple", "standard"),
    FoodItem("Green Apple", "basic"),
    FoodItem("Orange", "basic"),
    FoodItem("Large Orange", "standard"),
    FoodItem("Carrot", "basic"),
    FoodItem("Bunch of Carrots", "standard"),
    FoodItem("Fodder", "basic"),
    FoodItem("Fodder with Green Tea", "standard"),
    FoodItem("Hay Bale Deluxe", "standard"),
    FoodItem("Mineral Mix", "standard"),
    FoodItem("Cube Sugar", "premium"),
    FoodItem("Pudding", "standard"),
    FoodItem("Large Pudding", "premium"),
    # Nostalgia / easter egg: only offered on PERFECT training results.
    FoodItem("Draft Beer", "premium"),
    # Special genetic foods (appear only when unlocked)
    FoodItem("Herbal Dumpling", "special"),
    FoodItem("Large Herbal Dumpling", "special"),
    FoodItem("Large Korean Ginseng", "special"),
]

SPECIAL_ORDER = ["Herbal Dumpling","Large Herbal Dumpling","Large Korean Ginseng"]

PERFECT_ONLY = {"Draft Beer"}

def _diminish(cur: int, delta: int) -> int:
    if delta == 0:
        return 0
    mag = abs(delta)
    sign = 1 if delta > 0 else -1
    # Diminishing returns (externals are clamped to 8..48).
    # Keep food meaningful through mid-career; taper close to cap.
    if cur >= 46:
        mag = max(1, mag // 4)
    elif cur >= 42:
        mag = max(1, mag // 2)
    return sign * mag

def _apply(player: Horse, deltas: Dict[str,int]) -> None:
    """Apply already-computed deltas to externals.

    Note: compute_food_deltas() returns deltas that already incorporate the
    intended diminishing behavior for this feeding action. Here we only clamp
    and ensure the reported deltas match what was actually applied.
    """
    e = player.externals
    for k, v in list(deltas.items()):
        cur = getattr(e, k)
        nv = clamp_int(cur + v, 8, 48)
        setattr(e, k, nv)
        deltas[k] = nv - cur

def unlocked_specials(player: Horse) -> List[str]:
    # special availability:
    # after 1st G1 win -> Herbal Dumpling
    # after 2nd -> Large Herbal Dumpling
    # after 3rd -> Large Korean Ginseng
    # after 4th+ -> none new (regular list)
    n = max(0, min(player.g1_wins, 3))
    return SPECIAL_ORDER[:n]

def build_food_offering(
    global_seed: int,
    meet_iter: int,
    round_num: int,
    slot: str,
    grade: Grade,
    primary: Tuple[Stat,...],
    secondary: Tuple[Stat,...],
    player: Horse,
    k: int = 5
) -> List[str]:
    rng = RNG(hash64(global_seed, "FOOD_OFFER", round_num, slot, meet_iter))

    # Some foods are intentionally gated behind specific contexts.
    def gate_ok(f: FoodItem) -> bool:
        if f.name in PERFECT_ONLY and grade != "Perfect":
            return False
        return True

    # pool selection based on grade
    unlocked = set(unlocked_specials(player))
    basic = [f for f in FOODS if f.tier == "basic" and f.name not in unlocked and gate_ok(f)]
    standard = [f for f in FOODS if f.tier == "standard" and f.name not in unlocked and gate_ok(f)]
    premium = [f for f in FOODS if f.tier == "premium" and f.name not in unlocked and gate_ok(f)]
    specials = [f for f in FOODS if f.name in unlocked and gate_ok(f)]

    if grade == "Perfect":
        pool = premium + standard + basic
        bias_n = 4
    elif grade == "Cool":
        pool = premium + standard + basic
        bias_n = 3
    elif grade == "Great":
        pool = premium + standard + basic
        bias_n = 3
    elif grade == "Good" or grade == "None":
        pool = standard + basic + premium
        bias_n = 2
    else:
        # Bad: chaotic menu; still limited to unlocked specials if any
        pool = basic + standard + premium
        bias_n = 1

    rng.shuffle(pool)

    chosen: List[FoodItem] = []

    # If training was PERFECT, always include the special "Draft Beer" option.
    if grade == "Perfect":
        beer = [f for f in premium if f.name == "Draft Beer"]
        if beer:
            chosen.append(beer[0])

    # include at most 1 special if available, to preserve "specialness"
    force_special = bool(specials) and getattr(player, "pending_g1_superfood", False) and slot == "1R"
    if force_special:
        # Use the highest-tier unlocked special for a clear reward.
        best = max(specials, key=lambda f: SPECIAL_ORDER.index(f.name) if f.name in SPECIAL_ORDER else -1)
        chosen.append(best)
    elif specials and grade in ("Perfect","Cool","Great","Good","None"):
        p = {"Perfect":0.60,"Cool":0.50,"Great":0.40,"Good":0.30,"None":0.30}.get(grade, 0.30)
        if rng.random() < p:
            chosen.append(rng.choice(specials))

    # bias selection: pick foods that "fit" primary/secondary by simple name heuristics
    def bias_score(name: str) -> float:
        n = name.lower()
        score = 0.0
        if "carrot" in n and ("start" in primary or "oob" in primary):
            score += 2.0
        if "apple" in n and ("spurt" in primary or "speed" in n):
            score += 1.0
        if "dumpling" in n and ("tenacious" in primary or "competing" in primary):
            score += 1.5
        if "cheese" in n and ("competing" in primary or "tenacious" in primary):
            score += 1.0
        if "mineral" in n and ("corner" in primary or "tenacious" in primary):
            score += 1.0
        return score + rng.random()*0.05

    # pick biased items
    remaining = [f for f in pool if f not in chosen]
    remaining.sort(key=lambda f: bias_score(f.name), reverse=True)
    for f in remaining[:bias_n]:
        if f not in chosen:
            chosen.append(f)

    # fill random
    remaining2 = [f for f in pool if f not in chosen]
    rng.shuffle(remaining2)
    for f in remaining2:
        if len(chosen) >= k:
            break
        chosen.append(f)

    # ensure unique names
    names = []
    seen=set()
    for f in chosen:
        if f.name in seen:
            continue
        seen.add(f.name); names.append(f.name)
        if len(names) == k:
            break

    # if still short, pad from standard/basic
    pad_pool = [f.name for f in (standard+basic+premium) if f.name not in seen]
    rng.shuffle(pad_pool)
    while len(names) < k and pad_pool:
        names.append(pad_pool.pop())

    return names[:k]

def compute_food_deltas(seed, meet_iter, round_num, slot, grade: Grade, primary, secondary, chosen_food: str, player: Horse):
    rng = RNG(hash64(seed, "FOOD_DELTA", meet_iter, round_num, slot, chosen_food))

    prim_targets = primary
    sec_targets = secondary
    if prim_targets == sec_targets:
        sec_targets = tuple()

    # Identify premium reward foods
    is_beer = (chosen_food == "Draft Beer")
    is_special = (chosen_food in SPECIAL_ORDER)

    # Determine food tier (basic/standard/premium/special/beer)
    tier = "standard"
    for it in FOODS:
        if it.name == chosen_food:
            tier = it.tier
            break
    if is_beer:
        tier = "beer"

    # Deterministic preference (per-horse/per-food) without persisting new state.
    # We avoid using player.id because player horses are typically "PLAYER-001".
    pref_rng = RNG(hash64(0, "FOOD_PREF", player.name, player.sex, player.ac, chosen_food))
    r = pref_rng.random()
    if r < 0.15:
        pref_mult = 0.7  # hates
    elif r < 0.55:
        pref_mult = 1.0  # neutral
    elif r < 0.85:
        pref_mult = 1.2  # likes
    else:
        pref_mult = 1.4  # loves

    # Bad training can yield negative/weak feeding outcomes, but premium reward foods
    # should not punish the player.
    effective_grade = grade
    if grade == "Bad" and (is_beer or is_special):
        effective_grade = "Good"

    # Point-budget allocation (smaller than training): mostly +1/+2 ticks, with occasional spillover.
    # Budget is expressed in "raw points"; diminishing may convert some points into smaller realized gains.
    if effective_grade == "Bad":
        # Volatile, often negative; premium food softens the downside.
        bad_budget_by_tier = {
            "basic": (-3, 0),
            "standard": (-3, 1),
            "premium": (-2, 2),
        }
        lo, hi = bad_budget_by_tier.get(tier, (-3, 1))
        base_budget = rng.randint(lo, hi)
    else:
        # Normal feeding budgets (tier-driven)
        base_budget_by_tier = {
            "basic": (1, 2),
            "standard": (1, 3),
            "premium": (2, 4),
            "special": (3, 6),
            "beer": (3, 6),
        }

        # Special foods / Draft Beer get their own calibration so they feel meaningfully stronger.
        if tier == "special":
            special_budget = {
                "Herbal Dumpling": (3, 5),
                "Large Herbal Dumpling": (4, 6),
                "Large Korean Ginseng": (5, 7),
            }
            lo, hi = special_budget.get(chosen_food, (3, 6))
        elif tier == "beer":
            # "Perfect + Draft Beer" should feel like a premium reward.
            lo, hi = (4, 7) if grade == "Perfect" else (3, 6)
        else:
            lo, hi = base_budget_by_tier.get(tier, (1, 3))

        base_budget = rng.randint(lo, hi)

    # Apply preference multiplier (floor)
    budget = int(base_budget * pref_mult)
    if budget == 0:
        return {}

    # Simulate within this feeding event so diminishing/clamping behaves sensibly
    temp_vals = {k: getattr(player.externals, k) for k in EXTERNAL_KEYS}
    deltas: Dict[str, int] = {}

    def sim_apply(stat_name: str, raw_delta: int) -> None:
        cur = temp_vals[stat_name]
        d = _diminish(cur, raw_delta)
        new = max(8, min(48, cur + d))
        applied = new - cur
        temp_vals[stat_name] = new
        if applied:
            deltas[stat_name] = deltas.get(stat_name, 0) + applied

    # Build weighted target bag (primaries dominate)
    weight_bag = []
    for s in prim_targets:
        weight_bag.extend([s] * 4)
    for s in sec_targets:
        weight_bag.extend([s] * 2)
    if not weight_bag:
        weight_bag = list(EXTERNAL_KEYS)

    target_set = set(weight_bag)
    remaining = abs(budget)
    sign = 1 if budget > 0 else -1

    # Packet probability (helps produce +2 ticks and makes diminishing actually matter near cap)
    p2_by_tier = {
        "basic": 0.15,
        "standard": 0.25,
        "premium": 0.35,
        "special": 0.40,
        "beer": 0.45,
    }
    p2 = p2_by_tier.get(tier, 0.25)

    while remaining > 0:
        stat = rng.choice(weight_bag)
        cur = temp_vals[stat]

        packet = 1
        if remaining >= 2:
            # Force 2-point packets once diminishing is active so the budget gets "spent"
            # even when realized gains are scaled down.
            if cur >= 42 or rng.random() < p2:
                packet = 2

        sim_apply(stat, sign * packet)
        remaining -= packet

    # Spillover to a non-target stat (helps runs feel DOC-like)
    others = [s for s in EXTERNAL_KEYS if s not in target_set]
    if others:
        if tier in ("premium", "special", "beer"):
            p_other = 0.55
            extra = 2 if rng.random() < 0.33 else 1
        else:
            p_other = 0.30
            extra = 1

        if rng.random() < p_other:
            sim_apply(rng.choice(others), sign * extra)

    return deltas

def apply_feeding(
    global_seed: int,
    meet_iter: int,
    round_num: int,
    slot: str,
    grade: Grade,
    primary: Tuple[Stat,...],
    secondary: Tuple[Stat,...],
    player: Horse,
    chosen_food: str
) -> FeedingResult:
    offered = []  # caller should supply; here for record
    deltas = compute_food_deltas(global_seed, meet_iter, round_num, slot, grade, primary, secondary, chosen_food, player)
    _apply(player, deltas)

    notes = ""
    if chosen_food in SPECIAL_ORDER:
        # Genetic foods improve future breeding outcomes (used when a retired horse is selected as a parent).
        player.genetic_tokens += 1
        notes = "Special genetic food consumed. (+1 genetic token)"

    return FeedingResult(
        grade_context=grade,
        foods_offered=offered,
        chosen=chosen_food,
        deltas=deltas,
        notes=notes
    )
