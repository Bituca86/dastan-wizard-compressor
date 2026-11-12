"""Pattern catalogue (the 91 setups from the "Institutional Price Action & Liquidity"
cheat sheet) + real-time detectors for the ones that can be defined objectively.

Every detector receives the live MarketState and returns a Detection (or None) on
the bar where the pattern *triggers* (i.e. no repainting: only closed bars used).
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from .context import MarketState
from .models import BUY, SELL, Detection

# ---------------------------------------------------------------------------
# Catalogue: id -> (name, family). Families drive the matrix rows.
# ---------------------------------------------------------------------------
CATALOG: Dict[int, Tuple[str, str]] = {
    1: ("QM Quick Retest", "QM"), 2: ("QM Late Retest", "QM"), 3: ("QM Re-Entry", "QM"),
    4: ("Ignored QM / QMTR", "QM"), 5: ("Continuation QM", "QM"), 6: ("Reversal at QM", "QM"),
    7: ("DM Shadow", "QM"), 8: ("Continuation DM", "QM"), 9: ("2R/2S Fakeout", "FAKEOUT"),
    10: ("V Twin", "REVERSAL"), 11: ("Flag B", "CONTINUATION"), 12: ("Flag A + Flag B", "CONTINUATION"),
    13: ("Fakeout V1", "FAKEOUT"), 14: ("Fakeout V2 (SR Flip)", "FAKEOUT"),
    15: ("Fakeout V3 (Diamond)", "FAKEOUT"), 16: ("Double SSR", "CLASSIC"), 17: ("3 Drive", "REVERSAL"),
    18: ("Can-Can", "COMPRESSION"), 19: ("Compression (CP)", "COMPRESSION"),
    20: ("Compression Liquidity", "COMPRESSION"), 21: ("Can-Can + Fakeout", "FAKEOUT"),
    22: ("Ending Diagonal", "CLASSIC"), 23: ("Ruler (Pennants)", "CONTINUATION"), 24: ("R/S Flip", "CONTINUATION"),
    25: ("Inside Range", "RANGE"), 26: ("Outside Range", "RANGE"), 27: ("Triple Top", "CLASSIC"),
    28: ("Triple Bottom", "CLASSIC"), 29: ("Demand Zone", "ZONE"), 30: ("Supply Zone", "ZONE"),
    31: ("Order Block (OB)", "ZONE"), 32: ("Breaker Block", "ZONE"), 33: ("Mitigation Block", "ZONE"),
    34: ("FVG / Imbalance", "ZONE"), 35: ("Liquidity Void", "ZONE"), 36: ("Premium / Discount", "CONTEXT"),
    37: ("Equal Highs (EQH)", "LIQUIDITY"), 38: ("Equal Lows (EQL)", "LIQUIDITY"),
    39: ("Liquidity Sweep", "LIQUIDITY"), 40: ("SFP (Swing Failure Pattern)", "LIQUIDITY"),
    41: ("Stop Hunt", "LIQUIDITY"), 42: ("News Liquidity Grab", "LIQUIDITY"),
    43: ("Session Liquidity", "LIQUIDITY"), 44: ("Previous Day Levels", "LIQUIDITY"),
    45: ("Previous Week Levels", "LIQUIDITY"), 46: ("Trendline Liquidity", "LIQUIDITY"),
    47: ("Range High/Low Liquidity", "LIQUIDITY"), 48: ("Displacement + Reclaim", "STRUCTURE"),
    49: ("Parabolic Blowoff", "REVERSAL"), 50: ("Bear Trap", "FAKEOUT"), 51: ("Bull Trap", "FAKEOUT"),
    52: ("Accumulation", "WYCKOFF"), 53: ("Distribution", "WYCKOFF"), 54: ("Wyckoff Spring", "WYCKOFF"),
    55: ("Wyckoff UTAD", "WYCKOFF"), 56: ("Wyckoff LPS", "WYCKOFF"), 57: ("Inverse H&S", "CLASSIC"),
    58: ("Head & Shoulders", "CLASSIC"), 59: ("Double Top", "CLASSIC"), 60: ("Double Bottom", "CLASSIC"),
    61: ("Rounding Bottom", "CLASSIC"), 62: ("Rounding Top", "CLASSIC"), 63: ("Descending Triangle", "CLASSIC"),
    64: ("Ascending Triangle", "CLASSIC"), 65: ("Symmetrical Triangle", "CLASSIC"),
    66: ("Broadening Wedge", "CLASSIC"), 67: ("Falling Wedge", "CLASSIC"), 68: ("Rising Wedge", "CLASSIC"),
    69: ("Rectangle / Range", "RANGE"), 70: ("Diamond Top", "CLASSIC"), 71: ("Diamond Bottom", "CLASSIC"),
    72: ("Megaphone", "CLASSIC"), 73: ("Stepping Highs", "STRUCTURE"), 74: ("Stepping Lows", "STRUCTURE"),
    75: ("Elliott 1-2-3-4-5", "ELLIOTT"), 76: ("Elliott A-B-C", "ELLIOTT"), 77: ("Elliott W-X-Y", "ELLIOTT"),
    78: ("Liquidity Run (Buy Side)", "LIQUIDITY"), 79: ("Liquidity Run (Sell Side)", "LIQUIDITY"),
    80: ("Unfilled Wick", "ZONE"), 81: ("Gap Fill", "ZONE"), 82: ("Break of Structure (BOS)", "STRUCTURE"),
    83: ("Change of Character (CHOCH)", "STRUCTURE"), 84: ("Market Structure Shift (MSS)", "STRUCTURE"),
    85: ("Higher Timeframe POI", "CONTEXT"), 86: ("Multi Timeframe Confluence", "CONTEXT"),
    87: ("Volume Imbalance", "ZONE"), 88: ("Liquidity Pool", "LIQUIDITY"),
    89: ("Retest & Continuation", "CONTINUATION"), 90: ("Retest & Reversal", "REVERSAL"),
    91: ("Final Shakeout", "FAKEOUT"),
}

# Patterns used as *context features* in the matrix rather than standalone triggers.
CONTEXT_IDS = {36, 85, 86, 37, 38, 88}

Detector = Callable[[MarketState], List[Detection]]
DETECTORS: List[Tuple[str, Detector]] = []
IMPLEMENTED: set = set()


def detector(*ids: int):
    def wrap(fn: Detector) -> Detector:
        DETECTORS.append((fn.__name__, fn))
        IMPLEMENTED.update(ids)
        return fn
    return wrap


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _mk(st: MarketState, pid: int, direction: str, stop: float, reason: str,
        target: Optional[float] = None, min_rr: float = 1.5, **features) -> Optional[Detection]:
    entry = st.bar.close
    buf = 0.15 * st.atr_v
    stop = stop - buf if direction == BUY else stop + buf
    risk = abs(entry - stop)
    if risk <= 0 or (direction == BUY and stop >= entry) or (direction == SELL and stop <= entry):
        return None
    if risk > 6 * st.atr_v:  # stop too wide for an M1 scalp -> skip
        return None
    if target is None or abs(target - entry) < min_rr * risk or \
            (direction == BUY and target <= entry) or (direction == SELL and target >= entry):
        target = _liquidity_target(st, direction, entry, risk, min_rr)
    features.setdefault("risk_atr", risk / st.atr_v)
    return Detection(pid, CATALOG[pid][0], direction, st.i, entry, stop, target, reason, features)


def _liquidity_target(st: MarketState, direction: str, entry: float, risk: float, min_rr: float) -> float:
    """Nearest opposing liquidity pool that still gives >= min_rr, else fixed 2R."""
    pools = st.liquidity_levels(SELL if direction == BUY else BUY)
    swing = st.zz.last_of("H" if direction == BUY else "L")
    if swing:
        pools.append(("swing", swing.price))
    cands = sorted(p for _, p in pools if (p - entry) * (1 if direction == BUY else -1) >= min_rr * risk)
    if cands:
        return cands[0] if direction == BUY else cands[-1]
    return entry + (2.0 * risk if direction == BUY else -2.0 * risk)


# ---------------------------------------------------------------------------
# 1-7  Quasimodo (QM) family - setups are remembered and traded on retest
# ---------------------------------------------------------------------------
def _sweeps_liquidity(st: MarketState, sw, side_high: bool) -> bool:
    levels = st.liquidity_levels(SELL if side_high else BUY)
    tol = 0.1 * st.atr_v
    lv = [p for name, p in levels if name not in ("range_high", "range_low")]
    return any((sw.price > p + tol) if side_high else (sw.price < p - tol) for p in lv)


@detector(1, 2, 3, 4, 5, 6, 7)
def quasimodo(st: MarketState) -> List[Detection]:
    """Bearish QM: H1 -> L1 -> HH -> LL (below L1). QML = H1. Sell the retest of QML.
    Variants: 1 quick retest (<=20 bars), 2 late retest, 3 second touch (re-entry),
    4 QMTR (QML broken then engulfed back), 5 continuation QM (H1 was a LH, i.e. QM
    inside a downtrend), 6 reversal QM (the HH swept liquidity), 7 DM shadow (retest
    wick pierces QML and closes back). Bullish mirrored."""
    out: List[Detection] = []
    setups = st.memory.setdefault("qm", [])
    sw = st.zz.last(4)
    if len(sw) == 4:
        kinds = "".join(s.kind for s in sw)
        if kinds in ("HLHL", "LHLH"):
            bear = kinds == "HLHL"
            e1, m1, ext, brk = sw
            valid = (ext.price > e1.price and brk.price < m1.price) if bear else \
                    (ext.price < e1.price and brk.price > m1.price)
            if valid and not any(x["ext"] == ext.index for x in setups):
                setups.append({"dir": SELL if bear else BUY, "qml": e1.price, "ext": ext.index,
                               "ext_p": ext.price, "start": brk.index, "touch": 0, "broken": None,
                               "cont": e1.label == ("LH" if bear else "HL"),
                               "sweep": _sweeps_liquidity(st, ext, bear)})
    b, atr = st.bar, st.atr_v
    tol = 0.3 * atr
    keep = []
    for q in setups:
        bear = q["dir"] == SELL
        sg = 1 if bear else -1
        qml, age = q["qml"], st.i - q["start"]
        if age > 180 or sg * (b.close - q["ext_p"]) > 0:
            continue  # expired or invalidated beyond the extreme
        if q["broken"] is None and sg * (b.close - qml) > 0.25 * atr:
            q["broken"] = st.i
        if q["broken"] is not None:
            if st.i - q["broken"] > 15:
                continue
            p = st.prev
            engulf = (b.close < p.open and b.open >= p.close and p.bullish and b.close < qml) if bear else \
                     (b.close > p.open and b.open <= p.close and not p.bullish and b.close > qml)
            if engulf:
                d = _mk(st, 4, q["dir"], b.high if bear else b.low,
                        f"QMTR: QML {qml:.1f} a fost depășit (capcană), apoi lumânare engulfing înapoi "
                        f"-> QM ignorat devine intrare în direcția inițială", qm=1.0)
                if d: out.append(d)
                continue
            keep.append(q)
            continue
        touch = (b.high >= qml - tol and b.close < qml and not b.bullish) if bear else \
                (b.low <= qml + tol and b.close > qml and b.bullish)
        if touch and age >= 1:
            q["touch"] += 1
            pierce = (b.high - qml) if bear else (qml - b.low)
            if q["touch"] >= 2:
                pid = 3
            elif q["sweep"]:
                pid = 6
            elif q["cont"]:
                pid = 5
            elif pierce > 0.2 * atr:
                pid = 7
            else:
                pid = 1 if age <= 20 else 2
            what = {1: "retest rapid", 2: "retest târziu", 3: "re-intrare (a doua atingere)",
                    5: "QM de continuare în trend", 6: "QM de inversare după vânarea lichidității",
                    7: "DM shadow: fitilul străpunge QML și închide înapoi"}[pid]
            ext_txt = "HH" if bear else "LL"
            d = _mk(st, pid, q["dir"], max(b.high, qml) if bear else min(b.low, qml),
                    f"QM {'bearish' if bear else 'bullish'}: {ext_txt} {q['ext_p']:.1f} urmat de spargerea "
                    f"structurii; {what} la QML {qml:.1f}", qm=1.0, qm_age=float(age))
            if d: out.append(d)
            if q["touch"] >= 2:
                continue
        keep.append(q)
    st.memory["qm"] = keep[-10:]
    return out


# ---------------------------------------------------------------------------
# 39-44 / 50-51 / 54-55  Liquidity sweeps, SFP, session & PD levels, traps, springs
# ---------------------------------------------------------------------------
_LEVEL_PID = {"PDH": 44, "PDL": 44, "PWH": 45, "PWL": 45, "EQH": 37, "EQL": 38, "POOL": 88,
              "range_high": 47, "range_low": 47, "swing": 40}


@detector(37, 38, 39, 40, 41, 43, 44, 45, 47, 50, 51, 54, 55, 88)
def liquidity_sweep(st: MarketState) -> List[Detection]:
    out = []
    b = st.bar
    atr = st.atr_v
    dr = st.dealing_range()
    tight = dr is not None and (dr[0] - dr[1]) < 6 * atr
    for side, sign in ((SELL, 1), (BUY, -1)):
        levels = st.liquidity_levels(side)
        sw = st.zz.last_of("H" if side == SELL else "L")
        if sw and st.i - sw.index >= 3:
            levels.append(("swing", sw.price))
        best = None
        n_swept = 0
        for name, lvl in levels:
            if side == SELL:
                ok = b.high > lvl and b.close < lvl and (b.high - lvl) < 1.5 * atr
            else:
                ok = b.low < lvl and b.close > lvl and (lvl - b.low) < 1.5 * atr
            wick = (b.high - max(b.open, b.close)) if side == SELL else (min(b.open, b.close) - b.low)
            if ok and wick >= 0.4 * b.range:
                pri = {"PWH": 4, "PWL": 4, "PDH": 3, "PDL": 3, "POOL": 3, "range_high": 2.5,
                       "range_low": 2.5}.get(name, 1 if name == "swing" else 2)
                n_swept += 1
                if best is None or pri > best[0]:
                    best = (pri, name, lvl)
        if not best:
            continue
        _, name, lvl = best
        if name.endswith(("_high", "_low")):
            pid = 43
        else:
            pid = _LEVEL_PID.get(name, 39)
        if tight and name in ("swing", "EQH", "EQL"):
            pid = 55 if side == SELL else 54  # UTAD / Spring at range extreme
        elif name == "swing" and st.structure.trend == (1 if side == SELL else -1):
            pid = 51 if side == SELL else 50  # bull / bear trap: breakout of trend extreme fails
        elif name == "swing" and b.range >= 2.0 * atr:
            pid = 41  # stop hunt: violent spike through the swing
        if n_swept >= 2 and pid in (40, 43, 37, 38):
            pid = 39  # several pools taken in one candle = generic liquidity sweep
        stop = b.high if side == SELL else b.low
        word = "deasupra" if side == SELL else "sub"
        d = _mk(st, pid, side, stop,
                f"{CATALOG[pid][0]}: wick {word} {name} {lvl:.1f} (stop-uri luate) și închidere înapoi "
                f"în range -> lichiditate colectată, inversare probabilă",
                sweep_level=1.0, level_strength=float(best[0]))
        if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 82 / 89 BOS + retest continuation into OB / FVG
# ---------------------------------------------------------------------------
@detector(82, 89)
def bos_retest(st: MarketState) -> List[Detection]:
    out = []
    for side, ev in ((BUY, "BOS_UP"), (SELL, "BOS_DN")):
        if not st.recent(ev, 25) or st.i == st.events[ev]:
            continue
        if (side == BUY and st.structure.trend != 1) or (side == SELL and st.structure.trend != -1):
            continue
        z = st.zone_touch(side, kinds=("OB", "FVG"))
        if not z:
            continue
        b = st.bar
        reject = b.close > b.open if side == BUY else b.close < b.open
        if not reject:
            continue
        pid = 82 if st.i - st.events[ev] <= 8 else 89
        stop = min(z.bottom, b.low) if side == BUY else max(z.top, b.high)
        d = _mk(st, pid, side, stop,
                f"{ev.replace('_', ' ')} confirmat, retragere în {z.kind} {z.bottom:.1f}-{z.top:.1f} "
                f"și lumânare de respingere -> continuare trend (Retest & Continuation)",
                zone_fvg=1.0 if z.kind == "FVG" else 0.0)
        if d:
            z.mitigated = True
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# 83 / 84  CHOCH -> MSS entry on first retrace
# ---------------------------------------------------------------------------
@detector(83, 84)
def choch_mss(st: MarketState) -> List[Detection]:
    out = []
    for side, ev, disp in ((BUY, "CHOCH_UP", "DISPLACEMENT_UP"), (SELL, "CHOCH_DN", "DISPLACEMENT_DN")):
        if not st.recent(ev, 20) or st.i == st.events[ev]:
            continue
        z = st.zone_touch(side, kinds=("FVG", "OB"))
        if not z or z.created < st.events[ev] - 15:
            continue
        b = st.bar
        if (side == BUY and b.close <= b.open) or (side == SELL and b.close >= b.open):
            continue
        with_disp = st.recent(disp, 25)
        pid = 84 if with_disp else 83
        stop = min(z.bottom, b.low) if side == BUY else max(z.top, b.high)
        d = _mk(st, pid, side, stop,
                f"{'MSS' if with_disp else 'CHOCH'}: structura s-a întors "
                f"({'bullish' if side == BUY else 'bearish'})"
                f"{' cu deplasare' if with_disp else ''}; intrare la prima retragere în {z.kind}",
                displacement=1.0 if with_disp else 0.0)
        if d:
            z.mitigated = True
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# 32 Breaker block retest
# ---------------------------------------------------------------------------
@detector(32)
def breaker(st: MarketState) -> List[Detection]:
    out = []
    b = st.bar
    for side in (BUY, SELL):
        z = st.zone_touch(side, kinds=("BREAKER",))
        if not z:
            continue
        if (side == BUY and b.close <= b.open) or (side == SELL and b.close >= b.open):
            continue
        stop = min(z.bottom, b.low) if side == BUY else max(z.top, b.high)
        d = _mk(st, 32, side, stop,
                f"Breaker block: OB invalidat {z.bottom:.1f}-{z.top:.1f} retestat din partea cealaltă "
                f"(polaritate inversată)")
        if d:
            z.mitigated = True
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# 59 / 60 / 27 / 28  Double & triple top / bottom (neckline break)
# ---------------------------------------------------------------------------
@detector(27, 28, 59, 60)
def multi_top_bottom(st: MarketState) -> List[Detection]:
    out = []
    b, prev = st.bar, st.bars[-2] if len(st.bars) > 1 else None
    if prev is None:
        return out
    tol = 0.3 * st.atr_v
    for kind, side in (("H", SELL), ("L", BUY)):
        tops = [s for s in st.zz.swings[-7:] if s.kind == kind]
        if len(tops) < 2:
            continue
        ref = tops[-1]
        eq = [t for t in tops if abs(t.price - ref.price) <= tol]
        if len(eq) < 2:
            continue
        first = eq[0].index
        mids = [s for s in st.zz.swings if s.kind != kind and first < s.index < ref.index]
        if not mids:
            continue
        neck = min(m.price for m in mids) if side == SELL else max(m.price for m in mids)
        broke = (prev.close >= neck > b.close) if side == SELL else (prev.close <= neck < b.close)
        if not broke:
            continue
        n = len(eq)
        pid = {(SELL, 2): 59, (BUY, 2): 60}.get((side, n), 27 if side == SELL else 28)
        measured = abs(ref.price - neck)
        target = neck - measured if side == SELL else neck + measured
        stop = (ref.price + neck) / 2
        d = _mk(st, pid, side, stop,
                f"{CATALOG[pid][0]}: {n} {'maxime' if side == SELL else 'minime'} egale la ~{ref.price:.1f}, "
                f"neckline {neck:.1f} spart pe închidere", target=target, touches=float(n))
        if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 57 / 58  Head & Shoulders
# ---------------------------------------------------------------------------
@detector(57, 58)
def head_shoulders(st: MarketState) -> List[Detection]:
    out = []
    sw = st.zz.last(6)
    if len(sw) < 5 or len(st.bars) < 2:
        return out
    b, prev = st.bar, st.bars[-2]
    atr = st.atr_v
    for kind, side in (("H", SELL), ("L", BUY)):
        seq = sw[-5:] if sw[-1].kind == kind else sw[-6:-1]
        if len(seq) < 5 or "".join(s.kind for s in seq) != (kind + ("L" if kind == "H" else "H")) * 2 + kind:
            continue
        ls, n1, hd, n2, rs = seq
        sgn = 1 if kind == "H" else -1
        if not (sgn * (hd.price - ls.price) > 0.5 * atr and sgn * (hd.price - rs.price) > 0.5 * atr
                and abs(ls.price - rs.price) < 1.2 * atr):
            continue
        neck = (n1.price + n2.price) / 2
        broke = (prev.close >= neck > b.close) if side == SELL else (prev.close <= neck < b.close)
        if not broke:
            continue
        pid = 58 if side == SELL else 57
        target = neck - (hd.price - neck) if side == SELL else neck + (neck - hd.price)
        d = _mk(st, pid, side, rs.price, f"{CATALOG[pid][0]}: cap {hd.price:.1f}, umeri ~{ls.price:.1f}/"
                f"{rs.price:.1f}, neckline {neck:.1f} spart", target=target)
        if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 17  Three drives into exhaustion + CHOCH
# ---------------------------------------------------------------------------
@detector(17)
def three_drive(st: MarketState) -> List[Detection]:
    out = []
    for ev, kind, side, lab in (("CHOCH_DN", "H", SELL, "HH"), ("CHOCH_UP", "L", BUY, "LL")):
        if st.events.get(ev) != st.i:
            continue
        drives = [s for s in st.zz.swings[-8:] if s.kind == kind]
        if len(drives) >= 3 and all(d.label == lab for d in drives[-2:]):
            ext = [abs(drives[k].price - drives[k - 1].price) for k in (-2, -1)]
            if ext[1] <= ext[0] * 1.3:  # momentum fading
                d = _mk(st, 17, side, drives[-1].price,
                        f"3 Drive: trei împingeri ({', '.join(f'{x.price:.1f}' for x in drives[-3:])}) "
                        f"cu extensii descrescătoare + CHOCH -> epuizare")
                if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 19 / 20  Compression into a level then breakout against it (Compression Liquidity)
# ---------------------------------------------------------------------------
@detector(19, 20)
def compression(st: MarketState) -> List[Detection]:
    out = []
    if len(st.bars) < 12:
        return out
    win = st.bars[-11:-1]
    b = st.bar
    atr = st.atr_v
    avg_rng = sum(x.range for x in win) / len(win)
    if avg_rng > 0.7 * atr:
        return out
    hi = max(x.high for x in win)
    lo = min(x.low for x in win)
    if hi - lo > 3.5 * atr:
        return out
    half = win[:5]
    took_low = min(x.low for x in win[5:]) < min(x.low for x in half)
    took_high = max(x.high for x in win[5:]) > max(x.high for x in half)
    if b.close > hi and b.range > 1.3 * avg_rng and b.bullish:
        d = _mk(st, 20 if took_low else 19, BUY, lo, f"Compresie: 10 lumânări înguste ({lo:.1f}-{hi:.1f}), "
                f"spargere în sus cu expansiune -> lichiditatea compresiei alimentează mișcarea")
        if d: out.append(d)
    elif b.close < lo and b.range > 1.3 * avg_rng and not b.bullish:
        d = _mk(st, 20 if took_high else 19, SELL, hi, f"Compresie: 10 lumânări înguste ({lo:.1f}-{hi:.1f}), "
                f"spargere în jos cu expansiune")
        if d: out.append(d)
    return out


def detect_all(st: MarketState) -> List[Detection]:
    from . import patterns_ext  # noqa: F401  (registers the remaining detectors)
    res: List[Detection] = []
    if st.atr.value is None:
        return res
    for _, fn in DETECTORS:
        res.extend(fn(st))
    return res
