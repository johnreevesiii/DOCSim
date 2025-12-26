from __future__ import annotations
from typing import Dict

def _round_amt(x: float, unit: int, mode: str) -> int:
    if unit <= 1:
        return int(round(x))
    if mode == "floor":
        return int(x // unit * unit)
    if mode == "ceil":
        return int(-(-x // unit) * unit)
    return int(round(x / unit) * unit)

def purse_payouts_top3(winner_purse: int, round_unit: int = 10_000, rounding_mode: str = "nearest") -> Dict[int, int]:
    payouts = {pos: 0 for pos in range(1, 13)}
    payouts[1] = int(winner_purse)
    payouts[2] = _round_amt(winner_purse / 3.0, round_unit, rounding_mode)
    payouts[3] = _round_amt(winner_purse / 6.0, round_unit, rounding_mode)
    payouts[2] = max(payouts[2], payouts[3])
    payouts[3] = max(0, payouts[3])
    return payouts
