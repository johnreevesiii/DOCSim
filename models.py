from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

Style = Literal["FR","SD","LS","SR","AL"]
Sex = Literal["M","F"]
Surface = Literal["TURF","DIRT"]
Condition = Literal["GOOD","GOOD_TO_SOFT","SOFT","HEAVY"]

@dataclass
class Internals:
    stamina: int
    speed: int
    sharp: int

@dataclass
class Externals:
    start: int
    corner: int
    oob: int
    competing: int
    tenacious: int
    spurt: int

@dataclass
class TrainingResult:
    training_id: int
    training_name: str
    grade: Literal["Perfect","Cool","Great","Good","Bad","None"]
    deltas: Dict[str,int]

@dataclass
class FeedingResult:
    grade_context: Literal["Perfect","Cool","Great","Good","Bad","None"]
    foods_offered: List[str]
    chosen: str
    deltas: Dict[str,int]
    notes: str = ""

@dataclass
class RaceRunnerResult:
    pos: int
    horse_id: str
    horse_name: str
    time_seconds: float
    lengths_behind: float

@dataclass
class RaceLogEntry:
    round_num: int
    slot: str
    race_name: str
    track: str
    course_code: str
    surface: Surface
    condition: Condition
    distance: int
    winner_time: float
    player_pos: int
    player_time: float
    player_lengths: float
    payout: int
    earnings_total_after: int
    field: List[RaceRunnerResult]

@dataclass
class Horse:
    id: str
    name: str
    sex: Sex
    style: Style
    ac: int
    internals: Internals
    externals: Externals
    rating_base: Optional[float] = None

    # legacy
    genetic_tokens: int = 0
    g1_wins: int = 0
    pending_g1_superfood: bool = False

    # state/logging
    career_log: List[RaceLogEntry] = field(default_factory=list)
    last_training: Optional[TrainingResult] = None
    last_feeding: Optional[FeedingResult] = None
    # Optional extra metadata not yet used by the sim core (e.g., coat color/personality/hearts).
    # Persisted in save files so it can be used later and/or exported.
    extras: Dict[str, Any] = field(default_factory=dict)
