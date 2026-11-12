"""Forward evaluation of every detection / signal: confirmation vs. invalidation.

For each tracked item we follow price bar-by-bar until stop, target or timeout,
recording MFE/MAE and the outcome at several alternative reward:risk targets.
A Romanian post-mortem verdict explains *why* the setup was confirmed or failed,
which is also turned into learning signal (see Engine._learn).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .learner import RR_GRID
from .models import BUY, Bar, Outcome


@dataclass
class Tracked:
    key: int
    direction: str
    entry: float
    stop: float
    target: float
    start: int
    payload: dict = field(default_factory=dict)
    mfe: float = 0.0
    mae: float = 0.0
    alt: Dict[float, Optional[bool]] = field(default_factory=dict)
    done: bool = False
    result: Optional[str] = None
    exit_price: Optional[float] = None
    stop_wick_then_target: bool = False  # stop hit, but price later reached target

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)


class Evaluator:
    def __init__(self, timeout_bars: int = 60, post_bars: int = 30, cost_r: float = 0.05):
        self.timeout = timeout_bars
        self.post = post_bars  # keep watching after stop to detect "stop hunted" failures
        self.cost_r = cost_r  # spread+commission expressed in R
        self.open: List[Tracked] = []
        self.on_close: List[Callable[[Tracked, Outcome], None]] = []

    def track(self, t: Tracked) -> None:
        t.alt = {rr: None for rr in RR_GRID}
        self.open.append(t)

    def update(self, i: int, bar: Bar) -> None:
        keep = []
        for t in self.open:
            if i <= t.start:
                keep.append(t)
                continue
            if not t.done:
                self._step(t, i, bar)
            else:
                # post-mortem window after a loss
                fav = bar.high >= t.target if t.direction == BUY else bar.low <= t.target
                if fav:
                    t.stop_wick_then_target = True
            if t.done and (t.result != "LOSS" or i - t.payload["closed_at"] >= self.post
                           or t.stop_wick_then_target):
                self._emit(t, i)
            else:
                keep.append(t)
        self.open = keep

    def _step(self, t: Tracked, i: int, bar: Bar) -> None:
        sgn = 1 if t.direction == BUY else -1
        r = t.risk
        fav = (bar.high - t.entry) if sgn > 0 else (t.entry - bar.low)
        adv = (t.entry - bar.low) if sgn > 0 else (bar.high - t.entry)
        t.mfe = max(t.mfe, fav / r)
        t.mae = max(t.mae, adv / r)
        stop_hit = adv >= r
        # alternative targets (conservative: if stop hit in same bar -> loss)
        for rr in RR_GRID:
            if t.alt[rr] is None:
                if stop_hit:
                    t.alt[rr] = False
                elif fav >= rr * r:
                    t.alt[rr] = True
        tgt_hit = (bar.high >= t.target) if sgn > 0 else (bar.low <= t.target)
        if stop_hit:
            t.done, t.result, t.exit_price = True, "LOSS", t.stop
        elif tgt_hit:
            t.done, t.result, t.exit_price = True, "WIN", t.target
        elif i - t.start >= self.timeout:
            t.done, t.result, t.exit_price = True, "TIMEOUT", bar.close
            for rr in RR_GRID:
                if t.alt[rr] is None:
                    t.alt[rr] = False
        if t.done:
            t.payload["closed_at"] = i
            t.payload["bars_held"] = i - t.start

    def _emit(self, t: Tracked, i: int) -> None:
        sgn = 1 if t.direction == BUY else -1
        r_mult = sgn * (t.exit_price - t.entry) / t.risk - t.payload.get("cost_r", self.cost_r)
        out = Outcome(t.key, t.result, r_mult, t.payload.get("bars_held", i - t.start), t.mfe, t.mae,
                      verdict(t, r_mult), t.exit_price)
        for cb in self.on_close:
            cb(t, out)


def verdict(t: Tracked, r_mult: float) -> str:
    if t.result == "WIN":
        if t.mae < 0.3:
            return "CONFIRMAT curat: prețul a plecat imediat în direcția patternului (intrare precisă)."
        return (f"CONFIRMAT după presiune adversă de {t.mae:.1f}R: patternul a funcționat, "
                f"dar intrarea putea fi rafinată.")
    if t.result == "TIMEOUT":
        return (f"NECONFIRMAT (timeout): fără follow-through, MFE {t.mfe:.1f}R -> "
                f"lipsă de momentum / sesiune lentă.")
    if t.stop_wick_then_target:
        return ("INFIRMAT, dar direcția era corectă: stop-ul a fost vânat și apoi ținta atinsă -> "
                "stop prea strâns sau intrare prematură (lichiditate nevânată încă).")
    if t.mfe >= 1.0:
        return (f"INFIRMAT după {t.mfe:.1f}R în profit: ținta prea ambițioasă -> "
                f"învățare: ținte mai apropiate / break-even.")
    return "INFIRMAT direct: patternul a eșuat (context contrar sau lichiditate opusă mai puternică)."
