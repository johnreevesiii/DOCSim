"""MSR206u-compatible DOC horse card (.RAW) export.

This module implements the text-based .RAW format used by common MSR206u
magstripe emulation workflows and by the community DOC Tools Suite Card Editor.

The track encoding algorithm and header layout are based on the JavaScript
implementation in the provided DOC_Card_Editor.html (MSR206u Compatible).

DOCSim does not model every attribute available on real DOC cards.
This exporter therefore:
- maps known DOCSim stats into the card fields,
- deterministically generates missing attributes (color/personality/hearts/etc.),
- derives W/P/S/O and G1 title bits from the saved career log when available.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from docsim.models import Horse
from docsim.save_load import horse_from_dict


# ---------------------------------------------------------------------------
# Constants mirrored from DOC_Card_Editor.html
# ---------------------------------------------------------------------------

MSR_COLOR_OPTIONS: List[Tuple[str, int, int]] = [
    ("Bay", 0x00, 0x00),
    ("Dark Bay", 0x00, 0x0C),
    ("Seal Brown", 0x00, 0x07),
    ("Brown", 0x00, 0x06),
    ("Chestnut", 0x00, 0x08),
    ("Dark Chestnut", 0x00, 0x0A),
    ("Light Chestnut", 0x00, 0x09),
    ("Gray", 0x00, 0x02),
    ("Dark Gray", 0x00, 0x03),
    ("Light Gray", 0x00, 0x04),
    ("Black", 0x00, 0x01),
    ("White", 0x00, 0x05),
    ("Golden", 0x00, 0x0B),
]

MSR_PERSONALITIES: List[Tuple[str, int]] = [
    ("Easy Going", 0),
    ("Stubborn", 1),
    ("Competitive", 2),
    ("Hot Headed", 3),
    ("Always Serious", 4),
    ("Bashful", 5),
    ("Lonely", 6),
    ("Moody", 7),
    ("Show Off", 8),
    ("Lazy", 9),
    ("Rowdy", 10),
]

# In Card Editor: silkType is 0-7
MSR_SILK_TYPE_RANGE = (0, 7)

# In Card Editor: silk colors are 0-14
MSR_SILK_COLOR_RANGE = (0, 14)

# In Card Editor: hood values are a sparse set
MSR_HOOD_OPTIONS: List[int] = [0, 1, 2, 7, 15, 25, 30, 38, 63]

# G1 title bit mapping (a2[55..57]) from Card Editor
# Each entry: (id, name, byte_index, bit_mask)
MSR_G1_RACES: List[Tuple[int, str, int, int]] = [
    (0, "Unicom", 55, 0x01),
    (1, "Derby", 55, 0x02),
    (2, "Sprinter Trophy", 55, 0x10),
    (3, "Doc 1000", 55, 0x20),
    (4, "Doc 2000", 55, 0x40),
    (5, "Oaks", 55, 0x80),
    (6, "Crown", 56, 0x01),
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _clamp_int(val: Any, lo: int, hi: int, default: int) -> int:
    try:
        if val is None:
            return default
        i = int(val)
    except (TypeError, ValueError):
        return default
    if i < lo:
        return lo
    if i > hi:
        return hi
    return i


def _get_field(obj: Any, field: str) -> Any:
    """Best-effort field lookup on either a mapping or an object.

    DOCSim uses dataclasses (Internals/Externals/CareerLogEntry) in-memory, but older
    exports (or user tooling) may use plain dicts. This helper keeps the exporter
    tolerant of both.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(field)
    return getattr(obj, field, None)


def _sanitize_filename(name: str) -> str:
    # Keep it Windows-friendly.
    bad = '<>:/\\|?*"'
    out = ''.join('_' if c in bad else c for c in name)
    out = out.strip().strip('.')
    return out or 'horse'


def _rng_for(seed: int, horse: Horse) -> random.Random:
    # Deterministic RNG so the same saved horse exports consistently.
    base = f"{seed}|{horse.name}|{horse.id}".encode('utf-8', errors='ignore')
    digest = hashlib.sha256(base).digest()
    n = int.from_bytes(digest[:8], 'big', signed=False)
    return random.Random(n)


