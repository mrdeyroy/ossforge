"""Tiny before/after harness so any `perf:` claim ships with numbers (Agent.md quality bar)."""

from __future__ import annotations

import statistics
import timeit
from collections.abc import Callable


def compare(old: Callable[[], object], new: Callable[[], object], repeat: int = 7, number: int = 200) -> dict:
    if old() != new():
        raise ValueError("old and new return different results: not a valid optimisation")
    o = [t / number for t in timeit.repeat(old, repeat=repeat, number=number)]
    n = [t / number for t in timeit.repeat(new, repeat=repeat, number=number)]
    mo, mn = statistics.median(o), statistics.median(n)
    return {"old_s": mo, "new_s": mn, "speedup": mo / mn if mn else float("inf")}


def markdown(label: str, r: dict) -> str:
    return (f"Benchmark ({label}, median of runs): old {r['old_s']*1e6:.1f} us, "
            f"new {r['new_s']*1e6:.1f} us, speedup x{r['speedup']:.2f}")
