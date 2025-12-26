from __future__ import annotations
import argparse
import os
import re
import sys
from pathlib import Path
from typing import List

from . import __version__
from .rng import RNG, hash64
from .roster import ParentHorse, load_roster_from_breeder_html
from .breeding import breed_internals, breed_ac, compute_birth_ext_8_48_from_parents, derive_leg_type, clamp_int
from .models import Externals, Horse, Internals, RaceLogEntry
from .schedule import SCHEDULE as BASE_SCHEDULE, RaceMeta
from .cpu_pool import build_round_pool, select_cpu_field, compute_1r_handicap_band_shift
from .handicapping import render_handicapping_table
from .commentary import birth_comment, expected_score, race_insight_lines, retirement_poem_lines
from .race_engine import draw_gates, run_race_sim
from .race_reporting import timed_results, render_race_card, format_time
from .gambling import run_gambling_chance
from .training import TRAININGS, PACE_PLANS, PREFERRED, grade_from_minigame, apply_training, primary_secondary_for_training
from .feeding import build_food_offering, apply_feeding
from .progression import apply_post_race_growth, apply_g1_win_rewards
from .records import load_records, save_records, reset_records, record_surfaces_map
from .surfaces import enrich_schedule_with_codes_and_surfaces, roll_condition
from .save_load import save_game, load_game, horse_to_dict, horse_from_dict
from .raw_export import export_state_to_raw_files, ensure_horse_extras
from .msr_export import export_state_to_msr206u_raw, ensure_msr_extras
from .leaderboard import render_leaderboard, top_earnings_leaderboard
from .world import WorldState, load_world_state, save_world_state, reset_world_state, advance_world_round

G1_GATE = 1_000_000


def _clear_screen() -> None:
    """Best-effort terminal clear for a cleaner 'splash' main menu."""
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass


def print_splash() -> None:
    """Print a simple terminal splash screen (homage; not a logo replica)."""
    _clear_screen()
    art = r"""
  ██████╗  ██████╗  ██████╗███████╗██╗███╗   ███╗
  ██╔══██╗██╔═══██╗██╔════╝██╔════╝██║████╗ ████║
  ██║  ██║██║   ██║██║     █████╗  ██║██╔████╔██║
  ██║  ██║██║   ██║██║     ██╔══╝  ██║██║╚██╔╝██║
  ██████╔╝╚██████╔╝╚██████╗███████╗██║██║ ╚═╝ ██║
  ╚═════╝  ╚═════╝  ╚═════╝╚══════╝╚═╝╚═╝     ╚═╝
""".rstrip("\n")

    print(art)
    print(f"\n  DOCSim — Derby Owners Club Simulation Program  (v{__version__})")
    print("  World Edition  |  text-based homage")
    print("  " + ("=" * 54) + "\n")


def safe_filename(name: str) -> str:
    """Return a filesystem-safe stem for save files."""
    s = name.strip()
    # Replace characters that are problematic on Windows filesystems.
    s = re.sub(r'[<>:"/\\|?*]+', "_", s)
    # Collapse whitespace to underscores
    s = re.sub(r"\s+", "_", s)
    # Keep it tidy
    s = re.sub(r"_+", "_", s).strip("._ ")
    return s if s else "horse"

def prompt_int(prompt: str, lo: int, hi: int) -> int:
    while True:
        try:
            v = int(input(prompt).strip())
            if lo <= v <= hi:
                return v
        except Exception:
            pass
        print(f"Enter a number between {lo} and {hi}.")

def prompt_choice(prompt: str, options: List[str]) -> int:
    print(prompt)
    for i, opt in enumerate(options, start=1):
        print(f"  {i}. {opt}")
    return prompt_int("Select: ", 1, len(options)) - 1


def leg_type_label(code: str) -> str:
    return {
        "FR": "Front-runner",
        "SD": "Start Dash",
        "LS": "Last Spurt",
        "SR": "Stretch-runner",
        "AL": "Almighty",
    }.get(code, code)

def stable_card(player: Horse, deltas: dict | None = None) -> None:
    e = player.externals
    def fmt(stat: str, val: int) -> str:
        if deltas and stat in deltas and deltas[stat]:
            d = deltas[stat]
            sign = "+" if d > 0 else ""
            return f"{stat.upper():<4} {val:>2} ({sign}{d})"
        return f"{stat.upper():<4} {val:>2}"
    parts = [
        fmt("start", e.start),
        fmt("corner", e.corner),
        fmt("oob", e.oob),
        fmt("competing", e.competing),
        fmt("tenacious", e.tenacious),
        fmt("spurt", e.spurt),
    ]
    print(" | ".join(parts))

def display_parent(h) -> str:
    return f"{h.name} | INT {h.stamina}/{h.speed}/{h.sharp} | AC {h.ac} | EXT {h.start},{h.corner},{h.oob},{h.competing},{h.tenacious},{h.spurt}"


def render_parent_pick_table(parents: list[ParentHorse]) -> str:
    """Render sire/dam selection in a table (cosmetic only)."""

    if not parents:
        return "(no horses)"

    name_w = min(28, max(16, max(len(p.name) for p in parents)))

    header = (
        f"{'#':>2}  {'Horse':<{name_w}}  {'INT':>9}  {'AC':>4}  "
        f"{'Start':>5} {'Corner':>6} {'OOB':>4} {'Comp':>4} {'Ten':>3} {'Spurt':>5}"
    )
    sep = "-" * len(header)
    rows = [header, sep]
    for i, p in enumerate(parents, start=1):
        int_txt = f"{int(p.stamina):d}/{int(p.speed):d}/{int(p.sharp):d}"
        rows.append(
            f"{i:>2}  {p.name:<{name_w}}  {int_txt:>9}  {int(p.ac):>4}  "
            f"{int(p.start):>5} {int(p.corner):>6} {int(p.oob):>4} {int(p.competing):>4} {int(p.tenacious):>3} {int(p.spurt):>5}"
        )
    return "\n".join(rows)


