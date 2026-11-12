#!/usr/bin/env python3
"""US30 M1 pattern-matrix robot – CLI.

  python run.py demo                       # synthetic data, shows the whole loop
  python run.py backtest --csv us30_m1.csv # replay history, learn, save state
  python run.py live --symbol US30         # MT5 live (signals only, no orders)
"""
import argparse
import sys

from us30bot.engine import Engine, EngineConfig
from us30bot.feeds import csv_bars, mt5_live, synthetic_bars
from us30bot.patterns import CATALOG, IMPLEMENTED


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["demo", "backtest", "live", "catalog"])
    ap.add_argument("--csv")
    ap.add_argument("--symbol", default="US30")
    ap.add_argument("--state", default="state")
    ap.add_argument("--tz-shift", type=float, default=0.0, help="broker time -> UTC hours")
    ap.add_argument("--bars", type=int, default=30000)
    ap.add_argument("--explore", action="store_true", help="Thompson sampling (paper trading)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if a.mode == "catalog":
        for pid, (name, fam) in CATALOG.items():
            print(f"{pid:>3} {'✔' if pid in IMPLEMENTED else '·'} {fam:<13} {name}")
        print(f"\nDetectori activi pentru {len(IMPLEMENTED)}/{len(CATALOG)} pattern-uri.")
        return 0

    cfg = EngineConfig(explore=a.explore)
    eng = Engine.load(a.state, cfg)

    if not a.quiet:
        def show_sig(s):
            print(f"\n[{s.time:%Y-%m-%d %H:%M}] SEMNAL #{s.id} {s.direction} @ {s.entry:.1f} "
                  f"SL {s.stop:.1f} TP {s.target:.1f}\n{s.explanation}")

        def show_out(s, o):
            print(f"   ↳ #{s.id} {o.result} {o.r_multiple:+.2f}R după {o.bars_held} min – {o.verdict}")
        eng.on_signal.append(show_sig)
        eng.on_outcome.append(show_out)

    if a.mode == "demo":
        feed = synthetic_bars(a.bars)
    elif a.mode == "backtest":
        if not a.csv:
            ap.error("--csv required")
        feed = csv_bars(a.csv, a.tz_shift)
    else:
        feed = mt5_live(a.symbol, tz_shift_hours=a.tz_shift)

    try:
        for n, bar in enumerate(feed, 1):
            eng.on_bar(bar)
            if a.mode == "live" and n % 60 == 0:
                eng.save(a.state)
    except KeyboardInterrupt:
        pass
    eng.save(a.state)
    print("\n=== Rezumat ===")
    for k, v in eng.summary().items():
        print(f"{k:>18}: {v}")
    print("\nTop celule matrice (după R mediu):")
    for key, wr, n, avg in eng.learner.top_cells(10):
        print(f"  {key:<35} win {wr:5.0%}  n={n:6.1f}  avgR={avg:+.2f}")
    print("\nPonderi învățate (de ce funcționează):")
    for k, v in sorted(eng.learner.weights().items(), key=lambda kv: -abs(kv[1])):
        print(f"  {k:<15} {v:+.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
