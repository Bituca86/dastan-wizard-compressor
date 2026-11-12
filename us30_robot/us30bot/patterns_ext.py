"""Detectors for the remaining cheat-sheet patterns (so that all 91 are covered).

Subjective patterns (wedges, diamonds, Elliott, Can-Can ...) are translated into
objective, swing-based geometry rules. They are heuristics: the self-learning layer
decides, per matrix cell, how much each one is actually worth on US30 M1.
"""
from __future__ import annotations

from typing import List, Optional

from .context import MarketState, fit_line, fit_quadratic
from .models import BUY, SELL, Detection
from .patterns import CATALOG, _mk, detector


def _sg(side: str) -> int:
    return 1 if side == BUY else -1


def _once(st: MarketState, key: str) -> bool:
    """True the first time `key` is seen (prevents re-firing on the same structure)."""
    seen = st.memory.setdefault("_once", set())
    if key in seen:
        return False
    seen.add(key)
    if len(seen) > 5000:
        seen.clear()
    return True


# ---------------------------------------------------------------------------
# Breakout bookkeeping: 8, 9, 13, 14, 15, 16, 24, 26, 90
# ---------------------------------------------------------------------------
def _diamond(st: MarketState, n: int = 8) -> bool:
    sw = st.zz.last(n)
    if len(sw) < n:
        return False
    half = n // 2
    a, b = sw[:half], sw[half:]
    def width(xs):
        hs = [s.price for s in xs if s.kind == "H"]
        ls = [s.price for s in xs if s.kind == "L"]
        return (max(hs) - min(ls)) if hs and ls else 0
    first_exp = width(a[-2:]) > width(a[:2]) * 1.2
    second_con = width(b[-2:]) < width(b[:2]) * 0.8
    return first_exp and second_con


