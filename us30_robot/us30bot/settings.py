"""User-adjustable settings (dashboard, Telegram /set, or state/settings.json).

Every key maps to an attribute of ModeConfig or RiskConfig and has a safe range.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Tuple

from .modes import ModeController
from .risk import RiskManager

# key -> (object, attribute, min, max, type, description)
SPEC: Dict[str, Tuple[str, str, float, float, type, str]] = {
    "risk_pct": ("risk", "risk_pct", 0.05, 3.0, float, "risc % din sold pe tranzacție"),
    "max_daily_loss_pct": ("risk", "max_daily_loss_pct", 0.5, 10.0, float, "oprire la pierdere zilnică %"),
    "max_trades_day": ("risk", "max_trades_day", 1, 50, int, "maxim tranzacții pe zi"),
    "max_consecutive_losses": ("risk", "max_consecutive_losses", 1, 10, int, "pauză după N pierderi la rând"),
    "hybrid_auto_prob": ("mode", "hybrid_auto_prob", 0.3, 0.95, float, "HIBRID: P minim pt. execuție automată"),
    "hybrid_auto_exp": ("mode", "hybrid_auto_exp", 0.0, 3.0, float, "HIBRID: expectanță minimă (R) pt. auto"),
    "approval_timeout_bars": ("mode", "approval_timeout_bars", 1, 15, int, "HIBRID: minute pentru aprobare"),
    "approval_max_drift_r": ("mode", "approval_max_drift_r", 0.05, 1.0, float, "HIBRID: abatere max. de la intrare (R)"),
    "robot_min_prob": ("mode", "robot_min_prob", 0.3, 0.95, float, "ROBOT: P minim"),
    "robot_min_exp": ("mode", "robot_min_exp", 0.0, 3.0, float, "ROBOT: expectanță minimă (R)"),
    "robot_risk_factor": ("mode", "robot_risk_factor", 0.1, 1.0, float, "ROBOT: fracțiune din risc"),
    "offline_after_min": ("mode", "offline_after_sec", 2, 240, float, "minute fără activitate = offline"),
    "auto_robot_offline": ("mode", "auto_robot_offline", 0, 1, bool, "trecere automată în ROBOT când ești offline"),
}


class Settings:
    def __init__(self, modes: ModeController, risk: RiskManager, path: str = ""):
        self.modes, self.risk, self.path = modes, risk, path

    def _obj(self, which: str):
        return self.modes.cfg if which == "mode" else self.risk.cfg

    def get(self) -> Dict[str, object]:
        out = {}
        for k, (which, attr, *_rest) in SPEC.items():
            v = getattr(self._obj(which), attr)
            out[k] = v / 60 if k == "offline_after_min" else v
        return out

    def set(self, key: str, value) -> object:
        if key not in SPEC:
            raise KeyError(f"setare necunoscută: {key}")
        which, attr, lo, hi, typ, _ = SPEC[key]
        if typ is bool:
            v = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "da", "on", "yes")
        else:
            v = typ(float(str(value).replace(",", ".")))
            if not lo <= v <= hi:
                raise ValueError(f"{key} trebuie să fie între {lo} și {hi}")
        setattr(self._obj(which), attr, v * 60 if key == "offline_after_min" else v)
        self.save()
        return v

    def update(self, values: Dict[str, object]) -> Dict[str, object]:
        for k, v in values.items():
            self.set(k, v)
        return self.get()

    def describe(self) -> str:
        cur = self.get()
        return "\n".join(f"{k} = {cur[k]}  ({SPEC[k][5]})" for k in SPEC)

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.get(), fh, indent=1)

    def load(self) -> None:
        if self.path and os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            path, self.path = self.path, ""  # don't rewrite while loading
            for k, v in data.items():
                if k in SPEC:
                    try:
                        self.set(k, v)
                    except (ValueError, KeyError):
                        pass
            self.path = path
