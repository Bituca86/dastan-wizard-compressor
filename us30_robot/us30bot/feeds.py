"""Data feeds: CSV replay (MT5 / generic export), synthetic US30 M1 generator, MT5 live."""
from __future__ import annotations

import csv
import math
import random
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from .models import Bar


def _parse_time(row: dict) -> datetime:
    keys = {k.lower().strip("<>"): v for k, v in row.items()}
    if "datetime" in keys or "time" in keys and "date" not in keys:
        raw = keys.get("datetime") or keys["time"]
    else:
        raw = f"{keys['date']} {keys['time']}"
    raw = raw.strip().replace(".", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d %H:%M:%S", "%Y%m%d %H%M%S"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw), tz=timezone.utc).replace(tzinfo=None)
    raise ValueError(f"unrecognised timestamp: {raw}")


def csv_bars(path: str, tz_shift_hours: float = 0.0) -> Iterator[Bar]:
    """Reads CSV with columns date,time,open,high,low,close[,tickvol|volume] or datetime,...
    Tab / comma / semicolon delimiters supported (MT5 'Export bars' works out of the box).
    tz_shift_hours converts broker server time to UTC (e.g. -2 for GMT+2 servers)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        rd = csv.DictReader(fh, dialect=dialect)
        for row in rd:
            k = {key.lower().strip("<>"): val for key, val in row.items() if key}
            t = _parse_time(row) + timedelta(hours=tz_shift_hours)
            vol = float(k.get("tickvol") or k.get("volume") or k.get("vol") or 0)
            yield Bar(t, float(k["open"]), float(k["high"]), float(k["low"]), float(k["close"]), vol)


def synthetic_bars(n: int = 20000, seed: int = 1, start: Optional[datetime] = None,
                   price: float = 44000.0) -> Iterator[Bar]:
    """US30-like M1 random walk: session-dependent volatility, trending/ranging regimes and
    occasional liquidity sweeps (spike beyond recent extreme then reversal)."""
    rng = random.Random(seed)
    t = start or datetime(2026, 1, 5, 0, 0)
    drift, regime_left = 0.0, 0
    hist = []
    for _ in range(n):
        if t.weekday() >= 5:
            t += timedelta(minutes=1)
            continue
        h = t.hour + t.minute / 60
        vol = 4.0 if h < 7 else 9.0 if h < 14.5 else 22.0 if h < 16 else 12.0 if h < 21 else 3.0
        if regime_left <= 0:
            drift = rng.choice([0.0, 0.0, 0.25, -0.25]) * vol
            regime_left = rng.randint(60, 400)
        regime_left -= 1
        o = price
        c = o + drift + rng.gauss(0, vol)
        hi = max(o, c) + abs(rng.gauss(0, vol * 0.5))
        lo = min(o, c) - abs(rng.gauss(0, vol * 0.5))
        if len(hist) > 30 and rng.random() < 0.01:  # liquidity sweep
            ext_hi = max(b.high for b in hist[-30:])
            ext_lo = min(b.low for b in hist[-30:])
            if rng.random() < 0.5 and ext_hi - c < 3 * vol:
                hi = ext_hi + abs(rng.gauss(vol, vol * 0.3))
                c = o - abs(rng.gauss(0, vol * 0.3))
                drift = -abs(drift) - 0.3 * vol
            elif ext_lo < c and c - ext_lo < 3 * vol:
                lo = ext_lo - abs(rng.gauss(vol, vol * 0.3))
                c = o + abs(rng.gauss(0, vol * 0.3))
                drift = abs(drift) + 0.3 * vol
            hi, lo = max(hi, o, c), min(lo, o, c)
        b = Bar(t, round(o, 1), round(hi, 1), round(lo, 1), round(c, 1), rng.randint(50, 500))
        hist.append(b)
        if len(hist) > 60:
            hist.pop(0)
        price = c
        t += timedelta(minutes=1)
        yield b


def mt5_live(symbol: str = "US30", poll_seconds: float = 1.0, tz_shift_hours: float = 0.0,
             warmup: int = 3000) -> Iterator[Bar]:  # pragma: no cover - needs a terminal
    """Live M1 bars from MetaTrader 5 (Windows, `pip install MetaTrader5`). Yields only CLOSED bars."""
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    mt5.symbol_select(symbol, True)

    def conv(r) -> Bar:
        t = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc).replace(tzinfo=None)
        return Bar(t + timedelta(hours=tz_shift_hours), float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"]), float(r["tick_volume"]))

    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, warmup)
    last = None
    for r in rates:
        last = int(r["time"])
        yield conv(r)
    while True:
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, 1)
        if r is not None and len(r) and int(r[0]["time"]) != last:
            last = int(r[0]["time"])
            yield conv(r[0])
        _time.sleep(poll_seconds)
