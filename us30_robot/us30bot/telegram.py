"""Telegram notifications + remote control (stdlib only, Bot API over HTTPS).

Setup once:  python run.py telegram-setup --tg-token <token from @BotFather>
then write /start to your bot; the chat id is saved in state/telegram.json.

In chat:
  semnale cu butoane ✔ Aprob / ✖ Refuz (HIBRID), execuții, rezultate cu verdict,
  /status  /mod AUTO|MANUAL|HIBRID|ROBOT  /online  /risc 1.0  /prag 0.6 0.4
  /robot 0.55 0.3  /setari  /set <cheie> <valoare>  /ajutor
Only messages from the configured chat id are obeyed. Any message or button press
from you also counts as "online" presence.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.request
from typing import Callable, Dict, Optional

API = "https://api.telegram.org/bot{token}/{method}"

HELP = ("Comenzi:\n/status – situația curentă\n/mod MANUAL|HIBRID|AUTO|ROBOT\n/online – sunt aici\n"
        "/risc 1.0 – risc % pe tranzacție\n/prag 0.60 0.40 – HIBRID: P și expectanță pt. execuție automată\n"
        "/robot 0.55 0.30 – praguri ROBOT\n/setari – toate setările\n/set <cheie> <valoare>")


def http_transport(token: str) -> Callable[[str, dict, float], dict]:
    def call(method: str, params: dict, timeout: float = 35.0) -> dict:
        req = urllib.request.Request(API.format(token=token, method=method),
                                     data=json.dumps(params).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    return call


def load_config(state_dir: str) -> Optional[dict]:
    p = os.path.join(state_dir, "telegram.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    return {"token": tok, "chat_id": int(chat)} if tok and chat else None


def setup(token: str, state_dir: str, wait_sec: int = 300,
          transport: Optional[Callable] = None) -> int:
    call = transport or http_transport(token)
    me = call("getMe", {}, 15)["result"]
    print(f"Bot: @{me['username']}. Scrie-i acum /start din Telegram (aștept {wait_sec}s)...")
    offset, t0 = 0, time.time()
    while time.time() - t0 < wait_sec:
        for u in call("getUpdates", {"timeout": 20, "offset": offset}, 30).get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            if msg.get("text", "").startswith("/start"):
                chat_id = msg["chat"]["id"]
                os.makedirs(state_dir, exist_ok=True)
                with open(os.path.join(state_dir, "telegram.json"), "w", encoding="utf-8") as fh:
                    json.dump({"token": token, "chat_id": chat_id}, fh)
                call("sendMessage", {"chat_id": chat_id, "text": "✅ US30 Matrix conectat.\n\n" + HELP}, 15)
                print(f"Salvat chat_id={chat_id} în {state_dir}/telegram.json")
                return chat_id
    raise TimeoutError("nu am primit /start")


class TelegramBot:
    def __init__(self, token: str, chat_id: int, bridge, transport: Optional[Callable] = None,
                 notify_all_signals: bool = True):
        self.call = transport or http_transport(token)
        self.chat_id = int(chat_id)
        self.br = bridge  # server.Bridge: .t (Trader), .lock, .settings
        self.notify_all = notify_all_signals
        self.out: "queue.Queue[tuple]" = queue.Queue()
        self.msg_of_sid: Dict[int, int] = {}
        self.offset = 0
        self.running = False
        bridge.t.listeners.append(self.on_action)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.running = True
        threading.Thread(target=self._sender, daemon=True).start()
        threading.Thread(target=self._poller, daemon=True).start()
        self.send("🤖 US30 Matrix pornit. Mod: " + self.br.t.modes.mode + "\n/ajutor pentru comenzi")

    def stop(self) -> None:
        self.running = False

    # ------------------------------------------------------------------ outgoing
    def send(self, text: str, buttons=None, sid: Optional[int] = None) -> None:
        self.out.put(("send", text, buttons, sid))

    def edit(self, sid: int, suffix: str) -> None:
        self.out.put(("edit", suffix, None, sid))

    def _sender(self) -> None:
        texts: Dict[int, str] = {}
        while self.running:
            try:
                kind, text, buttons, sid = self.out.get(timeout=1)
            except queue.Empty:
                continue
            try:
                if kind == "send":
                    p = {"chat_id": self.chat_id, "text": text[:4000]}
                    if buttons:
                        p["reply_markup"] = {"inline_keyboard": buttons}
                    r = self.call("sendMessage", p, 15)
                    if sid is not None and r.get("ok"):
                        self.msg_of_sid[sid] = r["result"]["message_id"]
                        texts[sid] = text
                elif kind == "edit" and sid in self.msg_of_sid:
                    texts[sid] = texts.get(sid, "") + "\n" + text
                    self.call("editMessageText", {"chat_id": self.chat_id, "message_id": self.msg_of_sid[sid],
                                                  "text": texts[sid][:4000]}, 15)
            except Exception:
                time.sleep(2)  # network hiccup: drop this message, keep going

    # ------------------------------------------------------------------ trader events
    def on_action(self, a: dict) -> None:
        t = a.get("type")
        if t == "signal":
            st = a["status"]
            if st == "SKIP" or (st == "NOTIFY" and not self.notify_all):
                return
            icon = "🟢" if a["side"] == "BUY" else "🔴"
            head = (f"{icon} #{a['sid']} {a['side']} US30 @ {a['entry']:.1f}\n"
                    f"SL {a['sl']:.1f} · TP {a['tp']:.1f} · P={a['p']:.0%} · {a['exp']:+.2f}R\n"
                    f"[{a['mode']}] {a['why']}\n\n{a['text']}")
            btn = None
            if st == "PENDING":
                btn = [[{"text": "✔ Aprob", "callback_data": f"ok:{a['sid']}"},
                        {"text": "✖ Refuz", "callback_data": f"no:{a['sid']}"}]]
            self.send(head, btn, a["sid"])
        elif t == "status":
            self.edit(a["sid"], f"→ {a['status']}: {a['why']}")
        elif t == "outcome":
            if a["sid"] in self.msg_of_sid:
                icon = "✅" if a["result"] == "WIN" else "❌" if a["result"] == "LOSS" else "⏱"
                self.edit(a["sid"], f"{icon} {a['result']} {a['R']:+.2f}R – {a['verdict']}")
        elif t == "closed":
            self.send(f"💰 Poziția #{a['sid']} închisă: {a['pnl']:+.2f} ({a['reason']}). P/L azi: {a['day_pnl']:+.2f}")
        elif t == "breaker":
            self.send(f"⛔ Tranzacționare oprită pentru azi: {a['why']}")
        elif t == "mode" and a.get("auto"):
            self.send(f"🔁 Mod efectiv: {a['effective']} (ales: {a['mode']})"
                      + (" – nu te-am văzut online, pilot automat cu risc redus" if a["effective"] == "ROBOT" else ""))

    # ------------------------------------------------------------------ incoming
    def _poller(self) -> None:
        while self.running:
            try:
                r = self.call("getUpdates", {"timeout": 25, "offset": self.offset,
                                             "allowed_updates": ["message", "callback_query"]}, 35)
                for u in r.get("result", []):
                    self.offset = u["update_id"] + 1
                    self.handle_update(u)
            except Exception:
                time.sleep(5)

    def handle_update(self, u: dict) -> Optional[str]:
        cq = u.get("callback_query")
        if cq:
            if int(cq["message"]["chat"]["id"]) != self.chat_id:
                return None
            kind, sid = cq["data"].split(":")
            with self.br.lock:
                res = self.br.t.decide_pending(int(sid), kind == "ok")
            try:
                self.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": res}, 15)
            except Exception:
                pass
            return res
        msg = u.get("message") or {}
        if int((msg.get("chat") or {}).get("id", 0)) != self.chat_id or "text" not in msg:
            return None
        reply = self.command(msg["text"].strip())
        self.send(reply)
        return reply

    def command(self, text: str) -> str:
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]
        args = parts[1:]
        t, s = self.br.t, self.br.settings
        with self.br.lock:
            t.modes.presence()
            try:
                if cmd in ("/start", "/ajutor", "/help"):
                    return HELP
                if cmd == "/online":
                    return f"👋 Bun venit. Mod efectiv: {t.modes.effective}"
                if cmd == "/status":
                    x = t.status()
                    return (f"Mod {x['mode']} (efectiv {x['effective']}) · {'online' if x['online'] else 'offline'}\n"
                            f"Preț {x['price']} · sesiune {x['session']} · trend M1 {x['trend_m1']} / M15 {x['trend_m15']}\n"
                            f"Sold {x['balance']} · P/L azi {x['risk']['day_pnl']} · tranz. azi {x['risk']['day_trades']}\n"
                            f"Poziții: {x['positions'] or '-'} · în așteptare: {[p['sid'] for p in x['pending']] or '-'}\n"
                            f"Semnale {x['engine']['signals']} · win {x['engine']['win_rate']:.0%} · "
                            f"total {x['engine']['total_R']}R · învățare {x['engine']['learning_samples']}")
                if cmd == "/mod" and args:
                    return f"Mod setat: {t.set_mode(args[0])} (efectiv {t.modes.effective})"
                if cmd == "/risc" and args:
                    return f"Risc pe tranzacție: {s.set('risk_pct', args[0])}%"
                if cmd == "/prag" and len(args) == 2:
                    s.set("hybrid_auto_prob", args[0])
                    s.set("hybrid_auto_exp", args[1])
                    return f"HIBRID execută automat de la P ≥ {args[0]} și expectanță ≥ {args[1]}R"
                if cmd == "/robot" and len(args) == 2:
                    s.set("robot_min_prob", args[0])
                    s.set("robot_min_exp", args[1])
                    return f"ROBOT: P ≥ {args[0]}, expectanță ≥ {args[1]}R"
                if cmd == "/setari":
                    return s.describe()
                if cmd == "/set" and len(args) == 2:
                    return f"{args[0]} = {s.set(args[0], args[1])}"
                return "Comandă necunoscută.\n" + HELP
            except (ValueError, KeyError) as e:
                return f"⚠️ {e}"
