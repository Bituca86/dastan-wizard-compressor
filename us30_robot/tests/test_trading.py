import json
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer

from us30bot.context import SessionClock, SpreadModel, us_dst
from us30bot.engine import Engine, EngineConfig
from us30bot.feeds import synthetic_bars
from us30bot.modes import EXECUTE, NOTIFY, PENDING, SKIP, ModeConfig, ModeController
from us30bot.models import BUY, Bar, Detection, Signal
from us30bot.risk import RiskConfig, RiskManager
from us30bot.server import Bridge, make_handler
from us30bot.trader import Trader


class TestSessions(unittest.TestCase):
    def test_dst_and_spread(self):
        clk = SessionClock()
        self.assertTrue(us_dst(datetime(2026, 7, 1).date()))
        self.assertFalse(us_dst(datetime(2026, 12, 1).date()))
        # NYSE opens 13:30 UTC in summer, 14:30 UTC in winter
        self.assertEqual(clk.label(datetime(2026, 7, 1, 13, 35)), "ny_open")
        self.assertEqual(clk.label(datetime(2026, 12, 1, 13, 35)), "london")
        self.assertEqual(clk.label(datetime(2026, 12, 1, 14, 35)), "ny_open")
        self.assertEqual(clk.label(datetime(2026, 12, 1, 3, 0)), "asia")
        sp = SpreadModel()
        self.assertEqual(sp.cost(datetime(2026, 12, 1, 15, 0)), 0.7)
        self.assertEqual(sp.cost(datetime(2026, 12, 1, 10, 0)), 1.2)
        self.assertEqual(sp.cost(datetime(2026, 12, 1, 10, 0), live=2.0), 2.0)


class TestModes(unittest.TestCase):
    def test_matrix_of_modes(self):
        now = [1000.0]
        mc = ModeController("MANUAL", ModeConfig(offline_after_sec=60), clock=lambda: now[0])
        self.assertEqual(mc.decide(0.7, 0.8)[0], NOTIFY)
        mc.set_mode("AUTO")
        self.assertEqual(mc.decide(0.5, 0.2)[0], EXECUTE)
        mc.set_mode("HIBRID")
        self.assertEqual(mc.decide(0.7, 0.8)[0], EXECUTE)
        self.assertEqual(mc.decide(0.5, 0.2)[0], PENDING)
        mc.set_mode("ROBOT")
        act, f, _ = mc.decide(0.6, 0.5)
        self.assertEqual((act, f), (EXECUTE, 0.5))
        self.assertEqual(mc.decide(0.5, 0.2)[0], SKIP)
        # offline -> HIBRID behaves as ROBOT
        mc.set_mode("HIBRID")
        now[0] += 120
        self.assertEqual(mc.effective, "ROBOT")
        mc.presence()
        self.assertEqual(mc.effective, "HIBRID")


class TestRisk(unittest.TestCase):
    def test_sizing_and_breakers(self):
        rm = RiskManager(RiskConfig(risk_pct=0.5, leverage=30, max_consecutive_losses=2))
        rm.new_bar(datetime(2026, 3, 2).date(), 10000)
        units, money = rm.size(10000, 10000, 44000, 43980)  # 20 pt stop, 50 money risk
        self.assertAlmostEqual(money, 50, delta=0.5)
        self.assertAlmostEqual(units, 2.5, delta=0.01)
        # leverage cap: tiny stop would need huge size -> limited by margin
        units2, _ = rm.size(10000, 10000, 44000, 43999.9)
        self.assertLessEqual(units2 * 44000 / 30, 10000 * 0.8 + 1)
        rm.on_close(-50); rm.on_close(-50)
        self.assertFalse(rm.can_trade()[0])
        rm.new_bar(datetime(2026, 3, 3).date(), 9900)
        self.assertTrue(rm.can_trade()[0])


def _sig(eng, sid=1):
    d = Detection(39, "Liquidity Sweep", BUY, 0, 100.0, 90.0, 120.0, "test")
    return Signal(sid, datetime(2026, 3, 2, 15), 0, BUY, 100.0, 90.0, 120.0, 0.5, 0.3, [d],
                  {"session": "ny"}, "BUY test")


class TestTrader(unittest.TestCase):
    def test_hybrid_pending_and_approval(self):
        eng = Engine(EngineConfig())
        for b in synthetic_bars(50, seed=1):
            eng.on_bar(b)
        tr = Trader(eng, ModeController("HIBRID", always_online=True), RiskManager(), paper=False)
        sig = _sig(eng)
        eng.open_signal = sig.id
        eng.st.bars.append(Bar(eng.st.bar.time + timedelta(minutes=1), 100, 101, 99, 100.5))
        tr._on_signal(sig)
        acts = tr.drain()
        self.assertEqual(acts[0]["status"], PENDING)
        self.assertIn(1, tr.pending)
        self.assertEqual(tr.decide_pending(1, True), "executat")
        opens = [a for a in tr.drain() if a["type"] == "open"]
        self.assertEqual(len(opens), 1)
        self.assertEqual(opens[0]["comment"], "MX#1")

    def test_paper_backtest_runs_all_modes(self):
        for mode in ("MANUAL", "HIBRID", "AUTO", "ROBOT"):
            eng = Engine(EngineConfig())
            tr = Trader(eng, ModeController(mode, always_online=mode != "ROBOT"), RiskManager(), paper=True)
            for b in synthetic_bars(6000, seed=5):
                tr.on_bar(b)
            if mode == "MANUAL":
                self.assertEqual(tr.paper.trades, [])
            if mode == "AUTO":
                self.assertGreater(len(tr.paper.trades), 0)


class TestBridge(unittest.TestCase):
    def test_http_roundtrip(self):
        eng = Engine(EngineConfig())
        tr = Trader(eng, ModeController("AUTO", always_online=True), RiskManager())
        import tempfile
        tmp = tempfile.mkdtemp()
        br = Bridge(tr, tmp)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(br, "secret"))
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def call(path, body=None):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json", "X-Token": "secret"})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())

        bars = list(synthetic_bars(9000, seed=3))
        def js(b):
            return {"time": b.time.isoformat(), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
        r = call("/warmup", {"bars": [js(b) for b in bars[:4000]]})
        self.assertEqual(r["bars"], 4000)
        self.assertGreater(r["learning_samples"], 0)
        kinds = set()
        for b in bars[4000:]:
            d = js(b); d.update(spread=0.7, balance=10000, equity=10000, free_margin=10000)
            for a in call("/bar", d)["actions"]:
                kinds.add(a["type"])
                if a["type"] == "open":
                    call("/event", {"type": "opened", "sid": a["sid"]})
        self.assertIn("signal", kinds)
        self.assertIn("open", kinds)
        self.assertEqual(call("/mode", {"mode": "hybrid"})["mode"], "HIBRID")
        st = call("/status")
        self.assertEqual(st["mode"], "HIBRID")
        # bad token rejected
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/status", timeout=5)
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    unittest.main()
