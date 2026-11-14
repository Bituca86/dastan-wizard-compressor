"""EMA 2/5/10 stack on an aggregated timeframe, with the same definitions as the
US30_EMA10_Virtual indicator: trend arrow (M5) and state (M2), from CLOSED bars."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import Bar


class EmaStack:
    def __init__(self, minutes: int, periods=(2, 5, 10), atr_period: int = 14, min_gap_atr: float = 0.1):
        self.minutes = minutes
        self.alpha = [2.0 / (p + 1) for p in periods]
        self.e = [None, None, None]
        self.atr_period, self.min_gap_atr = atr_period, min_gap_atr
        self._tr: list = []
        self.atr: Optional[float] = None
        self._bucket: Optional[datetime] = None
        self._h = self._l = self._c = None
        self._prev_close: Optional[float] = None
        self.bars = 0

    def update(self, b: Bar) -> None:
        """Feed M1 bars; the stack advances when an aggregated bar closes."""
        t = b.time
        bucket = t.replace(minute=t.minute - t.minute % self.minutes, second=0, microsecond=0)
        if self._bucket is not None and bucket != self._bucket:
            self._close_bar()
        if self._bucket != bucket:
            self._bucket, self._h, self._l = bucket, b.high, b.low
        else:
            self._h, self._l = max(self._h, b.high), min(self._l, b.low)
        self._c = b.close

    def _close_bar(self) -> None:
        c = self._c
        for k in range(3):
            self.e[k] = c if self.e[k] is None else self.e[k] + self.alpha[k] * (c - self.e[k])
        tr = self._h - self._l if self._prev_close is None else \
            max(self._h, self._prev_close) - min(self._l, self._prev_close)
        self._tr.append(tr)
        if len(self._tr) > self.atr_period:
            self._tr.pop(0)
        self.atr = sum(self._tr) / len(self._tr)
        self._prev_close = c
        self.bars += 1

    @property
    def ready(self) -> bool:
        return self.bars >= 30

    def trend(self) -> int:
        """+1: EMA2 > EMA5 > EMA10 with gaps >= min_gap_atr x ATR · -1: reversed · 0: lateral."""
        if not self.ready:
            return 0
        g = self.min_gap_atr * (self.atr or 0.0)
        a, b = self.e[0] - self.e[1], self.e[1] - self.e[2]
        return 1 if (a > 0 and b > 0 and a >= g and b >= g) else -1 if (a < 0 and b < 0 and a <= -g and b <= -g) else 0

    def state(self) -> int:
        """+1: EMA2 above EMA5 and EMA10 (BUY) · -1: below both (SELL) · 0: between them (stop / trend change)."""
        if not self.ready:
            return 0
        return 1 if (self.e[0] > self.e[1] and self.e[0] > self.e[2]) else \
            -1 if (self.e[0] < self.e[1] and self.e[0] < self.e[2]) else 0
