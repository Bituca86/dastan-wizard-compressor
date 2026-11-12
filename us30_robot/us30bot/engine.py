"""Real-time engine: bar in -> detections -> matrix scoring -> signal -> forward
evaluation -> self-learning. Works identically on live M1 feed or historical replay."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .context import MarketState, SessionClock, SpreadModel
from .evaluator import Evaluator, Tracked
from .learner import Learner
from .matrix import cell_key, cluster, context_of, explain, family_key, features
from .models import BUY, Bar, Detection, Outcome, Signal
from .patterns import detect_all


@dataclass
class EngineConfig:
    htf_minutes: int = 15
    # chosen on Jun-Aug 2026 ICMarkets data, validated on Sep-Nov (see README)
    min_prob: float = 0.50
    min_expectancy_r: float = 0.30
    min_cell_samples: float = 0.0  # 0 = allow trading from family/global prior
    explore: bool = False  # Thompson sampling (paper trading accelerates learning)
    cooldown_bars: int = 5  # same pattern/direction re-fire suppression
    one_position: bool = True
    timeout_bars: int = 60
    half_life: float = 400.0
    sessions: SessionClock = field(default_factory=SessionClock)
    spread: SpreadModel = field(default_factory=SpreadModel)  # ICMarkets: 0.7 NYSE / 1.2 otherwise
    allowed_sessions: tuple = ("london", "ny_open", "ny")


class HTFAggregator:
    def __init__(self, minutes: int):
        self.minutes = minutes
        self.cur: Optional[Bar] = None
        self.bucket: Optional[datetime] = None

    def update(self, b: Bar) -> Optional[Bar]:
        bucket = b.time.replace(minute=b.time.minute - b.time.minute % self.minutes, second=0,
                                microsecond=0)
        done = None
        if self.bucket is not None and bucket != self.bucket:
            done = self.cur
            self.cur = None
        self.bucket = bucket
        if self.cur is None:
            self.cur = Bar(bucket, b.open, b.high, b.low, b.close, b.volume)
        else:
            c = self.cur
            self.cur = Bar(c.time, c.open, max(c.high, b.high), min(c.low, b.low), b.close,
                           c.volume + b.volume)
        return done


class Engine:
    def __init__(self, config: Optional[EngineConfig] = None, learner: Optional[Learner] = None):
        self.cfg = config or EngineConfig()
        self.st = MarketState(self.cfg.sessions)
        self.htf = MarketState(self.cfg.sessions, zz_mult=1.0)
        self.st.htf = self.htf
        self.agg = HTFAggregator(self.cfg.htf_minutes)
        self.learner = learner or Learner(half_life=self.cfg.half_life)
        self.ev = Evaluator(self.cfg.timeout_bars)
        self.ev.on_close.append(self._on_close)
        self._last_fire: Dict[str, int] = {}
        self._seq = 0
        self.signals: Dict[int, Signal] = {}
        self.journal: List[dict] = []
        self.open_signal: Optional[int] = None
        self.stop_widen: Dict[str, float] = {}  # adaptive stop buffer per cell (learned)
        self.on_signal: List[Callable[[Signal], None]] = []
        self.on_outcome: List[Callable[[Signal, Outcome], None]] = []
        self._atr_hist: List[float] = []
        self.shadow_count = 0

    # ------------------------------------------------------------------ main loop
    def spread_now(self) -> float:
        return self.cfg.spread.cost(self.st.bar.time, self.st.live_spread)

    def on_bar(self, bar: Bar, live_spread: Optional[float] = None) -> Optional[Signal]:
        st = self.st
        st.live_spread = live_spread
        st.update(bar)
        h = self.agg.update(bar)
        if h is not None:
            self.htf.update(h)
        self.ev.update(st.i, bar)
        if st.atr.value:
            self._atr_hist.append(st.atr.value)
            if len(self._atr_hist) > 1440:
                self._atr_hist.pop(0)
        dets = [d for d in detect_all(st) if self._not_cooling(d)]
        if not dets:
            return None
        base = sorted(self._atr_hist)[len(self._atr_hist) // 2] if self._atr_hist else st.atr_v
        scored = []
        groups = cluster(dets)
        for direction, ds in groups.items():
            for d in ds:
                ctx = context_of(st, self.htf, direction)
                cell, fam = cell_key(d, ctx), family_key(d)
                self._adapt(d, cell, fam)
                x = features(d, ctx, st, len(ds), base)
                p, n = self.learner.score(cell, fam, x, explore=self.cfg.explore)
                cost = self.spread_now() / d.risk
                exp_r = p * d.rr - (1 - p) - cost
                scored.append((exp_r, p, n, d, ctx, cell, fam, x))
                # every detection becomes a shadow trade -> learning sample
                self.shadow_count += 1
                self.ev.track(Tracked(-self.shadow_count, d.direction, d.entry, d.stop, d.target, st.i,
                                      {"cell": cell, "fam": fam, "x": x, "shadow": True,
                                       "cost_r": cost}))
        return self._decide(scored, groups)

    # ------------------------------------------------------------------ helpers
    def _not_cooling(self, d: Detection) -> bool:
        k = f"{d.pattern_id}|{d.direction}"
        last = self._last_fire.get(k)
        if last is not None and self.st.i - last < self.cfg.cooldown_bars:
            return False
        self._last_fire[k] = self.st.i
        return True

    def _adapt(self, d: Detection, cell: str, fam: str) -> None:
        """Apply what was learned: wider stop if this cell keeps getting stop-hunted,
        and the reward:risk target with the best observed expectancy."""
        widen = self.stop_widen.get(cell, 0.0)
        if widen > 0:
            extra = widen * self.st.atr_v
            d.stop = d.stop - extra if d.direction == BUY else d.stop + extra
        rr = self.learner.best_rr(cell, fam, default=d.rr)
        if abs(rr - d.rr) > 1e-9:
            sgn = 1 if d.direction == BUY else -1
            d.target = d.entry + sgn * rr * d.risk

    def _decide(self, scored, groups) -> Optional[Signal]:
        cfg = self.cfg
        if cfg.one_position and self.open_signal is not None:
            return None
        if self.st.session not in cfg.allowed_sessions:
            return None
        best_by_dir: Dict[str, tuple] = {}
        for row in scored:
            dr = row[3].direction
            if dr not in best_by_dir or row[0] > best_by_dir[dr][0]:
                best_by_dir[dr] = row
        if len(best_by_dir) == 2:  # conflicting patterns -> only trade a clear winner
            a, b = sorted(best_by_dir.values(), key=lambda r: r[0], reverse=True)
            if a[0] - b[0] < 0.25:
                return None
            best = a
        else:
            best = next(iter(best_by_dir.values()))
        exp_r, p, n, d, ctx, cell, fam, x = best
        if p < cfg.min_prob or exp_r < cfg.min_expectancy_r or n < cfg.min_cell_samples:
            return None
        self._seq += 1
        same = groups[d.direction]
        stats = []
        for dd in same:
            c = self.learner.cells.get(cell_key(dd, ctx))
            if c and c.n >= 1:
                stats.append((cell_key(dd, ctx), c.a / c.n, c.n))
        sig = Signal(self._seq, self.st.bar.time, self.st.i, d.direction, d.entry, d.stop, d.target, p,
                     exp_r, same, ctx, explain(d.direction, same, ctx, p, exp_r, stats))
        self.signals[sig.id] = sig
        self.open_signal = sig.id
        self.ev.track(Tracked(sig.id, sig.direction, sig.entry, sig.stop, sig.target, self.st.i,
                              {"shadow": False, "cell": cell,
                               "cost_r": self.spread_now() / abs(sig.entry - sig.stop)}))
        for cb in self.on_signal:
            cb(sig)
        return sig

    def _on_close(self, t: Tracked, out: Outcome) -> None:
        if t.payload.get("shadow"):
            win = out.result == "WIN"
            alt = {rr: bool(v) for rr, v in t.alt.items()}
            self.learner.update(t.payload["cell"], t.payload["fam"], t.payload["x"], win, out.r_multiple, alt)
            # learn from the post-mortem: stop-hunted losses widen the stop for that cell
            cell = t.payload["cell"]
            cur = self.stop_widen.get(cell, 0.0)
            if out.result == "LOSS" and t.stop_wick_then_target:
                self.stop_widen[cell] = min(1.0, cur + 0.1)
            elif out.result == "WIN" and cur > 0:
                self.stop_widen[cell] = max(0.0, cur - 0.02)
            return
        sig = self.signals.get(out.signal_id)
        if self.open_signal == out.signal_id:
            self.open_signal = None
        if sig is None:
            return
        self.journal.append({
            "id": sig.id, "time": sig.time.isoformat(), "dir": sig.direction, "entry": sig.entry,
            "stop": sig.stop, "target": sig.target, "p": round(sig.score, 3),
            "patterns": [d.name for d in sig.patterns], "result": out.result,
            "R": round(out.r_multiple, 2), "mfe": round(out.mfe_r, 2), "mae": round(out.mae_r, 2),
            "verdict": out.verdict,
        })
        for cb in self.on_outcome:
            cb(sig, out)

    # ------------------------------------------------------------------ reporting & persistence
    def summary(self) -> dict:
        j = self.journal
        wins = sum(1 for r in j if r["result"] == "WIN")
        tot = sum(r["R"] for r in j)
        return {"signals": len(j), "wins": wins, "win_rate": wins / len(j) if j else 0.0,
                "total_R": round(tot, 2), "avg_R": round(tot / len(j), 3) if j else 0.0,
                "learning_samples": self.learner.updates, "cells": len(self.learner.cells)}

    def save(self, folder: str) -> None:
        os.makedirs(folder, exist_ok=True)
        self.learner.save(os.path.join(folder, "learner.json"))
        with open(os.path.join(folder, "adaptive.json"), "w", encoding="utf-8") as fh:
            json.dump({"stop_widen": self.stop_widen}, fh, indent=1)
        with open(os.path.join(folder, "journal.json"), "w", encoding="utf-8") as fh:
            json.dump(self.journal, fh, indent=1, ensure_ascii=False)

    @classmethod
    def load(cls, folder: str, config: Optional[EngineConfig] = None) -> "Engine":
        cfg = config or EngineConfig()
        lp = os.path.join(folder, "learner.json")
        learner = Learner.load(lp, half_life=cfg.half_life) if os.path.exists(lp) else None
        eng = cls(cfg, learner)
        ap = os.path.join(folder, "adaptive.json")
        if os.path.exists(ap):
            with open(ap, encoding="utf-8") as fh:
                eng.stop_widen = json.load(fh).get("stop_widen", {})
        return eng
