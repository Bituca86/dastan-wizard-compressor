"""Accelerated self-learning.

Three learners combined:
 1. Hierarchical Beta posteriors per matrix cell, shrunk toward the pattern-family
    and then toward the global prior (empirical Bayes). A brand-new cell starts
    with the knowledge of its family, so it is useful after a few samples instead
    of hundreds.
 2. Online logistic regression (SGD, L2) on continuous context features -> learns
    *why* a pattern works (HTF alignment, session, premium/discount ...).
 3. Exponential forgetting (half-life in samples) -> adapts to regime changes.

Learning is "accelerated" because every detection (also the ones not traded =
shadow trades) and several alternative exits per detection (1R, 1.5R, 2R, planned
target) are labelled, multiplying the number of training labels per market event.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .matrix import FEATURE_NAMES

RR_GRID = (1.0, 1.5, 2.0, 3.0)


@dataclass
class BetaCell:
    a: float = 0.0  # weighted wins
    b: float = 0.0  # weighted losses
    r_sum: float = 0.0  # weighted realised R
    rr_wins: Dict[str, float] = field(default_factory=dict)  # alt-target wins, key = rr
    rr_n: float = 0.0

    @property
    def n(self) -> float:
        return self.a + self.b

    def decay(self, f: float) -> None:
        self.a *= f
        self.b *= f
        self.r_sum *= f
        self.rr_n *= f
        for k in self.rr_wins:
            self.rr_wins[k] *= f


class Learner:
    def __init__(self, half_life: float = 400.0, prior_strength: float = 6.0, lr: float = 0.05,
                 l2: float = 1e-3, seed: int = 7):
        self.decay = 0.5 ** (1.0 / half_life)
        self.k = prior_strength
        self.lr = lr
        self.l2 = l2
        self.cells: Dict[str, BetaCell] = {}
        self.families: Dict[str, BetaCell] = {}
        self.glob = BetaCell(a=2.0, b=3.0)  # mild pessimistic prior (~40%)
        self.w: List[float] = [0.0] * len(FEATURE_NAMES)
        self.updates = 0
        self.rng = random.Random(seed)

    # ------------------------------------------------------------------ priors
    @staticmethod
    def _mean(c: BetaCell, prior_mean: float, k: float) -> float:
        return (c.a + prior_mean * k) / (c.n + k)

    def family_mean(self, fam: str) -> float:
        g = self._mean(self.glob, 0.4, 2.0)
        f = self.families.get(fam)
        return self._mean(f, g, self.k) if f else g

    def cell_posterior(self, cell: str, fam: str) -> Tuple[float, float, float]:
        """returns (alpha, beta, n_effective)"""
        pm = self.family_mean(fam)
        c = self.cells.get(cell, BetaCell())
        return c.a + pm * self.k, c.b + (1 - pm) * self.k, c.n

    # ------------------------------------------------------------------ logistic
    def logit_p(self, x: List[float]) -> float:
        z = sum(wi * xi for wi, xi in zip(self.w, x))
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    # ------------------------------------------------------------------ scoring
    def score(self, cell: str, fam: str, x: List[float], explore: bool = False) -> Tuple[float, float]:
        """Blend Beta-cell probability with logistic model. Returns (p, n_eff).
        explore=True uses Thompson sampling (draw from posterior) for paper trading."""
        a, b, n = self.cell_posterior(cell, fam)
        p_cell = self.rng.betavariate(a, b) if explore else a / (a + b)
        p_log = self.logit_p(x)
        # trust the logistic model more as it sees more data
        w_log = min(0.5, self.updates / 2000.0)
        return (1 - w_log) * p_cell + w_log * p_log, n

    def best_rr(self, cell: str, fam: str, default: float) -> float:
        """Target RR with highest learned expectancy for this cell (after >=8 samples)."""
        c = self.cells.get(cell)
        if not c or c.rr_n < 8:
            return default
        best, best_e = default, -1e9
        for rr in RR_GRID:
            w = c.rr_wins.get(str(rr), 0.0)
            p = (w + self.family_mean(fam) * 2) / (c.rr_n + 2)
            e = p * rr - (1 - p)
            if e > best_e:
                best, best_e = rr, e
        return best

    # ------------------------------------------------------------------ update
    def update(self, cell: str, fam: str, x: List[float], win: bool, r: float,
               alt: Optional[Dict[float, bool]] = None, weight: float = 1.0) -> None:
        c = self.cells.setdefault(cell, BetaCell())
        f = self.families.setdefault(fam, BetaCell())
        for obj in (c, f, self.glob):
            obj.decay(self.decay)
            if win:
                obj.a += weight
            else:
                obj.b += weight
            obj.r_sum += weight * r
        if alt:
            c.rr_n += weight
            for rr, ok in alt.items():
                if ok:
                    c.rr_wins[str(rr)] = c.rr_wins.get(str(rr), 0.0) + weight
        # SGD step, log-loss + L2
        p = self.logit_p(x)
        g = (1.0 if win else 0.0) - p
        for j in range(len(self.w)):
            self.w[j] += self.lr * weight * (g * x[j] - self.l2 * self.w[j])
        self.updates += 1

    # ------------------------------------------------------------------ report
    def top_cells(self, n: int = 15, min_n: float = 5.0) -> List[Tuple[str, float, float, float]]:
        rows = []
        for k, c in self.cells.items():
            if c.n >= min_n:
                rows.append((k, c.a / c.n, c.n, c.r_sum / c.n))
        return sorted(rows, key=lambda r: r[3], reverse=True)[:n]

    def weights(self) -> Dict[str, float]:
        return dict(zip(FEATURE_NAMES, self.w))

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        def cd(c: BetaCell):
            return {"a": c.a, "b": c.b, "r": c.r_sum, "rw": c.rr_wins, "rn": c.rr_n}
        return {"cells": {k: cd(v) for k, v in self.cells.items()},
                "families": {k: cd(v) for k, v in self.families.items()},
                "glob": cd(self.glob), "w": self.w, "updates": self.updates}

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1)

    @classmethod
    def load(cls, path: str, **kw) -> "Learner":
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        L = cls(**kw)

        def bc(x):
            return BetaCell(x["a"], x["b"], x["r"], dict(x["rw"]), x["rn"])
        L.cells = {k: bc(v) for k, v in d["cells"].items()}
        L.families = {k: bc(v) for k, v in d["families"].items()}
        L.glob = bc(d["glob"])
        L.w = d["w"]
        L.updates = d["updates"]
        return L
