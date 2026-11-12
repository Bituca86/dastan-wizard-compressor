"""MarketState: one incremental object holding everything detectors need.

Liquidity (EQH/EQL, PDH/PDL, PWH/PWL, session extremes), zones (FVG, OB, breaker,
mitigation, supply/demand, liquidity void, unfilled wick, volume imbalance),
DST-aware sessions, premium/discount, range & trendline geometry helpers.
All times are UTC.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .models import BUY, SELL, Bar, Swing, Zone
from .structure import ATR, StructureTracker, ZigZag


# ---------------------------------------------------------------------------
# DST helpers (no external tz database needed -> works on Windows too)
# ---------------------------------------------------------------------------
def _nth_sunday(y: int, m: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_sunday(y: int, m: int) -> date:
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def us_dst(d: date) -> bool:
    return _nth_sunday(d.year, 3, 2) <= d < _nth_sunday(d.year, 11, 1)


def eu_dst(d: date) -> bool:
    return _last_sunday(d.year, 3) <= d < _last_sunday(d.year, 10)


def et_hour(t: datetime) -> float:
    """New York local time (decimal hours) for a UTC datetime."""
    off = 4 if us_dst(t.date()) else 5
    lt = t - timedelta(hours=off)
    return lt.hour + lt.minute / 60


def uk_hour(t: datetime) -> float:
    lt = t + timedelta(hours=1 if eu_dst(t.date()) else 0)
    return lt.hour + lt.minute / 60


@dataclass
class SessionClock:
    """Sessions defined in their *local* exchange time, converted with DST rules.

    asia    : 00:00-07:00 UTC (Tokyo/Sydney, no DST)
    london  : 08:00 London -> NY cash open
    ny_open : 09:30-11:00 New York (NYSE cash open, US30 highest volatility)
    ny      : 11:00-16:00 New York
    off     : everything else (incl. NY after-hours)
    """

    news_minutes_et: Tuple[float, ...] = (8.5, 10.0, 14.0)  # 08:30 data, 10:00 data, 14:00 FOMC

    def label(self, t: datetime) -> str:
        et = et_hour(t)
        if 9.5 <= et < 11.0:
            return "ny_open"
        if 11.0 <= et < 16.0:
            return "ny"
        if 8.0 <= uk_hour(t) and et < 9.5:
            return "london"
        h = t.hour + t.minute / 60
        if h < 7.0:
            return "asia"
        return "off"

    def nyse_open(self, t: datetime) -> bool:
        return 9.5 <= et_hour(t) < 16.0 and t.weekday() < 5

    def is_news_minute(self, t: datetime, window_min: int = 3) -> bool:
        et = et_hour(t)
        return any(0 <= (et - n) * 60 < window_min for n in self.news_minutes_et)


@dataclass
class SpreadModel:
    """ICMarkets cTrader US30: ~0.7 pt during NYSE session, ~1.2 pt otherwise.
    A live spread reported by the broker always overrides the model."""

    nyse: float = 0.7
    other: float = 1.2
    commission_pts: float = 0.0
    clock: SessionClock = field(default_factory=SessionClock)

    def cost(self, t: datetime, live: Optional[float] = None) -> float:
        base = live if live is not None else (self.nyse if self.clock.nyse_open(t) else self.other)
        return base + self.commission_pts


# ---------------------------------------------------------------------------
class MarketState:
    def __init__(self, clock: Optional[SessionClock] = None, zz_mult: float = 1.5,
                 max_zones: int = 60):
        self.bars: List[Bar] = []
        self.atr = ATR(14)
        self.zz = ZigZag(atr_mult=zz_mult)
        self.structure = StructureTracker()
        self.clock = clock or SessionClock()
        self.zones: List[Zone] = []
        self.max_zones = max_zones
        self.events: Dict[str, int] = {}
        self.memory: Dict[str, object] = {}  # detector scratch space (setups awaiting trigger)
        self.htf: Optional["MarketState"] = None  # attached by the engine
        self.live_spread: Optional[float] = None
        # day / week / session liquidity
        self._day: Optional[date] = None
        self.day_high = self.day_low = None
        self.pdh: Optional[float] = None
        self.pdl: Optional[float] = None
        self._week: Optional[Tuple[int, int]] = None
        self.week_high = self.week_low = None
        self.pwh: Optional[float] = None
        self.pwl: Optional[float] = None
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
    def prev(self) -> Bar:
        return self.bars[-2] if len(self.bars) > 1 else self.bars[-1]

    @property
    def atr_v(self) -> float:
        return self.atr.value or max(1.0, self.bar.range)

    def update(self, bar: Bar) -> None:
        self.bars.append(bar)
        i = self.i
        self.atr.update(bar)
        self._update_periods(bar)
        self.zz.update(i, bar, self.atr.value)
        ev = self.structure.update(i, bar, self.zz)
        if ev:
            self.events[ev] = i
            self._mark_order_block(ev)
        if self.is_displacement(i):
            self.events["DISPLACEMENT_UP" if bar.bullish else "DISPLACEMENT_DN"] = i
            self._mark_base_zone()
            self._mark_void()
        self._detect_fvg()
        self._detect_volume_imbalance()
        self._detect_wick()
        self._mitigate_zones(bar)

    # ------------------------------------------------------------------ periods
    def _update_periods(self, bar: Bar) -> None:
        d = bar.time.date()
        if self._day != d:
            if self._day is not None:
                self.pdh, self.pdl = self.day_high, self.day_low
            self._day, self.day_high, self.day_low = d, bar.high, bar.low
        else:
            self.day_high = max(self.day_high, bar.high)
            self.day_low = min(self.day_low, bar.low)
        wk = tuple(bar.time.isocalendar()[:2])
        if self._week != wk:
            if self._week is not None:
                self.pwh, self.pwl = self.week_high, self.week_low
            self._week, self.week_high, self.week_low = wk, bar.high, bar.low
        else:
            self.week_high = max(self.week_high, bar.high)
            self.week_low = min(self.week_low, bar.low)
        s = self.clock.label(bar.time)
        if s != self.session:
            if self.session in self.session_hl:
                self.prev_session_hl[self.session] = self.session_hl[self.session]
            self.session = s
            self.session_hl[s] = (bar.high, bar.low)
        else:
            h, l = self.session_hl[s]
            self.session_hl[s] = (max(h, bar.high), min(l, bar.low))

    # ------------------------------------------------------------------ zones
    def is_displacement(self, i: int, mult: float = 1.8) -> bool:
        b = self.bars[i]
        return b.range >= mult * self.atr_v and b.body >= 0.6 * b.range

    def _add_zone(self, z: Zone) -> None:
        self.zones.append(z)
        if len(self.zones) > self.max_zones:
            self.zones.pop(0)

    def _detect_fvg(self) -> None:
        if len(self.bars) < 3:
            return
        a, b, c = self.bars[-3], self.bars[-2], self.bars[-1]
        min_gap = 0.15 * self.atr_v
        if c.low - a.high > min_gap and b.bullish:
            self._add_zone(Zone("FVG", BUY, c.low, a.high, self.i))
        elif a.low - c.high > min_gap and not b.bullish:
            self._add_zone(Zone("FVG", SELL, a.low, c.high, self.i))

    def _detect_volume_imbalance(self) -> None:
        """Bodies don't overlap but wicks do (gap between consecutive bodies)."""
        if len(self.bars) < 2:
            return
        a, b = self.prev, self.bar
        gap = 0.1 * self.atr_v
        if a.bullish and b.bullish and b.open - a.close > gap and b.low <= a.high:
            self._add_zone(Zone("VI", BUY, b.open, a.close, self.i))
        elif not a.bullish and not b.bullish and a.close - b.open > gap and b.high >= a.low:
            self._add_zone(Zone("VI", SELL, a.close, b.open, self.i))

    def _detect_wick(self) -> None:
        b = self.bar
        if b.range < 1.5 * self.atr_v:
            return
        lw = min(b.open, b.close) - b.low
        uw = b.high - max(b.open, b.close)
        if lw >= 0.6 * b.range:
            self._add_zone(Zone("WICK", BUY, min(b.open, b.close) - lw * 0.5, b.low, self.i))
        elif uw >= 0.6 * b.range:
            self._add_zone(Zone("WICK", SELL, b.high, max(b.open, b.close) + uw * 0.5, self.i))

    def _mark_base_zone(self) -> None:
        """Supply/Demand: the small-range base candles right before a displacement."""
        b = self.bar
        base = []
        for j in range(self.i - 1, max(-1, self.i - 5), -1):
            x = self.bars[j]
            if x.range <= 0.8 * self.atr_v:
                base.append(x)
            else:
                break
        if not base:
            return
        hi = max(x.high for x in base)
        lo = min(x.low for x in base)
        self._add_zone(Zone("DEMAND" if b.bullish else "SUPPLY", BUY if b.bullish else SELL, hi, lo,
                            self.i - len(base)))

    def _mark_void(self) -> None:
        b = self.bar
        if b.range >= 2.5 * self.atr_v:
            self._add_zone(Zone("VOID", BUY if b.bullish else SELL, max(b.open, b.close),
                                min(b.open, b.close), self.i))

    def _mark_order_block(self, event: str) -> None:
        """OB = last opposite candle before the impulse that broke structure.
        If the opposite swing before the break was a *failure* swing (HL for a
        down-break / LH for an up-break, i.e. no liquidity taken) we also mark a
        MITIGATION block at that failed swing."""
        up = event.endswith("UP")
        for j in range(self.i - 1, max(-1, self.i - 30), -1):
            b = self.bars[j]
            if up and not b.bullish:
                self._add_zone(Zone("OB", BUY, b.high, b.low, j))
                break
            if not up and b.bullish:
                self._add_zone(Zone("OB", SELL, b.high, b.low, j))
                break
        failed = self.zz.last_of("L" if up else "H")
        if failed and failed.label == ("HL" if up else "LH"):
            fb = self.bars[failed.index]
            self._add_zone(Zone("MITIGATION", BUY if up else SELL, fb.high, fb.low, failed.index))

    def _mitigate_zones(self, bar: Bar) -> None:
        for z in self.zones:
            if z.mitigated or z.created >= self.i:
                continue
            if z.kind == "OB":
                if z.side == BUY and bar.close < z.bottom:
                    z.kind, z.side = "BREAKER", SELL
                    continue
                if z.side == SELL and bar.close > z.top:
                    z.kind, z.side = "BREAKER", BUY
                    continue
            if (z.side == BUY and bar.close < z.bottom - 0.1 * self.atr_v) or \
                    (z.side == SELL and bar.close > z.top + 0.1 * self.atr_v):
                z.mitigated = True  # zone invalidated by a close through it
            elif z.kind in ("FVG", "VI", "VOID"):
                if (z.side == BUY and bar.low <= z.bottom) or (z.side == SELL and bar.high >= z.top):
                    z.mitigated = True

    # ------------------------------------------------------------------ queries
    def active_zones(self, kind: Optional[str] = None, side: Optional[str] = None) -> List[Zone]:
        return [z for z in self.zones if not z.mitigated and (kind is None or z.kind == kind)
                and (side is None or z.side == side)]

    def zone_touch(self, side: str, kinds=("OB", "FVG", "BREAKER"), min_age: int = 2) -> Optional[Zone]:
        b = self.bar
        for z in reversed(self.zones):
            if z.mitigated or z.side != side or z.kind not in kinds or z.created > self.i - min_age:
                continue
            if side == BUY and b.low <= z.top and b.close >= z.bottom:
                return z
            if side == SELL and b.high >= z.bottom and b.close <= z.top:
                return z
        return None

    def rejection(self, side: str) -> bool:
        b = self.bar
        if side == BUY:
            return b.close > b.open and (b.close - b.low) >= 0.6 * b.range
        return b.close < b.open and (b.high - b.close) >= 0.6 * b.range

    def dealing_range(self) -> Optional[Tuple[float, float]]:
        hs = [s.price for s in self.zz.swings[-6:] if s.kind == "H"]
        ls = [s.price for s in self.zz.swings[-6:] if s.kind == "L"]
        if not hs or not ls:
            return None
        return max(hs), min(ls)

    def range_position(self) -> Optional[float]:
        dr = self.dealing_range()
        if not dr or dr[0] - dr[1] <= 0:
            return None
        return (self.bar.close - dr[1]) / (dr[0] - dr[1])

    def premium_discount(self) -> str:
        pos = self.range_position()
        if pos is None:
            return "eq"
        return "premium" if pos > 0.55 else "discount" if pos < 0.45 else "eq"

    def equal_levels(self, kind: str, tol_atr: float = 0.25, lookback: int = 10):
        """(price, count) of the most populated recent equal highs/lows cluster."""
        sw = [s for s in self.zz.swings[-lookback:] if s.kind == kind]
        tol = tol_atr * self.atr_v
        best = None
        for a in range(len(sw)):
            group = [s for s in sw[a:] if abs(s.price - sw[a].price) <= tol]
            if len(group) >= 2 and (best is None or len(group) >= best[1]):
                best = (sum(g.price for g in group) / len(group), len(group))
        return best

    def find_range(self, lookback: int = 8, max_atr: float = 8.0, tol_atr: float = 0.4):
        """Horizontal range from recent swings: (hi, lo, touches_hi, touches_lo, start_index)."""
        sw = self.zz.swings[-lookback:]
        if len(sw) < 4:
            return None
        hi = max(s.price for s in sw if s.kind == "H") if any(s.kind == "H" for s in sw) else None
        lo = min(s.price for s in sw if s.kind == "L") if any(s.kind == "L" for s in sw) else None
        if hi is None or lo is None or hi - lo > max_atr * self.atr_v or hi <= lo:
            return None
        tol = tol_atr * self.atr_v
        th = sum(1 for s in sw if s.kind == "H" and hi - s.price <= tol)
        tl = sum(1 for s in sw if s.kind == "L" and s.price - lo <= tol)
        if th < 2 or tl < 2:
            return None
        return hi, lo, th, tl, sw[0].index

    def liquidity_levels(self, side: str) -> List[Tuple[str, float]]:
        """External liquidity: SELL side = highs above (buy-stops), BUY side = lows below."""
        out: List[Tuple[str, float]] = []
        hi_side = side == SELL
        if hi_side:
            if self.pdh: out.append(("PDH", self.pdh))
            if self.pwh: out.append(("PWH", self.pwh))
            for s, (h, _) in self.prev_session_hl.items(): out.append((f"{s}_high", h))
        else:
            if self.pdl: out.append(("PDL", self.pdl))
            if self.pwl: out.append(("PWL", self.pwl))
            for s, (_, l) in self.prev_session_hl.items(): out.append((f"{s}_low", l))
        eq = self.equal_levels("H" if hi_side else "L")
        if eq:
            out.append(("POOL" if eq[1] >= 3 else ("EQH" if hi_side else "EQL"), eq[0]))
        rg = self.find_range()
        if rg:
            out.append(("range_high", rg[0]) if hi_side else ("range_low", rg[1]))
        return out

    def recent(self, event: str, within: int) -> bool:
        return event in self.events and self.i - self.events[event] <= within

    def swings_since(self, index: int) -> List[Swing]:
        return [s for s in self.zz.swings if s.index >= index]