def _set_string(ar: List[int], start_idx: int, text: str, max_len: int = 18) -> None:
    # Mirrors Card Editor setString(): writes forward characters into descending indices.
    if text is None:
        text = ""
    s = str(text)[:max_len]
    for i in range(max_len):
        idx = start_idx - i
        if idx < 0 or idx >= len(ar):
            break
        ar[idx] = 0
    for i, ch in enumerate(s):
        idx = start_idx - i
        if idx < 0 or idx >= len(ar):
            break
        ar[idx] = ord(ch) & 0xFF


# ---------------------------------------------------------------------------
# Track encoding and .RAW layout (ported from Card Editor)
# ---------------------------------------------------------------------------


def encode_track(ar_hex: Sequence[int]) -> Optional[str]:
    '''Encode one 70-byte track into the MSR206u-compatible 144-hex-character string.

    This is a direct port of `encodeTrack()` from DOC_Card_Editor.html.
    '''

    if len(ar_hex) != 70:
        raise ValueError('track array must be length 70')

    # Clamp to byte range (mirrors typical JS behaviour when values are already valid).
    ar = [int(v) & 0xFF for v in ar_hex]

    for multi_code in (128, 64, 32, 16, 8, 4, 2, 1):
        # newHex starts with (256 - multiCode)
        new_hex = f"{256 - multi_code:02X}"

        # Encode index 69
        new_data = ar[69] * multi_code + multi_code - 1
        t_val = new_data // 256
        new_hex = f"{new_data % 256:02X}" + new_hex

        # Encode indices 68..1
        for idx in range(68, 0, -1):
            new_data = ar[idx] * multi_code + t_val
            t_val = new_data // 256
            new_hex = f"{new_data % 256:02X}" + new_hex

        # Prefix (256 - multiCode) again
        new_hex = f"{256 - multi_code:02X}" + new_hex

        # Checksums
        chksum1 = 255 ^ int(new_hex[0:2], 16)
        for i in range(2, len(new_hex) - 1, 2):
            chksum1 ^= int(new_hex[i:i + 2], 16)

        chksum2 = int(new_hex[0:2], 16) ^ int(new_hex[2:4], 16)
        for i in range(4, len(new_hex) - 3, 2):
            chksum2 ^= int(new_hex[i:i + 2], 16)

        chksum2 = chksum2 + multi_code - 1

        if chksum1 == chksum2:
            return f"{chksum1:02X}" + new_hex

    return None


def generate_raw_content(track1_hex: str, track2_hex: str, track3_hex: str) -> str:
    """Build the MSR206u-compatible .RAW text file."""

    # NOTE: MSR206u uses a fixed [SETUP] header (identical for all cards) before [DATA].
    # The spacing/line-endings here intentionally match known-good exports.
    header = (
        "[SETUP]\r\n"
        "CARDTYPE =4\r\n"
        "PARITY1 =0\r\n"
        "PARITY2 =0\r\n"
        "PARITY3 =0\r\n"
        "BPC1 =8\r\n"
        "BPC2 =8\r\n"
        "BPC3 =8\r\n"
        "SS1 =5\r\n"
        "SS2 =10\r\n"
        "SS3 =10\r\n"
        "ES1 =31\r\n"
        "ES2 =15\r\n"
        "ES3 =15\r\n"
        "\r\n"
        "[DATA]\r\n"
    )

    # Control characters 0x01/0x02/0x03 prefix each track line.
    return header + "\x01" + track1_hex + "\r\n" + "\x02" + track2_hex + "\r\n" + "\x03" + track3_hex + "\r\n"


# ---------------------------------------------------------------------------
# MSR extras and state-to-card mapping
# ---------------------------------------------------------------------------


