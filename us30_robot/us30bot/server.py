"""Local HTTP bridge between the cTrader cBot and the Python brain + a small dashboard.

  POST /warmup   {"bars":[bar,...]}         history to learn from (no trading)
  POST /bar      bar + account fields        -> {"actions":[...]}
  GET  /actions                              -> {"actions":[...]}  (polled every second)
  POST /mode     {"mode":"AUTO"}
  POST /presence {}                          you are online (mouse on chart / dashboard)
  POST /decision {"sid":12,"approve":true}   HIBRID approvals
  POST /event    {"type":"opened|closed|rejected","sid":..,"pnl":..}
  POST /shutdown                             save state and exit (sent by the cBot on stop)
  GET/POST /settings  {"risk_pct":1.0,"hybrid_auto_prob":0.6,...}
  GET  /status   JSON;  GET / dashboard (HTML)

bar = {"time":"2026-11-12T14:31:00","o":..,"h":..,"l":..,"c":..,"v":..,"spread":..,
       "balance":..,"equity":..,"free_margin":..}
Binds to 127.0.0.1 by default. Use --host 0.0.0.0 --token SECRET to open the
dashboard from your phone on the same Wi-Fi.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .models import Bar
from .settings import SPEC, Settings
from .trader import Trader


def parse_bar(d: dict) -> Bar:
    t = d["time"].replace("Z", "")[:19]
    return Bar(datetime.fromisoformat(t), float(d["o"]), float(d["h"]), float(d["l"]), float(d["c"]),
               float(d.get("v", 0)))


class Bridge:
    def __init__(self, trader: Trader, state_dir: str, save_every: int = 30,
                 settings: Optional[Settings] = None):
        self.t = trader
        self.settings = settings or Settings(trader.modes, trader.risk)
        self.lock = threading.Lock()
        self.state_dir = state_dir
        self.save_every = save_every
        self._n = 0
        self.on_shutdown = None  # set by serve()

    def warmup(self, bars) -> dict:
        with self.lock:
            self.t.warmup = True
            last = self.t.eng.st.bar.time if self.t.eng.st.bars else None
            n = 0
            for d in bars:
                b = parse_bar(d)
                if last is not None and b.time <= last:
                    continue
                self.t.eng.on_bar(b, d.get("spread"))
                last = b.time
                n += 1
            self.t.warmup = False
            self.t.drain()
            self.t.eng.open_signal = None  # warm-up signals are virtual only
            return {"ok": True, "bars": n, "learning_samples": self.t.eng.learner.updates}

    def bar(self, d: dict) -> dict:
        with self.lock:
            b = parse_bar(d)
            if self.t.eng.st.bars and b.time <= self.t.eng.st.bar.time:
                return {"actions": self.t.drain(), "dup": True}
            acts = self.t.on_bar(b, d.get("spread"), d.get("balance"), d.get("equity"), d.get("free_margin"))
            self._n += 1
            if self._n % self.save_every == 0:
                self.t.eng.save(self.state_dir)
            return {"actions": acts}

    def save(self) -> None:
        with self.lock:
            self.t.eng.save(self.state_dir)


def make_handler(br: Bridge, token: Optional[str]):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _auth(self) -> bool:
            if not token:
                return True
            q = parse_qs(urlparse(self.path).query)
            return self.headers.get("X-Token") == token or q.get("t", [None])[0] == token

        def _send(self, code: int, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def do_GET(self):
            if not self._auth():
                return self._send(401, {"error": "token"})
            path = urlparse(self.path).path
            if path == "/":
                return self._send(200, DASHBOARD.encode(), "text/html")
            if path == "/status":
                with br.lock:
                    return self._send(200, br.t.status())
            if path == "/settings":
                with br.lock:
                    return self._send(200, {"values": br.settings.get(),
                                            "help": {k: v[5] for k, v in SPEC.items()}})
            if path == "/actions":
                with br.lock:
                    return self._send(200, {"actions": br.t.drain(), "mode": br.t.modes.effective})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._auth():
                return self._send(401, {"error": "token"})
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path == "/bar":
                    return self._send(200, br.bar(body))
                if path == "/warmup":
                    return self._send(200, br.warmup(body.get("bars", [])))
                if path == "/shutdown":
                    br.save()
                    self._send(200, {"ok": True, "saved": True})
                    if br.on_shutdown:
                        br.on_shutdown()
                    return
                with br.lock:
                    if path == "/mode":
                        return self._send(200, {"mode": br.t.set_mode(body["mode"]),
                                                "effective": br.t.modes.effective})
                    if path == "/settings":
                        br.t.modes.presence()
                        return self._send(200, {"values": br.settings.update(body)})
                    if path == "/presence":
                        br.t.modes.presence()
                        return self._send(200, {"online": True, "effective": br.t.modes.effective})
                    if path == "/decision":
                        return self._send(200, {"result": br.t.decide_pending(int(body["sid"]),
                                                                              bool(body["approve"]))})
                    if path == "/event":
                        br.t.broker_event(body)
                        return self._send(200, {"ok": True})
                self._send(404, {"error": "not found"})
            except Exception as e:  # never crash the bridge on a bad request
                self._send(400, {"error": str(e)})
    return H


def serve(br: Bridge, host: str = "127.0.0.1", port: int = 8765, token: Optional[str] = None):
    srv = ThreadingHTTPServer((host, port), make_handler(br, token))
    br.on_shutdown = lambda: threading.Thread(target=srv.shutdown, daemon=True).start()
    print(f"US30 Matrix bridge pe http://{host}:{port}  (dashboard: /)  mod={br.t.modes.mode}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        br.save()
        srv.server_close()
        print("Server oprit, starea a fost salvată.")


DASHBOARD = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>US30 Matrix</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--fg:#e6edf3;--mut:#8b949e;--buy:#2ea043;--sell:#f85149;--acc:#388bfd;--line:#30363d}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg);padding:16px}
h1{font-size:18px;margin:0 0 12px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}
button{background:#21262d;color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px 14px;font-weight:600;cursor:pointer}
button.on{background:var(--acc);border-color:var(--acc)}button.ok{background:var(--buy)}button.no{background:var(--sell)}
.mut{color:var(--mut)}.BUY{color:var(--buy);font-weight:700}.SELL{color:var(--sell);font-weight:700}
pre{white-space:pre-wrap;margin:6px 0;font:12px/1.4 ui-monospace,monospace;color:var(--fg)}
table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:4px;border-bottom:1px solid var(--line);text-align:left}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}.kpi div{background:#0d1117;border-radius:8px;padding:8px}
.kpi b{display:block;font-size:16px}
</style></head><body>
<h1>US30 M1 · Matrix Robot</h1>
<div class="card"><div class="row" id="modes"></div>
<div class="mut" id="eff" style="margin-top:8px"></div>
<div class="row" style="margin-top:8px"><button onclick="post('/presence',{})">Sunt online</button></div></div>
<div class="card"><div class="kpi" id="kpi"></div></div>
<div class="card" id="pending"></div>
<div class="card"><b>Semnale</b><div id="sigs"></div></div>
<div class="card"><b>Setări</b><div id="sets" class="kpi" style="margin-top:8px"></div>
<div class="row" style="margin-top:8px"><button onclick="saveSets()">Salvează setările</button><span class="mut" id="setmsg"></span></div></div>
<div class="card"><b>Matricea învățată – top celule</b><table id="cells"></table></div>
<script>
const T=new URLSearchParams(location.search).get('t');const q=p=>p+(T?('?t='+T):'');
async function post(p,b){await fetch(q(p),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});load()}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function load(){const s=await (await fetch(q('/status'))).json();
document.getElementById('modes').innerHTML=['MANUAL','HIBRID','AUTO','ROBOT'].map(m=>`<button class="${s.mode==m?'on':''}" onclick="post('/mode',{mode:'${m}'})">${m}</button>`).join('');
document.getElementById('eff').textContent=`Mod efectiv: ${s.effective} · ${s.online?'online':'offline'} · sesiune ${s.session} · trend M1 ${s.trend_m1} / M15 ${s.trend_m15}`;
const e=s.engine;document.getElementById('kpi').innerHTML=[['Preț',s.price],['Sold',s.balance],['P/L azi',s.risk.day_pnl],['Tranz. azi',s.risk.day_trades],['Semnale',e.signals],['Win-rate',(e.win_rate*100).toFixed(0)+'%'],['Total R',e.total_R],['Eșantioane învățare',e.learning_samples]].map(([k,v])=>`<div><span class="mut">${k}</span><b>${v??'-'}</b></div>`).join('');
document.getElementById('pending').innerHTML=s.pending.length?'<b>Așteaptă aprobarea ta</b>'+s.pending.map(p=>`<div class="card"><pre>${esc(p.text)}</pre><div class="row"><button class="ok" onclick="post('/decision',{sid:${p.sid},approve:true})">Aprob</button><button class="no" onclick="post('/decision',{sid:${p.sid},approve:false})">Refuz</button></div></div>`).join(''):'<span class="mut">Nicio aprobare în așteptare</span>';
document.getElementById('sigs').innerHTML=s.signals.map(r=>`<div class="card"><span class="${r.side}">${r.side}</span> #${r.sid} @ ${r.entry.toFixed(1)} SL ${r.sl.toFixed(1)} TP ${r.tp.toFixed(1)} · <b>${r.status}</b> <span class="mut">${esc(r.why||'')}</span>${r.result?` · <b>${r.result} ${r.R>0?'+':''}${r.R}R</b>`:''}<pre>${esc(r.text)}${r.verdict?'\\n→ '+esc(r.verdict):''}</pre></div>`).join('')||'<span class="mut">încă nimic</span>';
document.getElementById('cells').innerHTML='<tr><th>Celulă</th><th>Win</th><th>n</th><th>R mediu</th></tr>'+s.top_cells.map(c=>`<tr><td>${c.cell}</td><td>${(c.win*100).toFixed(0)}%</td><td>${c.n}</td><td>${c.avgR}</td></tr>`).join('');}
async function loadSets(){const r=await (await fetch(q('/settings'))).json();
document.getElementById('sets').innerHTML=Object.entries(r.values).map(([k,v])=>`<div><span class="mut">${esc(r.help[k])}</span><input data-k="${k}" value="${v}" style="width:100%;background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:4px;margin-top:4px"></div>`).join('')}
async function saveSets(){const b={};document.querySelectorAll('#sets input').forEach(i=>b[i.dataset.k]=i.value);
const r=await fetch(q('/settings'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
const j=await r.json();document.getElementById('setmsg').textContent=j.error?('⚠ '+j.error):' salvat ✓';loadSets()}
load();loadSets();setInterval(load,3000);
</script></body></html>"""
