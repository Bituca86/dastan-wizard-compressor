"""Rich context features for the meta-model (expected R of a detection).

Every value is known at the close of the detection bar (no look-ahead). Missing
values are encoded as MISSING so the pure-Python tree evaluator never sees NaN.
"""
from __future__ import annotations

from typing import List

from .context import MarketState, et_hour
from .models import BUY, Detection
from .patterns import CATALOG

MISSING = 99.0
FAMILIES = sorted({fam for _, fam in CATALOG.values()})
SESSIONS = ["asia", "london", "ny_open", "ny", "off"]

RICH_NAMES = [
    "pid", "family", "dir", "p_cell", "n_cell", "p_logit", "confl_same", "confl_opp",
    "htf_align", "m1_align", "pd_align", "session", "et_hour", "weekday",
    "vol_regime", "tr5_atr", "risk_atr", "rr", "cost_r",
    "ext_pos", "ret5", "ret15", "ret60", "er10",
    "body_rng", "rej_wick", "rng_atr",
    "d_day_ext", "d_day_opp", "d_pd_ext", "d_pd_opp",
    "htf_ret", "disp_same", "disp_opp", "bars_struct", "struct_dir",
    "sweep", "level_strength", "f_fakeout", "f_qm", "f_htf_zone", "f_disp",
]


def _c(x: float, lo: float = -20.0, hi: float = 20.0) -> float:
    return lo if x < lo else hi if x > hi else x


def rich_features(st: MarketState, htf: MarketState, d: Detection, ctx: dict, n_same: int, n_opp: int,
                  base_atr: float, cost_r: float, p_cell: float, n_cell: float, p_logit: float) -> List[float]:
    sg = 1.0 if d.direction == BUY else -1.0
    b = st.bar
    atr = st.atr_v
    bars = st.bars
    n = len(bars)
    c = b.close
    tri = {"with": 1.0, "flat": 0.0, "against": -1.0}

    def ret(k: int) -> float:
        return _c(sg * (c - bars[-k - 1].close) / atr) if n > k else 0.0

    # efficiency ratio over 10 bars, signed by direction
    er = 0.0
    if n > 10:
        path = sum(abs(bars[-j].close - bars[-j - 1].close) for j in range(1, 11))
        er = sg * (c - bars[-11].close) / path if path > 0 else 0.0
    tr5 = sum(x.range for x in bars[-5:]) / (5 * atr) if n >= 5 else 1.0
    rng = b.range or 1e-9
    wick = (min(b.open, c) - b.low) if sg > 0 else (b.high - max(b.open, c))

    pos = st.range_position()
    ext = MISSING if pos is None else _c((1.0 - pos) if sg > 0 else pos, -1, 2)   # 1 = at the stretched extreme

    def dist(level, toward_ext: bool) -> float:
        if level is None:
            return MISSING
        return _c(sg * (c - level) / atr)

    day_ext, day_opp = (st.day_low, st.day_high) if sg > 0 else (st.day_high, st.day_low)
    pd_ext, pd_opp = (st.pdl, st.pdh) if sg > 0 else (st.pdh, st.pdl)

    htf_ret = 0.0
    if len(htf.bars) > 4:
        htf_ret = _c(sg * (c - htf.bars[-4].close) / max(htf.atr_v, 1e-9))

    up, dn = st.events.get("DISPLACEMENT_UP", -999), st.events.get("DISPLACEMENT_DN", -999)
    same, opp = (up, dn) if sg > 0 else (dn, up)
    last_ev, last_dir = -999, 0.0
    for name, idx in st.events.items():
        if name.startswith(("BOS", "CHOCH")) and idx > last_ev:
            last_ev, last_dir = idx, (1.0 if name.endswith("UP") else -1.0)
    f = d.features
    return [
        float(d.pattern_id), float(FAMILIES.index(CATALOG[d.pattern_id][1])), sg,
        p_cell, min(n_cell, 500.0), p_logit, float(min(n_same, 6)), float(min(n_opp, 6)),
        tri[ctx["htf"]], tri[ctx["m1"]], {"ok": 1.0, "eq": 0.0, "bad": -1.0}[ctx["pd"]],
        float(SESSIONS.index(ctx["session"])), et_hour(b.time), float(b.time.weekday()),
        _c(atr / base_atr, 0, 6) if base_atr > 0 else 1.0, _c(tr5, 0, 6),
        _c(f.get("risk_atr", d.risk / atr), 0, 8), _c(d.rr, 0, 8), _c(cost_r, 0, 2),
        ext, ret(5), ret(15), ret(60), er,
        b.body / rng, wick / rng, _c(b.range / atr, 0, 8),
        dist(day_ext, True), dist(day_opp, False), dist(pd_ext, True), dist(pd_opp, False),
        htf_ret, 1.0 if st.i - same <= 30 else 0.0, 1.0 if st.i - opp <= 30 else 0.0,
        float(min(st.i - last_ev, 120)) if last_ev >= 0 else 120.0, sg * last_dir,
        f.get("sweep_level", 0.0), f.get("level_strength", 0.0), f.get("fakeout", 0.0), f.get("qm", 0.0),
        f.get("htf_zone", 0.0), f.get("displacement", 0.0),
    ]