# ---------------------------------------------------------------------------
# geometry helpers used by the chart-pattern detectors
# ---------------------------------------------------------------------------
def fit_line(points: List[Tuple[int, float]]) -> Optional[Tuple[float, float, float]]:
    """Least squares line through (index, price). Returns (slope, intercept, max_abs_residual)."""
    n = len(points)
    if n < 2:
        return None
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points)
    if sxx == 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in points) / sxx
    icpt = my - slope * mx
    res = max(abs(p[1] - (slope * p[0] + icpt)) for p in points)
    return slope, icpt, res


def fit_quadratic(ys: List[float]) -> Optional[Tuple[float, float, float, float]]:
    """y = a x^2 + b x + c over x = 0..n-1; returns (a, b, c, r2)."""
    n = len(ys)
    if n < 5:
        return None
    xs = list(range(n))
    s = [sum(x ** k for x in xs) for k in range(5)]
    t = [sum((x ** k) * y for x, y in zip(xs, ys)) for k in range(3)]
    # normal equations 3x3
    m = [[s[4], s[3], s[2], t[2]], [s[3], s[2], s[1], t[1]], [s[2], s[1], s[0], t[0]]]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        if abs(m[col][col]) < 1e-12:
            return None
        for r in range(3):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [a - f * b for a, b in zip(m[r], m[col])]
    a, b, c = (m[k][3] / m[k][k] for k in range(3))
    my = sum(ys) / n
    ss_tot = sum((y - my) ** 2 for y in ys) or 1e-12
    ss_res = sum((y - (a * x * x + b * x + c)) ** 2 for x, y in zip(xs, ys))
    return a, b, c, 1 - ss_res / ss_tot
