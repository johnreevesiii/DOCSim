from __future__ import annotations
from dataclasses import dataclass
from typing import List, Literal, Optional

from .models import Surface

Slot = Literal["1R","2R","3R","4R","5R","G1"]

TRACK_TO_CODE = {
    "Central City": "CC",
    "Eastern City": "EC",
    "Northern Park": "NP",
    "Southern Park": "SP",
    "Western Hills": "WH",
    "Western Hill": "WH",
    "Sega": "SEGA",
}

@dataclass(frozen=True)
class RaceMeta:
    round_num: int
    slot: Slot
    track: str
    distance: int
    winner_purse: int
    name: Optional[str] = None
    course_code: str = ""
    surface: Surface = "TURF"

SCHEDULE: List[List[RaceMeta]] = [
    [
        RaceMeta(1,"1R","Central City",1200,100_000),
        RaceMeta(1,"2R","Eastern City",1600,200_000),
        RaceMeta(1,"3R","Central City",1400,500_000),
        RaceMeta(1,"4R","Eastern City",2000,200_000),
        RaceMeta(1,"5R","Central City",3000,200_000),
        RaceMeta(1,"G1","Eastern City",1600,940_000,"Winter Stakes"),
    ],
    [
        RaceMeta(2,"1R","Northern Park",1800,100_000),
        RaceMeta(2,"2R","Southern Park",2000,200_000),
        RaceMeta(2,"3R","Northern Park",1600,500_000),
        RaceMeta(2,"4R","Southern Park",1700,200_000),
        RaceMeta(2,"5R","Northern Park",2500,200_000),
        RaceMeta(2,"G1","Southern Park",1200,940_000,"Sprinters Trophy"),
    ],
    [
        RaceMeta(3,"1R","Northern Park",1600,100_000),
        RaceMeta(3,"2R","Western Hills",1200,200_000),
        RaceMeta(3,"3R","Northern Park",1800,500_000),
        RaceMeta(3,"4R","Western Hills",2200,200_000),
        RaceMeta(3,"5R","Northern Park",1800,200_000),
        RaceMeta(3,"G1","Western Hills",1600,890_000,"DOC 1000 Guineas"),
    ],
    [
        RaceMeta(4,"1R","Central City",1200,100_000),
        RaceMeta(4,"2R","Northern Park",2500,200_000),
        RaceMeta(4,"3R","Central City",2200,500_000),
        RaceMeta(4,"4R","Northern Park",1800,200_000),
        RaceMeta(4,"5R","Central City",3000,200_000),
        RaceMeta(4,"G1","Northern Park",2000,970_000,"DOC 2000 Guineas"),
    ],
    [
        RaceMeta(5,"1R","Eastern City",1600,100_000),
        RaceMeta(5,"2R","Central City",3000,200_000),
        RaceMeta(5,"3R","Eastern City",2100,500_000),
        RaceMeta(5,"4R","Central City",1600,200_000),
        RaceMeta(5,"5R","Eastern City",1600,200_000),
        RaceMeta(5,"G1","Central City",3200,1_320_000,"Spring Classic"),
    ],
    [
        RaceMeta(6,"1R","Southern Park",1800,100_000),
        RaceMeta(6,"2R","Eastern City",2400,200_000),
        RaceMeta(6,"3R","Southern Park",1700,500_000),
        RaceMeta(6,"4R","Eastern City",1400,200_000),
        RaceMeta(6,"5R","Southern Park",1200,200_000),
        RaceMeta(6,"G1","Eastern City",2400,940_000,"American Oaks"),
    ],
    [
        RaceMeta(7,"1R","Southern Park",1800,100_000),
        RaceMeta(7,"2R","Eastern City",2400,200_000),
        RaceMeta(7,"3R","Southern Park",1700,500_000),
        RaceMeta(7,"4R","Eastern City",1400,200_000),
        RaceMeta(7,"5R","Southern Park",1200,200_000),
        RaceMeta(7,"G1","Eastern City",2400,920_000,"American Derby"),
    ],
    [
        RaceMeta(8,"1R","Northern Park",1600,100_000),
        RaceMeta(8,"2R","Western Hills",1400,200_000),
        RaceMeta(8,"3R","Northern Park",1800,500_000),
        RaceMeta(8,"4R","Western Hills",2000,200_000),
        RaceMeta(8,"5R","Northern Park",2500,200_000),
        RaceMeta(8,"G1","Western Hills",2200,1_320_000,"Summer Grand Prix"),
    ],
    [
        RaceMeta(9,"1R","Sega",1600,100_000),
        RaceMeta(9,"2R","Sega",2400,200_000),
        RaceMeta(9,"3R","Sega",1800,500_000),
        RaceMeta(9,"4R","Sega",1400,200_000),
        RaceMeta(9,"5R","Sega",1800,200_000),
        RaceMeta(9,"G1","Sega",2000,1_300_000,"Super Dirt Grand Prix"),
    ],
    [
        RaceMeta(10,"1R","Western Hill",1200,100_000),
        RaceMeta(10,"2R","Northern Park",2500,200_000),
        RaceMeta(10,"3R","Western Hill",1400,500_000),
        RaceMeta(10,"4R","Northern Park",1200,200_000),
        RaceMeta(10,"5R","Western Hill",2000,200_000),
        RaceMeta(10,"G1","Northern Park",1200,940_000,"Sprinters Stakes"),
    ],
    [
        RaceMeta(11,"1R","Western Hill",2000,100_000),
        RaceMeta(11,"2R","Central City",1600,200_000),
        RaceMeta(11,"3R","Western Hill",2000,500_000),
        RaceMeta(11,"4R","Central City",1200,200_000),
        RaceMeta(11,"5R","Western Hill",2200,200_000),
        RaceMeta(11,"G1","Central City",3000,1_120_000,"Stayers Stakes"),
    ],
    [
        RaceMeta(12,"1R","Southern Park",2000,100_000),
        RaceMeta(12,"2R","Central City",1400,200_000),
        RaceMeta(12,"3R","Southern Park",1700,500_000),
        RaceMeta(12,"4R","Central City",2000,200_000),
        RaceMeta(12,"5R","Southern Park",1200,200_000),
        RaceMeta(12,"G1","Central City",2000,1_000_000,"Queen Elizabeth Cup"),
    ],
    [
        RaceMeta(13,"1R","Eastern City",2000,100_000),
        RaceMeta(13,"2R","Central City",1600,200_000),
        RaceMeta(13,"3R","Eastern City",1600,500_000),
        RaceMeta(13,"4R","Central City",2000,200_000),
        RaceMeta(13,"5R","Eastern City",2400,200_000),
        RaceMeta(13,"G1","Central City",1600,940_000,"Mile Championship"),
    ],
    [
        RaceMeta(14,"1R","Western Hill",1200,100_000),
        RaceMeta(14,"2R","Eastern City",1600,200_000),
        RaceMeta(14,"3R","Western Hill",2000,500_000),
        RaceMeta(14,"4R","Eastern City",1400,200_000),
        RaceMeta(14,"5R","Western Hill",1600,200_000),
        RaceMeta(14,"G1","Eastern City",2100,1_300_000,"Japan Cup Dirt"),
    ],
    [
        RaceMeta(15,"1R","Central City",1400,100_000),
        RaceMeta(15,"2R","Eastern City",2100,200_000),
        RaceMeta(15,"3R","Central City",3200,500_000),
        RaceMeta(15,"4R","Eastern City",1200,200_000),
        RaceMeta(15,"5R","Central City",1600,200_000),
        RaceMeta(15,"G1","Eastern City",2400,2_500_000,"Japan Cup"),
    ],
    [
        RaceMeta(16,"1R","Northern Park",1800,100_000),
        RaceMeta(16,"2R","Eastern City",2100,200_000),
        RaceMeta(16,"3R","Sega",2000,500_000),
        RaceMeta(16,"4R","Sega",1600,200_000),
        RaceMeta(16,"5R","Sega",1800,200_000),
        RaceMeta(16,"G1","Sega",2400,2_000_000,"Derby Owners Cup"),
    ],
]
