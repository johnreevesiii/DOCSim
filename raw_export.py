"""DOCSim raw export utilities.

This module adds an *optional* export feature to generate a binary `.raw` file from
a DOCSim save (JSON). The goal is twofold:

1) Provide a deterministic, documented binary payload that can be consumed by
   other community tools.
2) Establish a clean place to later implement an *arcade-accurate* `.raw` schema
   once the byte-level layout is confirmed.

Important note
--------------
The `.raw` produced by this module is currently a **DOCSim-defined schema**
(`DOCSIMRAW`, version 1). It is **not guaranteed** to match the proprietary
arcade/game format used by Derby Owners Club.

To make iteration easier, we also export a JSON manifest alongside the `.raw`
that contains the full horse + relevant metadata in a human-readable form.

If you (or the community) can provide a reference `.raw` produced by an existing
tool suite for the same horse data, this exporter can be updated to match that
layout in a future patch.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Tuple

from .models import Horse
from .save_load import horse_from_dict, horse_to_dict


# ----------------------------
# Cosmetic / personality pools
# ----------------------------
# NOTE: These are *placeholders* until a confirmed arcade mapping exists.
# We keep explicit numeric codes so that a later mapping can be slotted in
# without changing save semantics.

COAT_COLORS = [
    (0, "Bay"),
    (1, "Chestnut"),
    (2, "Black"),
    (3, "Gray"),
    (4, "Dark Bay"),
    (5, "Palomino"),
    (6, "Buckskin"),
    (7, "Roan"),
]

PERSONALITIES = [
    (0, "Calm"),
    (1, "Spirited"),
    (2, "Aggressive"),
    (3, "Lazy"),
    (4, "Nervous"),
    (5, "Brave"),
    (6, "Intelligent"),
    (7, "Stubborn"),
]

MAX_HEARTS = 5


def _safe_int(value: Any, default: int = 0) -> int:
    """Best-effort int conversion.

    The export path may encounter older / hand-edited saves that contain
    explicit JSON nulls (None) or non-numeric strings. We treat these as
    missing values and fall back to a sensible default.
    """

    if value is None:
        return default
    try:
        # Preserve behaviour for booleans while still allowing explicit ints.
        if isinstance(value, bool):
            return 1 if value else 0
        return int(value)
    except Exception:
        return default


def _stable_u64_seed(*parts: str) -> int:
    """Deterministic, cross-platform seed builder (avoid Python's salted hash())."""
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(h[:8], "little", signed=False)


def ensure_horse_extras(horse: Horse, seed: int | None = None) -> Dict[str, Any]:
    """Ensure `horse.extras` contains coat color, personality and hearts.

    - Deterministic (based on save seed + horse id) when seed is provided.
    - Non-invasive: only fills missing keys.
    """

    # Defensive: older / externally-edited saves may contain `extras: null` or
    # other non-dict values.
    if horse.extras is None:
        horse.extras = {}
    if not isinstance(horse.extras, dict):
        horse.extras = dict(horse.extras)

    s = _stable_u64_seed(str(seed or 0), str(horse.id), "EXTRAS")

    # Small local RNG without importing random globally (keep deterministic).
    # We use a simple LCG stepper.
    def next_u32(x: int) -> int:
        return (1664525 * x + 1013904223) & 0xFFFFFFFF

    x = s & 0xFFFFFFFF

    # Coat
    coat = horse.extras.get("coat")
    need_coat = not isinstance(coat, dict)
    if not need_coat:
        # Prefer preserving an existing name if present.
        code_val = coat.get("code")
        name_val = coat.get("name")
        if code_val is None:
            # Try to infer code from name.
            if isinstance(name_val, str) and name_val.strip():
                for c, n in COAT_COLORS:
                    if n.lower() == name_val.strip().lower():
                        coat["code"] = c
                        break
            if coat.get("code") is None:
                need_coat = True
        else:
            coat["code"] = _safe_int(code_val, 0)
        # Fill missing name from code if possible.
        if not isinstance(coat.get("name"), str) or not coat.get("name"):
            for c, n in COAT_COLORS:
                if c == _safe_int(coat.get("code"), 0):
                    coat["name"] = n
                    break

    if need_coat:
        x = next_u32(x)
        code, name = COAT_COLORS[x % len(COAT_COLORS)]
        horse.extras["coat"] = {"code": code, "name": name}

    # Personality
    pers = horse.extras.get("personality")
    need_pers = not isinstance(pers, dict)
    if not need_pers:
        code_val = pers.get("code")
        name_val = pers.get("name")
        if code_val is None:
            if isinstance(name_val, str) and name_val.strip():
                for c, n in PERSONALITIES:
                    if n.lower() == name_val.strip().lower():
                        pers["code"] = c
                        break
            if pers.get("code") is None:
                need_pers = True
        else:
            pers["code"] = _safe_int(code_val, 0)

        if not isinstance(pers.get("name"), str) or not pers.get("name"):
            for c, n in PERSONALITIES:
                if c == _safe_int(pers.get("code"), 0):
                    pers["name"] = n
                    break

    if need_pers:
        x = next_u32(x)
        code, name = PERSONALITIES[x % len(PERSONALITIES)]
        horse.extras["personality"] = {"code": code, "name": name}

    # Hearts (1..MAX_HEARTS)
    hearts_val = horse.extras.get("hearts")
    hearts_i = _safe_int(hearts_val, 0)
    if hearts_i < 1 or hearts_i > MAX_HEARTS:
        x = next_u32(x)
        hearts_i = int(x % MAX_HEARTS) + 1
    horse.extras["hearts"] = hearts_i

    return horse.extras


def safe_filename(name: str) -> str:
    """Safe-ish filename slug for Windows/macOS/Linux."""
    ok = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ "
    cleaned = "".join(ch for ch in name.strip() if ch in ok)
    cleaned = cleaned.strip().replace(" ", "_")
    if not cleaned:
        return "horse"
    return cleaned[:64]


def _pack_str(buf: bytearray, offset: int, length: int, value: str) -> None:
    raw = (value or "").encode("utf-8", errors="replace")
    raw = raw[:length]
    buf[offset : offset + length] = raw + b"\x00" * (length - len(raw))


def _style_code(style: str) -> int:
    # Keep stable even if style is unknown.
    return {"SD": 0, "SR": 1, "FR": 2, "ST": 3, "FO": 4}.get(style, 2)


def _horse_type_code(horse: Horse) -> int:
    # 0 stamina, 1 speed, 2 sharp
    ints = getattr(horse, "internals", None)
    if not isinstance(ints, dict):
        ints = {}
    vals = {
        "stamina": _safe_int(ints.get("stamina"), 0),
        "speed": _safe_int(ints.get("speed"), 0),
        "sharp": _safe_int(ints.get("sharp"), 0),
    }
    # If horse.horse_type exists, respect it; else derive.
    ht = getattr(horse, "horse_type", None)
    if ht in vals:
        return {"stamina": 0, "speed": 1, "sharp": 2}[ht]
    # derive
    k = max(vals, key=vals.get)
    return {"stamina": 0, "speed": 1, "sharp": 2}[k]


def build_docsim_raw_payload(
    horse: Horse,
    *,
    seed: int = 0,
    rev: str = "revC",
    earnings: int = 0,
    races_run: int = 0,
) -> bytes:
    """Build the DOCSim-defined `.raw` payload.

    Layout (little-endian) — DOCSIMRAW v1
    -------------------------------------
    0x00  8   Magic: b"DOCSIMRAW"
    0x08  1   Schema version (1)
    0x09  1   Reserved
    0x0A  2   Reserved
    0x0C  4   Seed (uint32)
    0x10  4   Rev string (utf-8, NUL padded, e.g., "revC")
    0x20  32  Horse name (utf-8, NUL padded)
    0x40  1   Sex (0=F, 1=M)
    0x41  1   Style code (0..4)
    0x42  1   Horse type code (0..2)
    0x43  1   Coat color code
    0x44  1   Personality code
    0x45  1   Hearts
    0x46  2   Reserved
    0x48  2   AC (uint16)
    0x4A  2   rating_base (uint16)
    0x4C  4   earnings (uint32)
    0x50  4   races_run (uint32)
    0x60  3   Internals: stamina, speed, sharp (uint8)
    0x68  6   Externals: start, corner, oob, competing, tenacious, spurt (uint8)
    0x70  6   Breeding ext (uint8 0..16) if present, else zeros
    0x80  32  Sire name (utf-8, NUL padded)
    0xA0  32  Dam name (utf-8, NUL padded)

    Total size: 0x200 (512 bytes)
    """

    ensure_horse_extras(horse, seed=seed)

    buf = bytearray(0x200)
    buf[0:8] = b"DOCSIMRAW"
    struct.pack_into("<B", buf, 0x08, 1)
    struct.pack_into("<I", buf, 0x0C, _safe_int(seed, 0) & 0xFFFFFFFF)

    _pack_str(buf, 0x10, 4, rev)
    _pack_str(buf, 0x20, 32, horse.name)

    sex_code = 1 if horse.sex == "M" else 0
    struct.pack_into("<B", buf, 0x40, sex_code)
    struct.pack_into("<B", buf, 0x41, _style_code(horse.style))
    struct.pack_into("<B", buf, 0x42, _horse_type_code(horse))

    coat = horse.extras.get("coat", {}) if isinstance(horse.extras, dict) else {}
    pers = horse.extras.get("personality", {}) if isinstance(horse.extras, dict) else {}
    struct.pack_into("<B", buf, 0x43, _safe_int(coat.get("code"), 0) & 0xFF)
    struct.pack_into("<B", buf, 0x44, _safe_int(pers.get("code"), 0) & 0xFF)
    struct.pack_into("<B", buf, 0x45, _safe_int(horse.extras.get("hearts"), 1) & 0xFF)

    struct.pack_into("<H", buf, 0x48, _safe_int(getattr(horse, "ac", 0), 0) & 0xFFFF)
    struct.pack_into("<H", buf, 0x4A, _safe_int(getattr(horse, "rating_base", 0), 0) & 0xFFFF)
    struct.pack_into("<I", buf, 0x4C, _safe_int(earnings, 0) & 0xFFFFFFFF)
    struct.pack_into("<I", buf, 0x50, _safe_int(races_run, 0) & 0xFFFFFFFF)

    # Internals
    internals = horse.internals if isinstance(getattr(horse, "internals", None), dict) else {}
    struct.pack_into("<B", buf, 0x60, _safe_int(internals.get("stamina"), 0) & 0xFF)
    struct.pack_into("<B", buf, 0x61, _safe_int(internals.get("speed"), 0) & 0xFF)
    struct.pack_into("<B", buf, 0x62, _safe_int(internals.get("sharp"), 0) & 0xFF)

    # Externals
    externals = horse.externals if isinstance(getattr(horse, "externals", None), dict) else {}
    ext_fields = [
        _safe_int(externals.get("start"), 0),
        _safe_int(externals.get("corner"), 0),
        _safe_int(externals.get("oob"), 0),
        _safe_int(externals.get("competing"), 0),
        _safe_int(externals.get("tenacious"), 0),
        _safe_int(externals.get("spurt"), 0),
    ]
    for i, v in enumerate(ext_fields):
        struct.pack_into("<B", buf, 0x68 + i, v & 0xFF)

    # Breeding ext (0..16)
    be = getattr(horse, "breeding_ext", None)
    if isinstance(be, dict):
        keys = ["start", "corner", "oob", "comp", "ten", "spurt"]
        for i, k in enumerate(keys):
            struct.pack_into("<B", buf, 0x70 + i, _safe_int(be.get(k), 0) & 0xFF)

    _pack_str(buf, 0x80, 32, getattr(horse, "sire_name", "") or "")
    _pack_str(buf, 0xA0, 32, getattr(horse, "dam_name", "") or "")

    return bytes(buf)


def export_state_to_raw_files(state: Dict[str, Any], export_dir: Path) -> Tuple[Path, Path]:
    """Export `.raw` + manifest for a save-state dict."""

    export_dir.mkdir(parents=True, exist_ok=True)

    # Load horse and ensure extras
    horse = horse_from_dict(state.get("player", {}))

    seed = _safe_int(state.get("seed"), 0)
    rev = str(state.get("rev", "revC"))
    earnings = _safe_int(state.get("earnings"), 0)
    races_run = _safe_int(state.get("races_run"), 0)

    ensure_horse_extras(horse, seed=seed)

    raw_bytes = build_docsim_raw_payload(
        horse,
        seed=seed,
        rev=rev,
        earnings=earnings,
        races_run=races_run,
    )

    stem = safe_filename(horse.name)
    raw_path = export_dir / f"{stem}.raw"
    manifest_path = export_dir / f"{stem}.raw.json"

    raw_path.write_bytes(raw_bytes)

    manifest = {
        "schema": "DOCSIMRAW",
        "schema_version": 1,
        "seed": seed,
        "rev": rev,
        "earnings": earnings,
        "races_run": races_run,
        "horse": horse_to_dict(horse),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return raw_path, manifest_path
