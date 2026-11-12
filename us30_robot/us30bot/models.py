from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

BUY = "BUY"
SELL = "SELL"


@dataclass(frozen=True)
class Bar:
    time: datetime  # bar open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def bullish(self) -> bool:
        return self.close > self.open


@dataclass
class Swing:
    index: int
    price: float
    kind: str  # "H" or "L"
    label: str = ""  # HH / LH / HL / LL / "" (first swings)


@dataclass
class Zone:
    kind: str  # FVG, OB, BREAKER, SUPPLY, DEMAND, LIQ
    side: str  # BUY (support / demand) or SELL (resistance / supply)
    top: float
    bottom: float
    created: int
    mitigated: bool = False

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass
class Detection:
    """One pattern recognised on the chart at bar `index`."""

    pattern_id: int
    name: str
    direction: str  # BUY / SELL
    index: int
    entry: float
    stop: float
    target: float
    reason: str  # short Romanian explanation of the convergence
    features: Dict[str, float] = field(default_factory=dict)

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def rr(self) -> float:
        return abs(self.target - self.entry) / self.risk if self.risk > 0 else 0.0


@dataclass
class Signal:
    id: int
    time: datetime
    index: int
    direction: str
    entry: float
    stop: float
    target: float
    score: float  # learned probability of success (0..1)
    expectancy: float  # in R
    patterns: List[Detection]
    context: Dict[str, str]
    explanation: str
    traded: bool = True  # False => shadow signal (learning only)


@dataclass
class Outcome:
    signal_id: int
    result: str  # WIN / LOSS / TIMEOUT
    r_multiple: float
    bars_held: int
    mfe_r: float  # max favourable excursion, in R
    mae_r: float  # max adverse excursion, in R
    verdict: str  # Romanian post-mortem (confirmare / infirmare)
    exit_price: Optional[float] = None
