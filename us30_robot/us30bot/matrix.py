"""The Confluence Matrix.

Rows   = pattern id x direction (from the 91-pattern catalogue)
Columns= context: session x HTF alignment (+ continuous features for the learner)

Each cell owns its own learned win-probability (see learner.py). A signal is the
cluster of same-direction detections on the current bar, scored by the learner.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from .context import MarketState
from .models import BUY, Detection
from .patterns import CATALOG

FEATURE_NAMES = [
    "bias", "confluence", "htf_align", "m1_align", "pd_align", "s_london", "s_ny_open", "s_ny",
    "vol_regime", "displacement", "risk_atr", "rr", "sweep", "level_strength",
]


def context_of(st: MarketState, htf: MarketState, direction: str) -> Dict[str, str]:
    sgn = 1 if direction == BUY else -1
    htf_t = htf.structure.trend
    pd = st.premium_discount()
    return {
        "session": st.session,
        "htf": "with" if htf_t == sgn else "against" if htf_t == -sgn else "flat",
        "m1": "with" if st.structure.trend == sgn else "against" if st.structure.trend == -sgn else "flat",
        "pd": "ok" if (direction == BUY and pd == "discount") or (direction != BUY and pd == "premium")
              else "bad" if pd != "eq" else "eq",
    }


def cell_key(det: Detection, ctx: Dict[str, str]) -> str:
    return f"{det.pattern_id}|{det.direction}|{ctx['session']}|{ctx['htf']}"


def family_key(det: Detection) -> str:
    return f"{CATALOG[det.pattern_id][1]}|{det.direction}"


def features(det: Detection, ctx: Dict[str, str], st: MarketState, confluence: int,
             atr_baseline: float) -> List[float]:
    disp = st.recent("DISPLACEMENT_UP" if det.direction == BUY else "DISPLACEMENT_DN", 30)
    tri = {"with": 1.0, "flat": 0.0, "against": -1.0}
    return [
        1.0,
        min(confluence, 4) / 4.0,
        tri[ctx["htf"]],
        tri[ctx["m1"]],
        {"ok": 1.0, "eq": 0.0, "bad": -1.0}[ctx["pd"]],
        1.0 if ctx["session"] == "london" else 0.0,
        1.0 if ctx["session"] == "ny_open" else 0.0,
        1.0 if ctx["session"] == "ny" else 0.0,
        min(st.atr_v / atr_baseline, 3.0) - 1.0 if atr_baseline > 0 else 0.0,
        1.0 if disp else 0.0,
        min(det.features.get("risk_atr", 1.0), 6.0) / 6.0,
        min(det.rr, 5.0) / 5.0,
        det.features.get("sweep_level", 0.0),
        det.features.get("level_strength", 0.0) / 3.0,
    ]


def cluster(dets: List[Detection]) -> Dict[str, List[Detection]]:
    out: Dict[str, List[Detection]] = {}
    for d in dets:
        out.setdefault(d.direction, []).append(d)
    return out


def explain(direction: str, dets: List[Detection], ctx: Dict[str, str], p: float, exp_r: float,
            cell_stats: List[Tuple[str, float, float]]) -> str:
    lines = [f"{'CUMPĂRARE (BUY)' if direction == BUY else 'VÂNZARE (SELL)'} – "
             f"P(succes)={p:.0%}, expectanță={exp_r:+.2f}R"]
    for d in dets:
        lines.append(f"  • #{d.pattern_id} {d.name}: {d.reason}")
    ctx_txt = {
        "with": "în direcția trendului M15", "against": "CONTRA trendului M15", "flat": "M15 neutru",
    }[ctx["htf"]]
    pd_txt = {"ok": "zonă favorabilă (discount/premium corect)", "bad": "zonă nefavorabilă",
              "eq": "la echilibru"}[ctx["pd"]]
    lines.append(f"  Context: sesiune {ctx['session']}, {ctx_txt}, {pd_txt}.")
    for key, mean, n in cell_stats:
        lines.append(f"  Istoric celulă [{key}]: win-rate {mean:.0%} din {n:.0f} cazuri (ponderat).")
    return "\n".join(lines)
