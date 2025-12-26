from __future__ import annotations
import hashlib, random
from dataclasses import dataclass
from typing import Any, List, Sequence, TypeVar

T = TypeVar("T")

def hash64(*parts: Any) -> int:
    h = hashlib.blake2b(digest_size=8)
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return int.from_bytes(h.digest(), "big", signed=False)

@dataclass
class RNG:
    seed: int
    _r: random.Random = None  # type: ignore

    def __post_init__(self) -> None:
        self._r = random.Random(self.seed)

    def random(self) -> float:
        return self._r.random()

    def randint(self, a: int, b: int) -> int:
        return self._r.randint(a, b)

    def choice(self, seq: Sequence[T]) -> T:
        return self._r.choice(seq)

    def shuffle(self, items: List[T]) -> None:
        self._r.shuffle(items)

    def sample(self, seq: Sequence[T], k: int) -> List[T]:
        return self._r.sample(list(seq), k)

    def gauss(self, mu: float, sigma: float) -> float:
        return self._r.gauss(mu, sigma)

    def tri_centered(self) -> float:
        # approx triangular centered at 0 in [-1.5, +1.5]
        return (self.random() + self.random() + self.random()) - 1.5
