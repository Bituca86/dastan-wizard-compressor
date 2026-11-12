"""Incremental market-structure primitives: ATR, ZigZag swings, HH/HL/LH/LL, BOS/CHOCH."""
from __future__ import annotations

from typing import List, Optional

from .models import Bar, Swing


class ATR:
    def __init__(self, period: int = 14):
        self.period = period
        self.value: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._seed: List[float] = []

    def update(self, bar: Bar) -> Optional[float]:
        if self._prev_close is None:
            tr = bar.range
        else:
            tr = max(bar.high, self._prev_close) - min(bar.low, self._prev_close)
        self._prev_close = bar.close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) >= self.period:
                self.value = sum(self._seed) / len(self._seed)
            return self.value
        self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value


class ZigZag:
    """Swing detector: a swing is confirmed once price reverses by `mult * ATR`.

    Using an ATR-scaled threshold (instead of fixed points) keeps detection
    stable across US30 volatility regimes (Asia ~10pt ranges vs NY open ~80pt).
    """

    def __init__(self, atr_mult: float = 1.5, min_points: float = 4.0):
        self.atr_mult = atr_mult
        self.min_points = min_points
        self.swings: List[Swing] = []
        self._dir = 0  # +1 looking for high, -1 looking for low
        self._ext_price: Optional[float] = None
        self._ext_index = 0

    def _threshold(self, atr: Optional[float]) -> float:
        return max(self.min_points, (atr or 0.0) * self.atr_mult)

    def update(self, i: int, bar: Bar, atr: Optional[float]) -> Optional[Swing]:
        th = self._threshold(atr)
        if self._ext_price is None:
            self._ext_price, self._ext_index, self._dir = bar.high, i, 1
            return None
        if self._dir == 1:
            if bar.high >= self._ext_price:
                self._ext_price, self._ext_index = bar.high, i
            elif self._ext_price - bar.low >= th:
                sw = self._confirm(self._ext_index, self._ext_price, "H")
                self._dir, self._ext_price, self._ext_index = -1, bar.low, i
                return sw
        else:
            if bar.low <= self._ext_price:
                self._ext_price, self._ext_index = bar.low, i
            elif bar.high - self._ext_price >= th:
                sw = self._confirm(self._ext_index, self._ext_price, "L")
                self._dir, self._ext_price, self._ext_index = 1, bar.high, i
                return sw
        return None

    def _confirm(self, index: int, price: float, kind: str) -> Swing:
        prev = next((s for s in reversed(self.swings) if s.kind == kind), None)
        label = ""
        if prev is not None:
            if kind == "H":
                label = "HH" if price > prev.price else "LH"
            else:
                label = "HL" if price > prev.price else "LL"
        sw = Swing(index, price, kind, label)
        self.swings.append(sw)
        if len(self.swings) > 600:  # bounded memory/CPU for weeks of live running
            del self.swings[:100]
        return sw

    # helpers -------------------------------------------------------------
    def last(self, n: int) -> List[Swing]:
        return self.swings[-n:] if len(self.swings) >= n else []

    def last_of(self, kind: str, skip: int = 0) -> Optional[Swing]:
        for s in reversed(self.swings):
            if s.kind == kind:
                if skip == 0:
                    return s
                skip -= 1
        return None


class StructureTracker:
    """Tracks trend and emits BOS / CHOCH events on candle *close* beyond swings."""

    def __init__(self):
        self.trend = 0  # +1 bullish, -1 bearish, 0 unknown
        self.last_event: Optional[str] = None  # "BOS_UP", "BOS_DN", "CHOCH_UP", "CHOCH_DN"
        self.last_event_index = -1
        self._broken_high: Optional[int] = None
        self._broken_low: Optional[int] = None

    def update(self, i: int, bar: Bar, zz: ZigZag) -> Optional[str]:
        hi = zz.last_of("H")
        lo = zz.last_of("L")
        event = None
        if hi and bar.close > hi.price and self._broken_high != hi.index:
            self._broken_high = hi.index
            event = "BOS_UP" if self.trend >= 0 else "CHOCH_UP"
            self.trend = 1
        elif lo and bar.close < lo.price and self._broken_low != lo.index:
            self._broken_low = lo.index
            event = "BOS_DN" if self.trend <= 0 else "CHOCH_DN"
            self.trend = -1
        if event:
            self.last_event, self.last_event_index = event, i
        return event
