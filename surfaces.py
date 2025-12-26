from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Tuple

from .models import Condition, Surface
from .rng import RNG, hash64
from .schedule import TRACK_TO_CODE, RaceMeta

def ac_category(ac: int) -> str:
    if ac <= 63:
        return "TURF"
    if ac <= 212:
        return "MIXED"
    if ac <= 254:
        return "DIRT_LEAN"
    return "DIRT_MAX"

def surface_fit(ac: int, race_surface: Surface) -> float:
    cat = ac_category(ac)
    if cat == "TURF":
        return 0.9 if race_surface == "TURF" else -0.6
    if cat == "MIXED":
        return 0.2
    if cat == "DIRT_LEAN":
        return 0.6 if race_surface == "DIRT" else -0.2
    # DIRT_MAX
    return 1.0 if race_surface == "DIRT" else -0.5

def _default_condition_probs(surface: Surface) -> List[Tuple[Condition, float]]:
    if surface == "TURF":
        return [("GOOD",0.35),("GOOD_TO_SOFT",0.30),("SOFT",0.20),("HEAVY",0.15)]
    return [("SOFT",0.35),("HEAVY",0.30),("GOOD_TO_SOFT",0.20),("GOOD",0.15)]

def roll_condition(global_seed: int, round_num: int, slot: str, meet_iter: int, surface: Surface) -> Condition:
    rng = RNG(hash64(global_seed, "COND", round_num, slot, meet_iter))
    r = rng.random()
    acc = 0.0
    for c,p in _default_condition_probs(surface):
        acc += p
        if r <= acc:
            return c
    return _default_condition_probs(surface)[-1][0]

def condition_speed_scalar(surface: Surface, cond: Condition) -> float:
    # positive -> faster track (slightly)
    if surface == "TURF":
        return {"GOOD":0.02,"GOOD_TO_SOFT":0.00,"SOFT":-0.01,"HEAVY":-0.03}[cond]
    return {"SOFT":0.02,"HEAVY":0.01,"GOOD_TO_SOFT":0.00,"GOOD":-0.02}[cond]

def determine_surface_for_race(course_code: str, distance: int, name: str, record_surfaces: Dict[Tuple[str,int], List[Surface]], explicit_overrides: Dict[Tuple[int,str], Surface] | None = None, round_num:int|None=None, slot:str|None=None) -> Surface:
    # 1) explicit per (round,slot)
    if explicit_overrides and round_num and slot and (round_num, slot) in explicit_overrides:
        return explicit_overrides[(round_num, slot)]
    # 2) name contains "Dirt"
    if name and "dirt" in name.lower():
        return "DIRT"
    # 3) if only one surface exists in record set, use it
    key = (course_code, distance)
    if key in record_surfaces and len(record_surfaces[key]) == 1:
        return record_surfaces[key][0]
    # 4) if multiple, default TURF (more common in schedule)
    return "TURF"

def enrich_schedule_with_codes_and_surfaces(schedule: List[List[RaceMeta]], record_surfaces: Dict[Tuple[str,int], List[Surface]], explicit_overrides: Dict[Tuple[int,str], Surface]) -> List[List[RaceMeta]]:
    out: List[List[RaceMeta]] = []
    for round_list in schedule:
        rr: List[RaceMeta] = []
        for r in round_list:
            code = TRACK_TO_CODE.get(r.track, "")
            nm = r.name or ""
            surf = determine_surface_for_race(code, r.distance, nm, record_surfaces, explicit_overrides, r.round_num, r.slot)
            rr.append(replace(r, course_code=code, surface=surf))
        out.append(rr)
    return out
