from __future__ import annotations
import json, re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Tuple

Revision = Literal["revA","revB","revC","revD"]

@dataclass(frozen=True)
class ParentHorse:
    name: str
    stamina: int
    speed: int
    sharp: int
    ac: int
    start: int
    corner: int
    oob: int
    competing: int
    tenacious: int
    spurt: int

def _parse_game_data_from_breeder_html(html_text: str) -> Dict:
    m = re.search(r"const\s+gameData\s*=\s*(\{.*?\});", html_text, re.DOTALL)
    if not m:
        raise ValueError("Could not find `const gameData = {...};` in breeder HTML.")
    return json.loads(m.group(1))

def load_roster_from_breeder_html(html_path: str, revision: Revision) -> Tuple[List[ParentHorse], List[ParentHorse]]:
    p = Path(html_path)
    if not p.exists():
        raise FileNotFoundError(f"Breeder HTML not found: {html_path}")
    txt = p.read_text(encoding="utf-8", errors="ignore")
    data = _parse_game_data_from_breeder_html(txt)
    if revision not in data:
        raise KeyError(f"Revision {revision} not found. Available: {list(data.keys())}")
    rev = data[revision]
    sires = [ParentHorse(**h) for h in rev["sires"]]
    dams  = [ParentHorse(**h) for h in rev["dams"]]
    return sires, dams
