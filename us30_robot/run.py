#!/usr/bin/env python3
"""US30 M1 pattern-matrix robot – CLI.

  python run.py serve --mode HIBRID          # bridge for the cTrader cBot + dashboard
  python run.py backtest --csv us30_m1.csv   # replay history (paper account), learn, save state
  python run.py demo                         # synthetic data, whole loop
  python run.py catalog                      # the 91 patterns
"""
import argparse
import os
import sys

from us30bot.engine import Engine, EngineConfig
from us30bot.feeds import csv_bars, synthetic_bars
from us30bot.modes import ModeConfig, ModeController
from us30bot.patterns import CATALOG, IMPLEMENTED, detect_all  # noqa: F401
from us30bot.risk import RiskConfig, RiskManager
from us30bot.settings import Settings
from us30bot.trader import Trader


class _Tee:
    """Duplicate console output into state/server.log (kept even if the window closes)."""

    def __init__(self, stream, fh):
        self.stream, self.fh = stream, fh

    def write(self, data):
        try:
            if self.stream:
                self.stream.write(data)
        except Exception:
            pass
        self.fh.write(data)
        self.fh.flush()

    def flush(self):
        try:
            if self.stream:
                self.stream.flush()
        except Exception:
            pass


def setup_logging(state_dir: str) -> None:
    import atexit
    import threading
    import traceback
    from datetime import datetime
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, "server.log")
    if os.path.exists(path) and os.path.getsize(path) > 5_000_000:
        os.replace(path, path + ".old")
    fh = open(path, "a", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, fh)
    sys.stderr = _Tee(sys.stderr, fh)
    print(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} pornire server (pid {os.getpid()}) =====")

    def log_exc(exc_type, exc, tb):
        print(f"[{datetime.now():%H:%M:%S}] EROARE NETRATATĂ:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))
    sys.excepthook = log_exc
    threading.excepthook = lambda a: log_exc(a.exc_type, a.exc_value, a.exc_traceback)
    atexit.register(lambda: print(f"[{datetime.now():%H:%M:%S}] proces Python oprit normal"))


def build(a, paper: bool) -> Trader:
    eng = Engine.load(a.state, EngineConfig(explore=a.explore))
    modes = ModeController(a.mode, ModeConfig(), always_online=paper and a.mode != "ROBOT")
    risk = RiskManager(RiskConfig(risk_pct=a.risk, leverage=a.leverage))
    tr = Trader(eng, modes, risk, paper=paper, balance=a.balance)
    tr.settings = Settings(modes, risk, os.path.join(a.state, "settings.json"), engine_cfg=eng.cfg)
    tr.settings.load()  # values changed from dashboard / Telegram survive restarts
    if "--risk" in sys.argv:
        tr.settings.set("risk_pct", a.risk)
    return tr


def report(tr: Trader) -> None:
    eng = tr.eng
    print("\n=== Rezumat semnale (în R) ===")
    for k, v in eng.summary().items():
        print(f"{k:>18}: {v}")
    if tr.paper:
        print("\n=== Cont paper ===")
        for k, v in tr.paper.stats(tr.start_balance).items():
            print(f"{k:>18}: {v}")
    print("\nTop celule matrice (după R mediu):")
    for key, wr, n, avg in eng.learner.top_cells(12):
        print(f"  {key:<35} win {wr:5.0%}  n={n:6.1f}  avgR={avg:+.2f}")
    print("\nPonderi învățate (de ce funcționează):")
    for k, v in sorted(eng.learner.weights().items(), key=lambda kv: -abs(kv[1])):
        print(f"  {k:<15} {v:+.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "backtest", "demo", "catalog", "telegram-setup"])
    ap.add_argument("--csv")
    ap.add_argument("--state", default="state")
    ap.add_argument("--mode", default="AUTO", help="MANUAL | HIBRID | AUTO | ROBOT")
    ap.add_argument("--risk", type=float, default=1.0, help="%% din sold riscat pe tranzacție")
    ap.add_argument("--leverage", type=float, default=30.0)
    ap.add_argument("--balance", type=float, default=10000.0)
    ap.add_argument("--tz-shift", type=float, default=0.0, help="ore de adăugat ca să obții UTC")
    ap.add_argument("--bars", type=int, default=30000)
    ap.add_argument("--explore", action="store_true", help="Thompson sampling (paper)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token")
    ap.add_argument("--tg-token", help="token de la @BotFather (pentru telegram-setup)")
    ap.add_argument("--tg-only-actionable", action="store_true",
                    help="Telegram: doar semnale executate / de aprobat (fără cele MANUAL)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if a.cmd == "catalog":
        for pid, (name, fam) in CATALOG.items():
            print(f"{pid:>3} {'✔' if pid in IMPLEMENTED else '·'} {fam:<13} {name}")
        print(f"\nDetectori activi pentru {len(IMPLEMENTED)}/{len(CATALOG)} pattern-uri.")
        return 0

    if a.cmd == "telegram-setup":
        from us30bot.telegram import setup
        if not a.tg_token:
            ap.error("--tg-token necesar (îl primești de la @BotFather)")
        setup(a.tg_token, a.state)
        return 0

    if a.cmd == "serve":
        setup_logging(a.state)
        from us30bot.server import Bridge, serve
        from us30bot.telegram import TelegramBot, load_config
        mode_file = os.path.join(a.state, "mode.txt")
        if "--mode" not in sys.argv:
            a.mode = "MANUAL"  # safe default for live ...
            if os.path.exists(mode_file):  # ... unless a mode was chosen before a restart
                with open(mode_file, encoding="utf-8") as fh:
                    a.mode = fh.read().strip() or "MANUAL"
        tr = build(a, paper=False)
        br = Bridge(tr, a.state, settings=tr.settings)

        def remember_mode(act):
            if act.get("type") == "mode" and not act.get("auto"):
                os.makedirs(a.state, exist_ok=True)
                with open(mode_file, "w", encoding="utf-8") as fh:
                    fh.write(act["mode"])
        tr.listeners.append(remember_mode)
        tg = load_config(a.state)
        if tg:
            TelegramBot(tg["token"], tg["chat_id"], br, notify_all_signals=not a.tg_only_actionable).start()
            print("Telegram activ.")
        else:
            print("Telegram neconfigurat (python run.py telegram-setup --tg-token ...).")
        serve(br, a.host, a.port, a.token)
        return 0

    tr = build(a, paper=True)
    if not a.quiet:
        def show(acts):
            for x in acts:
                if x["type"] == "signal":
                    print(f"\n[{x['time'][:16]}] SEMNAL #{x['sid']} {x['side']} @ {x['entry']:.1f} "
                          f"SL {x['sl']:.1f} TP {x['tp']:.1f}  [{x['status']}: {x['why']}]\n{x['text']}")
                elif x["type"] == "outcome":
                    print(f"   ↳ #{x['sid']} {x['result']} {x['R']:+.2f}R – {x['verdict']}")
    else:
        def show(acts):
            pass
    feed = synthetic_bars(a.bars) if a.cmd == "demo" else csv_bars(a.csv, a.tz_shift) if a.csv else None
    if feed is None:
        ap.error("--csv necesar pentru backtest")
    try:
        for bar in feed:
            show(tr.on_bar(bar))
    except KeyboardInterrupt:
        pass
    tr.eng.save(a.state)
    report(tr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
