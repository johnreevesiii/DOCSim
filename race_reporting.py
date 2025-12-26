from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import Condition, Horse, RaceRunnerResult, Surface
from .schedule import RaceMeta
from .surfaces import condition_speed_scalar
from .records import RecordEntry, ensure_record, update_if_broken

@dataclass
class TimedRace:
    runners: List[RaceRunnerResult]
    winner_time: float
    record_broken: bool
    record_entry: RecordEntry

def format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds - 60 * m
    return f"{m}:{s:05.2f}"

def condition_time_penalty(surface: Surface, condition: Condition, distance: int) -> float:
    """Adds seconds to the baseline winning time based on surface+condition.

    In DOC lore, Turf is fastest on GOOD; Dirt is fastest on SOFT.
    We model worsening conditions as a meaningful slowdown, scaled by distance.
    """
    if surface == "TURF":
        order = ["GOOD", "GOOD_TO_SOFT", "SOFT", "HEAVY"]
    else:
        order = ["SOFT", "HEAVY", "GOOD_TO_SOFT", "GOOD"]

    step = order.index(condition) if condition in order else 0
    per_step_1600 = 0.55  # tunable
    return step * per_step_1600 * (distance / 1600.0)

def par_time_seconds(distance: int, surface: Surface) -> float:
    # Synthetic baseline if no record is known:
    # approx 17 m/s for turf, 16.6 m/s for dirt
    v = 17.0 if surface == "TURF" else 16.6
    return distance / v

def timed_results(
    race: RaceMeta,
    condition: Condition,
    finish_order: List[Horse],
    scores: Dict[str, float],
    records_state: Dict[str, RecordEntry],
) -> TimedRace:
    # Ensure record exists. If missing, create from synthetic par.
    rec = ensure_record(
        records_state,
        race.course_code,
        race.distance,
        race.surface,
        time_seconds=par_time_seconds(race.distance, race.surface),
        holder="N/A",
    )

    # Baseline winning time is intentionally slower than the national record.
    cond_fastness = condition_speed_scalar(race.surface, condition)
    base = rec.time_seconds + 2.00
    base += condition_time_penalty(race.surface, condition, race.distance)
    base *= (1.0 - 0.25 * cond_fastness)

    # Convert score spread into time spread
    sc = [scores.get(h.id, 0.0) for h in finish_order]
    mu = sum(sc) / max(1, len(sc))
    var = sum((x - mu) ** 2 for x in sc) / max(1, len(sc))
    sd = math.sqrt(var) if var > 1e-9 else 1.0

    k = 0.55  # seconds per 1 sd score advantage (tunable)

    runners_raw: List[Tuple[Horse, float]] = []
    for h in finish_order:
        z = (scores.get(h.id, mu) - mu) / sd
        t = base - k * z
        runners_raw.append((h, t))

    # Winner time and clamps (keep it sane)
    winner_time = min(t for _, t in runners_raw)
    winner_time = max(rec.time_seconds - 0.25, min(winner_time, rec.time_seconds + 8.00))

    # Re-anchor so winner matches winner_time; keep gaps but compress extremes
    min_t = min(t for _, t in runners_raw)
    updated: List[Tuple[Horse, float]] = []
    for h, t in runners_raw:
        gap = t - min_t
        gap = max(0.0, min(gap, 10.0))
        updated.append((h, winner_time + gap))

    # Final timed placing
    updated.sort(key=lambda ht: ht[1])

    LEN_SEC = 0.20
    out: List[RaceRunnerResult] = []
    for pos, (h, t) in enumerate(updated, start=1):
        out.append(
            RaceRunnerResult(
                pos=pos,
                horse_id=h.id,
                horse_name=h.name,
                time_seconds=t,
                lengths_behind=(t - winner_time) / LEN_SEC,
            )
        )

    # Records can only be updated on "fastest" conditions
    fastest_ok = (condition == ("GOOD" if race.surface == "TURF" else "SOFT"))
    if fastest_ok:
        record_broken, new_rec = update_if_broken(
            records_state, race.course_code, race.distance, race.surface, winner_time, out[0].horse_name
        )
    else:
        record_broken, new_rec = False, rec

    return TimedRace(runners=out, winner_time=winner_time, record_broken=record_broken, record_entry=new_rec)

def render_race_card(
    race: RaceMeta,
    condition: Condition,
    timed: TimedRace,
    payouts_by_pos: dict[int, int] | None = None,
) -> str:
    lines: List[str] = []
    nm = race.name or ""
    title = f"{race.slot} {nm} | {race.track} {race.distance}m {race.surface} ({condition})".strip()
    lines.append(title)
    # Show the current national record under the race header.
    if timed.record_entry is not None:
        rec_t = format_time(timed.record_entry.time_seconds)
        holder = timed.record_entry.holder
        if holder and holder != "N/A":
            lines.append(f"Record: {rec_t} by {holder}")
        else:
            lines.append(f"Record: {rec_t}")
    if timed.record_broken:
        lines.append(f"*** NEW NATIONAL RECORD: {format_time(timed.winner_time)} by {timed.runners[0].horse_name} ***")
    lines.append("")
    lines.append("Pos  Horse                         Time     Lgths   Earned")
    lines.append("---  ----------------------------  -------  -----  --------")
    for rr in timed.runners:
        earned = 0
        if payouts_by_pos:
            earned = int(payouts_by_pos.get(int(rr.pos), 0))
        lines.append(
            f"{rr.pos:>3}  {rr.horse_name[:28]:<28}  {format_time(rr.time_seconds):>7}  {rr.lengths_behind:>5.1f}  ${earned:>10,}"
        )
    return "\n".join(lines)
