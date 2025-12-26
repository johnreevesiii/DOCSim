"""Pre-race "Horse Handicapping" preview (informational only).

This module intentionally has **no gameplay impact**.
It renders a compact, horse-by-horse comparison view that ranks entrants by stat.

Ranking markers mirror the reference Excel sheet ("Horse Handicapping"):

  - '◎' : best (top 1)
  - '○' : 2nd
  - '▲' : 3rd
  - '△' : 4th–6th
  - ''  : 7th+
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Sequence

from .models import Horse
from .schedule import RaceMeta


@dataclass(frozen=True)
class StatColumn:
    key: str
    label: str
    getter: Callable[[Horse], int]


def _get_field(obj: Any, key: str, default: int = 0) -> int:
    """Return a numeric field from either a dict-like mapping or an object.

    Earlier prototypes stored internals/externals as dicts. The current model uses
    dataclasses (Internals/Externals). This helper supports both so the
    handicapping screen works across saves and future refactors.
    """

    if obj is None:
        return default

    # dict-like (legacy)
    if isinstance(obj, dict):
        try:
            return int(obj.get(key, default))
        except Exception:
            return default

    # attribute-based (current dataclasses)
    try:
        return int(getattr(obj, key, default))
    except Exception:
        return default


STAT_COLUMNS: List[StatColumn] = [
    StatColumn("stamina", "ST", lambda h: _get_field(h.internals, "stamina")),
    StatColumn("speed", "SP", lambda h: _get_field(h.internals, "speed")),
    StatColumn("sharp", "SH", lambda h: _get_field(h.internals, "sharp")),
    StatColumn("start", "Start", lambda h: _get_field(h.externals, "start")),
    StatColumn("corner", "Corner", lambda h: _get_field(h.externals, "corner")),
    StatColumn("oob", "OOB", lambda h: _get_field(h.externals, "oob")),
    StatColumn("competing", "Comp", lambda h: _get_field(h.externals, "competing")),
    StatColumn("tenacious", "Ten", lambda h: _get_field(h.externals, "tenacious")),
    StatColumn("spurt", "Spurt", lambda h: _get_field(h.externals, "spurt")),
]


def _top_values(values: Sequence[int], k: int = 6) -> List[int]:
    """Return the k-th largest values (with duplicates), like Excel LARGE(range, k)."""
    if not values:
        return []
    sorted_desc = sorted(values, reverse=True)
    return sorted_desc[: min(k, len(sorted_desc))]


def _marker_for_value(v: int, top: Sequence[int]) -> str:
    """Marker mapping mirroring the Excel 'Horse Handicapping' sheet."""
    # Excel logic (per cell):
    # IF(v=top1,"◎", IF(v=top2,"○", IF(v=top3,"▲", IF(v in top4..top6,"△",""))))
    if len(top) >= 1 and v == top[0]:
        return "◎"
    if len(top) >= 2 and v == top[1]:
        return "○"
    if len(top) >= 3 and v == top[2]:
        return "▲"
    if len(top) >= 4 and v == top[3]:
        return "△"
    if len(top) >= 5 and v == top[4]:
        return "△"
    if len(top) >= 6 and v == top[5]:
        return "△"
    return ""


def _stat_markers(horses: Sequence[Horse], getter: Callable[[Horse], int]) -> List[str]:
    vals = [int(getter(h)) for h in horses]
    top = _top_values(vals, k=6)
    return [_marker_for_value(v, top) for v in vals]


def render_handicapping_table(
    horses: Sequence[Horse],
    *,
    title: str = "Horse Handicapping",
    include_legend: bool = True,
    gate_by_id: dict[str, int] | None = None,
    race: Optional[RaceMeta] = None,
    condition: Optional[str] = None,
) -> str:
    """Render the pre-race handicapping preview.

    The output is designed for a monospaced console.
    """
    if not horses:
        return ""

    # Display order: sort by gate number (DOC-style) when available.
    horses = list(horses)
    if gate_by_id:
        horses.sort(key=lambda h: int(gate_by_id.get(h.id, 999)))

    # Pre-compute markers per stat column.
    markers_by_col = {
        col.key: _stat_markers(horses, col.getter) for col in STAT_COLUMNS
    }

    # "Favorite" (Fav) is an on-paper ranking for the upcoming race. This is informational only.
    fav_rank_by_id: dict[str, int] = {}
    if race is not None and condition is not None:
        # Import lazily to avoid any startup overhead when the feature isn't used.
        from .commentary import expected_score

        scored: list[tuple[float, str]] = []
        for i, h in enumerate(horses):
            gate = int(gate_by_id.get(h.id, i + 1)) if gate_by_id else (i + 1)
            scored.append((float(expected_score(h, race, condition, gate)), h.id))

        scored.sort(key=lambda t: t[0], reverse=True)
        for rank, (_, hid) in enumerate(scored, start=1):
            fav_rank_by_id[hid] = rank

    gate_w = 4
    horse_w = 24
    sex_w = 3
    ac_w = 4

    # Header
    left = f"{'Gate':<{gate_w}} {'Horse':<{horse_w}} {'Sex':<{sex_w}} {'AC':>{ac_w}}"
    stat_labels = [c.label for c in STAT_COLUMNS] + ["Fav"]
    stat_hdr = " ".join([f"{lab:>{max(3, len(lab))}}" for lab in stat_labels])
    lines: List[str] = []
    lines.append(f"=== {title} (informational only) ===")
    lines.append(left + "  " + stat_hdr)
    lines.append(
        f"{'-'*gate_w} {'-'*horse_w} {'-'*sex_w} {'-'*ac_w}" + "  " + " ".join(["-" * max(3, len(lab)) for lab in stat_labels])
    )

    # Rows
    for i, h in enumerate(horses, start=1):
        gate_num = gate_by_id.get(h.id, i) if gate_by_id else i
        gate = str(gate_num)
        name = (h.name or "").strip()
        if len(name) > horse_w:
            name = name[: horse_w - 1] + "…"
        sex = (h.sex or "").strip()[:1] or "?"
        ac = int(getattr(h, "ac", 0))
        row_left = f"{gate:<{gate_w}} {name:<{horse_w}} {sex:<{sex_w}} {ac:>{ac_w}d}"
        row_marks: List[str] = []
        for col in STAT_COLUMNS:
            m = markers_by_col[col.key][i - 1]
            # Keep columns narrow and aligned.
            width = max(3, len(col.label))
            row_marks.append(f"{m:>{width}}")

        fav = fav_rank_by_id.get(h.id)
        fav_s = str(fav) if fav is not None else ""
        row_marks.append(f"{fav_s:>{max(3, len('Fav'))}}")
        lines.append(row_left + "  " + " ".join(row_marks))

    if include_legend:
        lines.append("")
        lines.append("Legend: ◎ best | ○ 2nd | ▲ 3rd | △ 4th–6th")
        lines.append("Fav: 1 = top on paper")

    return "\n".join(lines)
