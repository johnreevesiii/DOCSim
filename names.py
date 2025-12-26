from __future__ import annotations
from pathlib import Path
from typing import List

from .rng import RNG, hash64

DEFAULT_FALLBACK = [
    "Silver Comet","Thunder Boy","Silent Storm","Timber Country","Runaway King","Northern Star",
    "Eastern Legend","Central Pride","Western Ace","Southern Charm","Sega Lightning","Blue Horizon",
    "Golden Derby","Rapid River","Midnight Arrow","Emerald Crown","Crimson Rocket","Lucky Stride",
]

def load_name_pool(data_dir: Path) -> List[str]:
    p = data_dir / "cpu_names.txt"
    if p.exists():
        lines = [ln.strip() for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines()]
        lines = [ln for ln in lines if ln and not ln.startswith("#")]
        if len(lines) >= 10:
            # de-dup while preserving order
            seen=set(); uniq=[]
            for n in lines:
                if n not in seen:
                    uniq.append(n); seen.add(n)
            return uniq
    return DEFAULT_FALLBACK

def build_round_names(global_seed: int, round_num: int, pool_size: int, base_pool: List[str]) -> List[str]:
    rng = RNG(hash64(global_seed, "CPU_NAMES", round_num))
    pool = base_pool[:]
    rng.shuffle(pool)
    out: List[str] = []
    # ensure enough names by reusing with suffixes
    suffixes = [""," II"," III"," IV"," V"," Jr."," Sr."," A"," B"," C"," D"]
    i = 0
    while len(out) < pool_size:
        base = pool[i % len(pool)]
        suf = suffixes[(i // len(pool)) % len(suffixes)]
        out.append(base + suf)
        i += 1
    return out
