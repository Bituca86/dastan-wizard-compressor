"""Trader: glues Engine (brain) + ModeController + RiskManager and produces broker
actions (open / close / signal / msg) for cTrader, or simulates them (paper)."""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional

from .engine import Engine
from .modes import EXECUTE, NOTIFY, PENDING, SKIP, ModeController
from .models import Bar, Outcome, Signal
from .risk import PaperAccount, RiskManager


class Trader:
    def __init__(self, engine: Engine, modes: ModeController, risk: RiskManager,
                 paper: bool = False, balance: float = 10000.0, label: str = "US30MX"):
        self.eng, self.modes, self.risk = engine, modes, risk
        self.label = label
        self.queue: List[dict] = []
        self.pending: Dict[int, dict] = {}
        self.positions: Dict[int, dict] = {}
        self.balance = self.equity = self.free_margin = balance
        self.start_balance = balance
        self.paper = PaperAccount(balance) if paper else None
        self.warmup = False
        self.feed: Deque[dict] = deque(maxlen=60)
        self.live_log: List[dict] = []
        self.listeners: List = []  # e.g. Telegram notifier, called with every action
        engine.on_signal.append(self._on_signal)
        engine.on_outcome.append(self._on_outcome)

    # ------------------------------------------------------------------ input
    def on_bar(self, bar: Bar, spread: Optional[float] = None, balance: Optional[float] = None,
               equity: Optional[float] = None, free_margin: Optional[float] = None) -> List[dict]:
        if self.paper:
            self.balance = self.equity = self.free_margin = self.paper.balance
        else:
            self.balance = balance if balance is not None else self.balance
            self.equity = equity if equity is not None else self.equity
            self.free_margin = free_margin if free_margin is not None else self.free_margin
        self.risk.new_bar(bar.time.date(), self.balance)
        eff = self.modes.effective
        if eff != getattr(self, "_last_eff", eff):
            self._emit({"type": "mode", "mode": self.modes.mode, "effective": eff,
                        "auto": True})
        self._last_eff = eff
        self.eng.on_bar(bar, spread)
        i = self.eng.st.i
        for sid in list(self.pending):
            if i - self.pending[sid]["i"] >= self.modes.cfg.approval_timeout_bars:
                self._status(sid, "EXPIRAT", "aprobare neprimită la timp")
                del self.pending[sid]
        return self.drain()

    def _emit(self, action: dict) -> None:
        self.queue.append(action)
        for fn in self.listeners:
            try:
                fn(action)
            except Exception:  # a notifier must never break trading
                pass

    def drain(self) -> List[dict]:
        q, self.queue = self.queue, []
        return q

    def set_mode(self, mode: str) -> str:
        m = self.modes.set_mode(mode)
        self.modes.presence()
        self._emit({"type": "mode", "mode": m, "effective": self.modes.effective})
        return m

    def decide_pending(self, sid: int, approve: bool) -> str:
        self.modes.presence()
        p = self.pending.pop(sid, None)
        if not p:
            return "semnal inexistent sau expirat"
        sig: Signal = p["sig"]
        if not approve:
            self._status(sid, "REFUZAT", "refuzat de tine")
            return "refuzat"
        drift = abs(self.eng.st.bar.close - sig.entry) / max(abs(sig.entry - sig.stop), 1e-9)
        if drift > self.modes.cfg.approval_max_drift_r or self.eng.open_signal != sid:
            self._status(sid, "EXPIRAT", f"prețul a plecat ({drift:.1f}R de la intrare)")
            return "prea târziu: prețul a plecat"
        return self._execute(sig, p["factor"], "aprobat de tine")

    def broker_event(self, ev: dict) -> None:
        sid = int(ev.get("sid", -1))
        kind = ev.get("type")
        if kind == "opened":
            self.risk.on_open()
            self.positions.setdefault(sid, {})["live"] = True
        elif kind == "closed":
            pnl = float(ev.get("pnl", 0.0))
            self.risk.on_close(pnl)
            self.positions.pop(sid, None)
            self.live_log.append(ev)
            self._emit({"type": "closed", "sid": sid, "pnl": pnl, "reason": ev.get("reason", ""),
                        "day_pnl": round(self.risk.day_pnl, 2)})
            ok, why = self.risk.can_trade()
            if not ok:
                self._emit({"type": "breaker", "why": why})
        elif kind == "rejected":
            self.positions.pop(sid, None)
            self._status(sid, "RESPINS", ev.get("reason", "respins de broker"))

    # ------------------------------------------------------------------ engine callbacks
    def _on_signal(self, sig: Signal) -> None:
        if self.warmup:
            return
        action, factor, why = self.modes.decide(sig.score, sig.expectancy)
        rec = {"type": "signal", "sid": sig.id, "time": sig.time.isoformat(), "side": sig.direction,
               "entry": sig.entry, "sl": sig.stop, "tp": sig.target, "p": round(sig.score, 3),
               "exp": round(sig.expectancy, 2), "text": sig.explanation,
               "patterns": [d.name for d in sig.patterns], "mode": self.modes.effective,
               "status": action, "why": why}
        self.feed.appendleft(rec)
        self._emit(rec)
        if action == EXECUTE:
            self._execute(sig, factor, why)
        elif action == PENDING:
            self.pending[sig.id] = {"sig": sig, "i": self.eng.st.i, "factor": factor}

    def _execute(self, sig: Signal, factor: float, why: str) -> str:
        ok, reason = self.risk.can_trade()
        if not ok:
            self._status(sig.id, SKIP, reason)
            return reason
        units, risk_money = self.risk.size(self.balance, self.free_margin, sig.entry, sig.stop, factor)
        if self.paper is not None:
            if units <= 0:
                self._status(sig.id, SKIP, "volum sub minim / marjă insuficientă")
                return "volum prea mic"
            self.risk.on_open()
        self.positions[sig.id] = {"units": units, "risk_money": risk_money, "factor": factor}
        self._emit({"type": "open", "sid": sig.id, "side": sig.direction, "entry": sig.entry,
                           "sl": sig.stop, "tp": sig.target,
                           "risk_pct": round(self.risk.cfg.risk_pct * factor, 3),
                           "label": self.label, "comment": f"MX#{sig.id}"})
        self._status(sig.id, "EXECUTAT", why)
        return "executat"

    def _on_outcome(self, sig: Signal, out: Outcome) -> None:
        pos = self.positions.get(sig.id)
        for r in self.feed:
            if r["sid"] == sig.id:
                r["result"], r["R"], r["verdict"] = out.result, round(out.r_multiple, 2), out.verdict
        self._emit({"type": "outcome", "sid": sig.id, "result": out.result,
                           "R": round(out.r_multiple, 2), "verdict": out.verdict})
        if pos is None:
            return
        if self.paper is not None:
            pnl = out.r_multiple * pos["risk_money"]
            self.paper.apply(pnl)
            self.risk.on_close(pnl)
            self.positions.pop(sig.id, None)
        else:
            # broker SL/TP normally closed it already; timeout (or safety) close
            self._emit({"type": "close", "sid": sig.id, "label": self.label,
                               "comment": f"MX#{sig.id}", "reason": out.result})

    def _status(self, sid: int, status: str, why: str) -> None:
        for r in self.feed:
            if r["sid"] == sid:
                r["status"], r["why"] = status, why
        self._emit({"type": "status", "sid": sid, "status": status, "why": why})

    # ------------------------------------------------------------------ report
    def status(self) -> dict:
        st = self.eng.st
        return {
            "mode": self.modes.mode, "effective": self.modes.effective, "online": self.modes.online,
            "bar": st.bar.time.isoformat() if st.bars else None, "price": st.bar.close if st.bars else None,
            "session": st.session, "trend_m1": st.structure.trend, "trend_m15": self.eng.htf.structure.trend,
            "balance": round(self.balance, 2), "equity": round(self.equity, 2),
            "risk": {"day_pnl": round(self.risk.day_pnl, 2), "day_trades": self.risk.day_trades,
                     "streak": self.risk.streak, "can_trade": self.risk.can_trade()[0]},
            "pending": [{"sid": k, "side": v["sig"].direction, "entry": v["sig"].entry,
                         "text": v["sig"].explanation} for k, v in self.pending.items()],
            "positions": list(self.positions.keys()),
            "signals": list(self.feed)[:25],
            "engine": self.eng.summary(),
            "top_cells": [{"cell": k, "win": round(w, 3), "n": round(n, 1), "avgR": round(r, 2)}
                          for k, w, n, r in self.eng.learner.top_cells(12)],
            "weights": {k: round(v, 3) for k, v in self.eng.learner.weights().items()},
        }
