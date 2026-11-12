// US30 Matrix Bridge – cBot pentru cTrader (ICMarkets)
// Trimite lumânările M1 închise către "creierul" Python (run.py serve), execută ordinele
// primite, desenează semnalele pe grafic și oferă butoane pentru modurile
// MANUAL / HIBRID / AUTO / ROBOT + aprobare/refuz pentru HIBRID.
//
// Instalare: cTrader -> Automate -> New cBot -> lipește acest fișier -> Build.
// Necesită AccessRights.FullAccess (rețea locală + export CSV).

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.Json;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    public enum MxMode { MANUAL, HIBRID, AUTO, ROBOT }

    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class US30MatrixBridge : Robot
    {
        [Parameter("Server URL", DefaultValue = "http://127.0.0.1:8765", Group = "Conexiune")]
        public string ServerUrl { get; set; }

        [Parameter("Pornește serverul Python automat", DefaultValue = true, Group = "Server Python")]
        public bool AutoStartServer { get; set; }

        [Parameter("Folder robot (cu run.py)", DefaultValue = "", Group = "Server Python")]
        public string RobotFolder { get; set; }

        [Parameter("Comanda Python", DefaultValue = "python", Group = "Server Python")]
        public string PythonCmd { get; set; }

        [Parameter("Fereastră server vizibilă", DefaultValue = true, Group = "Server Python")]
        public bool ShowServerWindow { get; set; }

        [Parameter("Oprește serverul la oprirea cBot-ului", DefaultValue = true, Group = "Server Python")]
        public bool StopServerOnStop { get; set; }

        [Parameter("Token (opțional)", DefaultValue = "", Group = "Conexiune")]
        public string Token { get; set; }

        [Parameter("Mod la pornire", DefaultValue = MxMode.MANUAL, Group = "Mod")]
        public MxMode StartMode { get; set; }

        [Parameter("Risc maxim % / tranzacție", DefaultValue = 2.0, MinValue = 0.05, MaxValue = 3.0, Group = "Risc")]
        public double MaxRiskPercent { get; set; }

        [Parameter("Leverage", DefaultValue = 30, MinValue = 1, Group = "Risc")]
        public double Leverage { get; set; }

        [Parameter("Distanță max. de la intrare (în R)", DefaultValue = 0.3, MinValue = 0.0, Group = "Risc")]
        public double MaxEntryDriftR { get; set; }

        [Parameter("Bare warm-up", DefaultValue = 5000, MinValue = 0, Group = "Istoric")]
        public int WarmupBars { get; set; }

        [Parameter("Export istoric CSV la pornire", DefaultValue = false, Group = "Istoric")]
        public bool ExportHistory { get; set; }

        [Parameter("Bare de exportat", DefaultValue = 150000, MinValue = 1000, Group = "Istoric")]
        public int ExportBars { get; set; }

        [Parameter("Label poziții", DefaultValue = "US30MX", Group = "Execuție")]
        public string BotLabel { get; set; }

        private static readonly System.Net.Http.HttpClient _client = new System.Net.Http.HttpClient { Timeout = TimeSpan.FromSeconds(30) };
        private Bars _m1;
        private string _mode = "MANUAL";
        private string _effective = "MANUAL";
        private DateTime _lastPresence = DateTime.MinValue;
        private bool _serverOk;
        private bool _needResync;
        private System.Diagnostics.Process _server;
        private DateTime _lastStartAttempt = DateTime.MinValue;
        private readonly Dictionary<string, Button> _modeButtons = new Dictionary<string, Button>();
        private TextBlock _status;
        private TextBlock _pendingText;
        private StackPanel _pendingPanel;
        private int _pendingSid = -1;
        private readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        protected override void OnStart()
        {
            if (!SymbolName.ToUpperInvariant().Contains("US30"))
                Print("ATENȚIE: robotul este calibrat pentru US30, simbolul curent este " + SymbolName);

            _m1 = MarketData.GetBars(TimeFrame.Minute);
            BuildUi();

            if (AutoStartServer && !Ping())
            {
                StartServer();
                WaitForServer(90);
            }

            if (ExportHistory)
                ExportCsv();

            SendWarmup();
            SetMode(StartMode.ToString());

            _m1.BarOpened += OnM1BarOpened;
            Positions.Closed += OnPositionClosed;
            Chart.MouseMove += args => Presence(false);
            Timer.Start(1);
        }

        protected override void OnStop()
        {
            if (!StopServerOnStop || _server == null) return;
            try
            {
                Post("/shutdown", new Dictionary<string, object>()); // server saves its learning, then exits
                if (!_server.WaitForExit(8000)) _server.Kill(true);
                Print("Server Python oprit.");
            }
            catch (Exception e) { Print("Oprire server: " + e.Message); }
        }

        // ------------------------------------------------------------------ python server
        private string ResolveRobotFolder()
        {
            var cands = new List<string>();
            if (!string.IsNullOrWhiteSpace(RobotFolder)) cands.Add(RobotFolder.Trim().Trim('"'));
            string docs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            cands.Add(System.IO.Path.Combine(docs, "us30_robot"));
            cands.Add(System.IO.Path.Combine(docs, "US30MX", "us30_robot"));
            cands.Add(System.IO.Path.Combine(docs, "dastan-wizard-compressor", "us30_robot"));
            foreach (var c in cands)
                if (System.IO.File.Exists(System.IO.Path.Combine(c, "run.py"))) return c;
            return null;
        }

        private void StartServer()
        {
            _lastStartAttempt = DateTime.UtcNow;
            string folder = ResolveRobotFolder();
            if (folder == null)
            {
                Print("Nu găsesc run.py. Setează parametrul 'Folder robot' (ex. C:\\Users\\...\\us30_robot).");
                return;
            }
            int port = 8765;
            try { port = new Uri(ServerUrl).Port; } catch { }
            string args = "run.py serve --port " + port + (string.IsNullOrEmpty(Token) ? "" : " --token " + Token);
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo(PythonCmd, args)
                {
                    WorkingDirectory = folder,
                    UseShellExecute = ShowServerWindow,
                    CreateNoWindow = !ShowServerWindow,
                    WindowStyle = ShowServerWindow ? System.Diagnostics.ProcessWindowStyle.Minimized
                                                   : System.Diagnostics.ProcessWindowStyle.Hidden
                };
                _server = System.Diagnostics.Process.Start(psi);
                Print("Server Python pornit din " + folder + " (" + PythonCmd + " " + args + ")");
            }
            catch (Exception e)
            {
                Print("Nu pot porni Python ('" + PythonCmd + "'): " + e.Message +
                      ". Verifică instalarea Python sau setează 'Comanda Python' (ex. py sau calea completă python.exe).");
            }
        }

        private void WaitForServer(int seconds)
        {
            var until = DateTime.UtcNow.AddSeconds(seconds);
            while (DateTime.UtcNow < until)
            {
                if (Ping()) { Print("Server Python gata."); return; }
                if (_server != null && _server.HasExited)
                {
                    Print("Serverul Python s-a oprit imediat (cod " + _server.ExitCode + "). Rulează manual 'python run.py serve' ca să vezi eroarea.");
                    return;
                }
                System.Threading.Thread.Sleep(500);
            }
            Print("Serverul Python nu a răspuns în " + seconds + " s.");
        }

        private bool Ping()
        {
            try
            {
                var req = new System.Net.Http.HttpRequestMessage(System.Net.Http.HttpMethod.Get, ServerUrl + "/settings");
                if (!string.IsNullOrEmpty(Token)) req.Headers.Add("X-Token", Token);
                using (var cts = new System.Threading.CancellationTokenSource(TimeSpan.FromSeconds(2)))
                    return _client.SendAsync(req, cts.Token).Result.IsSuccessStatusCode;
            }
            catch { return false; }
        }

        // ------------------------------------------------------------------ data flow
        private void OnM1BarOpened(BarOpenedEventArgs args)
        {
            int k = _m1.Count - 2; // last CLOSED bar
            if (k < 0) return;
            var payload = new Dictionary<string, object>
            {
                ["time"] = _m1.OpenTimes[k].ToString("yyyy-MM-ddTHH:mm:ss", Inv),
                ["o"] = _m1.OpenPrices[k], ["h"] = _m1.HighPrices[k], ["l"] = _m1.LowPrices[k],
                ["c"] = _m1.ClosePrices[k], ["v"] = _m1.TickVolumes[k],
                ["spread"] = Symbol.Spread,
                ["balance"] = Account.Balance, ["equity"] = Account.Equity, ["free_margin"] = Account.FreeMargin
            };
            HandleActions(Post("/bar", payload));
        }

        protected override void OnTimer()
        {
            // watchdog: restart the Python server if the one we started has died
            if (AutoStartServer && !_serverOk && (DateTime.UtcNow - _lastStartAttempt).TotalSeconds > 20
                && (_server == null || _server.HasExited) && !Ping())
            {
                Print("Serverul Python nu răspunde – îl repornesc.");
                StartServer();
            }
            HandleActions(Get("/actions"));
            if (_serverOk && _needResync)
            {
                // the Python server came back (maybe restarted): resend history and our mode
                _needResync = false;
                Print("Server Python reconectat – retrimit istoricul și modul " + _mode);
                SendWarmup();
                SetMode(_mode);
            }
        }

        private void SendWarmup()
        {
            if (WarmupBars <= 0) return;
            while (_m1.Count < WarmupBars + 1)
                if (_m1.LoadMoreHistory() == 0) break;
            int start = Math.Max(0, _m1.Count - 1 - WarmupBars);
            var batch = new List<Dictionary<string, object>>();
            for (int k = start; k < _m1.Count - 1; k++)
            {
                batch.Add(new Dictionary<string, object>
                {
                    ["time"] = _m1.OpenTimes[k].ToString("yyyy-MM-ddTHH:mm:ss", Inv),
                    ["o"] = _m1.OpenPrices[k], ["h"] = _m1.HighPrices[k], ["l"] = _m1.LowPrices[k],
                    ["c"] = _m1.ClosePrices[k], ["v"] = _m1.TickVolumes[k]
                });
                if (batch.Count == 1000 || k == _m1.Count - 2)
                {
                    Post("/warmup", new Dictionary<string, object> { ["bars"] = batch });
                    batch = new List<Dictionary<string, object>>();
                }
            }
            Print("Warm-up trimis: " + (_m1.Count - 1 - start) + " bare M1");
        }

        private void ExportCsv()
        {
            while (_m1.Count < ExportBars)
                if (_m1.LoadMoreHistory() == 0) break;
            string dir = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "US30MX");
            System.IO.Directory.CreateDirectory(dir);
            string file = System.IO.Path.Combine(dir, SymbolName + "_M1_UTC.csv");
            var sb = new StringBuilder("datetime,open,high,low,close,volume\n");
            for (int k = 0; k < _m1.Count - 1; k++)
                sb.AppendFormat(Inv, "{0:yyyy-MM-dd HH:mm:ss},{1},{2},{3},{4},{5}\n", _m1.OpenTimes[k],
                    _m1.OpenPrices[k], _m1.HighPrices[k], _m1.LowPrices[k], _m1.ClosePrices[k], _m1.TickVolumes[k]);
            System.IO.File.WriteAllText(file, sb.ToString());
            Print("Istoric exportat (" + (_m1.Count - 1) + " bare): " + file);
        }

        // ------------------------------------------------------------------ actions
        private void HandleActions(JsonElement root)
        {
            if (root.TryGetProperty("mode", out var m) && m.ValueKind == JsonValueKind.String)
                _effective = m.GetString();
            if (!root.TryGetProperty("actions", out var acts) || acts.ValueKind != JsonValueKind.Array) return;
            foreach (var a in acts.EnumerateArray())
            {
                string type = Str(a, "type");
                try
                {
                    switch (type)
                    {
                        case "open": OpenFromSignal(a); break;
                        case "close": CloseSignal(Int(a, "sid"), Str(a, "reason")); break;
                        case "signal": DrawSignal(a); break;
                        case "status": OnStatus(a); break;
                        case "outcome":
                            Print(string.Format("#{0} {1} {2:+0.00;-0.00}R – {3}", Int(a, "sid"), Str(a, "result"),
                                Dbl(a, "R"), Str(a, "verdict")));
                            break;
                        case "mode":
                            _mode = Str(a, "mode"); _effective = Str(a, "effective");
                            RefreshModeButtons();
                            break;
                    }
                }
                catch (Exception e) { Print("Eroare la acțiunea " + type + ": " + e.Message); }
            }
            UpdateStatus();
        }

        private void OpenFromSignal(JsonElement a)
        {
            int sid = Int(a, "sid");
            var side = Str(a, "side") == "BUY" ? TradeType.Buy : TradeType.Sell;
            double sl = Dbl(a, "sl"), tp = Dbl(a, "tp"), entry = Dbl(a, "entry");
            double riskPct = Math.Min(Dbl(a, "risk_pct"), MaxRiskPercent);
            double price = side == TradeType.Buy ? Symbol.Ask : Symbol.Bid;
            double plannedR = Math.Abs(entry - sl);
            if (plannedR <= 0) { Reject(sid, "SL invalid"); return; }
            if (Math.Abs(price - entry) / plannedR > MaxEntryDriftR) { Reject(sid, "prețul a plecat de la intrare"); return; }

            double slDist = Math.Abs(price - sl), tpDist = Math.Abs(tp - price);
            bool slOk = side == TradeType.Buy ? sl < price : sl > price;
            bool tpOk = side == TradeType.Buy ? tp > price : tp < price;
            if (!slOk || !tpOk) { Reject(sid, "SL/TP pe partea greșită a prețului"); return; }

            double perPointPerUnit = Symbol.TickValue / Symbol.TickSize;
            double riskMoney = Account.Balance * riskPct / 100.0;
            double units = riskMoney / (slDist * perPointPerUnit);
            double maxUnitsMargin = Account.FreeMargin * 0.8 * Leverage / (price * perPointPerUnit);
            units = Math.Min(units, maxUnitsMargin);
            units = Symbol.NormalizeVolumeInUnits(units, RoundingMode.Down);
            if (units < Symbol.VolumeInUnitsMin) { Reject(sid, "volum sub minimul brokerului pentru riscul ales"); return; }
            units = Math.Min(units, Symbol.VolumeInUnitsMax);

            double slPips = slDist / Symbol.PipSize, tpPips = tpDist / Symbol.PipSize;
            var res = ExecuteMarketOrder(side, SymbolName, units, BotLabel, slPips, tpPips, "MX#" + sid);
            if (res.IsSuccessful)
            {
                Print(string.Format(Inv, "Deschis #{0} {1} {2} unități @ {3} SL {4:F1} TP {5:F1} (risc {6:F2}%)",
                    sid, side, units, res.Position.EntryPrice, sl, tp, riskPct));
                Post("/event", new Dictionary<string, object>
                {
                    ["type"] = "opened", ["sid"] = sid, ["price"] = res.Position.EntryPrice, ["units"] = units
                });
            }
            else Reject(sid, "eroare broker: " + res.Error);
        }

        private void Reject(int sid, string reason)
        {
            Print("Semnal #" + sid + " neexecutat: " + reason);
            Post("/event", new Dictionary<string, object> { ["type"] = "rejected", ["sid"] = sid, ["reason"] = reason });
        }

        private void CloseSignal(int sid, string reason)
        {
            foreach (var p in Positions.FindAll(BotLabel, SymbolName).Where(p => p.Comment == "MX#" + sid))
            {
                ClosePosition(p);
                Print("Închis #" + sid + " (" + reason + ")");
            }
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            var p = args.Position;
            if (p.Label != BotLabel || p.Comment == null || !p.Comment.StartsWith("MX#")) return;
            int sid;
            if (!int.TryParse(p.Comment.Substring(3), out sid)) return;
            Post("/event", new Dictionary<string, object>
            {
                ["type"] = "closed", ["sid"] = sid, ["pnl"] = p.NetProfit, ["pips"] = p.Pips,
                ["reason"] = args.Reason.ToString()
            });
        }

        // ------------------------------------------------------------------ chart
        private void DrawSignal(JsonElement a)
        {
            int sid = Int(a, "sid");
            bool buy = Str(a, "side") == "BUY";
            var t0 = Server.Time;
            var t1 = t0.AddMinutes(60);
            double e = Dbl(a, "entry"), sl = Dbl(a, "sl"), tp = Dbl(a, "tp");
            Chart.DrawTrendLine("mx_e" + sid, t0, e, t1, e, Color.White);
            Chart.DrawTrendLine("mx_s" + sid, t0, sl, t1, sl, Color.Red);
            Chart.DrawTrendLine("mx_t" + sid, t0, tp, t1, tp, Color.LimeGreen);
            string head = string.Format(Inv, "#{0} {1} P={2:P0} {3}", sid, buy ? "BUY" : "SELL", Dbl(a, "p"), Str(a, "status"));
            var txt = Chart.DrawText("mx_x" + sid, head, t0, sl, buy ? Color.LimeGreen : Color.OrangeRed);
            txt.VerticalAlignment = buy ? VerticalAlignment.Bottom : VerticalAlignment.Top;
            Print("\n" + Str(a, "text") + "\n[" + Str(a, "status") + "] " + Str(a, "why"));

            if (Str(a, "status") == "PENDING")
            {
                _pendingSid = sid;
                _pendingText.Text = Str(a, "text");
                _pendingPanel.IsVisible = true;
                Notifications.PlaySound(SoundType.Announcement);
            }
        }

        private void OnStatus(JsonElement a)
        {
            int sid = Int(a, "sid");
            Print("Semnal #" + sid + ": " + Str(a, "status") + " – " + Str(a, "why"));
            if (sid == _pendingSid && Str(a, "status") != "PENDING")
            {
                _pendingPanel.IsVisible = false;
                _pendingSid = -1;
            }
        }

        private void BuildUi()
        {
            var root = new StackPanel
            {
                HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top,
                Margin = 8, BackgroundColor = Color.FromArgb(200, 13, 17, 23)
            };
            var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = 4 };
            foreach (var name in new[] { "MANUAL", "HIBRID", "AUTO", "ROBOT" })
            {
                var b = new Button { Text = name, Margin = 2, Padding = new Thickness(6, 3, 6, 3) };
                string m = name;
                b.Click += args => SetMode(m);
                _modeButtons[name] = b;
                row.AddChild(b);
            }
            root.AddChild(row);
            _status = new TextBlock { Margin = 4, ForegroundColor = Color.Silver, Text = "conectare..." };
            root.AddChild(_status);

            _pendingPanel = new StackPanel { Margin = 4, IsVisible = false };
            _pendingText = new TextBlock { ForegroundColor = Color.White, MaxWidth = 420, TextWrapping = TextWrapping.Wrap };
            _pendingPanel.AddChild(_pendingText);
            var pr = new StackPanel { Orientation = Orientation.Horizontal };
            var ok = new Button { Text = "✔ Aprob", Margin = 2, BackgroundColor = Color.SeaGreen };
            var no = new Button { Text = "✖ Refuz", Margin = 2, BackgroundColor = Color.Firebrick };
            ok.Click += args => Decide(true);
            no.Click += args => Decide(false);
            pr.AddChild(ok);
            pr.AddChild(no);
            _pendingPanel.AddChild(pr);
            root.AddChild(_pendingPanel);
            Chart.AddControl(root);
        }

        private void Decide(bool approve)
        {
            if (_pendingSid < 0) return;
            var r = Post("/decision", new Dictionary<string, object> { ["sid"] = _pendingSid, ["approve"] = approve });
            if (r != null) Print("Decizie #" + _pendingSid + ": " + Str(r.Value, "result"));
            _pendingPanel.IsVisible = false;
            _pendingSid = -1;
            OnTimer(); // fetch the resulting open action immediately
        }

        private void SetMode(string mode)
        {
            var r = Post("/mode", new Dictionary<string, object> { ["mode"] = mode });
            if (r != null)
            {
                _mode = Str(r.Value, "mode");
                _effective = Str(r.Value, "effective");
            }
            RefreshModeButtons();
            UpdateStatus();
        }

        private void RefreshModeButtons()
        {
            foreach (var kv in _modeButtons)
                kv.Value.BackgroundColor = kv.Key == _mode ? Color.RoyalBlue : Color.FromArgb(255, 33, 38, 45);
        }

        private void Presence(bool force)
        {
            if (!force && (DateTime.UtcNow - _lastPresence).TotalSeconds < 60) return;
            _lastPresence = DateTime.UtcNow;
            Post("/presence", new Dictionary<string, object>());
        }

        private void UpdateStatus()
        {
            int open = Positions.FindAll(BotLabel, SymbolName).Length;
            _status.Text = (_serverOk ? "● conectat" : "○ server oprit") + "  |  mod: " + _mode +
                           (_effective != _mode ? " (efectiv: " + _effective + ")" : "") +
                           "  |  poziții: " + open;
        }

        // ------------------------------------------------------------------ http helpers
        private JsonElement? Post(string path, object body)
        {
            try
            {
                var req = new System.Net.Http.HttpRequestMessage(System.Net.Http.HttpMethod.Post, ServerUrl + path)
                {
                    Content = new System.Net.Http.StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json")
                };
                if (!string.IsNullOrEmpty(Token)) req.Headers.Add("X-Token", Token);
                var res = _client.SendAsync(req).Result;
                var txt = res.Content.ReadAsStringAsync().Result;
                _serverOk = true;
                return JsonDocument.Parse(txt).RootElement.Clone();
            }
            catch (Exception e)
            {
                if (_serverOk) Print("Server Python indisponibil: " + e.Message);
                _needResync = true; // covers also "server not started yet" when the cBot starts
                _serverOk = false;
                return null;
            }
        }

        private JsonElement? Get(string path)
        {
            try
            {
                var req = new System.Net.Http.HttpRequestMessage(System.Net.Http.HttpMethod.Get, ServerUrl + path);
                if (!string.IsNullOrEmpty(Token)) req.Headers.Add("X-Token", Token);
                var res = _client.SendAsync(req).Result;
                _serverOk = true;
                return JsonDocument.Parse(res.Content.ReadAsStringAsync().Result).RootElement.Clone();
            }
            catch
            {
                _needResync = true;
                _serverOk = false;
                return null;
            }
        }

        private void HandleActions(JsonElement? r) { if (r.HasValue) HandleActions(r.Value); }

        private static string Str(JsonElement e, string k) =>
            e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : "";

        private static double Dbl(JsonElement e, string k) =>
            e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : 0.0;

        private static int Int(JsonElement e, string k) =>
            e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetInt32() : -1;
    }
}