def ensure_msr_extras(horse: Horse, seed: int) -> None:
    """Ensure the Horse.extras has the MSR fields required for card export."""

    if horse.extras is None:
        horse.extras = {}

    ex = horse.extras
    rng = _rng_for(seed, horse)

    # Stable 4-byte ID
    uid = ex.get("msr_uid")
    if not (isinstance(uid, list) and len(uid) == 4 and all(isinstance(x, int) for x in uid)):
        uid = [rng.randrange(0, 256) for _ in range(4)]
        ex["msr_uid"] = uid

    # Color
    if not (isinstance(ex.get("msr_color_val"), int) and isinstance(ex.get("msr_color_val2"), int)):
        name, v1, v2 = rng.choice(MSR_COLOR_OPTIONS)
        ex["msr_color_name"] = name
        ex["msr_color_val"] = v1
        ex["msr_color_val2"] = v2

    # Personality
    if not isinstance(ex.get("msr_personality_code"), int):
        pname, pcode = rng.choice(MSR_PERSONALITIES)
        ex["msr_personality_name"] = pname
        ex["msr_personality_code"] = pcode

    # Hearts (1..15); default to 8 like Card Editor
    ex["msr_hearts"] = _clamp_int(ex.get("msr_hearts"), 1, 15, 8)

    # Silks
    ex["msr_silk_type"] = _clamp_int(ex.get("msr_silk_type"), MSR_SILK_TYPE_RANGE[0], MSR_SILK_TYPE_RANGE[1], rng.randrange(0, 8))
    ex["msr_silk_color1"] = _clamp_int(ex.get("msr_silk_color1"), MSR_SILK_COLOR_RANGE[0], MSR_SILK_COLOR_RANGE[1], rng.randrange(0, 15))
    ex["msr_silk_color2"] = _clamp_int(ex.get("msr_silk_color2"), MSR_SILK_COLOR_RANGE[0], MSR_SILK_COLOR_RANGE[1], rng.randrange(0, 15))

    # Hood
    hood = ex.get("msr_hood")
    if not isinstance(hood, int) or hood not in MSR_HOOD_OPTIONS:
        ex["msr_hood"] = rng.choice(MSR_HOOD_OPTIONS)

    # Dirt ability (0..255), default 128
    ex["msr_dirt_ability"] = _clamp_int(ex.get("msr_dirt_ability"), 0, 255, 128)


def _derive_w_p_s_o_from_career_log(horse: Horse) -> Tuple[int, int, int, int, int]:
    """Return (total, wins, places, shows, outs) from saved career_log.

    DOCSim stores career_log as either:
      * a list of dicts (older)
      * a list of CareerLogEntry dataclasses (current)
    """

    total = 0
    wins = places = shows = outs = 0

    for entry in getattr(horse, "career_log", []) or []:
        pos_val = _get_field(entry, "player_pos")
        if pos_val is None:
            continue
        try:
            pos = int(pos_val)
        except Exception:
            continue

        total += 1
        if pos == 1:
            wins += 1
        elif pos == 2:
            places += 1
        elif pos == 3:
            shows += 1
        elif pos >= 4:
            outs += 1

    return total, wins, places, shows, outs


def _derive_g1_title_ids(horse: Horse) -> List[int]:
    """Infer DOC G1 title bit IDs (0..6) from career_log and stored extras.

    DOC MSR export stores G1 wins in 3 bytes (a2[55], a2[56], a2[57]) where
    each bit corresponds to a specific G1 race. The mapping here follows the
    Tools Suite Card Editor's G1_RACES list.
    """

    ids: List[int] = []

    # 1) Prefer explicitly stored IDs (if present)
    ex = horse.extras or {}
    stored = ex.get("g1_title_ids")
    if isinstance(stored, list):
        for x in stored:
            try:
                i = int(x)
            except Exception:
                continue
            if 0 <= i <= 6 and i not in ids:
                ids.append(i)

    # 2) Derive from career_log race names
    for entry in getattr(horse, "career_log", []) or []:
        pos_val = _get_field(entry, "player_pos")
        if pos_val is None:
            continue
        try:
            pos = int(pos_val)
        except Exception:
            continue
        if pos != 1:
            continue

        race_name = str(_get_field(entry, "race_name") or "")
        if not race_name:
            continue
        if "G1" not in race_name.upper():
            continue

        rn = race_name.lower()
        match_id: Optional[int] = None
        if "unicom" in rn:
            match_id = 0
        elif "derby" in rn:
            match_id = 1
        elif "sprinter" in rn and "trophy" in rn:
            match_id = 2
        elif "1000" in rn and "guine" in rn:
            match_id = 3
        elif "2000" in rn and "guine" in rn:
            match_id = 4
        elif "oaks" in rn:
            match_id = 5
        elif "crown" in rn:
            match_id = 6

        if match_id is not None and match_id not in ids:
            ids.append(match_id)

    return ids