def _ext_8_48_to_0_16(v: int) -> int:
    """Convert in-career external scale (8..48) back to breeder-scale (0..16)."""
    return clamp_int(int(round(((int(v) - 8) / 40.0) * 16.0)), 0, 16)


def _parent_from_retired(h: Horse) -> ParentHorse:
    """Build a roster-style ParentHorse from a retired race horse."""
    # Prefer the breeding-card externals (genetic, derived from sire/dam)
    # when available. If missing (older saves), fall back to converting the
    # trained 8..48 externals.
    be = getattr(h, "breeding_ext", None)
    if isinstance(be, dict) and all(k in be for k in ("start", "corner", "oob", "competing", "tenacious", "spurt")):
        start = clamp_int(int(be["start"]), 0, 16)
        corner = clamp_int(int(be["corner"]), 0, 16)
        oob = clamp_int(int(be["oob"]), 0, 16)
        competing = clamp_int(int(be["competing"]), 0, 16)
        tenacious = clamp_int(int(be["tenacious"]), 0, 16)
        spurt = clamp_int(int(be["spurt"]), 0, 16)
    else:
        start = _ext_8_48_to_0_16(h.externals.start)
        corner = _ext_8_48_to_0_16(h.externals.corner)
        oob = _ext_8_48_to_0_16(h.externals.oob)
        competing = _ext_8_48_to_0_16(h.externals.competing)
        tenacious = _ext_8_48_to_0_16(h.externals.tenacious)
        spurt = _ext_8_48_to_0_16(h.externals.spurt)

    return ParentHorse(
        name=h.name,
        stamina=int(h.internals.stamina),
        speed=int(h.internals.speed),
        sharp=int(h.internals.sharp),
        ac=int(h.ac),
        start=start,
        corner=corner,
        oob=oob,
        competing=competing,
        tenacious=tenacious,
        spurt=spurt,
    )


def _load_retired_candidates(retired_dir: Path) -> List[dict]:
    """Load retired horses that can be used as breeding parents."""
    out: List[dict] = []
    if not retired_dir.exists():
        return out
    for p in sorted(retired_dir.glob("*.json")):
        try:
            state = load_game(str(p))
            if not state:
                continue
            h = horse_from_dict(state.get("player", {}))
            out.append(
                {
                    "path": p,
                    "horse": h,
                    "earnings": int(state.get("earnings", 0)),
                    "races_run": int(state.get("races_run", 0)),
                    "g1_wins": int(getattr(h, "g1_wins", 0)),
                    "tokens": int(getattr(h, "genetic_tokens", 0)),
                }
            )
        except Exception:
            continue
    return out


def create_player_horse(seed: int, sires, dams, rev: str, retired_dir: Path) -> Horse:
    rng = RNG(hash64(seed, "MARKET", rev))
    sires_pick = rng.sample(sires, 10)
    dams_pick = rng.sample(dams, 10)

    retired = _load_retired_candidates(retired_dir)
    retired_stallions = [r for r in retired if r["horse"].sex == "M"]
    retired_mares = [r for r in retired if r["horse"].sex == "F"]

    # --- Sire selection ---
    print("\n=== Choose your Sire (10) ===")
    print(render_parent_pick_table(sires_pick))

    sire_tokens = 0
    if retired_stallions:
        src = (input("Sire source: (M)arket or (R)etired stable? [M]: ").strip().lower() or "m")
    else:
        src = "m"

    if src == "r" and retired_stallions:
        print("\n=== Retired Stallions (Stable) ===")
        for i, r in enumerate(retired_stallions, start=1):
            h = r["horse"]
            print(
                f"{i:2d}. {h.name} (M) | ${r['earnings']:,} | Races {r['races_run']} | G1 {r['g1_wins']} | Tokens {r['tokens']}"
            )
        pick = prompt_int("Pick retired sire (1-{0}): ".format(len(retired_stallions)), 1, len(retired_stallions)) - 1
        sire_h = retired_stallions[pick]["horse"]
        sire = _parent_from_retired(sire_h)
        sire_tokens = int(getattr(sire_h, "genetic_tokens", 0))
    else:
        sire = sires_pick[prompt_int("Pick sire (1-10): ", 1, 10) - 1]

    # --- Dam selection ---
    print("\n=== Choose your Dam (10) ===")
    print(render_parent_pick_table(dams_pick))

    dam_tokens = 0
    if retired_mares:
        src = (input("Dam source: (M)arket or (R)etired stable? [M]: ").strip().lower() or "m")
    else:
        src = "m"

    if src == "r" and retired_mares:
        print("\n=== Retired Mares (Stable) ===")
        for i, r in enumerate(retired_mares, start=1):
            h = r["horse"]
            print(
                f"{i:2d}. {h.name} (F) | ${r['earnings']:,} | Races {r['races_run']} | G1 {r['g1_wins']} | Tokens {r['tokens']}"
            )
        pick = prompt_int("Pick retired dam (1-{0}): ".format(len(retired_mares)), 1, len(retired_mares)) - 1
        dam_h = retired_mares[pick]["horse"]
        dam = _parent_from_retired(dam_h)
        dam_tokens = int(getattr(dam_h, "genetic_tokens", 0))
    else:
        dam = dams_pick[prompt_int("Pick dam (1-10): ", 1, 10) - 1]

    # Roll foal sex BEFORE naming (helps the player pick a fitting name).
    sex = "M" if rng.random() < 0.5 else "F"
    print(f"\nFoal sex will be: {'Colt' if sex == 'M' else 'Filly'} ({sex})")
    # NOTE: create_player_horse() receives `seed` as an argument; `args` is not
    # in scope here.
    print(birth_comment(seed, sex, sire, dam))
    name = input("Name your foal: ").strip() or "Unnamed Foal"

    ints = breed_internals(sire, dam)
    birth_rng = RNG(hash64(seed, "BIRTH", name))
    ext = compute_birth_ext_8_48_from_parents(
        sire,
        dam,
        birth_rng,
        cap_sum=160,
        genetic_tokens_sire=sire_tokens,
        genetic_tokens_dam=dam_tokens,
    )
    ac = breed_ac(sire, dam, birth_rng)
    style = derive_leg_type(ext)

    horse = Horse(
        id="PLAYER-001",
        name=name,
        sex=sex,
        style=style,
        ac=ac,
        internals=Internals(**ints),
        externals=Externals(**ext),
    )

    # Store pedigree data for retirement display (Dam/Sire registration card)
    # and for future breeding-pool use.
    horse.sire_name = sire.name
    horse.dam_name = dam.name
    horse.sire_ext = {
        "start": int(sire.start),
        "corner": int(sire.corner),
        "oob": int(sire.oob),
        "competing": int(sire.competing),
        "tenacious": int(sire.tenacious),
        "spurt": int(sire.spurt),
    }
    horse.dam_ext = {
        "start": int(dam.start),
        "corner": int(dam.corner),
        "oob": int(dam.oob),
        "competing": int(dam.competing),
        "tenacious": int(dam.tenacious),
        "spurt": int(dam.spurt),
    }
    horse.breeding_ext = {
        "start": (int(sire.start) + int(dam.start)) // 2,
        "corner": (int(sire.corner) + int(dam.corner)) // 2,
        "oob": (int(sire.oob) + int(dam.oob)) // 2,
        "competing": (int(sire.competing) + int(dam.competing)) // 2,
        "tenacious": (int(sire.tenacious) + int(dam.tenacious)) // 2,
        "spurt": (int(sire.spurt) + int(dam.spurt)) // 2,
    }

    # Optional cosmetic/personality metadata (used by raw export; not used by the sim core yet)
    ensure_horse_extras(horse, seed=seed)
    ensure_msr_extras(horse, seed=seed)

    print(f"\nFoal created: {horse.name} ({horse.sex}) {leg_type_label(horse.style)} [{horse.style}]  AC={horse.ac}")
    print(f"Internals ST/SP/SH: {horse.internals.stamina}/{horse.internals.speed}/{horse.internals.sharp}")
    print("Externals:")
    stable_card(horse)
    return horse

