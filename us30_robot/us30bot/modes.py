"""Operating modes.

MANUAL  - robot only proposes (chart + dashboard); you execute by hand. It still learns.
HIBRID  - high-confidence signals execute automatically, the rest wait for your approval
          (expire after a few minutes, M1 moves fast).
AUTO    - every signal that passes the normal filters is executed (you are watching).
ROBOT   - autopilot for when you are offline: stricter filters, reduced risk, daily
          loss / losing-streak circuit breakers. Can be selected explicitly or kicks in
          automatically when no presence (mouse on chart, dashboard, buttons) is seen.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

MODES = ("MANUAL", "HIBRID", "AUTO", "ROBOT")

EXECUTE, PENDING, NOTIFY, SKIP = "EXECUTE", "PENDING", "NOTIFY", "SKIP"


@dataclass
class ModeConfig:
    hybrid_auto_prob: float = 0.60  # HIBRID: execute without asking above these
    hybrid_auto_exp: float = 0.40
    approval_timeout_bars: int = 3
    approval_max_drift_r: float = 0.3  # reject approval if price moved > 0.3R from entry
    robot_min_prob: float = 0.55
    robot_min_exp: float = 0.30
    robot_risk_factor: float = 0.5
    offline_after_sec: float = 20 * 60
    auto_robot_offline: bool = True  # switch to ROBOT when you are not online


class ModeController:
    def __init__(self, mode: str = "MANUAL", cfg: Optional[ModeConfig] = None,
                 clock: Callable[[], float] = time.time, always_online: bool = False):
        self.cfg = cfg or ModeConfig()
        self.clock = clock
        self.always_online = always_online
        self.mode = "MANUAL"
        self.set_mode(mode)
        self.last_presence = clock()

    def set_mode(self, mode: str) -> str:
        mode = mode.upper().replace("HYBRID", "HIBRID")
        if mode not in MODES:
            raise ValueError(f"mod necunoscut: {mode} (valide: {', '.join(MODES)})")
        self.mode = mode
        return mode

    def presence(self) -> None:
        self.last_presence = self.clock()

    @property
    def online(self) -> bool:
        return self.always_online or (self.clock() - self.last_presence) < self.cfg.offline_after_sec

    @property
    def effective(self) -> str:
        if self.mode != "ROBOT" and self.cfg.auto_robot_offline and not self.online:
            return "ROBOT"
        return self.mode

    def decide(self, p: float, exp_r: float) -> Tuple[str, float, str]:
        """-> (action, risk_factor, reason)"""
        c, m = self.cfg, self.effective
        if m == "MANUAL":
            return NOTIFY, 0.0, "MANUAL: propunere, execuți tu"
        if m == "AUTO":
            return EXECUTE, 1.0, "AUTO: executat"
        if m == "HIBRID":
            if p >= c.hybrid_auto_prob and exp_r >= c.hybrid_auto_exp:
                return EXECUTE, 1.0, f"HIBRID: încredere mare (P={p:.0%}) -> executat automat"
            return PENDING, 1.0, f"HIBRID: aștept aprobarea ta ({c.approval_timeout_bars} min)"
        # ROBOT
        if p >= c.robot_min_prob and exp_r >= c.robot_min_exp:
            why = "offline" if self.mode != "ROBOT" else "ROBOT"
            return EXECUTE, c.robot_risk_factor, f"ROBOT ({why}): filtru strict trecut, risc redus"
        return SKIP, 0.0, "ROBOT: sub pragul strict -> doar învățare"
