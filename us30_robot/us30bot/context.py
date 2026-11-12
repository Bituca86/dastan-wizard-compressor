"""MarketState: one incremental object holding everything detectors need.

Liquidity (EQH/EQL, PDH/PDL, session extremes), zones (FVG, OB, breaker),
premium/discount and session labelling for US30 (Dow Jones CFD).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Dict, List, Optional, Tuple

from .models import BUY, SELL, Bar, Zone
from .structure import ATR, StructureTracker, ZigZag


@dataclass
class SessionClock:
    """Session boundaries in UTC (defaults = US winter time; shift by 1h in summer)."""

    asia: Tuple[time, time] = (time(0, 0), time(7, 0))
    london: Tuple[time, time] = (time(7, 0), time(13, 30))
    ny_open: Tuple[time, time] = (time(14, 30), time(16, 0))  # cash open 9:30 ET
    ny: Tuple[time, time] = (time(16, 0), time(21, 0))

    def label(self, t: time) -> str:
        for name in ("asia", "london", "ny_open", "ny"):
            a, b = getattr(self, name)
            if a <= t < b:
                return name
        return "off"


class MarketState:
    def __init__(self, clock: Optional[SessionClock] = None, zz_mult: float = 1.5,
                 max_zones: int = 40):
        self.bars: List[Bar] = []
        self.atr = ATR(14)
        self.zz = ZigZag(atr_mult=zz_mult)
        self.structure = StructureTracker()
        self.clock = clock or SessionClock()
        self.zones: List[Zone] = []
        self.max_zones = max_zones
        self.events: Dict[str, int] = {}  # last index of event type
        # day / session liquidity
        self._day: Optional[date] = None
        self.day_high = self.day_low = None
        self.pdh: Optional[float] = None
        self.pdl: Optional[float] = None
        self.session = "off"
        self.session_hl: Dict[str, Tuple[float, float]] = {}
        self.prev_session_hl: Dict[str, Tuple[float, float]] = {}

    # ------------------------------------------------------------------
    @property
    def i(self) -> int:
        return len(self.bars) - 1

    @property
    def bar(self) -> Bar:
        return self.bars[-1]

    @property
    def atr_v(self) -> float:
        return self.atr.value or max(1.0, self.bar.range)

    def update(self, bar: Bar) -> None:
        self.bars.append(bar)
        i = self.i
        self.atr.update(bar)
        self._update_day_session(bar)
        self.zz.update(i, bar, self.atr.value)
        ev = self.structure.update(i, bar, self.zz)
        if ev:
            self.events[ev] = i
            self._mark_order_block(ev)
        if self.is_displacement(i):
            self.events["DISPLACEMENT_UP" if bar.bullish else "DISPLACEMENT_DN"] = i
        self._detect_fvg()
        self._mitigate_zones(bar)
        if len(self.bars) > 5000:  # bounded memory for live running
            self._trim()

    # ------------------------------------------------------------------
    def _trim(self) -> None:
        # keep indexes stable by never removing; just drop very old zones
        self.zones = [z for z in self.zones if self.i - z.created < 2000]

    def _update_day_session(self, bar: Bar) -> None:
        d = bar.time.date()
        if self._day != d:
            if self._day is not None:
                self.pdh, self.pdl = self.day_high, self.day_low
            self._day, self.day_high, self.day_low = d, bar.high, bar.low
        else:
            self.day_high = max(self.day_high, bar.high)
            self.day_low = min(self.day_low, bar.low)
        s = self.clock.label(bar.time.time())
        if s != self.session:
            if self.session in self.session_hl:
                self.prev_session_hl[self.session] = self.session_hl[self.session]
            self.session = s
            self.session_hl[s] = (bar.high, bar.low)
        else:
            h, l = self.session_hl[s]
            self.session_hl[s] = (max(h, bar.high), min(l, bar.low))

    def is_displacement(self, i: int, mult: float = 1.8) -> bool:
        b = self.bars[i]
        return b.range >= mult * self.atr_v and b.body >= 0.6 * b.range

    def _detect_fvg(self) -> None:
        if len(self.bars) < 3:
            return
        a, b, c = self.bars[-3], self.bars[-2], self.bars[-1]
        min_gap = 0.15 * self.atr_v
        if c.low - a.high > min_gap and b.bullish:
            self._add_zone(Zone("FVG", BUY, c.low, a.high, self.i))
        elif a.low - c.high > min_gap and not b.bullish:
            self._add_zone(Zone("FVG", SELL, a.low, c.high, self.i))

    def _mark_order_block(self, event: str) -> None:
        """OB = last opposite-colour candle before the impulse that broke structure."""
        up = event.endswith("UP")
        for j in range(self.i - 1, max(-1, self.i - 30), -1):
            b = self.bars[j]
            if up and not b.bullish:
                self._add_zone(Zone("OB", BUY, b.high, b.low, j))
                return
            if not up and b.bullish:
                self._add_zone(Zone("OB", SELL, b.high, b.low, j))
                return

    def _add_zone(self, z: Zone) -> None:
        self.zones.append(z)
        if len(self.zones) > self.max_zones:
            self.zones.pop(0)

    def _mitigate_zones(self, bar: Bar) -> None:
        for z in self.zones:
            if z.mitigated or z.created >= self.i:
                continue
            # a close through an OB flips it into a breaker block
            if z.kind == "OB":
                if z.side == BUY and bar.close < z.bottom:
                    z.kind, z.side = "BREAKER", SELL
                    continue
                if z.side == SELL and bar.close > z.top:
                    z.kind, z.side = "BREAKER", BUY
                    continue
            if z.kind == "FVG":
                if (z.side == BUY and bar.low <= z.bottom) or (z.side == SELL and bar.high >= z.top):
                    z.mitigated = True

    # ------------------------------------------------------------------
    def active_zones(self, kind: Optional[str] = None, side: Optional[str] = None) -> List[Zone]:
        return [z for z in self.zones if not z.mitigated and (kind is None or z.kind == kind)
                and (side is None or z.side == side)]

    def zone_touch(self, side: str, kinds=("OB", "FVG", "BREAKER")) -> Optional[Zone]:
        b = self.bar
        for z in reversed(self.zones):
            if z.mitigated or z.side != side or z.kind not in kinds or z.created >= self.i - 1:
                continue
            if side == BUY and b.low <= z.top and b.close >= z.bottom:
                return z
            if side == SELL and b.high >= z.bottom and b.close <= z.top:
                return z
        return None

    def dealing_range(self) -> Optional[Tuple[float, float]]:
        hs = [s.price for s in self.zz.swings[-6:] if s.kind == "H"]
        ls = [s.price for s in self.zz.swings[-6:] if s.kind == "L"]
        if not hs or not ls:
            return None
        return max(hs), min(ls)

    def premium_discount(self) -> str:
        dr = self.dealing_range()
        if not dr:
            return "eq"
        hi, lo = dr
        if hi - lo <= 0:
            return "eq"
        pos = (self.bar.close - lo) / (hi - lo)
        return "premium" if pos > 0.55 else "discount" if pos < 0.45 else "eq"

    def equal_levels(self, kind: str, tol_atr: float = 0.25, lookback: int = 8):
        """Return (price, count) of the most recent equal highs/lows cluster."""
        sw = [s for s in self.zz.swings[-lookback:] if s.kind == kind]
        tol = tol_atr * self.atr_v
        best = None
        for a in range(len(sw)):
            group = [s for s in sw[a:] if abs(s.price - sw[a].price) <= tol]
            if len(group) >= 2 and (best is None or len(group) >= best[1]):
                best = (sum(g.price for g in group) / len(group), len(group))
        return best

    def liquidity_levels(self, side: str) -> List[Tuple[str, float]]:
        """External liquidity pools: SELL side = highs above (buy-stops), BUY side = lows below."""
        out: List[Tuple[str, float]] = []
        if side == SELL:
            if self.pdh: out.append(("PDH", self.pdh))
            for s, (h, _) in self.prev_session_hl.items(): out.append((f"{s}_high", h))
            eq = self.equal_levels("H")
            if eq: out.append(("EQH", eq[0]))
        else:
            if self.pdl: out.append(("PDL", self.pdl))
            for s, (_, l) in self.prev_session_hl.items(): out.append((f"{s}_low", l))
            eq = self.equal_levels("L")
            if eq: out.append(("EQL", eq[0]))
        return out

    def recent(self, event: str, within: int) -> bool:
        return event in self.events and self.i - self.events[event] <= within
