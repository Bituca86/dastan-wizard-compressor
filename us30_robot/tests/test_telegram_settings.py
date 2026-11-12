import os
import tempfile
import time
import unittest

from us30bot.engine import Engine, EngineConfig
from us30bot.modes import ModeController
from us30bot.risk import RiskManager
from us30bot.server import Bridge
from us30bot.settings import Settings
from us30bot.telegram import TelegramBot
from us30bot.trader import Trader
from tests.test_trading import _sig
from us30bot.feeds import synthetic_bars
from us30bot.models import Bar
from datetime import timedelta


class FakeTG:
    def __init__(self):
        self.calls = []
        self.mid = 100

    def __call__(self, method, params, timeout=0):
        self.calls.append((method, params))
        if method == "getUpdates":
            time.sleep(0.05)
            return {"ok": True, "result": []}
        if method == "sendMessage":
            self.mid += 1
            return {"ok": True, "result": {"message_id": self.mid}}
        return {"ok": True, "result": True}


def make():
    eng = Engine(EngineConfig())
    for b in synthetic_bars(50, seed=1):
        eng.on_bar(b)
    tr = Trader(eng, ModeController("HIBRID", always_online=True), RiskManager())
    d = tempfile.mkdtemp()
    tr.settings = Settings(tr.modes, tr.risk, os.path.join(d, "settings.json"))
    return tr, Bridge(tr, d, settings=tr.settings), d


class TestSettings(unittest.TestCase):
    def test_defaults_validation_persistence(self):
        tr, br, d = make()
        self.assertEqual(tr.risk.cfg.risk_pct, 1.0)
        tr.settings.set("risk_pct", "1,5")
        self.assertEqual(tr.risk.cfg.risk_pct, 1.5)
        with self.assertRaises(ValueError):
            tr.settings.set("risk_pct", 9)
        tr.settings.set("offline_after_min", 30)
        self.assertEqual(tr.modes.cfg.offline_after_sec, 1800)
        tr.settings.set("auto_robot_offline", "nu")
        self.assertFalse(tr.modes.cfg.auto_robot_offline)
        tr2, _, _ = make()
        s2 = Settings(tr2.modes, tr2.risk, os.path.join(d, "settings.json"))
        s2.load()
        self.assertEqual(tr2.risk.cfg.risk_pct, 1.5)
        self.assertEqual(s2.get()["offline_after_min"], 30)


class TestTelegram(unittest.TestCase):
    def test_pending_buttons_callback_and_commands(self):
        tr, br, _ = make()
        fake = FakeTG()
        bot = TelegramBot("x", 42, br, transport=fake)
        bot.start()
        sig = _sig(tr.eng, sid=7)
        tr.eng.open_signal = 7
        tr.eng.st.bars.append(Bar(tr.eng.st.bar.time + timedelta(minutes=1), 100, 101, 99, 100.2))
        tr._on_signal(sig)
        time.sleep(0.3)
        sends = [p for m, p in fake.calls if m == "sendMessage"]
        with_buttons = [p for p in sends if "reply_markup" in p]
        self.assertEqual(len(with_buttons), 1)
        self.assertEqual(with_buttons[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "ok:7")
        # a stranger cannot approve
        self.assertIsNone(bot.handle_update({"update_id": 1, "callback_query": {
            "id": "a", "data": "ok:7", "message": {"chat": {"id": 999}}}}))
        res = bot.handle_update({"update_id": 2, "callback_query": {
            "id": "b", "data": "ok:7", "message": {"chat": {"id": 42}}}})
        self.assertEqual(res, "executat")
        self.assertTrue(any(a["type"] == "open" for a in tr.drain()))
        self.assertIn("1.2%", bot.command("/risc 1.2"))
        self.assertEqual(tr.risk.cfg.risk_pct, 1.2)
        bot.command("/prag 0.7 0.5")
        self.assertEqual((tr.modes.cfg.hybrid_auto_prob, tr.modes.cfg.hybrid_auto_exp), (0.7, 0.5))
        self.assertIn("AUTO", bot.command("/mod auto"))
        self.assertIn("⚠️", bot.command("/risc 50"))
        self.assertIn("Mod AUTO", bot.command("/status"))
        time.sleep(0.2)
        self.assertTrue(any(m == "editMessageText" for m, _ in fake.calls))
        bot.stop()


if __name__ == "__main__":
    unittest.main()
