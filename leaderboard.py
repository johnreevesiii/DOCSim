from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .rng import RNG, hash64
from .names import load_name_pool


@dataclass(frozen=True)
class LeaderboardEntry:
    name: str
    sex: str
    earnings: int
    races: int = 0
    g1_wins: int = 0
    source: str = "PLAYER"  # PLAYER | RETIRED | CPU


def _safe_int(x, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _load_state_file(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def collect_player_entries(save_dir: Path, retired_dir: Path) -> List[LeaderboardEntry]:
    entries: List[LeaderboardEntry] = []

    def scan_dir(d: Path, source: str) -> None:
        if not d.exists():
            return
        for p in sorted(d.glob("*.json")):
            st = _load_state_file(p)
            if not isinstance(st, dict):
                continue
            horse = st.get("player") if isinstance(st.get("player"), dict) else st.get("horse")
            if not isinstance(horse, dict):
                continue
            name = str(horse.get("name", "")).strip() or p.stem
            sex = str(horse.get("sex", "?")).strip() or "?"
            earnings = _safe_int(st.get("earnings", 0))
            races = _safe_int(st.get("races_run", 0))
            g1 = _safe_int(st.get("g1_wins", 0))
            entries.append(
                LeaderboardEntry(
                    name=name,
                    sex=sex,
                    earnings=max(0, earnings),
                    races=max(0, races),
                    g1_wins=max(0, g1),
                    source=source,
                )
            )

    scan_dir(save_dir, "PLAYER")
    scan_dir(retired_dir, "RETIRED")

    # Deduplicate by name+sex, keeping the max earnings.
    best: dict[tuple[str, str], LeaderboardEntry] = {}
    for e in entries:
        k = (e.name, e.sex)
        if k not in best or e.earnings > best[k].earnings:
            best[k] = e
    return list(best.values())


def generate_cpu_hof(seed: int, data_dir: Path, n: int = 25) -> List[LeaderboardEntry]:
    """Deterministic 'CPU Hall of Fame' leaderboard for empty installs."""
    names = load_name_pool(data_dir)
    if not names:
        names = [f"CPU Horse {i+1}" for i in range(max(1, n))]

    rng = RNG(hash64(seed, "LEADERBOARD", "CPU_HOF"))
    picks = rng.sample(names, k=min(len(names), n))

    # Create a descending earnings curve with light noise.
    entries: List[LeaderboardEntry] = []
    top = 25_000_000
    step = 900_000
    for i, nm in enumerate(picks):
        base = top - i * step
        noise = rng.randint(-120_000, 120_000)
        earnings = max(250_000, base + noise)
        sex = rng.choice(["M", "F"])
        entries.append(LeaderboardEntry(name=nm, sex=sex, earnings=earnings, source="CPU"))
    entries.sort(key=lambda e: (-e.earnings, e.name))
    return entries


def top_earnings_leaderboard(
    save_dir: Path,
    retired_dir: Path,
    seed: int,
    data_dir: Path,
    limit: int = 25,
) -> Tuple[str, List[LeaderboardEntry]]:
    """Return (title, entries) for the leaderboard display."""
    players = collect_player_entries(save_dir, retired_dir)
    if players:
        players.sort(key=lambda e: (-e.earnings, e.name))
        return ("Leaderboard (Top Earnings)", players[:limit])
    # No player horses yet -> show CPU hall of fame.
    cpu = generate_cpu_hof(seed=seed, data_dir=data_dir, n=limit)
    return ("Leaderboard (CPU Hall of Fame)", cpu[:limit])


def render_leaderboard(title: str, entries: Iterable[LeaderboardEntry]) -> str:
    rows = list(entries)
    if not rows:
        return f"{title}\n\n(No horses yet.)\n"

    # Column widths
    name_w = max(10, min(26, max(len(e.name) for e in rows)))
    lines: List[str] = []
    lines.append("=" * 28)
    lines.append(title)
    lines.append("=" * 28)
    lines.append(f"{'#':>2}  {'Horse':<{name_w}}  {'Sex':<3}  {'Earnings':>12}")
    lines.append(f"{'-'*2}  {'-'*name_w}  {'-'*3}  {'-'*12}")
    for i, e in enumerate(rows, start=1):
        lines.append(
            f"{i:>2}  {e.name:<{name_w}}  {e.sex:<3}  ${e.earnings:>11,}"
        )
    return "\n".join(lines)
