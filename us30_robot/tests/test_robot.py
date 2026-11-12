import os
import tempfile
import unittest
from datetime import datetime, timedelta

from us30bot.context import MarketState
from us30bot.engine import Engine, EngineConfig
from us30bot.evaluator import Evaluator, Tracked
from us30bot.feeds import csv_bars, synthetic_bars
from us30bot.learner import Learner
from us30bot.models import BUY, SELL, Bar
from us30bot.patterns import CATALOG, IMPLEMENTED, liquidity_sweep

T0 = datetime(2026, 3, 2, 8, 0)


def bars_from(path, t0=T0):
    """Build bars from a list of (open, high, low, close)."""
    return [Bar(t0 + timedelta(minutes=k), *ohlc) for k, ohlc in enumerate(path)]


def zig(points, step=2.0):
    """Linear legs between pivot prices -> list of small-bodied OHLC bars."""
    out = []
    for a, b in zip(points, points[1:]):
        n = max(1, int(abs(b - a) / step))
        for k in range(n):
            o = a + (b - a) * k / n
            c = a + (b - a) * (k + 1) / n
            out.append((o, max(o, c) + 0.3, min(o, c) - 0.3, c))
    return out


class TestCatalog(unittest.TestCase):
    def test_91_patterns(self):
        self.assertEqual(sorted(CATALOG), list(range(1, 92)))
        self.assertTrue(IMPLEMENTED <= set(CATALOG))
        self.assertEqual(IMPLEMENTED, set(CATALOG))


class TestStructure(unittest.TestCase):
    def test_swings_and_bos(self):
        st = MarketState()
        for b in bars_from(zig([100, 140, 120, 160, 135, 190])):
            st.update(b)
        labels = [s.label for s in st.zz.swings]
        self.assertIn("HH", labels)
        self.assertIn("HL", labels)
        self.assertEqual(st.structure.trend, 1)
        self.assertIn("BOS_UP", st.events)


class TestSweep(unittest.TestCase):
    def test_sell_side_sweep_of_swing_high(self):
        st = MarketState()
        path = zig([100, 140, 110, 135, 115, 132])
        for b in bars_from(path):
            st.update(b)
        hi = st.zz.last_of("H")
        self.assertIsNotNone(hi)
        last = st.bar
        # wick above the high, close back below, bearish candle with long upper wick
        sweep = Bar(last.time + timedelta(minutes=1), 132, hi.price + 3, 128, 129)
        st.update(sweep)
        dets = liquidity_sweep(st)
        self.assertTrue(any(d.direction == SELL for d in dets), dets)
        d = [d for d in dets if d.direction == SELL][0]
        self.assertGreater(d.stop, sweep.high)
        self.assertLess(d.target, d.entry)


class TestEvaluator(unittest.TestCase):
    def test_win_loss_timeout(self):
        ev = Evaluator(timeout_bars=3, post_bars=2, cost_r=0.0)
        got = []
        ev.on_close.append(lambda t, o: got.append((t.key, o.result, round(o.r_multiple, 2))))
        ev.track(Tracked(1, BUY, 100, 90, 120, 0))
        ev.track(Tracked(2, SELL, 100, 110, 80, 0))
        ev.track(Tracked(3, BUY, 100, 90, 200, 0))
        seq = [(100, 105, 99, 104), (104, 121, 103, 120), (120, 122, 118, 119), (119, 120, 117, 118),
               (118, 119, 117, 118), (118, 119, 117, 118)]
        for i, b in enumerate(bars_from(seq), 1):
            ev.update(i, b)
        res = {k: (r, R) for k, r, R in got}
        self.assertEqual(res[1], ("WIN", 2.0))
        self.assertEqual(res[2][0], "LOSS")
        self.assertEqual(res[3][0], "TIMEOUT")


class TestLearner(unittest.TestCase):
    def test_learns_and_persists(self):
        L = Learner(half_life=1e9)
        x = [1.0] * 14
        p0, _ = L.score("c", "F|BUY", x)
        for _ in range(40):
            L.update("c", "F|BUY", x, True, 2.0, {1.0: True, 2.0: True, 3.0: False})
        p1, n = L.score("c", "F|BUY", x)
        self.assertGreater(p1, p0 + 0.3)
        self.assertGreater(n, 30)
        # a new cell of the same family benefits immediately (hierarchical prior)
        p_new, _ = L.score("c2", "F|BUY", x)
        self.assertGreater(p_new, p0)
        self.assertEqual(L.best_rr("c", "F|BUY", 1.5), 2.0)
        with tempfile.TemporaryDirectory() as d:
            L.save(os.path.join(d, "l.json"))
            L2 = Learner.load(os.path.join(d, "l.json"), half_life=1e9)
            self.assertAlmostEqual(L2.score("c", "F|BUY", x)[0], p1)


class TestEngine(unittest.TestCase):
    def test_end_to_end_synthetic(self):
        eng = Engine(EngineConfig())
        sigs, outs = [], []
        eng.on_signal.append(sigs.append)
        eng.on_outcome.append(lambda s, o: outs.append(o))
        for b in synthetic_bars(8000, seed=3):
            eng.on_bar(b)
        self.assertGreater(eng.learner.updates, 100)
        self.assertGreater(len(sigs), 0)
        for s in sigs:
            self.assertIn(s.direction, (BUY, SELL))
            self.assertTrue(s.explanation)
            if s.direction == BUY:
                self.assertLess(s.stop, s.entry)
                self.assertGreater(s.target, s.entry)
            else:
                self.assertGreater(s.stop, s.entry)
                self.assertLess(s.target, s.entry)
        self.assertTrue(all(o.verdict for o in outs))
        with tempfile.TemporaryDirectory() as d:
            eng.save(d)
            eng2 = Engine.load(d)
            self.assertEqual(eng2.learner.updates, eng.learner.updates)

    def test_csv_feed(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.csv")
            with open(p, "w") as fh:
                fh.write("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\n")
                fh.write("2026.03.02\t08:00:00\t44000\t44010\t43990\t44005\t120\n")
                fh.write("2026.03.02\t08:01:00\t44005\t44012\t44001\t44011\t90\n")
            bars = list(csv_bars(p, tz_shift_hours=-2))
            self.assertEqual(len(bars), 2)
            self.assertEqual(bars[0].time, datetime(2026, 3, 2, 6, 0))
            self.assertEqual(bars[1].close, 44011.0)


if __name__ == "__main__":
    unittest.main()