def training_flow(seed: int, meet_iter: int, race: RaceMeta, player: Horse) -> tuple[int, str]:
    # returns (training_index, grade)
    if input("Train before race? (y/N): ").strip().lower() != "y":
        print("No training.")
        return -1, "None"

    idx = prompt_choice("Choose training:", [t[0] for t in TRAININGS])
    # Pace plan is no longer user-selectable (DOC-like). We still keep its
    # randomness / grade impact, but roll it deterministically from the seed.
    plan_rng = RNG(hash64(seed, "TRAIN_PLAN", race.round_num, race.slot, meet_iter, idx))
    plan_name = PACE_PLANS[plan_rng.randint(0, len(PACE_PLANS) - 1)]

    rng = RNG(hash64(seed, "TRAIN_GRADE", race.round_num, race.slot, meet_iter, idx))
    preferred = PREFERRED.get((TRAININGS[idx][0], player.style), ["Even"])
    grade = grade_from_minigame(rng, plan_name, preferred)

    trng = RNG(hash64(seed, "TRAIN_DELTA", race.round_num, race.slot, meet_iter, idx))
    tr = apply_training(player, idx, grade, trng)
    player.last_training = tr
    print(f"Training: {tr.training_name} | Plan: {plan_name} (auto) => {grade}")
    if any(v for v in tr.deltas.values()):
        stable_card(player, tr.deltas)
    return idx, grade

def feeding_flow(seed: int, meet_iter: int, race: RaceMeta, player: Horse, training_index: int, grade: str) -> None:
    # Feeding always occurs (even if no training)
    if training_index >= 0:
        prim, sec = primary_secondary_for_training(training_index)
    else:
        prim, sec = (), ()
    # Offer foods
    offered = build_food_offering(seed, meet_iter, race.round_num, race.slot, grade, prim, sec, player, k=5)
    print("\nFeeding Phase: choose a meal")
    for i,f in enumerate(offered, start=1):
        print(f"  {i}. {f}")
    choice = prompt_int("Select food (1-5): ", 1, 5) - 1
    chosen = offered[choice]
    fr = apply_feeding(seed, meet_iter, race.round_num, race.slot, grade, prim, sec, player, chosen)
    fr.foods_offered = offered
    player.last_feeding = fr
    print(f"You fed: {chosen}")
    stable_card(player, fr.deltas)

def profile_screen(player: Horse, earnings: int, races_run: int) -> None:
    print("\n=== Horse Profile ===")
    print(f"Name: {player.name} ({player.sex})  Leg Type: {leg_type_label(player.style)} [{player.style}]  AC: {player.ac}")
    print(f"Earnings: ${earnings:,} | Races: {races_run}")
    print(f"Internals ST/SP/SH: {player.internals.stamina}/{player.internals.speed}/{player.internals.sharp}")
    print(f"G1 wins: {player.g1_wins} | Genetic tokens: {player.genetic_tokens}")
    print("Externals:")
    stable_card(player)
    if getattr(player, "pending_g1_superfood", False):
        print("Note: A special food is guaranteed at your next 1R feeding (from your last G1 win).")
    input("Press Enter to continue...")


def _internal_type_label(h: Horse) -> str:
    """DOC-style 'type' derived from the highest internal value."""
    st = int(h.internals.stamina)
    sp = int(h.internals.speed)
    sh = int(h.internals.sharp)
    if st >= sp and st >= sh:
        return "STAMINA type"
    if sp >= st and sp >= sh:
        return "SPEED type"
    return "SHARP type"


