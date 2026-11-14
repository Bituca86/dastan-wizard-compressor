"""Persistent trade journal: state/jurnal.csv (append-only, opens directly in Excel).

One row per event of a signal: PROPUS (signal created, with the decision of the
current mode), STARE (executed / refused / expired / rejected by broker),
REZULTAT (virtual outcome WIN/LOSS/TIMEOUT in R) and INCHIS (real position closed
by the broker, with money P/L). Nothing is ever rewritten, so the history
survives restarts.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Dict, List

COLS = ["data_ora", "sid", "eveniment", "directie", "intrare", "sl", "tp", "p_succes", "expectanta_R",
        "mod", "stare", "rezultat", "R", "pnl", "pl_azi", "pattern-uri", "detalii"]


def _fmt(v):
    """Numbers with 2 decimals and a decimal comma, so Romanian Excel reads them as numbers."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return v
    if isinstance(v, int):
        return v
    return f"{v:.2f}".replace(".", ",")


class CsvJournal:
    def __init__(self, path: str, trader=None):
        self.path = path
        self.trader = trader
        self.sig: Dict[int, dict] = {}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh, delimiter=";").writerow(COLS)

    def _write(self, row: dict) -> None:
        row.setdefault("data_ora", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            with open(self.path, "a", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh, delimiter=";").writerow([_fmt(row.get(c, "")) for c in COLS])
        except OSError:
            pass  # file open in Excel: skip this row rather than stop trading

    def on_action(self, a: dict) -> None:
        if self.trader is not None and getattr(self.trader, "warmup", False):
            return
        t = a.get("type")
        if t == "signal":
            self.sig[a["sid"]] = a
            self._write(self._base(a["sid"], "PROPUS", stare=a.get("status", ""), detalii=a.get("why", "")))
        elif t == "status":
            self._write(self._base(a["sid"], "STARE", stare=a.get("status", ""), detalii=a.get("why", "")))
        elif t == "outcome":
            self._write(self._base(a["sid"], "REZULTAT", rezultat=a.get("result", ""), R=a.get("R", ""),
                                   detalii=a.get("verdict", "")))
        elif t == "closed":
            self._write(self._base(a["sid"], "INCHIS", pnl=a.get("pnl", ""), pl_azi=a.get("day_pnl", ""),
                                   detalii=a.get("reason", "")))
        elif t == "breaker":
            self._write({"eveniment": "OPRIRE", "detalii": a.get("why", "")})

    def _base(self, sid: int, event: str, **extra) -> dict:
        s = self.sig.get(sid, {})
        row = {"sid": sid, "eveniment": event, "directie": s.get("side", ""), "intrare": s.get("entry", ""),
               "sl": s.get("sl", ""), "tp": s.get("tp", ""), "p_succes": s.get("p", ""),
               "expectanta_R": s.get("exp", ""), "mod": s.get("mode", ""),
               "pattern-uri": " + ".join(s.get("patterns", []))}
        row.update(extra)
        return row

    def tail(self, n: int = 10) -> List[dict]:
        try:
            with open(self.path, newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh, delimiter=";"))
        except OSError:
            return []
        return rows[-n:]