@detector(8, 9, 13, 14, 15, 16, 24, 26, 90)
def breakouts(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    b, p, atr = st.bar, st.prev, st.atr_v
    brks = st.memory.setdefault("breaks", [])
    # 1) register new close-breaks of the last swing high / low
    for kind, side in (("H", BUY), ("L", SELL)):
        sw = st.zz.last_of(kind)
        if not sw or st.i - sw.index < 3:
            continue
        sg = _sg(side)
        if sg * (b.close - sw.price) > 0.1 * atr and sg * (p.close - sw.price) <= 0:
            if any(x["level_i"] == sw.index for x in brks):
                continue
            eq = st.equal_levels(kind)
            touches = eq[1] if eq and abs(eq[0] - sw.price) < 0.4 * atr else 1
            rng = st.find_range()
            brks.append({"side": side, "level": sw.price, "level_i": sw.index, "i": st.i,
                         "touches": touches, "range": bool(rng), "diamond": _diamond(st),
                         "retested": False, "fired": False})
            if touches >= 3 and rng:
                d = _mk(st, 16, side, rng[1] if side == BUY else rng[0],
                        f"Double SSR: nivel atins de {touches} ori ({sw.price:.1f}) spart pe închidere "
                        f"din range -> lichiditatea acumulată alimentează continuarea", touches=float(touches))
                if d: out.append(d)
    # 2) manage active breaks
    keep = []
    for x in brks:
        side, lvl, age = x["side"], x["level"], st.i - x["i"]
        sg = _sg(side)
        if age > 40 or age == 0:
            if age == 0:
                keep.append(x)
            continue
        failed = sg * (b.close - lvl) < -0.1 * atr
        if failed:
            opp = SELL if side == BUY else BUY
            if age <= 5:
                pid = 15 if x["diamond"] else 9 if x["touches"] >= 2 else 14 if x["retested"] else 13
            elif x["retested"]:
                pid = 90
            else:
                continue
            ext = max(st.bars[k].high for k in range(x["i"], st.i + 1)) if side == BUY else \
                min(st.bars[k].low for k in range(x["i"], st.i + 1))
            d = _mk(st, pid, opp, ext,
                    f"{CATALOG[pid][0]}: spargere {'în sus' if side == BUY else 'în jos'} a nivelului "
                    f"{lvl:.1f} eșuată, închidere înapoi sub/peste nivel -> breakout fals, "
                    f"traderii prinși alimentează mișcarea opusă", fakeout=1.0)
            if d: out.append(d)
            continue
        touched = (b.low <= lvl + 0.25 * atr) if side == BUY else (b.high >= lvl - 0.25 * atr)
        if touched and age >= 2:
            x["retested"] = True
            if not x["fired"] and st.rejection(side) and sg * (b.close - lvl) > 0:
                pierce = (lvl - b.low) if side == BUY else (b.high - lvl)
                if x["range"]:
                    pid = 26
                elif pierce > 0.15 * atr and st.structure.trend == sg:
                    pid = 8
                else:
                    pid = 24
                stop = min(b.low, lvl) if side == BUY else max(b.high, lvl)
                d = _mk(st, pid, side, stop,
                        f"{CATALOG[pid][0]}: nivelul spart {lvl:.1f} retestat din partea cealaltă și "
                        f"respins -> rezistența a devenit suport" if side == BUY else
                        f"{CATALOG[pid][0]}: nivelul spart {lvl:.1f} retestat de jos și respins -> "
                        f"suportul a devenit rezistență")
                if d:
                    x["fired"] = True
                    out.append(d)
        keep.append(x)
    st.memory["breaks"] = keep[-12:]
    return out


# ---------------------------------------------------------------------------
# Chart geometry: 22, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72
# ---------------------------------------------------------------------------
def _geometry(st: MarketState, n: int = 6) -> Optional[dict]:
    sw = st.zz.last(n)
    if len(sw) < n:
        return None
    key = sw[-1].index
    cache = st.memory.get("geo")
    if cache and cache.get("key") == key:
        return cache["g"]
    hs = [(s.index, s.price) for s in sw if s.kind == "H"]
    ls = [(s.index, s.price) for s in sw if s.kind == "L"]
    g = None
    lu, ll = fit_line(hs), fit_line(ls)
    atr = st.atr_v
    if lu and ll and lu[2] <= 0.7 * atr and ll[2] <= 0.7 * atr:
        i0, i1 = sw[0].index, sw[-1].index
        span = max(1, i1 - i0)
        du, dl = lu[0] * span / atr, ll[0] * span / atr
        w0 = (lu[0] * i0 + lu[1]) - (ll[0] * i0 + ll[1])
        w1 = (lu[0] * i1 + lu[1]) - (ll[0] * i1 + ll[1])
        if w0 > 0 and w1 > 0:
            flat = 0.8
            conv, div = w1 < 0.75 * w0, w1 > 1.3 * w0
            up_f, lo_f = abs(du) < flat, abs(dl) < flat
            if up_f and lo_f:
                kind = 69
            elif up_f and dl > 0:
                kind = 64
            elif lo_f and du < 0:
                kind = 63
            elif du < 0 < dl:
                kind = 65
            elif du > 0 > dl:
                kind = 72
            elif du > 0 and dl > 0:
                kind = 68 if conv else 66 if div else None
            elif du < 0 and dl < 0:
                kind = 67 if conv else 66 if div else None
            else:
                kind = None
            if kind == 68 and len(st.zz.swings) >= n + 2 and \
                    st.zz.swings[-n - 1].price < sw[0].price - 2 * atr:
                kind = 22  # wedge at the end of an extended up-move = ending diagonal
            if kind == 67 and len(st.zz.swings) >= n + 2 and \
                    st.zz.swings[-n - 1].price > sw[0].price + 2 * atr:
                kind = 22
            if kind:
                g = {"kind": kind, "up": lu, "lo": ll, "hs": hs, "ls": ls, "end": i1}
    if _diamond(st):
        sw8 = st.zz.last(8)
        g = {"kind": "diamond", "hs": [(s.index, s.price) for s in sw8 if s.kind == "H"],
             "ls": [(s.index, s.price) for s in sw8 if s.kind == "L"],
             "up": fit_line([(s.index, s.price) for s in sw8[4:] if s.kind == "H"] or [(0, 0)]),
             "lo": fit_line([(s.index, s.price) for s in sw8[4:] if s.kind == "L"] or [(0, 0)]),
             "end": sw8[-1].index}
    st.memory["geo"] = {"key": key, "g": g}
    return g


# which breakout directions are tradeable for each geometry
_GEO_DIRS = {63: (SELL,), 64: (BUY,), 65: (BUY, SELL), 66: (BUY, SELL), 67: (BUY,), 68: (SELL,),
             69: (BUY, SELL), 72: (BUY, SELL), 22: (BUY, SELL)}


@detector(22, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72)
def chart_geometry(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    g = _geometry(st)
    if not g or not g["up"] or not g["lo"] or st.i - g["end"] > 40:
        return out
    b, p = st.bar, st.prev
    up = g["up"][0] * st.i + g["up"][1]
    lo = g["lo"][0] * st.i + g["lo"][1]
    up_p = g["up"][0] * (st.i - 1) + g["up"][1]
    lo_p = g["lo"][0] * (st.i - 1) + g["lo"][1]
    side = None
    if b.close > up and p.close <= up_p:
        side = BUY
    elif b.close < lo and p.close >= lo_p:
        side = SELL
    if not side:
        return out
    kind = g["kind"]
    if kind == "diamond":
        pid = 71 if side == BUY else 70
    else:
        if side not in _GEO_DIRS.get(kind, ()):
            return out
        if kind == 22:  # ending diagonal: trade against the wedge's direction only
            if (g["up"][0] > 0 and side == BUY) or (g["up"][0] < 0 and side == SELL):
                return out
        pid = kind
    if not _once(st, f"geo{pid}{g['end']}{side}"):
        return out
    stop = g["ls"][-1][1] if side == BUY else g["hs"][-1][1]
    height = max(h for _, h in g["hs"]) - min(l for _, l in g["ls"])
    target = b.close + _sg(side) * height
    d = _mk(st, pid, side, stop,
            f"{CATALOG[pid][0]}: linii de trend trasate prin {len(g['hs'])} maxime și {len(g['ls'])} minime; "
            f"închidere {'peste linia superioară' if side == BUY else 'sub linia inferioară'} "
            f"-> breakout, țintă = înălțimea figurii ({height:.0f} pct)", target=target)
    if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 11 / 12 Flags after an impulse
# ---------------------------------------------------------------------------
@detector(11, 12)
def flags(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    atr = st.atr_v
    for side, ev in ((BUY, "DISPLACEMENT_UP"), (SELL, "DISPLACEMENT_DN")):
        if not st.recent(ev, 40):
            continue
        k = st.events[ev]
        n = st.i - k - 1  # bars in the flag (excluding current)
        if n < 5:
            continue
        flag = st.bars[k + 1:st.i]
        imp = st.bars[k]
        hi, lo = max(x.high for x in flag), min(x.low for x in flag)
        if hi - lo > 0.6 * max(imp.range, 2 * atr) or hi - lo > 4 * atr:
            continue
        b = st.bar
        sg = _sg(side)
        broke = b.close > hi if side == BUY else b.close < lo
        engulf = (b.bullish if side == BUY else not b.bullish) and b.body >= 0.6 * b.range
        if not (broke and engulf):
            continue
        cnt_key = f"flag_{ev}_{k}"
        cnt = st.memory.get(cnt_key, 0) + 1
        st.memory[cnt_key] = cnt
        pid = 12 if st.memory.get(f"lastflag_{side}", -999) >= st.i - 120 else 11
        st.memory[f"lastflag_{side}"] = st.i
        d = _mk(st, pid, side, lo if side == BUY else hi,
                f"{CATALOG[pid][0]}: impuls {('în sus' if sg > 0 else 'în jos')} urmat de consolidare îngustă "
                f"({lo:.1f}-{hi:.1f}, {n} lumânări); lumânare engulfing de ieșire din steag")
        if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 18 / 21 Can-Can (slow grinding correction after an impulse) (+ fakeout)
# ---------------------------------------------------------------------------
@detector(18, 21)
def can_can(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    sw = st.zz.last(2)
    if len(sw) < 2:
        return out
    a, c = sw
    atr = st.atr_v
    side = SELL if (a.kind == "H" and c.kind == "L") else BUY
    leg = abs(a.price - c.price)
    if leg < 4 * atr or c.index - a.index > 20:
        return out
    corr = st.bars[c.index + 1:st.i]
    if len(corr) < 12:
        return out
    if sum(x.range for x in corr) / len(corr) > 0.75 * atr:
        return out
    ext = max(x.high for x in corr) if side == SELL else min(x.low for x in corr)
    retr = abs(ext - c.price) / leg
    if not 0.25 <= retr <= 0.75:
        return out
    b = st.bar
    trig = min(x.low for x in corr[-6:]) if side == SELL else max(x.high for x in corr[-6:])
    if (side == SELL and b.close < trig) or (side == BUY and b.close > trig):
        if not _once(st, f"cancan{c.index}"):
            return out
        # fake higher-high inside the correction?
        if side == SELL:
            piv = [corr[j] for j in range(1, len(corr) - 1)
                   if corr[j].high > corr[j - 1].high and corr[j].high >= corr[j + 1].high]
        else:
            piv = [corr[j] for j in range(1, len(corr) - 1)
                   if corr[j].low < corr[j - 1].low and corr[j].low <= corr[j + 1].low]
        fake = len(piv) >= 2 and ((piv[-1].high > piv[-2].high) if side == SELL else (piv[-1].low < piv[-2].low))
        pid = 21 if fake else 18
        d = _mk(st, pid, side, ext,
                f"{CATALOG[pid][0]}: impuls de {leg:.0f} pct, corecție lentă de {len(corr)} lumânări "
                f"({retr:.0%} retragere){' cu fakeout în corecție' if fake else ''}; "
                f"spargerea corecției reia impulsul")
        if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 23 Ruler, 25 Inside range, 46 Trendline liquidity
# ---------------------------------------------------------------------------
@detector(23, 25, 46)
def levels_and_lines(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    b, atr = st.bar, st.atr_v
    tol = 0.35 * atr
    # Ruler: flat support with rising highs (or flat resistance with falling lows)
    for kind, okind, side in (("L", "H", BUY), ("H", "L", SELL)):
        fl = [s for s in st.zz.swings[-8:] if s.kind == kind]
        ot = [s for s in st.zz.swings[-8:] if s.kind == okind]
        if len(fl) >= 3 and len(ot) >= 3:
            lvl = sum(s.price for s in fl[-3:]) / 3
            flat = all(abs(s.price - lvl) <= tol for s in fl[-3:])
            trend = all((ot[j].price > ot[j - 1].price) if side == BUY else (ot[j].price < ot[j - 1].price)
                        for j in range(len(ot) - 2, len(ot)))
            near = (b.low <= lvl + tol) if side == BUY else (b.high >= lvl - tol)
            if flat and trend and near and st.rejection(side) and _once(st, f"ruler{st.i}{side}"):
                d = _mk(st, 23, side, lvl,
                        f"Ruler: nivel plat atins de 3 ori ({lvl:.1f}) cu {'maxime crescătoare' if side == BUY else 'minime descrescătoare'}; "
                        f"respingere la a 4-a atingere")
                if d: out.append(d)
    # Inside range fade
    rg = st.find_range()
    if rg:
        hi, lo = rg[0], rg[1]
        if b.high >= hi - tol and b.close < hi and st.rejection(SELL):
            d = _mk(st, 25, SELL, max(b.high, hi), f"Inside Range: respingere la marginea superioară "
                    f"{hi:.1f} (range {lo:.1f}-{hi:.1f}, {rg[2]}/{rg[3]} atingeri) -> țintă marginea opusă",
                    target=lo + 0.1 * (hi - lo))
            if d: out.append(d)
        elif b.low <= lo + tol and b.close > lo and st.rejection(BUY):
            d = _mk(st, 25, BUY, min(b.low, lo), f"Inside Range: respingere la marginea inferioară "
                    f"{lo:.1f} (range {lo:.1f}-{hi:.1f}) -> țintă marginea opusă", target=hi - 0.1 * (hi - lo))
            if d: out.append(d)
    # Trendline: 3 aligned swings, trade the 4th touch
    for kind, side in (("H", SELL), ("L", BUY)):
        pts = [s for s in st.zz.swings[-7:] if s.kind == kind][-3:]
        if len(pts) < 3 or st.i - pts[-1].index < 3:
            continue
        ln = fit_line([(s.index, s.price) for s in pts])
        if not ln or ln[2] > 0.3 * atr:
            continue
        if (side == SELL and ln[0] >= 0) or (side == BUY and ln[0] <= 0):
            continue
        v = ln[0] * st.i + ln[1]
        near = (b.high >= v - 0.2 * atr and b.close < v) if side == SELL else (b.low <= v + 0.2 * atr and b.close > v)
        if near and st.rejection(side) and _once(st, f"tl{pts[-1].index}{side}"):
            d = _mk(st, 46, side, b.high if side == SELL else b.low,
                    f"Trendline Liquidity: linie {'descendentă' if side == SELL else 'ascendentă'} prin 3 "
                    f"{'maxime' if side == SELL else 'minime'}, respingere la a 4-a atingere ({v:.1f})")
            if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# Zone retests: 29, 30, 33, 35, 80, 87, 85, 86
# ---------------------------------------------------------------------------
_ZONE_PID = {"OB": 31, "FVG": 34, "DEMAND": 29, "SUPPLY": 30, "MITIGATION": 33, "VOID": 35, "WICK": 80, "VI": 87}
_ZONE_TXT = {31: "order block (ultima lumânare opusă înaintea impulsului)", 34: "FVG / imbalance (gol de preț în 3 lumânări)",
             29: "zonă de cerere (bază înaintea unui impuls)", 30: "zonă de ofertă (bază înaintea unui impuls)",
             33: "mitigation block (swing eșuat fără lichiditate luată)",
             35: "liquidity void (lumânare uriașă, zonă cu ordine puține)",
             80: "fitil neumplut (respingere puternică anterioară)", 87: "volume imbalance (corpuri fără suprapunere)"}


@detector(29, 30, 31, 33, 34, 35, 80, 87, 85, 86)
def zone_retests(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    b = st.bar
    for side in (BUY, SELL):
        if not st.rejection(side):
            continue
        for kind, pid in _ZONE_PID.items():
            z = st.zone_touch(side, kinds=(kind,), min_age=3)
            if not z:
                continue
            stop = min(z.bottom, b.low) if side == BUY else max(z.top, b.high)
            d = _mk(st, pid, side, stop, f"{CATALOG[pid][0]}: retest al {_ZONE_TXT[pid]} "
                    f"{z.bottom:.1f}-{z.top:.1f} cu lumânare de respingere")
            if d:
                z.mitigated = True
                out.append(d)
        # higher timeframe point of interest
        h = st.htf
        if h is None or not h.zones:
            continue
        for z in reversed(h.zones):
            if z.mitigated or z.side != side or z.kind not in ("OB", "FVG", "DEMAND", "SUPPLY", "BREAKER"):
                continue
            inside = (b.low <= z.top and b.close >= z.bottom) if side == BUY else (b.high >= z.bottom and b.close <= z.top)
            if not inside:
                continue
            sg = _sg(side)
            mtf = st.recent("CHOCH_UP" if side == BUY else "CHOCH_DN", 15) and h.structure.trend == sg
            pid = 86 if mtf else 85
            if not _once(st, f"htf{id(z)}{pid}"):
                break
            stop = min(z.bottom, b.low) if side == BUY else max(z.top, b.high)
            d = _mk(st, pid, side, stop,
                    f"{CATALOG[pid][0]}: preț în {z.kind} M15 {z.bottom:.1f}-{z.top:.1f}"
                    + (" + CHOCH pe M1 + trend M15 aliniat (confluență multi-timeframe)" if mtf else
                       " cu respingere pe M1"), htf_zone=1.0)
            if d: out.append(d)
            break
    return out


# ---------------------------------------------------------------------------
# 36 Premium / Discount (OTE 62-79%)
# ---------------------------------------------------------------------------
@detector(36)
def ote(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    sw = st.zz.last(2)
    if len(sw) < 2:
        return out
    a, c = sw
    b = st.bar
    if a.kind == "L" and c.kind == "H" and st.structure.trend == 1:
        leg = c.price - a.price
        r = (c.price - b.low) / leg if leg > 0 else 0
        if 0.62 <= r <= 0.85 and st.rejection(BUY) and _once(st, f"ote{c.index}"):
            d = _mk(st, 36, BUY, a.price, f"Discount/OTE: retragere de {r:.0%} din impulsul "
                    f"{a.price:.1f}->{c.price:.1f} în trend ascendent, respingere în zona de discount",
                    target=c.price)
            if d: out.append(d)
    if a.kind == "H" and c.kind == "L" and st.structure.trend == -1:
        leg = a.price - c.price
        r = (b.high - c.price) / leg if leg > 0 else 0
        if 0.62 <= r <= 0.85 and st.rejection(SELL) and _once(st, f"ote{c.index}"):
            d = _mk(st, 36, SELL, a.price, f"Premium/OTE: retragere de {r:.0%} din impulsul "
                    f"{a.price:.1f}->{c.price:.1f} în trend descendent, respingere în zona premium",
                    target=c.price)
            if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 42 News liquidity grab, 81 gap fill, 91 final shakeout, 49 parabolic blow-off
# ---------------------------------------------------------------------------
@detector(42, 49, 81, 91)
def spikes(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    b, p, atr = st.bar, st.prev, st.atr_v
    mem = st.memory
    # register events
    if st.clock.is_news_minute(b.time) and b.range >= 2.5 * atr:
        mem["news"] = {"i": st.i, "hi": b.high, "lo": b.low, "up": b.bullish}
    gap = b.open - p.close
    if abs(gap) >= 0.6 * atr and len(st.bars) > 1:
        mem["gap"] = {"i": st.i, "from": p.close, "to": b.open, "up": gap > 0}
    sw_l, sw_h = st.zz.last_of("L"), st.zz.last_of("H")
    if b.range >= 2 * atr:
        if not b.bullish and sw_l and b.close < sw_l.price and st.structure.trend == 1:
            mem["shake"] = {"i": st.i, "side": BUY, "ref": b.open, "ext": b.low}
        if b.bullish and sw_h and b.close > sw_h.price and st.structure.trend == -1:
            mem["shake"] = {"i": st.i, "side": SELL, "ref": b.open, "ext": b.high}
    # news fade
    n = mem.get("news")
    if n and 0 < st.i - n["i"] <= 5:
        mid = (n["hi"] + n["lo"]) / 2
        if n["up"] and b.close < mid and not b.bullish:
            d = _mk(st, 42, SELL, n["hi"], f"News Liquidity Grab: spike la știri până la {n['hi']:.1f}, "
                    f"închidere sub 50% din spike -> lichiditate luată, revenire")
            if d: out.append(d); mem.pop("news")
        elif not n["up"] and b.close > mid and b.bullish:
            d = _mk(st, 42, BUY, n["lo"], f"News Liquidity Grab: spike la știri până la {n['lo']:.1f}, "
                    f"închidere peste 50% din spike -> revenire")
            if d: out.append(d); mem.pop("news")
    # gap fill
    g = mem.get("gap")
    if g and 0 < st.i - g["i"] <= 30:
        if g["up"] and b.close > g["from"] and st.rejection(SELL):
            d = _mk(st, 81, SELL, b.high, f"Gap Fill: gap în sus {g['from']:.1f}->{g['to']:.1f}, "
                    f"respingere -> țintă închiderea gap-ului", target=g["from"])
            if d: out.append(d); mem.pop("gap")
        elif not g["up"] and b.close < g["from"] and st.rejection(BUY):
            d = _mk(st, 81, BUY, b.low, f"Gap Fill: gap în jos {g['from']:.1f}->{g['to']:.1f}, "
                    f"respingere -> țintă închiderea gap-ului", target=g["from"])
            if d: out.append(d); mem.pop("gap")
    # final shakeout
    s = mem.get("shake")
    if s and 0 < st.i - s["i"] <= 4:
        rec = b.close > s["ref"] if s["side"] == BUY else b.close < s["ref"]
        if rec:
            d = _mk(st, 91, s["side"], s["ext"], f"Final Shakeout: spargere violentă contra trendului "
                    f"(până la {s['ext']:.1f}) recuperată integral în {st.i - s['i']} lumânări -> "
                    f"ultimii participanți scoși, trendul continuă")
            if d: out.append(d); mem.pop("shake")
    # parabolic blow-off
    if len(st.bars) > 60:
        sma = sum(x.close for x in st.bars[-50:]) / 50
        for kind, side in (("H", SELL), ("L", BUY)):
            pts = [s for s in st.zz.swings[-7:] if s.kind == kind][-3:]
            if len(pts) < 3:
                continue
            mono = (pts[0].price < pts[1].price < pts[2].price) if side == SELL else \
                (pts[0].price > pts[1].price > pts[2].price)
            steep = [abs(pts[k + 1].price - pts[k].price) / max(1, pts[k + 1].index - pts[k].index)
                     for k in range(2)]
            far = (b.high - sma >= 4 * atr) if side == SELL else (sma - b.low >= 4 * atr)
            engulf = (not b.bullish and p.bullish and b.close < p.open) if side == SELL else \
                (b.bullish and not p.bullish and b.close > p.open)
            if mono and steep[1] > steep[0] * 1.2 and far and engulf and _once(st, f"para{pts[-1].index}"):
                d = _mk(st, 49, side, max(b.high, p.high) if side == SELL else min(b.low, p.low),
                        f"Parabolic Blowoff: accelerare (pantă x{steep[1] / max(steep[0], 1e-9):.1f}), "
                        f"preț la {abs(b.close - sma) / atr:.1f} ATR de media 50 + engulfing -> epuizare",
                        target=sma)
                if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 52 / 53 / 56 Wyckoff accumulation / distribution / LPS
# ---------------------------------------------------------------------------
@detector(52, 53, 56)
def wyckoff(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    b, atr = st.bar, st.atr_v
    rg = st.find_range(lookback=10, max_atr=10.0)
    if rg:
        hi, lo, _, _, start = rg
        dur = st.i - start
        if dur >= 40 and start > 60:
            before = st.bars[start - 60].close
            mid = (hi + lo) / 2
            if b.close > hi and b.range >= 1.5 * atr and before > mid + (hi - lo) and _once(st, f"acc{start}"):
                d = _mk(st, 52, BUY, lo + (hi - lo) * 0.4, f"Acumulare: range de {dur} lumânări "
                        f"({lo:.1f}-{hi:.1f}) după scădere, ieșire în sus cu expansiune (SOS)")
                if d: out.append(d)
                st.memory["lps"] = {"side": BUY, "hi": hi, "lo": lo, "i": st.i}
            if b.close < lo and b.range >= 1.5 * atr and before < mid - (hi - lo) and _once(st, f"dis{start}"):
                d = _mk(st, 53, SELL, hi - (hi - lo) * 0.4, f"Distribuție: range de {dur} lumânări "
                        f"({lo:.1f}-{hi:.1f}) după creștere, ieșire în jos cu expansiune (SOW)")
                if d: out.append(d)
                st.memory["lps"] = {"side": SELL, "hi": hi, "lo": lo, "i": st.i}
    l = st.memory.get("lps")
    if l and 2 < st.i - l["i"] <= 60:
        hi, lo = l["hi"], l["lo"]
        if l["side"] == BUY and b.low <= hi + 0.5 * atr and b.low > (hi + lo) / 2 and st.rejection(BUY):
            d = _mk(st, 56, BUY, b.low, f"Wyckoff LPS: prima retragere după acumulare ține deasupra "
                    f"range-ului ({hi:.1f}) -> ultimul punct de suport")
            if d: out.append(d); st.memory.pop("lps")
        elif l["side"] == SELL and b.high >= lo - 0.5 * atr and b.high < (hi + lo) / 2 and st.rejection(SELL):
            d = _mk(st, 56, SELL, b.high, f"Wyckoff LPSY: prima retragere după distribuție se oprește "
                    f"sub range ({lo:.1f}) -> ultimul punct de ofertă")
            if d: out.append(d); st.memory.pop("lps")
    return out


# ---------------------------------------------------------------------------
# 61 / 62 Rounding bottom / top
# ---------------------------------------------------------------------------
@detector(61, 62)
def rounding(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    n = 40
    if len(st.bars) < n + 2 or st.i % 2:
        return out
    ys = [x.close for x in st.bars[-n - 1:-1]]
    q = fit_quadratic(ys)
    if not q:
        return out
    a, bq, _, r2 = q
    if r2 < 0.7:
        return out
    vx = -bq / (2 * a) if a else -1
    if not 0.3 * n <= vx <= 0.7 * n:
        return out
    depth = abs(a) * (n / 2) ** 2
    if depth < 2.5 * st.atr_v:
        return out
    b = st.bar
    rim = max(ys[:5]) if a > 0 else min(ys[:5])
    if a > 0 and b.close > rim and _once(st, f"rb{st.i // 20}"):
        d = _mk(st, 61, BUY, min(ys), f"Rounding Bottom: formă de U (R²={r2:.2f}, adâncime {depth:.0f} pct), "
                f"închidere peste marginea stângă {rim:.1f}")
        if d: out.append(d)
    if a < 0 and b.close < rim and _once(st, f"rt{st.i // 20}"):
        d = _mk(st, 62, SELL, max(ys), f"Rounding Top: formă de U inversat (R²={r2:.2f}), "
                f"închidere sub marginea stângă {rim:.1f}")
        if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 73 / 74 Stepping highs / lows
# ---------------------------------------------------------------------------
@detector(73, 74)
def stepping(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    sw = st.zz.last(7)
    if len(sw) < 7:
        return out
    hl = [s.label for s in sw]
    ups = sum(1 for l in hl if l in ("HH", "HL"))
    dns = sum(1 for l in hl if l in ("LH", "LL"))
    for side, stair in ((BUY, ups >= 6), (SELL, dns >= 6)):
        if not stair:
            continue
        z = st.zone_touch(side, kinds=("OB", "FVG", "DEMAND", "SUPPLY"))
        if z and st.rejection(side):
            stop = min(z.bottom, st.bar.low) if side == BUY else max(z.top, st.bar.high)
            d = _mk(st, 73, side, stop, f"Stepping {'Highs' if side == BUY else 'Lows'}: scară de "
                    f"{ups if side == BUY else dns} swing-uri în trend, retest al ultimei trepte "
                    f"({z.kind}) -> continuare")
            if d: out.append(d)
        # exhaustion of the staircase -> reversal (74)
        ev = "CHOCH_DN" if side == BUY else "CHOCH_UP"
        if st.events.get(ev) == st.i:
            opp = SELL if side == BUY else BUY
            ext = max(s.price for s in sw if s.kind == "H") if opp == SELL else min(s.price for s in sw if s.kind == "L")
            d = _mk(st, 74, opp, ext, f"Stepping {'Highs' if side == BUY else 'Lows'} epuizat: după "
                    f"{len(sw)} trepte lichiditatea de sub/peste trepte e țintă; CHOCH confirmă inversarea")
            if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 75 / 76 / 77 Elliott
# ---------------------------------------------------------------------------
def _confirm_turn(st: MarketState, side: str, piv_index: int, within: int = 10) -> bool:
    if not 0 < st.i - piv_index <= within + 20:
        return False
    b = st.bar
    last3 = st.bars[-4:-1]
    return (b.close > max(x.high for x in last3)) if side == BUY else (b.close < min(x.low for x in last3))


@detector(75, 76, 77)
def elliott(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    sw = st.zz.last(5)
    if len(sw) < 5:
        return out
    p0, p1, p2, p3, p4 = sw
    for side in (BUY, SELL):
        sg = _sg(side)
        first = "L" if side == BUY else "H"
        if p0.kind != first:
            continue
        v = [sg * s.price for s in sw]  # transform so that bullish logic works for both
        l1, l3 = v[1] - v[0], v[3] - v[2]
        # 75 impulse, entry after wave 4 for wave 5
        if v[2] > v[0] and v[3] > v[1] and l1 > 0 and l3 >= 0.618 * l1 and v[4] > v[1] \
                and 0.2 <= (v[3] - v[4]) / max(l3, 1e-9) <= 0.62:
            if _confirm_turn(st, side, p4.index) and _once(st, f"ew5{p4.index}"):
                tgt = p4.price + sg * l1
                d = _mk(st, 75, side, p4.price, f"Elliott 1-2-3-4-5: undele 1-4 respectă regulile "
                        f"(2 nu depășește 0, 3 nu e cea mai scurtă, 4 nu intră în 1); intrare pentru unda 5 "
                        f"(țintă 5=1 la {tgt:.1f})", target=tgt)
                if d: out.append(d)
        # 76 / 77 corrective against the trend, entry at end of C / Y
        # bullish: p1=H0 (top), p2=A, p3=B, p4=C ; in transformed space bullish => p1 high
    for side in (BUY, SELL):
        sg = _sg(side)
        h0, a, bb, c = sw[1:]
        if h0.kind != ("H" if side == BUY else "L"):
            continue
        V = [sg * x.price for x in (h0, a, bb, c)]
        wa = V[0] - V[1]
        if wa <= 0:
            continue
        rb = (V[2] - V[1]) / wa
        wc = V[2] - V[3]
        if V[3] >= V[1] or V[2] >= V[0]:
            continue
        ratio = wc / wa
        if 0.38 <= rb <= 0.79 and 0.8 <= ratio <= 1.27:
            pid = 76
        elif 0.15 <= rb < 0.38 and 0.7 <= ratio <= 1.4:
            pid = 77
        else:
            continue
        if _confirm_turn(st, side, c.index) and _once(st, f"ew{pid}{c.index}"):
            d = _mk(st, pid, side, c.price, f"{CATALOG[pid][0]}: corecție în 3 valuri "
                    f"({'B' if pid == 76 else 'X'} retrage {rb:.0%}, {'C' if pid == 76 else 'Y'}≈"
                    f"{ratio:.2f}x{'A' if pid == 76 else 'W'}), întoarcere confirmată -> reluarea trendului",
                    target=h0.price)
            if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 78 / 79 Liquidity runs (displacement through buy-/sell-side liquidity)
# ---------------------------------------------------------------------------
@detector(78, 79)
def liquidity_run(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    b, p, atr = st.bar, st.prev, st.atr_v
    if not st.is_displacement(st.i, 1.5):
        return out
    side = BUY if b.bullish else SELL
    levels = st.liquidity_levels(SELL if side == BUY else BUY)
    for name, lvl in levels:
        crossed = (b.close > lvl + 0.2 * atr and p.close <= lvl) if side == BUY else \
            (b.close < lvl - 0.2 * atr and p.close >= lvl)
        if crossed:
            pid = 78 if side == BUY else 79
            d = _mk(st, pid, side, b.low if side == BUY else b.high,
                    f"{CATALOG[pid][0]}: lumânare de deplasare închide {'peste' if side == BUY else 'sub'} "
                    f"{name} {lvl:.1f} -> lichiditatea {'BSL' if side == BUY else 'SSL'} a fost consumată cu "
                    f"intenție, continuare spre următorul pool", displacement=1.0)
            if d: out.append(d)
            break
    return out


# ---------------------------------------------------------------------------
# 10 V Twin (two sharp V pivots at the same level)
# ---------------------------------------------------------------------------
@detector(10)
def v_twin(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    atr = st.atr_v
    for kind, side in (("L", BUY), ("H", SELL)):
        pv = [s for s in st.zz.swings[-6:] if s.kind == kind][-2:]
        if len(pv) < 2 or abs(pv[0].price - pv[1].price) > 0.4 * atr:
            continue
        def sharp(s):
            lo_i, hi_i = max(0, s.index - 4), min(st.i, s.index + 4)
            seg = st.bars[lo_i:hi_i + 1]
            if side == BUY:
                return max(seg[0].high, seg[-1].high) - s.price >= 2 * atr
            return s.price - min(seg[0].low, seg[-1].low) >= 2 * atr
        if not (sharp(pv[0]) and sharp(pv[1])):
            continue
        mids = [s for s in st.zz.swings if s.kind != kind and pv[0].index < s.index < pv[1].index]
        if not mids:
            continue
        neck = mids[-1].price
        b, p = st.bar, st.prev
        if (side == BUY and p.close <= neck < b.close) or (side == SELL and p.close >= neck > b.close):
            d = _mk(st, 10, side, pv[1].price, f"V Twin: două întoarceri bruște în V la ~{pv[1].price:.1f}, "
                    f"spargerea vârfului dintre ele ({neck:.1f})")
            if d: out.append(d)
    return out


# ---------------------------------------------------------------------------
# 48 Displacement + Reclaim
# ---------------------------------------------------------------------------
@detector(48)
def displacement_reclaim(st: MarketState) -> List[Detection]:
    out: List[Detection] = []
    b = st.bar
    for side, ev in ((BUY, "DISPLACEMENT_UP"), (SELL, "DISPLACEMENT_DN")):
        if not st.recent(ev, 25) or st.i - st.events[ev] < 3:
            continue
        k = st.events[ev]
        d0 = st.bars[k]
        mid = (d0.open + d0.close) / 2
        after = st.bars[k + 1:st.i]
        dipped = (min(x.low for x in after) <= mid) if side == BUY else (max(x.high for x in after) >= mid)
        reclaim = (b.close > d0.high and st.prev.close <= d0.high) if side == BUY else \
            (b.close < d0.low and st.prev.close >= d0.low)
        if dipped and reclaim and _once(st, f"dr{k}"):
            ext = min(x.low for x in after) if side == BUY else max(x.high for x in after)
            d = _mk(st, 48, side, ext, f"Displacement + Reclaim: lumânare de deplasare, retragere în "
                    f"jumătatea ei ({mid:.1f}), apoi recucerirea extremei {d0.high if side == BUY else d0.low:.1f}")
            if d: out.append(d)
    return out
