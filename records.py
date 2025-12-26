from __future__ import annotations
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from .models import Surface

EPS_BREAK = 0.10  # seconds; record must be beaten by at least this margin

PLACEHOLDER_HOLDER = "(Default Nat Rec)"

def _fill_placeholder_holders(records: Dict[str, RecordEntry], *, data_dir: Path, seed: Optional[int]=None) -> None:
    """Replace placeholder record holders with plausible horse names (cosmetic only)."""
    keys = [k for k, v in records.items() if (v.holder or '').strip() == PLACEHOLDER_HOLDER]
    if not keys:
        return
    try:
        from .names import load_name_pool
        pool = load_name_pool(str(data_dir))
    except Exception:
        # Fallback in worst case; keep placeholder.
        return

    rng = random.Random(seed if seed is not None else 1337)
    rng.shuffle(pool)
    used: set[str] = set()
    for idx, k in enumerate(keys):
        base = pool[idx % len(pool)] if pool else f"Horse {idx+1}"
        name = base
        # Ensure uniqueness if the pool wraps.
        suffix = 2
        while name in used:
            name = f"{base} {suffix}"
            suffix += 1
        records[k].holder = name
        used.add(name)

@dataclass
class RecordEntry:
    time_seconds: float
    holder: str = "N/A"

def _key(course_code: str, distance: int, surface: Surface) -> str:
    return f"{course_code}|{distance}|{surface}"

def _parse_key(k: str) -> Tuple[str,int,Surface]:
    cc, dist, surf = k.split("|")
    return cc, int(dist), surf  # type: ignore

def load_records(path: Path, default_path: Path) -> Dict[str, RecordEntry]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        out: Dict[str, RecordEntry] = {}
        for k,v in data.items():
            out[k] = RecordEntry(time_seconds=float(v["time_seconds"]), holder=str(v.get("holder","N/A")))
        return out
    # if no state, bootstrap from defaults
    if default_path.exists():
        data = json.loads(default_path.read_text(encoding="utf-8", errors="ignore"))
        out: Dict[str, RecordEntry] = {}
        for k,v in data.items():
            out[k] = RecordEntry(time_seconds=float(v["time_seconds"]), holder=str(v.get("holder","N/A")))
        return out
    return {}

def save_records(path: Path, records: Dict[str, RecordEntry]) -> None:
    data = {k: {"time_seconds": v.time_seconds, "holder": v.holder} for k,v in records.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def reset_records(state_path: Path, default_path: Path, *, seed: Optional[int]=None) -> Dict[str, RecordEntry]:
    if default_path.exists():
        state_path.write_text(default_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    records = load_records(state_path, default_path)
    # Cosmetic: replace placeholder holders with random-but-stable names.
    _fill_placeholder_holders(records, data_dir=default_path.parent, seed=seed)
    save_records(state_path, records)
    return records

def get_record(records: Dict[str, RecordEntry], course_code: str, distance: int, surface: Surface) -> Optional[RecordEntry]:
    return records.get(_key(course_code, distance, surface))

def ensure_record(records: Dict[str, RecordEntry], course_code: str, distance: int, surface: Surface, time_seconds: float, holder: str="N/A") -> RecordEntry:
    k = _key(course_code, distance, surface)
    if k not in records:
        records[k] = RecordEntry(time_seconds=time_seconds, holder=holder)
    return records[k]

def update_if_broken(records: Dict[str, RecordEntry], course_code: str, distance: int, surface: Surface, time_seconds: float, holder: str) -> Tuple[bool, RecordEntry]:
    k = _key(course_code, distance, surface)
    if k not in records:
        records[k] = RecordEntry(time_seconds=time_seconds, holder=holder)
        return True, records[k]
    if time_seconds < (records[k].time_seconds - EPS_BREAK):
        records[k] = RecordEntry(time_seconds=time_seconds, holder=holder)
        return True, records[k]
    return False, records[k]

def record_surfaces_map(default_records: Dict[str, RecordEntry]) -> Dict[Tuple[str,int], list[Surface]]:
    out: Dict[Tuple[str,int], list[Surface]] = {}
    for k in default_records.keys():
        cc, dist, surf = _parse_key(k)
        kk=(cc, dist)
        out.setdefault(kk, [])
        if surf not in out[kk]:
            out[kk].append(surf)
    return out
