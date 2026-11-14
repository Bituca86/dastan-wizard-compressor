"""Detection dataset: state/detectii.csv (append-only).

One row per closed detection (traded or not): context features known at the
detection bar + what happened afterwards. On 5 months of data (73k detections)
gradient-boosted meta-models did NOT beat the simple matrix rule out of sample,
so they are not used for trading; this log exists so the question can be
re-tested later on a much larger sample.
"""
from __future__ import annotations

import csv
import os

from .features import RICH_NAMES
from .learner import RR_GRID

HEAD = ["time_utc", "direction", "result", "R", "mfe_R", "mae_R", "bars", "p_rule", "exp_rule"] + \
       [f"hit_{rr}R" for rr in RR_GRID] + RICH_NAMES


class DetectionLog:
    def __init__(self, path: str, trader=None):
        self.path, self.trader = path, trader
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(HEAD)

    def on_detection(self, t, out) -> None:
        if self.trader is not None and getattr(self.trader, "warmup", False):
            return  # replayed history would be duplicated at every restart
        p = t.payload
        if "xr" not in p:
            return
        row = [p["t"].strftime("%Y-%m-%d %H:%M:%S"), t.direction, out.result, round(out.r_multiple, 3),
               round(out.mfe_r, 3), round(out.mae_r, 3), out.bars_held, round(p["p"], 4), round(p["exp"], 4)] + \
              [int(bool(t.alt.get(rr))) for rr in RR_GRID] + [round(v, 4) for v in p["xr"]]
        try:
            with open(self.path, "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(row)
        except OSError:
            pass