def _breeding_card_ext_0_16(h: Horse) -> Dict[str, int]:
    """Return breeder-scale (0..16) externals for the retirement 'registration card'.

    Preferred source:
      1) h.breeding_ext (stored at birth: floor((sire+dam)/2))
      2) h.sire_ext + h.dam_ext (compute floor average)
      3) fallback: convert current race externals 8..48 -> 0..16-ish
    """
    keys = ("start", "corner", "oob", "competing", "tenacious", "spurt")

    be = getattr(h, "breeding_ext", None)
    if isinstance(be, dict) and all(k in be for k in keys):
        out = {k: int(be[k]) for k in keys}
        return out

    se = getattr(h, "sire_ext", None)
    de = getattr(h, "dam_ext", None)
    if isinstance(se, dict) and isinstance(de, dict) and all(k in se and k in de for k in keys):
        out = {k: (int(se[k]) + int(de[k])) // 2 for k in keys}
        return out

    # Fallback: derive something reasonable from trained stats.
    return {
        "start": _ext_8_48_to_0_16(h.externals.start),
        "corner": _ext_8_48_to_0_16(h.externals.corner),
        "oob": _ext_8_48_to_0_16(h.externals.oob),
        "competing": _ext_8_48_to_0_16(h.externals.competing),
        "tenacious": _ext_8_48_to_0_16(h.externals.tenacious),
        "spurt": _ext_8_48_to_0_16(h.externals.spurt),
    }


def retirement_tier_label(*, earnings: int, g1_wins: int) -> Tuple[str, str]:
    """A simple legacy tier used in the retirement screen."""
    # Heavier weight on G1 wins, with an earnings fallback.
    if g1_wins >= 3 or earnings >= 5_000_000:
        return "◎", "Legend"
    if g1_wins >= 1 or earnings >= 2_500_000:
        return "○", "Star"
    if earnings >= 750_000:
        return "▲", "Fighter"
    return "△", "Quiet"


def _symbol_for_breeding_value(v: int) -> str:
    """Map a 0..16-ish stat to DOC-like symbols.

    This is an absolute tiering (not field-relative like handicapping).
    """
    try:
        n = int(v)
    except Exception:
        n = 0
    if n >= 12:
        return "◎"
    if n >= 9:
        return "○"
    if n >= 6:
        return "▲"
    return "△"


def retirement_screen(seed: int, player: Horse, earnings: int, races_run: int) -> None:
    """DOC-style 'Dam/Sire reg.' splash with poem + stats + symbols."""
    _clear_screen()

    # Text and poem
    print("Dam reg.")
    print("=" * 62)
    print(f"{player.name} has finished its racing career...")
    print("Dam reg. and is")
    print("now ready to retire to the breeding farm.")
    print()

    g1_wins = int(getattr(player, "g1_wins", 0))
    tier_sym, tier_label = retirement_tier_label(earnings=earnings, g1_wins=g1_wins)
    print(f"Legacy: {tier_sym} {tier_label}")

    poem = retirement_poem_lines(seed, player)
    if poem:
        for line in poem:
            print(line)
        print()

    # Stats block
    internal_type = _internal_type_label(player)
    ext = _breeding_card_ext_0_16(player)
    sym = {k: _symbol_for_breeding_value(ext.get(k, 0)) for k in ext}

    print(f"{internal_type:>54}")
    print("".ljust(62, "-"))
    print(f"Earnings: ${earnings:,}  |  Races: {races_run}  |  G1 wins: {g1_wins}  |  Tokens: {int(getattr(player, 'genetic_tokens', 0))}")
    print(f"Internals ST/SP/SH: {player.internals.stamina}/{player.internals.speed}/{player.internals.sharp}")
    print()
    if getattr(player, "sire_name", None) or getattr(player, "dam_name", None):
        sire_name = getattr(player, "sire_name", "?")
        dam_name = getattr(player, "dam_name", "?")
        print(f"Sire: {sire_name}  |  Dam: {dam_name}")
        print()

    print("Breeding Card (externals)")
    print("START".ljust(14) + sym.get("start", "△"))
    print("CORNER".ljust(14) + sym.get("corner", "△"))
    print("OUT OF BOX".ljust(14) + sym.get("oob", "△"))
    print("COMPETING".ljust(14) + sym.get("competing", "△"))
    print("TENACIOUS".ljust(14) + sym.get("tenacious", "△"))
    print("SPURT".ljust(14) + sym.get("spurt", "△"))
    print()

    print("Final Trained Externals")
    stable_card(player)
    print()
    print("Do not leave Dam reg. card.")
    input("Press Enter to continue...")

def export_saved_horse_menu(save_dir: Path, retired_dir: Path, export_dir: Path) -> None:
    # Ensure output folder exists
    export_dir.mkdir(parents=True, exist_ok=True)

    candidates = []  # list[(path, label, state)]

    if save_dir.exists():
        for p in sorted(save_dir.glob("*.json")):
            try:
                st = load_game(p)
                candidates.append((p, "SAVE", st))
            except Exception:
                continue

    if retired_dir.exists():
        for p in sorted(retired_dir.glob("*.json")):
            try:
                st = load_game(p)
                candidates.append((p, "RETIRED", st))
            except Exception:
                continue

    if not candidates:
        print()
        print("No save/retired files found to export.")
        return

    print()
    print("=== Export a Saved Horse ===")
    for i, (_p, label, st) in enumerate(candidates, start=1):
        try:
            h = horse_from_dict(st.get("player", {}))
        except Exception:
            continue
        earnings = int(st.get("earnings", 0) or 0)
        races_run = int(st.get("races_run", 0) or 0)
        print(f"  {i}. {h.name} ({h.sex}) | ${earnings:,} | Races {races_run} [{label}]")

    choice = input("Pick a save number, or press Enter to cancel: ").strip()
    if not choice:
        return

    try:
        idx = int(choice) - 1
    except ValueError:
        print("Invalid selection.")
        return

    if idx < 0 or idx >= len(candidates):
        print("Invalid selection.")
        return

    st = candidates[idx][2]

    print()
    print("Choose export format:")
    print("  1) DOCSim RAW (binary)        -> .raw + manifest")
    print("  2) MSR206u RAW (Tools Suite)  -> .RAW (MSR206u Compatible)")
    print("  3) Both")
    fmt = (input("Select [3]: ").strip() or "3")

    if fmt not in ("1", "2", "3"):
        print("Invalid selection.")
        return

    raw_path = None
    manifest_path = None
    msr_path = None

    try:
        if fmt in ("1", "3"):
            raw_path, manifest_path = export_state_to_raw_files(st, export_dir=export_dir)
        if fmt in ("2", "3"):
            msr_path = export_state_to_msr206u_raw(st, out_dir=str(export_dir / "msr206u"))
    except Exception as e:
        print()
        print(f"Export failed: {e}")
        return

    print()
    print("Export complete")
    if raw_path and manifest_path:
        print(f"  RAW:      {raw_path}")
        print(f"  Manifest: {manifest_path}")
    if msr_path:
        print(f"  MSR206u:  {msr_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rev", type=str, default="revC", choices=["revA","revB","revC","revD"])
    ap.add_argument("--breeder-html", type=str, default=None, help="Path to DOC_Horse_Breeder_Lite_RevC_RevD.html")
    ap.add_argument("--max-rounds", type=int, default=1, help="How many rounds to play this run (1..16).")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--save", type=str, default=None, help="Save file path (.json). If omitted, defaults to saves/<horse_name>.json or continues the loaded save file.")
    ap.add_argument("--save-dir", type=str, default=str(Path("saves")), help="Directory to store autosaves when --save is not provided.")
    ap.add_argument(
        "--data-dir",
        type=str,
        default=str(Path("data")),
        help="Directory containing static data files (e.g., cpu_names.json, records defaults).",
    )
    ap.add_argument("--load", type=str, default=None)
    ap.add_argument("--reset-records", action="store_true")
    ap.add_argument("--records-state", type=str, default=str(Path("data")/"records_state.json"))
    ap.add_argument("--records-default", type=str, default=str(Path("data")/"records_default.json"))
    ap.add_argument(
        "--world-state",
        type=str,
        default=str(Path("data") / "world_state.json"),
        help="Path to persistent world race-program state (advances across horses).",
    )
    ap.add_argument("--reset-world", action="store_true", help="Reset the world race program back to Round 1.")
    ap.add_argument(
        "--retired-dir",
        type=str,
        default=str(Path("retired")),
        help="Directory where retired horses are stored for breeding.",
    )
    ap.add_argument(
        "--export-dir",
        type=str,
        default=str(Path("exports")),
        help="Directory where exported .raw files are written.",
    )

    args = ap.parse_args()

    # seed=0 means "random" (still printed so the run can be reproduced)
    if args.seed == 0:
        import secrets
        args.seed = secrets.randbelow(2_147_483_647 - 1) + 1
        print(f"(Using random seed: {args.seed})")

    # interactive fallback
    if not args.breeder_html:
        print("\nNo --breeder-html provided. Enter the path to DOC_Horse_Breeder_Lite_RevC_RevD.html")
        args.breeder_html = input("Breeder HTML path: ").strip() or None
    if not args.breeder_html:
        raise SystemExit("breeder-html is required (provide --breeder-html or enter it when prompted).")

    sires, dams = load_roster_from_breeder_html(args.breeder_html, args.rev)

    # Records
    records_state_path = Path(args.records_state)
    records_default_path = Path(args.records_default)
    if args.reset_records:
        reset_records(records_state_path, records_default_path, seed=args.seed)
    records = load_records(records_state_path, records_default_path)
    record_surfaces = record_surfaces_map(load_records(records_default_path, records_default_path))

    # World (cross-horse) race program
    world_state_path = Path(args.world_state)
    if args.reset_world:
        world = reset_world_state(world_state_path)
    else:
        world = load_world_state(world_state_path)

    retired_dir = Path(args.retired_dir)
    retired_dir.mkdir(parents=True, exist_ok=True)

    # schedule enrichment
    explicit_overrides = {
        (1,"G1"): "DIRT",  # Winter Stakes (DOC community schedule marks this as Dirt in many guides)
        (9,"G1"): "DIRT",  # Super Dirt GP
        (14,"G1"): "DIRT", # Japan Cup Dirt
    }
    schedule = enrich_schedule_with_codes_and_surfaces(BASE_SCHEDULE, record_surfaces, explicit_overrides)

    # load game if requested
    earnings = 0
    races_run = 0
    meet_iter = 1
    start_round = 1

    save_dir = Path(args.save_dir)
    export_dir = Path(args.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    save_path: Path | None = None

    # Main menu (interactive only).
    # This keeps the core flow intact while exposing extra utilities (e.g., Leaderboard).
    if args.load is None and sys.stdin.isatty():
        while True:
            print_splash()
            print("=== Main Menu ===")
            print("  1. Play")
            print("  2. Leaderboard")
            print("  3. Export Saved Horse (.raw)")
            print("  Q. Quit")
            sel = input("Select [1]: ").strip().lower()
            if sel in ("", "1", "p", "play"):
                break
            if sel in ("2", "l", "leaderboard", "board", "lb"):
                title, entries = top_earnings_leaderboard(
                    Path(args.save_dir),
                    Path(args.retired_dir),
                    seed=(args.seed if args.seed is not None else 0),
                    data_dir=Path(args.data_dir),
                    limit=25,
                )
                print()
                print(render_leaderboard(title, entries))
                input("\nPress Enter to return to the main menu: ")
                continue
            if sel in ("3", "e", "export"):
                export_saved_horse_menu(save_dir=save_dir, retired_dir=retired_dir, export_dir=export_dir)
                input("\nPress Enter to return to the main menu: ")
                continue
            if sel.startswith("q"):
                print("Goodbye.")
                return

    # Optional interactive load menu (if --load not provided)
    if args.load is None and sys.stdin.isatty():
        while True:
            choice = input("Start (N)ew horse or (L)oad save? [N]: ").strip().lower()
            if not choice or choice.startswith("n"):
                break
            if not choice.startswith("l"):
                break

            saves = sorted(save_dir.glob("*.json"))
            if not saves:
                print(f"No save files found in {save_dir}. Starting a new horse.")
                break

            print("\n=== Load a Saved Horse ===")
            for idx, p in enumerate(saves, start=1):
                summary = p.stem
                st = load_game(p)
                if st and isinstance(st, dict) and st.get("player"):
                    try:
                        h = horse_from_dict(st["player"])
                        e = int(st.get("earnings", 0))
                        r = int(st.get("races_run", 0))
                        retired_flag = bool(st.get("retired", False))
                        suffix = " [Retired]" if retired_flag else ""
                        summary = f"{h.name} ({h.sex}) | ${e:,} | Races {r}{suffix}"
                    except Exception:
                        pass
                print(f" {idx}. {summary}")

            sel = input(f"Pick save (1-{len(saves)}), or press Enter to cancel: ").strip()
            if not sel:
                break
            if sel.isdigit():
                k = int(sel)
                if 1 <= k <= len(saves):
                    # Validate non-retired here to avoid surprising crash later.
                    st = load_game(saves[k - 1])
                    if st and bool(st.get("retired", False)):
                        print("That horse is retired and cannot be loaded for racing.\n"
                              "Tip: start a new foal and select it as a retired sire/dam.")
                        continue
                    args.load = str(saves[k - 1])
                    break

    if args.load:
        state = load_game(Path(args.load))
        if state:
            if bool(state.get("retired", False)):
                print(
                    "This horse is retired and cannot be loaded for racing.\n"
                    "Tip: start a new foal and select it as a retired sire/dam."
                )
                return
            # Keep continuity: use the save's seed/rev if present
            if "seed" in state:
                try:
                    args.seed = int(state["seed"])
                except Exception:
                    pass
            if "rev" in state:
                try:
                    args.rev = str(state["rev"])
                except Exception:
                    pass

            player = horse_from_dict(state["player"])
            earnings = int(state.get("earnings", 0))
            races_run = int(state.get("races_run", 0))
            meet_iter = int(state.get("meet_iter", 1))
            start_round = int(state.get("round_num", 1))
            # Respect the global race program: the world never goes backwards.
            if start_round < world.current_round:
                start_round = world.current_round
            elif start_round > world.current_round:
                # If the save is ahead of the world (e.g., manual edits),
                # bring the world forward for consistency.
                world.current_round = start_round
                world.race_index = 0
                save_world_state(world_state_path, world)
            save_path = Path(args.load)
            print(f"Loaded save from {args.load}. (Seed: {args.seed} | Next round: {start_round})")
        else:
            print(f"Could not load save file: {args.load}. Starting a new horse instead.")
            args.load = None
            start_round = world.current_round
            player = create_player_horse(args.seed, sires, dams, args.rev, retired_dir)
    else:
        start_round = world.current_round
        player = create_player_horse(args.seed, sires, dams, args.rev, retired_dir)

    # Decide save file path
    if args.save:
        save_path = Path(args.save)
    elif save_path is None:
        save_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_filename(player.name)
        save_path = save_dir / f"{stem}.json"
        n = 2
        while save_path.exists():
            save_path = save_dir / f"{stem}_{n}.json"
            n += 1

    print(f"(Save file: {save_path})")

    retired_flag = bool(state.get("retired", False)) if args.load and state else False
    retired_reason: str | None = state.get("retired_reason") if args.load and state else None

    streak_oom = 0
    difficulty_offset = 0.0  # anti-runaway difficulty scaler

    def _build_state(next_round: int) -> dict:
        return {
            "seed": args.seed,
            "rev": args.rev,
            "round_num": next_round,
            "meet_iter": meet_iter,
            "earnings": earnings,
            "races_run": races_run,
            "retired": retired_flag,
            "retired_reason": retired_reason,
            "player": horse_to_dict(player),
            # Convenience for players who manage multiple horses
            "world": {"current_round": world.current_round, "cycle": world.cycle},
        }

    def save_now(next_round: int) -> dict:
        st = _build_state(next_round)
        save_game(save_path, st)
        return st

    def archive_retired_copy(st: dict) -> None:
        """Write a copy of the final state into retired/ for breeding."""
        try:
            retired_dir.mkdir(parents=True, exist_ok=True)
            base = safe_filename(player.name) or "retired_horse"
            target = retired_dir / f"{base}.json"
            n = 2
            while target.exists() and target.resolve() != save_path.resolve():
                target = retired_dir / f"{base}_{n}.json"
                n += 1
            save_game(target, st)
            print(f"(Retired horse archived: {target})")
        except Exception as e:
            print(f"(Warning: could not archive retired horse: {e})")

    # Ensure the save exists immediately after creating/loading.
    save_now(start_round)

    rounds_to_play = max(1, min(args.max_rounds, 16))
    current_round = start_round

    for _ in range(rounds_to_play):
        if sys.stdin.isatty():
            cmd = input(f"\nNext up: ROUND {current_round}. Press Enter to play, or (Q)uit: ").strip().lower()
            if cmd.startswith("q"):
                break

        print(f"\n====================\nROUND {current_round}\n====================")
        pool = build_round_pool(args.seed, current_round, sires, dams, data_dir="data", pool_size=36)

        round_earnings_start = earnings
        round_stat_start = (
            player.externals.start,
            player.externals.corner,
            player.externals.oob,
            player.externals.competing,
            player.externals.tenacious,
            player.externals.spurt,
        )
        best_finish_this_round = 99
        best_race_name = ""
        stop_after_round = False

        round_schedule = schedule[current_round - 1]
        start_race_idx = 0
        if world.current_round == current_round:
            start_race_idx = max(0, min(5, getattr(world, 'race_index', 0)))
        else:
            # Keep world aligned with the round we are about to play.
            world.current_round = current_round
            world.race_index = 0
            save_world_state(world_state_path, world)

        if start_race_idx > 0:
            print(f"(Resuming Round {current_round} at race {start_race_idx + 1}/{len(round_schedule)})")

        for race_idx, race in enumerate(round_schedule[start_race_idx:], start=start_race_idx):
            # World pointer always tracks the *next* race to run.
            world.race_index = race_idx
            # Stable, world-scoped iteration key for this specific race.
            # Keeps matchups/conditions deterministic when switching horses mid-program.
            world_iter = (world.cycle * 1000) + (current_round * 10) + race_idx
            nm = race.name or ""
            title = f"{race.slot} {nm} | {race.track} {race.distance}m {race.surface}"
            print(f"\n--- {title} ---")
            print(f"Winner purse: ${race.winner_purse:,} | Earnings: ${earnings:,} | Races: {races_run}/64")

            # quick menu
            cmd = input("Enter to continue, or (P)rofile: ").strip().lower()
            if cmd == "p":
                profile_screen(player, earnings, races_run)

            # Training
            tr_idx, grade = training_flow(args.seed, meet_iter, race, player)

            # Feeding (always)
            feeding_flow(args.seed, meet_iter, race, player, tr_idx, grade)

            # Race briefing (shown after feeding, before committing)
            print(f"\nNext race: {title}")
            condition = roll_condition(args.seed, world_iter, race.round_num, race.slot, race.surface)
            print(f"Track condition revealed: {condition}")

            band_shift = (-0.05 if streak_oom >= 5 else 0.0) + difficulty_offset

            # 1R difficulty scaling: as the player's horse becomes more successful,
            # slightly shift the 1R opponent band upward (harder field).
            # (This is the only handicapping feature that affects outcomes.)
            one_r_shift = 0.0
            one_r_wins = 0
            one_r_pct = 0.0
            if race.slot == "1R":
                one_r_shift, one_r_wins, one_r_pct = compute_1r_handicap_band_shift(player, pool.horses)
                band_shift += one_r_shift

            # G1 gate
            if race.slot == "G1" and earnings < G1_GATE:
                print(f"G1 entry requires ${G1_GATE:,}. You have ${earnings:,}.")
                q = input("Press Enter to run Gambling Chance, or (Q)uit & save: ").strip().lower()
                if q.startswith("q"):
                    save_now(current_round)
                    save_world_state(world_state_path, world)
                    print("Saved. You can load another horse and continue from this race.")
                    return
                print("Gambling Chance round (pick the winner).")
                cpu12 = select_cpu_field(args.seed, pool, "G1", world_iter, field_size=12, band_shift=band_shift)

                tmp = run_gambling_chance(args.seed, world_iter, race.round_num, race.slot, cpu12, cpu12[0].id)
                for i, h in enumerate(cpu12, start=1):
                    print(f"{i:2d}. {h.name[:26]:<26} [{h.style}] odds ~ {tmp.odds_by_horse[h.id]:.2f}")

                pick_idx = prompt_int("Pick winner (1-12): ", 1, 12) - 1
                pick_id = cpu12[pick_idx].id
                res = run_gambling_chance(args.seed, world_iter, race.round_num, race.slot, cpu12, pick_id)

                winner_name = next(h.name for h in cpu12 if h.id == res.winner_horse_id)
                picked_name = next(h.name for h in cpu12 if h.id == res.picked_horse_id)
                print(f"Winner: {winner_name} | Your pick: {picked_name}")
                if res.won:
                    print(f"You won ${res.payout:,}!")
                    earnings += res.payout
                else:
                    print("No payout.")

                # Save progress (still within the current round)
                save_now(current_round)

                # Advance global program pointer
                if race_idx >= len(round_schedule) - 1:
                    world = advance_world_round(world, 1)
                else:
                    world.race_index = race_idx + 1
                save_world_state(world_state_path, world)

                continue

            # Normal race sim
            cpu11 = select_cpu_field(args.seed, pool, race.slot, world_iter, field_size=11, band_shift=band_shift)

            # --- Horse Handicapping (informational only) ---
            # Shown after "Enter race" (and after the track condition is revealed),
            # but before results are generated.
            print("")
            if race.slot == "1R" and one_r_shift > 0.0:
                pct_txt = f"{one_r_pct*100:.0f}th" if one_r_pct > 0 else "?"
                print(
                    f"1R Handicap: field strength +{one_r_shift:.2f} "
                    f"(Wins: {one_r_wins} | Power: {pct_txt} pct)"
                )
            runners = [player] + cpu11
            gate_by_id = draw_gates(args.seed, world_iter, race, condition, runners)
            print(
                render_handicapping_table(
                    runners,
                    gate_by_id=gate_by_id,
                    race=race,
                    condition=condition,
                )
            )
            # Final confirmation (with quit+save) before results are generated.
            print(f"\nNext race: {title}")
            print(f"Track condition: {condition}")
            cmd = input("Enter race? (Enter to run, S to skip, Q to quit & save): ").strip().lower()
            if cmd.startswith("q"):
                save_now(current_round)
                save_world_state(world_state_path, world)
                print("Saved. You can load another horse and continue from this race.")
                return

            if cmd.startswith("s"):
                print("\nYou skipped this race.")
                # Advance the world pointer without changing earnings/race count.
                if race_idx + 1 < len(schedule):
                    world.pointer += 1
                    meet_iter += 1
                    save_now(current_round)
                    save_world_state(world_state_path, world)
                    continue
                # End of round / schedule.
                save_now(current_round)
                save_world_state(world_state_path, world)
                break

            # Expected rank (on paper), used for post-race commentary only
            expected_scores = {h.id: expected_score(h, race, condition, int(gate_by_id.get(h.id, 1))) for h in runners}
            expected_order = sorted(expected_scores.items(), key=lambda kv: kv[1], reverse=True)
            expected_rank = 1 + next((i for i,(hid,_) in enumerate(expected_order) if hid == player.id), len(expected_order))
            sim = run_race_sim(args.seed, world_iter, race, condition, player, cpu11, gate_by_id=gate_by_id)

            timed = timed_results(race, condition, sim.finish_order, sim.scores, records)

            # print card
            print("")
            print(render_race_card(race, condition, timed, sim.payouts_by_pos))

            # determine player's place in timed results
            player_row = next(rr for rr in timed.runners if rr.horse_id == player.id)
            pos = player_row.pos

            payout = sim.payouts_by_pos.get(pos, 0)
            print(f"\nYour finish: {pos}/12 | Time: {format_time(player_row.time_seconds)} | {player_row.lengths_behind:.1f}L | Payout: ${payout:,}")
            # Post-race insight (DOC-style hints; informational only)
            insights = race_insight_lines(args.seed, player, race, condition, expected_rank=expected_rank, actual_pos=pos, gate=int(gate_by_id.get(player.id, 1)))
            if insights:
                for msg in insights:
                    print("\nTrainer's Comment: " + msg)
            earnings += payout
            races_run += 1

            best_finish_this_round = min(best_finish_this_round, pos)
            if pos == best_finish_this_round:
                best_race_name = race.name or f"{race.slot} {race.track}"

            if pos <= 3:
                streak_oom = 0
            else:
                streak_oom += 1

            # Anti-runaway difficulty: keep the career interesting by strengthening (or easing)
            # future CPU fields based on recent performance.
            if pos == 1:
                difficulty_offset += 0.03
            elif pos == 2:
                difficulty_offset += 0.02
            elif pos == 3:
                difficulty_offset += 0.01
            elif pos >= 10:
                difficulty_offset -= 0.03
            elif pos >= 7:
                difficulty_offset -= 0.02
            elif pos >= 4:
                difficulty_offset -= 0.01

            # Clamp to keep it fair
            if difficulty_offset > 0.10:
                difficulty_offset = 0.10
            if difficulty_offset < -0.08:
                difficulty_offset = -0.08


            # Growth + G1 win tracking
            growth = apply_post_race_growth(args.seed, meet_iter, race, player, pos)
            if any(v for v in growth.values()):
                print("Internal growth:", {k:v for k,v in growth.items() if v})

            if race.slot == "G1":
                eff = apply_g1_win_rewards(player, pos)
                if eff["g1_wins_added"]:
                    print("G1 Win recorded! (A special food is guaranteed in next round's 1R feeding.)")

            # Log entry
            entry = RaceLogEntry(
                round_num=race.round_num,
                slot=race.slot,
                race_name=race.name or "",
                track=race.track,
                course_code=race.course_code,
                surface=race.surface,
                condition=condition,
                distance=race.distance,
                winner_time=timed.winner_time,
                player_pos=pos,
                player_time=player_row.time_seconds,
                player_lengths=player_row.lengths_behind,
                payout=payout,
                earnings_total_after=earnings,
                field=timed.runners
            )
            player.career_log.append(entry)

            # persist records if changed
            save_records(records_state_path, records)

            # Save progress after each race (but keep the same round number so
            # an unexpected exit doesn't skip ahead).
            save_now(current_round)

            # Advance global program pointer (race-by-race) so other horses can join mid-round.
            if race_idx >= len(round_schedule) - 1:
                world = advance_world_round(world, 1)
            else:
                world.race_index = race_idx + 1
            save_world_state(world_state_path, world)

            if races_run >= 64:
                retired_flag = True
                retired_reason = "forced_64"
                print("Reached 64 races. Forced retirement.")
                stop_after_round = True
                break

        # Round summary
        round_earnings = earnings - round_earnings_start
        round_stat_end = (player.externals.start, player.externals.corner, player.externals.oob, player.externals.competing, player.externals.tenacious, player.externals.spurt)
        delta_stats = tuple(e - s for s,e in zip(round_stat_start, round_stat_end))
        print("\n=== Round Summary ===")
        print(f"Round {current_round} earnings: ${round_earnings:,} | Best finish: {best_finish_this_round} ({best_race_name})")
        print("External changes this round:")
        deltas = {"start":delta_stats[0],"corner":delta_stats[1],"oob":delta_stats[2],"competing":delta_stats[3],"tenacious":delta_stats[4],"spurt":delta_stats[5]}
        stable_card(player, deltas)

        # Optional retirement prompt between rounds (less spammy than per-race)
        if (not retired_flag) and races_run >= 20 and sys.stdin.isatty():
            ans = input("You may retire now. Retire horse? (y/N): ").strip().lower()
            if ans.startswith("y"):
                retired_flag = True
                retired_reason = "player_choice"
                stop_after_round = True

        # Per-horse meet tick
        meet_iter += 1

        # Advance round (wrap 16 -> 1)
        next_round = current_round + 1
        if next_round > 16:
            next_round = 1

        st_final = save_now(next_round)

        # Archive retired horses for breeding
        if retired_flag:
            # Persist final career totals and ensure optional counters exist.
            player.earnings = int(earnings)
            player.races_run = int(races_run)
            if not hasattr(player, "g1_wins"):
                player.g1_wins = 0
            if not hasattr(player, "genetic_tokens"):
                player.genetic_tokens = 0

            # Update the on-disk save with retirement metadata, then archive a
            # copy into the retired pool for future breeding.
            st_final["player"] = horse_to_dict(player)
            st_final["meet_iter"] = meet_iter
            st_final["retired"] = True

            # Persist a short note & poem in the archived record
            g1_wins = int(getattr(player, "g1_wins", 0))
            st_final["retire_note"] = f"Retired at ${earnings:,} after {races_run} races. G1 wins: {g1_wins}."
            st_final["retire_poem"] = "\n".join(retirement_poem_lines(args.seed, player))

            tier_sym, tier_label = retirement_tier_label(earnings=earnings, g1_wins=g1_wins)
            st_final["retire_tier"] = f"{tier_sym} {tier_label}"

            # Archive and remove active save so the horse cannot be loaded again
            archive_retired_copy(st_final)
            try:
                if save_path.exists():
                    save_path.unlink()
            except Exception:
                pass

            retirement_screen(args.seed, player, earnings, races_run)
            return

        current_round = next_round

        if stop_after_round:
            break

    print("\n=== Career Summary ===")
    print(f"Horse: {player.name} ({player.sex}) [{player.style}] AC={player.ac}")
    print(f"Races: {races_run} | Earnings: ${earnings:,}")
    print(f"Internals ST/SP/SH: {player.internals.stamina}/{player.internals.speed}/{player.internals.sharp}")
    print("Externals:")
    stable_card(player)
    print(f"G1 wins: {player.g1_wins} | Genetic tokens: {player.genetic_tokens}")
    print(f"Save file: {save_path}")

if __name__ == "__main__":
    main()