def _g1_title_bytes(title_ids: Sequence[int]) -> Tuple[int, int, int]:
    """Convert title IDs to the three packed bytes stored at a2[55..57]."""

    b55 = 0
    b56 = 0
    b57 = 0

    for tid in title_ids:
        try:
            i = int(tid)
        except Exception:
            continue

        for race_id, _name, byte_idx, bit_mask in MSR_G1_RACES:
            if race_id != i:
                continue
            if byte_idx == 55:
                b55 |= bit_mask
            elif byte_idx == 56:
                b56 |= bit_mask
            elif byte_idx == 57:
                b57 |= bit_mask
            break

    return b55 & 0xFF, b56 & 0xFF, b57 & 0xFF



def build_msr_arrays(state: Dict[str, Any]) -> Tuple[List[int], List[int], List[int]]:
    """Convert a DOCSim save-state dict to 3x 70-byte MSR track arrays."""

    seed = _clamp_int(state.get("seed"), 0, 2**31 - 1, 0)
    player_obj = state.get("player")
    horse = player_obj if isinstance(player_obj, Horse) else horse_from_dict(player_obj or {})

    ensure_msr_extras(horse, seed)
    ex = horse.extras or {}

    # Base arrays (Card Editor createNewHorse defaults)
    a1 = [0] * 70
    a2 = [0] * 70
    a3 = [0] * 70


    uid = ex.get("msr_uid") or [0, 0, 0, 0]
    uid = [int(x) & 0xFF for x in uid][:4]
    while len(uid) < 4:
        uid.append(0)

    for i in range(4):
        a1[2 + i] = uid[i]
        a2[2 + i] = uid[i]
        a3[2 + i] = uid[i]

    # Strings (horse / sire / dam)
    _set_string(a1, 69, horse.name or "")
    _set_string(a1, 49, getattr(horse, "sire_name", "") or "")
    _set_string(a1, 29, getattr(horse, "dam_name", "") or "")

    # Color / personality
    a1[6] = _clamp_int(ex.get("msr_personality_code"), 0, 255, 0)
    a1[8] = _clamp_int(ex.get("msr_color_val"), 0, 255, 0)
    a1[9] = _clamp_int(ex.get("msr_color_val2"), 0, 255, 0)

    # Sex mapping: Card Editor uses 0=Male, 1=Female, 2=Gelding
    sex = str(getattr(horse, "sex", "M") or "M").upper()
    if sex.startswith("F"):
        sex_code = 1
    elif sex.startswith("G"):
        sex_code = 2
    else:
        sex_code = 0
    a2[16] = sex_code

    # Silks / hood
    a2[15] = _clamp_int(ex.get("msr_silk_type"), 0, 255, 0)
    a2[14] = _clamp_int(ex.get("msr_silk_color1"), 0, 255, 0)
    a2[13] = _clamp_int(ex.get("msr_silk_color2"), 0, 255, 0)
    a2[26] = _clamp_int(ex.get("msr_hood"), 0, 255, 0)

    # Current externals (1..64 stored as value-1)
    ext = getattr(horse, "externals", None)

    def _ext_current(key: str, default: int) -> int:
        v = _get_field(ext, key)
        v = _clamp_int(v, 1, 64, default)
        return (v - 1) & 0xFF

    a2[43] = _ext_current("start", 16)
    a2[42] = _ext_current("corner", 16)
    a2[41] = _ext_current("oob", 16)
    a2[40] = _ext_current("competing", 16)
    a2[39] = _ext_current("tenacious", 16)
    a2[38] = _ext_current("spurt", 16)

    # Retirement externals (tiers): card editor expects 1..16 in UI, stored as value-1 (0..15)
    b_ext = getattr(horse, "breeding_ext", None)

    def _ext_retired(key: str, default_display: int = 16) -> int:
        v = _get_field(b_ext, key)
        if v is None:
            v = default_display
        # DOCSim breeding tiers are typically stored as 1..16; convert to 0..15.
        v = _clamp_int(v, 0, 16, default_display)
        if v == 0:
            return 0
        return _clamp_int(v - 1, 0, 15, 15) & 0xFF

    a2[33] = _ext_retired("start", 16)
    a2[32] = _ext_retired("corner", 16)
    a2[31] = _ext_retired("oob", 16)
    a2[30] = _ext_retired("competing", 16)
    a2[29] = _ext_retired("tenacious", 16)
    a2[28] = _ext_retired("spurt", 16)

    # Current internals (0..60)
    intr = getattr(horse, "internals", None)
    a2[69] = _clamp_int(_get_field(intr, "stamina"), 0, 60, 0)
    a2[65] = _clamp_int(_get_field(intr, "speed"), 0, 60, 0)
    a2[61] = _clamp_int(_get_field(intr, "sharp"), 0, 60, 0)

    # Retired internals (breeding): floor((sire+dam)/2), capped 45 (Tools Suite convention)
    sire_int = getattr(horse, "sire_int", None)
    dam_int = getattr(horse, "dam_int", None)

    def _ret_int(key: str, fallback: int) -> int:
        s = _get_field(sire_int, key)
        d = _get_field(dam_int, key)
        if s is None or d is None:
            return _clamp_int(fallback, 0, 45, 0)
        try:
            avg = (int(s) + int(d)) // 2
        except Exception:
            avg = fallback
        return _clamp_int(avg, 0, 45, 0)

    a2[25] = _ret_int("stamina", min(a2[69], 45))
    a2[24] = _ret_int("speed", min(a2[65], 45))
    a2[23] = _ret_int("sharp", min(a2[61], 45))

    # Hearts encoding: hearts*4 - 1
    hearts = _clamp_int(ex.get("msr_hearts"), 1, 15, 8)
    a2[37] = (hearts * 4 - 1) & 0xFF

    # W/P/S/O
    total_races, wins, places, shows, outs = _derive_w_p_s_o_from_career_log(horse)
    # If career log missing, fallback to state's races_run
    if total_races <= 0:
        total_races = _clamp_int(state.get("races_run"), 0, 255, 0)

    a2[35] = _clamp_int(total_races, 0, 255, 0)
    a2[49] = _clamp_int(wins, 0, 255, 0)
    a2[48] = _clamp_int(places, 0, 255, 0)
    a2[47] = _clamp_int(shows, 0, 255, 0)
    a2[46] = _clamp_int(outs, 0, 255, 0)
    a2[34] = a2[49]

    # Earnings (stored as thousands, 3 bytes big-endian)
    earnings_dollars = _clamp_int(state.get("earnings"), 0, 2**31 - 1, 0)
    earnings_internal = earnings_dollars // 1000
    if earnings_internal < 0:
        earnings_internal = 0
    if earnings_internal > 0xFFFFFF:
        earnings_internal = 0xFFFFFF
    a2[51] = (earnings_internal >> 16) & 0xFF
    a2[52] = (earnings_internal >> 8) & 0xFF
    a2[53] = earnings_internal & 0xFF

    # G1 titles
    title_ids = _derive_g1_title_ids(horse)
    b55, b56, b57 = _g1_title_bytes(title_ids)
    a2[55] = b55
    a2[56] = b56
    a2[57] = b57

    # Track3: dirt ability + retire flags
    a3[61] = _clamp_int(ex.get("msr_dirt_ability"), 0, 255, 128)

    retired = bool(state.get("retired", False))
    a3[57] = 1 if retired else 0

    # Breeds count encoding in Card Editor: a3[53] = breeds*2 when retired else 0
    breeds = _clamp_int(state.get("breeds"), 0, 127, 0)
    a3[53] = (breeds * 2) & 0xFF if retired else 0

    # Final sanity clamp 0..255
    a1 = [int(x) & 0xFF for x in a1]
    a2 = [int(x) & 0xFF for x in a2]
    a3 = [int(x) & 0xFF for x in a3]

    return a1, a2, a3


def export_state_to_msr206u_raw(state: Dict[str, Any], out_dir: str = "exports/msr206u") -> str:
    """Export DOCSim save-state to an MSR206u-compatible .RAW file.

    Returns the written file path.
    """

    player_obj = state.get("player")
    horse = player_obj if isinstance(player_obj, Horse) else horse_from_dict(player_obj or {})

    # Pass a shallow-copied state with an actual Horse object for downstream helpers.
    st: Dict[str, Any] = dict(state)
    st["player"] = horse

    a1, a2, a3 = build_msr_arrays(st)

    t1 = encode_track(a1)
    t2 = encode_track(a2)
    t3 = encode_track(a3)

    if not (t1 and t2 and t3):
        raise RuntimeError("MSR track encoding failed (unexpected values out of range)")

    content = generate_raw_content(t1, t2, t3)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    fname = _sanitize_filename(horse.name or "horse") + ".RAW"
    full = out_path / fname

    # Write as text but include control chars; use latin-1 to preserve bytes 0x01-0x03.
    full.write_bytes(content.encode('latin-1', errors='replace'))

    return str(full)
