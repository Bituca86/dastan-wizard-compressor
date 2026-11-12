"""Risk management + paper account (ICMarkets US30, leverage 1:30)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple


@dataclass
class RiskConfig:
    risk_pct: float = 0.5  # % of balance risked per trade (before mode factor)
    max_daily_loss_pct: float = 2.0  # circuit breaker
    max_trades_day: int = 10
    max_consecutive_losses: int = 3  # pause for the rest of the day
    leverage: float = 30.0
    margin_use_max: float = 0.8  # never use more than 80% of free margin
    point_value: float = 1.0  # account currency per index point per 1 unit (cBot uses real TickValue)
    min_units: float = 0.01
    unit_step: float = 0.01


class RiskManager:
    def __init__(self, cfg: Optional[RiskConfig] = None):
        self.cfg = cfg or RiskConfig()
        self.day: Optional[date] = None
        self.day_pnl = 0.0
        self.day_trades = 0
        self.streak = 0
        self.day_start_balance = 0.0

    def new_bar(self, d: date, balance: float) -> None:
        if self.day != d:
            self.day, self.day_pnl, self.day_trades, self.streak = d, 0.0, 0, 0
            self.day_start_balance = balance

    def can_trade(self) -> Tuple[bool, str]:
        c = self.cfg
        if self.day_start_balance and -self.day_pnl >= self.day_start_balance * c.max_daily_loss_pct / 100:
            return False, f"limita de pierdere zilnică ({c.max_daily_loss_pct}%) atinsă"
        if self.day_trades >= c.max_trades_day:
            return False, f"maxim {c.max_trades_day} tranzacții/zi"
        if self.streak >= c.max_consecutive_losses:
            return False, f"{self.streak} pierderi consecutive -> pauză până mâine"
        return True, ""

    def size(self, balance: float, free_margin: float, entry: float, stop: float,
             factor: float = 1.0) -> Tuple[float, float]:
        """-> (units, risk_money). Units respect the 1:30 leverage margin limit."""
        c = self.cfg
        risk_money = balance * c.risk_pct * factor / 100
        dist = abs(entry - stop)
        if dist <= 0:
            return 0.0, 0.0
        units = risk_money / (dist * c.point_value)
        max_units = free_margin * c.margin_use_max * c.leverage / (entry * c.point_value)
        units = min(units, max_units)
        units = int(units / c.unit_step) * c.unit_step
        if units < c.min_units:
            return 0.0, 0.0
        return units, units * dist * c.point_value

    def on_open(self) -> None:
        self.day_trades += 1

    def on_close(self, pnl: float) -> None:
        self.day_pnl += pnl
        self.streak = self.streak + 1 if pnl < 0 else 0


@dataclass
class PaperAccount:
    balance: float = 10000.0
    curve: List[float] = field(default_factory=list)
    trades: List[float] = field(default_factory=list)

    def apply(self, pnl: float) -> None:
        self.balance += pnl
        self.trades.append(pnl)
        self.curve.append(self.balance)

    def stats(self, start: float) -> dict:
        peak, mdd = start, 0.0
        for v in self.curve:
            peak = max(peak, v)
            mdd = max(mdd, (peak - v) / peak)
        gains = sum(t for t in self.trades if t > 0)
        losses = -sum(t for t in self.trades if t < 0)
        return {"balance": round(self.balance, 2), "return_pct": round((self.balance / start - 1) * 100, 2),
                "max_drawdown_pct": round(mdd * 100, 2),
                "profit_factor": round(gains / losses, 2) if losses else None, "trades": len(self.trades)}
