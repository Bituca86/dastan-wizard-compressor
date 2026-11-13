// =====================================================================================
//  EMAP_Manual_v1 (v1.4: TRAILING cu PAS + PROFILURI LOCK)  —  derivat din EMA_Proiectie_Bot v8.8
//  Gestioneaza DOAR pozitiile manuale (fara label) de pe simbolul graficului:
//    • SL virtual: SL-ul tau daca il pui, altfel distanta fixa
//    • TP virtual optional (automat / pus de tine / din panou), cu LOCK-uri on/off la TP
//    • LOCK1 / LOCK2 / LOCK3 — in puncte SAU in % din TP (selectabil)
//    • TRAILING dupa ultimul LOCK: la fiecare PAS de profit in plus, SL urca cu PAS
//      (distanta pret-SL ramane cea de la ultimul LOCK); SL doar se strange
//    • PROFIL LOCK: Personalizat (parametrii tai) / Rapid / Echilibrat / Trend
//    • Executie virtuala + SL de catastrofa pe server; PILOT (niveluri pe server)
//    • Panou compact: 1 rand / pozitie
//  Paralel: nu atinge pozitiile cu label (alti roboti), obiecte grafice cu prefix unic,
//  rezervare pozitie intre instante (LocalStorage Device) — doua copii nu se bat pe aceeasi pozitie.
//  Distante in unitati de pret (US30: 1 punct = 1.0).
// =====================================================================================
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    public enum EmmExec { Virtual = 0, Server = 1 }
    public enum EmmLock { Puncte = 0, ProcentTP = 1 }
    public enum EmmColt { StangaSus = 0, DreaptaSus = 1, StangaJos = 2, DreaptaJos = 3 }
    public enum EmmProfil { Personalizat = 0, Rapid = 1, Echilibrat = 2, Trend = 3 }

    [Robot(AccessRights = AccessRights.None, TimeZone = TimeZones.UTC)]
    public class EMAP_Manual_v1 : Robot
    {
        // ------------------------------- Mod de lucru -------------------------------
        [Parameter("Executie niveluri", Group = "Mod de lucru", DefaultValue = EmmExec.Virtual)]
        public EmmExec Exec { get; set; }

        [Parameter("PILOT automat la oprirea robotului", Group = "Mod de lucru", DefaultValue = true)]
        public bool PilotOnStop { get; set; }

        [Parameter("SL de catastrofa pe server", Group = "Mod de lucru", DefaultValue = true)]
        public bool CatOn { get; set; }

        [Parameter("SL catastrofa: dincolo de SL virtual (pct)", Group = "Mod de lucru", DefaultValue = 50.0, MinValue = 1)]
        public double CatPts { get; set; }

        [Parameter("SL catastrofa: pas minim actualizare (pct)", Group = "Mod de lucru", DefaultValue = 2.0, MinValue = 0)]
        public double CatStep { get; set; }

        [Parameter("Liniile virtuale se pot trage cu mouse-ul", Group = "Mod de lucru", DefaultValue = true)]
        public bool DragLines { get; set; }

        [Parameter("Reincercare inchidere (ms)", Group = "Mod de lucru", DefaultValue = 300, MinValue = 50)]
        public int RetryMs { get; set; }

        // ------------------------------- Paralel ------------------------------------
        [Parameter("Gestioneaza si label-urile (lista, virgula)", Group = "Functionare in paralel", DefaultValue = "")]
        public string ExtraLabels { get; set; }

        [Parameter("Ignora pozitiile cu comentariu care contine", Group = "Functionare in paralel", DefaultValue = "#skip")]
        public string SkipComment { get; set; }

        [Parameter("Rezervare pozitie intre instante", Group = "Functionare in paralel", DefaultValue = true)]
        public bool ClaimOn { get; set; }

        // ------------------------------- Stop Loss ----------------------------------
        [Parameter("SL pus de tine = SL virtual", Group = "Stop Loss", DefaultValue = true)]
        public bool UseUserSl { get; set; }

        [Parameter("SL fix daca nu ai pus SL (pct)", Group = "Stop Loss", DefaultValue = 25.0, MinValue = 0.1)]
        public double SlFixPts { get; set; }

        // ------------------------------- TP virtual ---------------------------------
        [Parameter("TP virtual automat la preluare", Group = "TP virtual", DefaultValue = false)]
        public bool TpOn { get; set; }

        [Parameter("TP virtual (pct)", Group = "TP virtual", DefaultValue = 40.0, MinValue = 0.1)]
        public double TpPts { get; set; }

        [Parameter("TP pus de tine = TP virtual", Group = "TP virtual", DefaultValue = true)]
        public bool UseUserTp { get; set; }

        [Parameter("LOCK-uri active cand pozitia are TP", Group = "TP virtual", DefaultValue = true)]
        public bool TpLocks { get; set; }

        // ------------------------------- LOCK ---------------------------------------
        [Parameter("Profil LOCK (Personalizat = valorile de mai jos)", Group = "LOCK", DefaultValue = EmmProfil.Personalizat)]
        public EmmProfil Profil { get; set; }

        [Parameter("Mod LOCK", Group = "LOCK", DefaultValue = EmmLock.Puncte)]
        public EmmLock LockMode { get; set; }

        [Parameter("Spatiu minim pret - SL la activare (pct)", Group = "LOCK", DefaultValue = 1.0, MinValue = 0)]
        public double LockMinGap { get; set; }

        [Parameter("Mod %: TP de referinta daca nu are TP (pct)", Group = "LOCK", DefaultValue = 40.0, MinValue = 1)]
        public double RefTpPts { get; set; }

        [Parameter("LOCK1 activ", Group = "LOCK in puncte", DefaultValue = true)] public bool L1On { get; set; }
        [Parameter("LOCK1 activare la profit (pct)", Group = "LOCK in puncte", DefaultValue = 6.0, MinValue = 0.1)] public double L1Trig { get; set; }
        [Parameter("LOCK1 SL peste intrare (pct)", Group = "LOCK in puncte", DefaultValue = 3.0, MinValue = -1000)] public double L1Sl { get; set; }
        [Parameter("LOCK2 activ", Group = "LOCK in puncte", DefaultValue = true)] public bool L2On { get; set; }
        [Parameter("LOCK2 activare la profit (pct)", Group = "LOCK in puncte", DefaultValue = 9.0, MinValue = 0.1)] public double L2Trig { get; set; }
        [Parameter("LOCK2 SL peste intrare (pct)", Group = "LOCK in puncte", DefaultValue = 6.0, MinValue = -1000)] public double L2Sl { get; set; }
        [Parameter("LOCK3 activ", Group = "LOCK in puncte", DefaultValue = true)] public bool L3On { get; set; }
        [Parameter("LOCK3 activare la profit (pct)", Group = "LOCK in puncte", DefaultValue = 12.0, MinValue = 0.1)] public double L3Trig { get; set; }
        [Parameter("LOCK3 SL peste intrare (pct)", Group = "LOCK in puncte", DefaultValue = 9.0, MinValue = -1000)] public double L3Sl { get; set; }

        [Parameter("LOCK1 activare (% din TP)", Group = "LOCK in % din TP", DefaultValue = 50.0, MinValue = 1, MaxValue = 99)] public double L1TrigP { get; set; }
        [Parameter("LOCK1 SL (% din TP)", Group = "LOCK in % din TP", DefaultValue = 30.0, MinValue = -100, MaxValue = 99)] public double L1SlP { get; set; }
        [Parameter("LOCK2 activare (% din TP)", Group = "LOCK in % din TP", DefaultValue = 70.0, MinValue = 1, MaxValue = 99)] public double L2TrigP { get; set; }
        [Parameter("LOCK2 SL (% din TP)", Group = "LOCK in % din TP", DefaultValue = 50.0, MinValue = -100, MaxValue = 99)] public double L2SlP { get; set; }
        [Parameter("LOCK3 activare (% din TP)", Group = "LOCK in % din TP", DefaultValue = 85.0, MinValue = 1, MaxValue = 99)] public double L3TrigP { get; set; }
        [Parameter("LOCK3 SL (% din TP)", Group = "LOCK in % din TP", DefaultValue = 70.0, MinValue = -100, MaxValue = 99)] public double L3SlP { get; set; }

        // ------------------------------- TRAILING dupa ultimul LOCK ------------------
        [Parameter("TRAILING dupa ultimul LOCK", Group = "TRAILING (PAS)", DefaultValue = true)] public bool TrailOn { get; set; }
        [Parameter("PAS in puncte (mod LOCK = puncte)", Group = "TRAILING (PAS)", DefaultValue = 3.0, MinValue = 0.1)] public double TrailStep { get; set; }
        [Parameter("PAS in % din TP (mod LOCK = % din TP)", Group = "TRAILING (PAS)", DefaultValue = 10.0, MinValue = 0.5, MaxValue = 100)] public double TrailStepP { get; set; }

        // ------------------------------- Panou --------------------------------------
        [Parameter("Panou: colt initial", Group = "Panou", DefaultValue = EmmColt.StangaSus)] public EmmColt PanelCorner { get; set; }
        [Parameter("Panou: distanta X fata de colt", Group = "Panou", DefaultValue = 10, MinValue = 0)] public int PanelX { get; set; }
        [Parameter("Panou: distanta Y fata de colt", Group = "Panou", DefaultValue = 90, MinValue = 0)] public int PanelY { get; set; }
        [Parameter("Panou: pas sageti (px)", Group = "Panou", DefaultValue = 20, MinValue = 1, MaxValue = 200)] public int MoveStep { get; set; }
        [Parameter("Panou: ignora pozitia salvata", Group = "Panou", DefaultValue = false)] public bool ResetPos { get; set; }

        // ====================================================================================
        private class St
        {
            public long Id; public Position Pos; public bool Buy;
            public double VSl; public double? VTp; public int Lvl; public bool LocksOn = true; public int TrailK;
            public double? ExpSl, ExpTp;            // ce stim ca e pe server (detectie modificari tale)
            public bool Pending; public DateTime PendSince, FailUntil;
            public bool Closing; public DateTime CloseTry; public int CloseTries; public string CloseWhy = "";
            public bool Dirty = true;
        }

        private const LocalStorageScope Scope = LocalStorageScope.Device;
        private readonly Dictionary<long, St> _st = new Dictionary<long, St>();
        private HashSet<string> _labels;
        private string _inst, _pfx;
        private bool _pilot, _useStore;
        private int _foreign, _cand;
        private DateTime _lastClaim = DateTime.MinValue, _confirmUntil = DateTime.MinValue;
        private double _tol;

        private static readonly CultureInfo IC = CultureInfo.InvariantCulture;

        // ====================================================================================
        protected override void OnStart()
        {
            _inst = Guid.NewGuid().ToString("N").Substring(0, 8);
            _pfx = "EMM_" + _inst + "_";
            _pilot = Exec == EmmExec.Server;
            _tol = Symbol.TickSize * 0.5;
            _useStore = !IsBacktesting;
            ApplyProfile();
            _labels = new HashSet<string>((ExtraLabels ?? "").Split(new[] { ',', ';' }, StringSplitOptions.RemoveEmptyEntries)
                                          .Select(s => s.Trim()).Where(s => s.Length > 0));

            Positions.Opened += e => { if (IsCandidate(e.Position)) _lastClaim = DateTime.MinValue; };
            Positions.Closed += OnClosed;
            Positions.Modified += e => { if (_st.TryGetValue(e.Position.Id, out var s)) DetectUser(s); };
            Chart.ObjectsUpdated += OnObjUpdated;

            BuildPanel();
            ClaimCycle();
            Timer.Start(TimeSpan.FromMilliseconds(250));
            Event("Pornit · instanta " + _inst);
        }

        protected override void OnTick()
        {
            foreach (var s in _st.Values.ToList()) Process(s);
        }

        protected override void OnTimer()
        {
            if ((DateTime.UtcNow - _lastClaim).TotalMilliseconds >= 1000) { ClaimCycle(); _lastClaim = DateTime.UtcNow; }
            foreach (var s in _st.Values.ToList())
            {
                if (s.Pending && (DateTime.UtcNow - s.PendSince).TotalSeconds > 5) s.Pending = false;
                DetectUser(s);
                Process(s);
                SyncServer(s);
            }
            UpdateLines();
            UpdatePanel();
        }

        protected override void OnStop()
        {
            foreach (var s in _st.Values.ToList())
            {
                var p = s.Pos; if (p == null) continue;
                if (PilotOnStop && !_pilot)
                {
                    try { ModifyPosition(p, R(s.VSl), s.VTp.HasValue ? R(s.VTp.Value) : (double?)null); s.ExpSl = R(s.VSl); s.ExpTp = s.VTp; }
                    catch { }
                }
                Save(s);
                StoreRemove("EMM_OWN_" + s.Id);
            }
            StoreFlush();
        }

        // =============================== Profiluri LOCK ====================================
        // Valori in puncte (US30). Simulare pe US30 M1 ICMarkets iun-nov 2026: cu cat lock-urile
        // sunt mai stranse, cu atat mai multe iesiri pe profit mic; TRAILING-ul a adaugat profit
        // in toate variantele.
        private void ApplyProfile()
        {
            if (Profil == EmmProfil.Personalizat) return;
            LockMode = EmmLock.Puncte;
            L1On = L2On = L3On = true;
            TrailOn = true;
            switch (Profil)
            {
                case EmmProfil.Rapid:      SetLocks(6, 3, 9, 6, 12, 9, 3); break;      // iesiri rapide; PAS = pasul dintre lock-uri
                case EmmProfil.Echilibrat: SetLocks(10, 2, 15, 6, 20, 11, 3); break;
                case EmmProfil.Trend:      SetLocks(15, 2, 25, 12, 35, 25, 3); break;  // tine trendul, cedeaza mai mult
            }
            Event("Profil " + Profil + ": LOCK " + L1Trig + "/" + L1Sl + " · " + L2Trig + "/" + L2Sl + " · "
                  + L3Trig + "/" + L3Sl + " · PAS " + TrailStep);
        }

        private void SetLocks(double t1, double s1, double t2, double s2, double t3, double s3, double step)
        {
            L1Trig = t1; L1Sl = s1; L2Trig = t2; L2Sl = s2; L3Trig = t3; L3Sl = s3; TrailStep = step;
        }

        // =============================== Selectie & rezervare ===============================
        private bool IsCandidate(Position p)
        {
            if (p.SymbolName != SymbolName) return false;
            if (!string.IsNullOrEmpty(p.Label) && !_labels.Contains(p.Label)) return false;   // pozitie a altui robot
            if (!string.IsNullOrEmpty(SkipComment) && !string.IsNullOrEmpty(p.Comment) && p.Comment.Contains(SkipComment)) return false;
            return true;
        }

        private void ClaimCycle()
        {
            var cands = Positions.Where(IsCandidate).ToList();
            _cand = cands.Count;
            if (!ClaimOn || !_useStore)
            {
                foreach (var p in cands) if (!_st.ContainsKey(p.Id)) Adopt(p);
                SaveDirty(); StoreFlush();
                return;
            }
            try { LocalStorage.Reload(Scope); } catch { }
            long now = DateTime.UtcNow.Ticks, stale = TimeSpan.FromSeconds(5).Ticks;
            _foreign = 0;
            foreach (var p in cands)
            {
                string key = "EMM_OWN_" + p.Id, owner = null; long t = 0;
                var v = StoreGet(key);
                if (!string.IsNullOrEmpty(v))
                {
                    var a = v.Split('|'); owner = a[0];
                    if (a.Length > 1) long.TryParse(a[1], NumberStyles.Integer, IC, out t);
                }
                // alta instanta vie => cedeaza doar daca are ID mai mic (arbitraj determinist, fara blocaj reciproc)
                bool otherAlive = owner != null && owner != _inst && now - t < stale;
                if (otherAlive && string.CompareOrdinal(owner, _inst) < 0)
                {
                    _foreign++;
                    if (_st.ContainsKey(p.Id)) { DropLocal(p.Id); Event("#" + p.Id + " preluata de alta instanta"); }
                    continue;
                }
                StoreSet(key, _inst + "|" + now.ToString(IC));
                if (!_st.ContainsKey(p.Id)) Adopt(p);                       // preluare imediata
            }
            SaveDirty();
            StoreFlush();
        }

        private void Adopt(Position p)
        {
            bool buy = p.TradeType == TradeType.Buy;
            var s = Load(p) ?? new St
            {
                VSl = UseUserSl && p.StopLoss.HasValue ? p.StopLoss.Value
                      : R(buy ? p.EntryPrice - SlFixPts : p.EntryPrice + SlFixPts),
                VTp = UseUserTp && p.TakeProfit.HasValue ? p.TakeProfit
                      : TpOn ? R(buy ? p.EntryPrice + TpPts : p.EntryPrice - TpPts) : (double?)null,
                ExpSl = p.StopLoss, ExpTp = p.TakeProfit
            };
            s.Id = p.Id; s.Pos = p; s.Buy = buy; s.Dirty = true;
            _st[p.Id] = s;
            Event("#" + p.Id + " preluata · SL v " + F(s.VSl) + (s.VTp.HasValue ? " · TP v " + F(s.VTp.Value) : ""));
        }

        private void DropLocal(long id)
        {
            _st.Remove(id);
            Chart.RemoveObject(_pfx + "SL_" + id);
            Chart.RemoveObject(_pfx + "TP_" + id);
            _drawn.Remove(_pfx + "SL_" + id); _drawn.Remove(_pfx + "TP_" + id);
        }

        private void OnClosed(PositionClosedEventArgs e)
        {
            var p = e.Position;
            if (!_st.TryGetValue(p.Id, out var s)) return;
            string why = s.Closing ? s.CloseWhy : e.Reason.ToString();
            Event("#" + p.Id + " inchisa (" + why + ") " + p.NetProfit.ToString("+0.00;-0.00", IC));
            DropLocal(p.Id);
            StoreRemove("EMM_OWN_" + p.Id);
            StoreRemove("EMM_ST_" + p.Id);
            StoreFlush();
        }

        // =============================== Logica pozitie ====================================
        private void Process(St s)
        {
            var p = s.Pos; if (p == null) return;
            double px = s.Buy ? Symbol.Bid : Symbol.Ask;
            ApplyLocks(s, px);
            if (!_pilot) CheckExit(s, px);
        }

        private bool LocksActive(St s) => s.LocksOn && (!s.VTp.HasValue || TpLocks);

        private bool LockDef(int i, St s, out double trig, out double off)
        {
            trig = off = 0;
            bool on = i == 1 ? L1On : i == 2 ? L2On : L3On;
            if (!on) return false;
            if (LockMode == EmmLock.Puncte)
            {
                trig = i == 1 ? L1Trig : i == 2 ? L2Trig : L3Trig;
                off = i == 1 ? L1Sl : i == 2 ? L2Sl : L3Sl;
            }
            else
            {
                double refd = s.VTp.HasValue ? Math.Abs(s.VTp.Value - s.Pos.EntryPrice) : RefTpPts;
                trig = refd * (i == 1 ? L1TrigP : i == 2 ? L2TrigP : L3TrigP) / 100.0;
                off = refd * (i == 1 ? L1SlP : i == 2 ? L2SlP : L3SlP) / 100.0;
            }
            return true;
        }

        private void ApplyLocks(St s, double px)
        {
            if (!LocksActive(s)) return;
            double e = s.Pos.EntryPrice, prof = s.Buy ? px - e : e - px;
            for (int i = s.Lvl + 1; i <= 3; i++)
            {
                if (!LockDef(i, s, out double trig, out double off)) continue;
                if (prof < trig) break;
                double ns = R(s.Buy ? e + off : e - off);
                double gap = s.Buy ? px - ns : ns - px;
                if (gap < LockMinGap) break;                                   // reincearca la tick-ul urmator
                if (s.Buy ? ns > s.VSl : ns < s.VSl) s.VSl = ns;               // SL doar se strange
                s.Lvl = i; s.Dirty = true;
                Event("#" + s.Id + " LOCK" + i + " · SL v " + F(s.VSl));
            }
            ApplyTrail(s, px, e, prof);
        }

        // ultimul LOCK activat din parametri (1..3), 0 daca niciunul
        private int LastLock(St s)
        {
            for (int i = 3; i >= 1; i--) if (LockDef(i, s, out _, out _)) return i;
            return 0;
        }

        private double Step(St s)
        {
            if (LockMode == EmmLock.Puncte) return TrailStep;
            double refd = s.VTp.HasValue ? Math.Abs(s.VTp.Value - s.Pos.EntryPrice) : RefTpPts;
            return Math.Max(Symbol.TickSize, refd * TrailStepP / 100.0);
        }

        // TRAILING: dupa ultimul LOCK, la fiecare PAS de profit in plus SL urca cu un PAS
        private void ApplyTrail(St s, double px, double e, double prof)
        {
            int last = LastLock(s);
            if (!TrailOn || last == 0 || s.Lvl < last) return;
            if (!LockDef(last, s, out double trig, out double off)) return;
            double step = Step(s);
            int k = (int)Math.Floor((prof - trig) / step);
            if (k < 1) return;
            double ns = R(s.Buy ? e + off + k * step : e - off - k * step);
            double gap = s.Buy ? px - ns : ns - px;
            if (gap < LockMinGap) return;                                      // reincearca la tick-ul urmator
            if (s.Buy ? ns > s.VSl + _tol : ns < s.VSl - _tol)
            {
                s.VSl = ns; s.Dirty = true;
                if (k > s.TrailK) Event("#" + s.Id + " TRAIL pas " + k + " · SL v " + F(s.VSl));
            }
            if (k > s.TrailK) s.TrailK = k;
        }

        // urmatorul pas de trailing (pentru panou)
        private bool NextTrail(St s, out int k, out double atPts, out double slPts)
        {
            k = 0; atPts = slPts = 0;
            int last = LastLock(s);
            if (!TrailOn || last == 0 || s.Lvl < last || !LockDef(last, s, out double trig, out double off)) return false;
            double step = Step(s);
            double prof = s.Buy ? Symbol.Bid - s.Pos.EntryPrice : s.Pos.EntryPrice - Symbol.Ask;
            k = Math.Max(0, (int)Math.Floor((prof - trig) / step)) + 1;
            atPts = trig + k * step;
            slPts = off + k * step;
            return true;
        }

        private void CheckExit(St s, double px)
        {
            if (s.Closing && (DateTime.UtcNow - s.CloseTry).TotalMilliseconds < (s.CloseTries < 5 ? RetryMs : 2000)) return;
            bool sl = s.Buy ? px <= s.VSl : px >= s.VSl;
            bool tp = s.VTp.HasValue && (s.Buy ? px >= s.VTp.Value : px <= s.VTp.Value);
            if (sl) DoClose(s, s.Lvl > 0 ? "LOCK" + s.Lvl : "SL v");
            else if (tp) DoClose(s, "TP v");
        }

        private void DoClose(St s, string why)
        {
            var p = s.Pos; if (p == null) return;
            s.Closing = true; s.CloseTry = DateTime.UtcNow; s.CloseTries++; s.CloseWhy = why;
            ClosePositionAsync(p, r =>
            {
                if (!r.IsSuccessful) Event("#" + s.Id + " inchidere esuata (" + r.Error + ") · reincerc");
            });
        }

        // =============================== Server: catastrofa / PILOT =========================
        private void SyncServer(St s)
        {
            var p = s.Pos;
            if (p == null || s.Pending || s.Closing || DateTime.UtcNow < s.FailUntil) return;

            double? dSl, dTp;
            if (_pilot) { dSl = R(s.VSl); dTp = s.VTp.HasValue ? R(s.VTp.Value) : (double?)null; }
            else
            {
                dTp = null;                                                    // TP ascuns de broker
                if (CatOn)
                {
                    double cat = R(s.Buy ? s.VSl - CatPts : s.VSl + CatPts);
                    dSl = p.StopLoss.HasValue && Math.Abs(p.StopLoss.Value - cat) < CatStep ? p.StopLoss : cat;
                }
                else dSl = null;
            }

            if (Eq(p.StopLoss, dSl) && Eq(p.TakeProfit, dTp)) { s.ExpSl = p.StopLoss; s.ExpTp = p.TakeProfit; return; }

            s.Pending = true; s.PendSince = DateTime.UtcNow; s.ExpSl = dSl; s.ExpTp = dTp;
            ModifyPositionAsync(p, dSl, dTp, r =>
            {
                s.Pending = false;
                if (!r.IsSuccessful)
                {
                    s.FailUntil = DateTime.UtcNow.AddSeconds(2);
                    s.ExpSl = p.StopLoss; s.ExpTp = p.TakeProfit;
                    Event("#" + s.Id + " modificare server respinsa (" + r.Error + ")");
                }
            });
        }

        // SL/TP modificat de tine in terminal => devine nivel virtual
        private void DetectUser(St s)
        {
            var p = s.Pos;
            if (p == null || s.Pending || s.Closing) return;
            if (!Eq(p.StopLoss, s.ExpSl))
            {
                if (p.StopLoss.HasValue && UseUserSl)
                {
                    s.VSl = R(p.StopLoss.Value); s.Dirty = true;
                    Event("#" + s.Id + " SL din terminal -> SL v " + F(s.VSl));
                }
                s.ExpSl = p.StopLoss;
            }
            if (!Eq(p.TakeProfit, s.ExpTp))
            {
                if (p.TakeProfit.HasValue && UseUserTp)
                {
                    s.VTp = R(p.TakeProfit.Value); s.Dirty = true;
                    Event("#" + s.Id + " TP din terminal -> TP v " + F(s.VTp.Value));
                }
                else if (!p.TakeProfit.HasValue && _pilot) { s.VTp = null; s.Dirty = true; }
                s.ExpTp = p.TakeProfit;
            }
        }

        // =============================== Linii pe grafic (stil v8.7) =======================
        private readonly Dictionary<string, double> _drawn = new Dictionary<string, double>();

        private void UpdateLines()
        {
            string tag = _pilot ? " (PILOT)" : "";
            foreach (var s in _st.Values)
            {
                DrawLevel(_pfx + "SL_" + s.Id, s.VSl, Color.Gold, "SL virtual #" + s.Id + tag);
                if (s.VTp.HasValue) DrawLevel(_pfx + "TP_" + s.Id, s.VTp.Value, Color.MediumSpringGreen, "TP virtual #" + s.Id + tag);
                else { Chart.RemoveObject(_pfx + "TP_" + s.Id); _drawn.Remove(_pfx + "TP_" + s.Id); }
            }
        }

        private void DrawLevel(string name, double y, Color clr, string comment)
        {
            if (_drawn.TryGetValue(name, out double old) && Math.Abs(old - y) <= _tol) return;   // nu redesena in timpul tragerii
            var ln = Chart.DrawHorizontalLine(name, y, clr, 2, LineStyle.Solid);
            ln.IsInteractive = DragLines;
            ln.Comment = comment;
            _drawn[name] = y;
        }

        private void OnObjUpdated(ChartObjectsUpdatedEventArgs e)
        {
            foreach (var o in e.ChartObjects)
            {
                if (o == null || o.Name == null || !o.Name.StartsWith(_pfx)) continue;
                if (!(o is ChartHorizontalLine hl)) continue;
                var rest = o.Name.Substring(_pfx.Length);              // "SL_123" / "TP_123"
                if (rest.Length < 4 || !long.TryParse(rest.Substring(3), out long id)) continue;
                if (!_st.TryGetValue(id, out var s)) continue;
                double y = R(hl.Y), px = s.Buy ? Symbol.Bid : Symbol.Ask;

                if (rest.StartsWith("SL_"))
                {
                    if (Math.Abs(y - s.VSl) <= _tol) continue;
                    if (s.Buy ? y < px : y > px) { s.VSl = y; s.Dirty = true; _drawn[o.Name] = y; Event("#" + id + " SL virtual tras la " + F(y)); }
                    else { _drawn.Remove(o.Name); Event("#" + id + " SL dincolo de pret – anulat"); }
                }
                else if (rest.StartsWith("TP_") && s.VTp.HasValue)
                {
                    if (Math.Abs(y - s.VTp.Value) <= _tol) continue;
                    if (s.Buy ? y > px : y < px) { s.VTp = y; s.Dirty = true; _drawn[o.Name] = y; Event("#" + id + " TP virtual tras la " + F(y)); }
                    else { _drawn.Remove(o.Name); Event("#" + id + " TP dincolo de pret – anulat"); }
                }
            }
        }

        // =============================== Panou (aspect EMA_Proiectie_Bot v8.7) =============
        private class Card
        {
            public long Id; public StackPanel Root; public TextBlock Head, Pnl, Tp, Sl, Next, Info; public Border Spacer, Fill;
            public Button BL, BT, BX;
        }
        private readonly List<Card> _cards = new List<Card>();
        private const int MaxCards = 6;
        private const double ProgW = 300;
        private static readonly Color CGreen = Color.FromArgb(255, 38, 201, 120);
        private static readonly Color CRed = Color.FromArgb(255, 239, 83, 80);
        private static readonly Color COrange = Color.FromArgb(255, 255, 167, 38);
        private static readonly Color CMuted = Color.FromArgb(255, 150, 155, 165);
        private static readonly Color CText = Color.FromArgb(255, 225, 225, 225);
        private static readonly Color CTrack = Color.FromArgb(255, 40, 46, 56);
        private static readonly string[] CornerName = { "stanga-sus", "dreapta-sus", "stanga-jos", "dreapta-jos" };

        private TextBlock _hdr, _posTxt, _evTxt, _moveHint;
        private Button _btnPilot, _btnAll, _btnMove, _btnCorner;
        private Border _panel;
        private StackPanel _moveRow;
        private int _px, _py, _corner;
        private bool _mouseHooked;
        private string _lastEvent = "";

        private void Event(string s)
        {
            _lastEvent = $"{Server.Time:HH:mm:ss} {s}";
            Print("EMAP-M: " + s);
        }

        private TextBlock T(string text, double dSize, Color clr, bool bold = false) =>
            new TextBlock { Text = text, FontSize = 11 + dSize, ForegroundColor = clr, FontWeight = bold ? FontWeight.Bold : FontWeight.Normal };

        private static string Dur(TimeSpan d) =>
            d.TotalHours >= 1 ? $"{(int)d.TotalHours}h{d.Minutes:00}m" : $"{(int)d.TotalMinutes:00}:{d.Seconds:00}";

        private void BuildPanel()
        {
            LoadUI();
            var border = new Border
            {
                BackgroundColor = Color.FromArgb(215, 18, 18, 18), BorderColor = Color.DimGray, BorderThickness = 1,
                CornerRadius = 4, Padding = new Thickness(8)
            };
            _panel = border;
            var st = new StackPanel { Orientation = Orientation.Vertical };
            _hdr = new TextBlock { ForegroundColor = Color.Orange, FontSize = 12, FontWeight = FontWeight.Bold };
            _posTxt = new TextBlock { ForegroundColor = CText, FontSize = 12, FontWeight = FontWeight.Bold, Margin = new Thickness(0, 6, 0, 0) };
            _evTxt = new TextBlock { ForegroundColor = Color.LightSteelBlue, FontSize = 11, Margin = new Thickness(0, 4, 0, 0) };

            var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 6, 0, 0) };
            _btnPilot = new Button { Text = "PILOT", Margin = new Thickness(0, 0, 6, 0) };
            _btnPilot.Click += a => { _pilot = !_pilot; Event(_pilot ? "PILOT ON – niveluri pe server" : "PILOT OFF – niveluri virtuale"); };
            _btnAll = new Button { Text = "Inchide tot", Margin = new Thickness(0, 0, 6, 0) };
            _btnAll.Click += a =>
            {
                if (DateTime.UtcNow > _confirmUntil) { _confirmUntil = DateTime.UtcNow.AddSeconds(3); return; }
                _confirmUntil = DateTime.MinValue;
                foreach (var s in _st.Values.ToList()) DoClose(s, "manual (tot)");
            };
            _btnMove = new Button { Text = "⇱ Pozitie" };
            _btnMove.Click += a => ToggleMove();
            row.AddChild(_btnPilot); row.AddChild(_btnAll); row.AddChild(_btnMove);

            _moveRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 0), IsVisible = false };
            _btnCorner = new Button { Text = "Colt: " + CornerName[_corner], Margin = new Thickness(0, 0, 4, 0) };
            _btnCorner.Click += a => NextCorner();
            _moveRow.AddChild(_btnCorner);
            _moveRow.AddChild(MoveBtn("◄", -1, 0));
            _moveRow.AddChild(MoveBtn("▲", 0, -1));
            _moveRow.AddChild(MoveBtn("▼", 0, 1));
            _moveRow.AddChild(MoveBtn("►", 1, 0));
            var bOk = new Button { Text = "OK", BackgroundColor = Color.FromArgb(255, 25, 120, 75), ForegroundColor = Color.White };
            bOk.Click += a => ToggleMove();
            _moveRow.AddChild(bOk);
            _moveHint = new TextBlock { Text = "Click pe grafic = panoul se muta acolo (coltul stanga-sus). Sagetile = reglaj fin. OK = fixeaza.",
                                        ForegroundColor = Color.Orange, FontSize = 11, TextWrapping = TextWrapping.Wrap, IsVisible = false };

            st.AddChild(_hdr); st.AddChild(_posTxt);
            for (int i = 0; i < MaxCards; i++) { var cd = BuildCard(); _cards.Add(cd); st.AddChild(cd.Root); }
            st.AddChild(_evTxt); st.AddChild(row); st.AddChild(_moveRow); st.AddChild(_moveHint);
            border.Child = st;
            Chart.AddControl(border);
            ApplyPos();
        }

        private Card BuildCard()
        {
            var c = new Card { Root = new StackPanel { Margin = new Thickness(0, 5, 0, 2), IsVisible = false } };
            var row = new StackPanel { Orientation = Orientation.Horizontal };
            c.Head = T("", 1, CText, true);
            c.Pnl = T("", 3, CText, true); c.Pnl.Margin = new Thickness(10, 0, 0, 0);
            row.AddChild(c.Head); row.AddChild(c.Pnl);
            c.Root.AddChild(row);

            var track = new Border { BackgroundColor = CTrack, Width = ProgW, Height = 6, Margin = new Thickness(0, 3, 0, 3), HorizontalAlignment = HorizontalAlignment.Left };
            var bar = new StackPanel { Orientation = Orientation.Horizontal };
            c.Spacer = new Border { Width = ProgW / 2, Height = 6 };
            c.Fill = new Border { Width = 0, Height = 6, BackgroundColor = CGreen };
            bar.AddChild(c.Spacer); bar.AddChild(c.Fill);
            track.Child = bar;
            c.Root.AddChild(track);

            c.Tp = T("", 1, CGreen, true);
            c.Sl = T("", 1, COrange, true);
            c.Next = T("", 0, CText); c.Next.TextWrapping = TextWrapping.Wrap;
            c.Info = T("", -1, CMuted); c.Info.TextWrapping = TextWrapping.Wrap;
            c.Root.AddChild(c.Tp); c.Root.AddChild(c.Sl); c.Root.AddChild(c.Next); c.Root.AddChild(c.Info);

            var br = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 3, 0, 0) };
            c.BL = new Button { Text = "LOCK", Margin = new Thickness(0, 0, 6, 0) };
            c.BT = new Button { Text = "TP", Margin = new Thickness(0, 0, 6, 0) };
            c.BX = new Button { Text = "Inchide" };
            c.BL.Click += a =>
            {
                if (!_st.TryGetValue(c.Id, out var s)) return;
                s.LocksOn = !s.LocksOn; s.Dirty = true; Event("#" + s.Id + " LOCK-uri " + (s.LocksOn ? "ON" : "OFF"));
            };
            c.BT.Click += a =>
            {
                if (!_st.TryGetValue(c.Id, out var s)) return;
                if (s.VTp.HasValue) s.VTp = null;
                else s.VTp = R(s.Buy ? s.Pos.EntryPrice + TpPts : s.Pos.EntryPrice - TpPts);
                s.Dirty = true; Event("#" + s.Id + (s.VTp.HasValue ? " TP virtual " + F(s.VTp.Value) : " fara TP"));
            };
            c.BX.Click += a => { if (_st.TryGetValue(c.Id, out var s)) DoClose(s, "manual"); };
            br.AddChild(c.BL); br.AddChild(c.BT); br.AddChild(c.BX);
            c.Root.AddChild(br);
            return c;
        }

        private void UpdatePanel()
        {
            string cur = Account.Asset.Name;
            var list = _st.Values.Where(x => x.Pos != null).OrderBy(x => x.Pos.EntryTime).ToList();
            double sumPts = 0, sumNet = 0;
            foreach (var s in list)
            {
                sumPts += s.Buy ? Symbol.Bid - s.Pos.EntryPrice : s.Pos.EntryPrice - Symbol.Ask;
                sumNet += s.Pos.NetProfit;
            }

            _hdr.Text = $"EMAP_Manual v1.4 | {Profil} | {(_pilot ? "✈ PILOT" : "VIRTUAL")} | LOCK: {(LockMode == EmmLock.Puncte ? "puncte" : "% din TP")}"
                        + (TrailOn ? $" | TRAIL pas {(LockMode == EmmLock.Puncte ? TrailStep.ToString("0.#", IC) + " pct" : TrailStepP.ToString("0.#", IC) + "% TP")}" : " | fara TRAIL")
                        + (TpOn ? $" | TP auto {TpPts:0.#}" : " | fara TP auto");
            if (list.Count == 0)
            {
                _posTxt.Text = _cand > 0 ? $"Pozitii manuale {SymbolName}: {_cand} · negestionate (vezi evenimente)" : "Pozitii manuale: niciuna";
                _posTxt.ForegroundColor = _cand > 0 ? COrange : CMuted;
            }
            else
            {
                _posTxt.Text = $"Pozitii {list.Count} · Total {sumPts:+0.0;-0.0;0.0} · {sumNet:+0.00;-0.00;0.00} {cur}"
                               + (list.Count > MaxCards ? $" (afisate {MaxCards})" : "")
                               + (_cand > list.Count ? $" · ATENTIE: {_cand - list.Count} manuale negestionate" : "");
                _posTxt.ForegroundColor = _cand > list.Count ? COrange : sumNet >= 0 ? CGreen : CRed;
            }

            for (int i = 0; i < _cards.Count; i++)
            {
                if (i >= list.Count) { _cards[i].Root.IsVisible = false; _cards[i].Id = 0; continue; }
                FillCard(_cards[i], list[i], i + 1, cur);
            }

            _btnPilot.Text = _pilot ? "PILOT: ON" : "PILOT: OFF";
            bool conf = DateTime.UtcNow <= _confirmUntil;
            _btnAll.Text = conf ? "Confirma inchiderea" : "Inchide tot";
            _btnAll.BackgroundColor = conf ? Color.FromArgb(255, 150, 30, 30) : Color.FromArgb(255, 60, 60, 60);
            _btnAll.IsEnabled = list.Count > 0;
            _evTxt.Text = "Ultimul eveniment: " + _lastEvent + (_foreign > 0 ? $"  ·  {_foreign} poz. la alta instanta" : "");
        }

        private void FillCard(Card k, St s, int nr, string cur)
        {
            var p = s.Pos;
            k.Id = s.Id;
            double e = p.EntryPrice, dir = s.Buy ? 1 : -1;
            double px = s.Buy ? Symbol.Bid : Symbol.Ask;
            double pts = dir * (px - e);
            double perPt = Symbol.PipValue / Symbol.PipSize * p.VolumeInUnits;     // bani / 1 punct

            k.Root.IsVisible = true;
            k.Head.Text = $"#{nr} {(s.Buy ? "BUY▲" : "SELL▼")} {Symbol.VolumeInUnitsToQuantity(p.VolumeInUnits)} @ {F(e)} · {Dur(Server.Time - p.EntryTime)} · a ta{(_pilot ? " · PILOT" : "")}";
            k.Head.ForegroundColor = s.Buy ? CGreen : CRed;
            k.Pnl.Text = $"{pts:+0.0;-0.0;0.0}  ·  {p.NetProfit:+0.00;-0.00;0.00} {cur}";
            k.Pnl.ForegroundColor = pts >= 0 ? CGreen : CRed;

            // TP
            if (s.VTp.HasValue)
            {
                double tpPts = dir * (s.VTp.Value - e), left = dir * (s.VTp.Value - px);
                k.Tp.Text = $"TP  {F(s.VTp.Value)}   ({tpPts:+0.0;-0.0;0.0} · {tpPts * perPt:+0.00;-0.00;0.00} {cur})   mai sunt {Math.Max(0, left):0.0}";
                k.Tp.ForegroundColor = CGreen;
            }
            else { k.Tp.Text = "TP  — fara TP (doar LOCK-uri)"; k.Tp.ForegroundColor = CMuted; }

            // SL
            double slPts = dir * (s.VSl - e), toSl = dir * (px - s.VSl);
            k.Sl.Text = $"SL  {F(s.VSl)}   ({slPts:+0.0;-0.0;0.0} · {slPts * perPt:+0.00;-0.00;0.00} {cur})   mai sunt {Math.Max(0, toSl):0.0}"
                        + (s.Lvl > 0 ? $"   LOCK{s.Lvl} ✓" : "") + (s.TrailK > 0 ? $"  TRAIL {s.TrailK} ✓" : "");
            k.Sl.ForegroundColor = slPts >= 0 ? CGreen : COrange;

            // urmatorul prag
            double nextLvl = s.VTp.HasValue ? dir * (s.VTp.Value - e) : 0;
            if (s.Closing) { k.Next.Text = $"⏳ inchidere in curs ({s.CloseWhy})"; k.Next.ForegroundColor = COrange; }
            else if (!s.LocksOn) { k.Next.Text = "▶ LOCK-uri oprite pe aceasta pozitie"; k.Next.ForegroundColor = COrange; }
            else if (s.VTp.HasValue && !TpLocks) { k.Next.Text = "▶ LOCK-uri oprite cand exista TP – urmeaza TP"; k.Next.ForegroundColor = CMuted; }
            else if (NextLock(s, out int li, out double atPts, out double nSlPts))
            {
                k.Next.Text = $"▶ LOCK{li} la {F(e + dir * atPts)} ({atPts:+0.0;-0.0;0.0}) · mai sunt {Math.Max(0, atPts - pts):0.0} → SL {F(e + dir * nSlPts)} ({nSlPts:+0.0;-0.0;0.0})";
                k.Next.ForegroundColor = CText;
                nextLvl = atPts;
            }
            else if (NextTrail(s, out int tk, out double tAt, out double tSl))
            {
                k.Next.Text = $"▶ TRAIL pas {tk} la {F(e + dir * tAt)} ({tAt:+0.0;-0.0;0.0}) · mai sunt {Math.Max(0, tAt - pts):0.0} → SL {F(e + dir * tSl)} ({tSl:+0.0;-0.0;0.0})";
                k.Next.ForegroundColor = CText;
                nextLvl = tAt;
            }
            else { k.Next.Text = s.VTp.HasValue ? "▶ toate LOCK-urile aplicate – urmeaza TP" : "▶ toate LOCK-urile aplicate"; k.Next.ForegroundColor = CMuted; }

            string srv = (p.StopLoss.HasValue ? "SL " + F(p.StopLoss.Value) + " " : "") + (p.TakeProfit.HasValue ? "TP " + F(p.TakeProfit.Value) : "");
            k.Info.Text = $"server: {(srv.Trim() == "" ? "—" : srv.Trim())}" + (!_pilot && CatOn ? " (catastrofa)" : "");

            k.BL.Text = s.LocksOn ? "LOCK: ON" : "LOCK: OFF";
            k.BT.Text = s.VTp.HasValue ? "TP: ON" : "TP: OFF";

            // bara: centru = intrare; stanga (rosu) = spre SL, dreapta (verde) = spre urmatorul prag / TP
            double half = ProgW / 2;
            if (pts >= 0 && nextLvl > 0)
            {
                k.Spacer.Width = half;
                k.Fill.Width = half * Math.Min(1.0, pts / nextLvl);
                k.Fill.BackgroundColor = CGreen;
            }
            else if (pts < 0 && slPts < 0)
            {
                double w = half * Math.Min(1.0, -pts / -slPts);
                k.Spacer.Width = half - w; k.Fill.Width = w;
                k.Fill.BackgroundColor = CRed;
            }
            else { k.Spacer.Width = half; k.Fill.Width = 0; }
            k.Fill.IsVisible = k.Fill.Width > 0.5;
        }

        private bool NextLock(St s, out int idx, out double atPts, out double slPts)
        {
            idx = 0; atPts = slPts = 0;
            for (int i = s.Lvl + 1; i <= 3; i++)
                if (LockDef(i, s, out atPts, out slPts)) { idx = i; return true; }
            return false;
        }

        // ---------- pozitia panoului (colt + distante, salvata) ----------
        private bool CornerRight => _corner == (int)EmmColt.DreaptaSus || _corner == (int)EmmColt.DreaptaJos;
        private bool CornerBottom => _corner == (int)EmmColt.StangaJos || _corner == (int)EmmColt.DreaptaJos;

        private Button MoveBtn(string text, int dx, int dy)
        {
            var b = new Button { Text = text, Margin = new Thickness(0, 0, 4, 0) };
            b.Click += a => MoveBy(dx * MoveStep, dy * MoveStep);
            return b;
        }

        private void ApplyPos()
        {
            if (_panel == null) return;
            bool r = CornerRight, b = CornerBottom;
            _panel.HorizontalAlignment = r ? HorizontalAlignment.Right : HorizontalAlignment.Left;
            _panel.VerticalAlignment = b ? VerticalAlignment.Bottom : VerticalAlignment.Top;
            _panel.Margin = new Thickness(r ? 0 : _px, b ? 0 : _py, r ? _px : 0, b ? _py : 0);
        }

        private void ClampPanel()
        {
            double w = 0, h = 0;
            try { w = Chart.Width; h = Chart.Height; } catch { }
            if (w > 120) _px = Math.Min(_px, (int)w - 100);
            if (h > 60) _py = Math.Min(_py, (int)h - 40);
            _px = Math.Max(0, _px);
            _py = Math.Max(0, _py);
            ApplyPos();
        }

        private void MoveBy(int dx, int dy)
        {
            _px += CornerRight ? -dx : dx;
            _py += CornerBottom ? -dy : dy;
            ClampPanel();
        }

        private void NextCorner()
        {
            _corner = _corner == (int)EmmColt.StangaSus ? (int)EmmColt.DreaptaSus
                    : _corner == (int)EmmColt.DreaptaSus ? (int)EmmColt.DreaptaJos
                    : _corner == (int)EmmColt.DreaptaJos ? (int)EmmColt.StangaJos
                    : (int)EmmColt.StangaSus;
            _px = 10;
            _py = CornerBottom ? 10 : 30;
            _btnCorner.Text = "Colt: " + CornerName[_corner];
            ClampPanel();
        }

        private void ToggleMove()
        {
            _moveRow.IsVisible = !_moveRow.IsVisible;
            _moveHint.IsVisible = _moveRow.IsVisible;
            if (_moveRow.IsVisible)
            {
                _btnCorner.Text = "Colt: " + CornerName[_corner];
                if (!_mouseHooked) { Chart.MouseDown += OnChartMouseDownMove; _mouseHooked = true; }
            }
            else
            {
                if (_mouseHooked) { Chart.MouseDown -= OnChartMouseDownMove; _mouseHooked = false; }
                SaveUI();
                Event($"Panou fixat: {CornerName[_corner]}, X={_px}, Y={_py}");
            }
        }

        private void OnChartMouseDownMove(ChartMouseEventArgs a)
        {
            if (_moveRow == null || !_moveRow.IsVisible) return;
            _corner = (int)EmmColt.StangaSus;
            _px = (int)Math.Round(a.MouseX);
            _py = (int)Math.Round(a.MouseY);
            _btnCorner.Text = "Colt: " + CornerName[_corner];
            ClampPanel();
        }

        private string UIKey(string k) =>
            "EMMUI" + new string((SymbolName + TimeFrame).Where(char.IsLetterOrDigit).ToArray()) + k;

        private void SaveUI()
        {
            try
            {
                LocalStorage.SetString(UIKey("X"), _px.ToString(IC), LocalStorageScope.Type);
                LocalStorage.SetString(UIKey("Y"), _py.ToString(IC), LocalStorageScope.Type);
                LocalStorage.SetString(UIKey("C"), _corner.ToString(IC), LocalStorageScope.Type);
                LocalStorage.Flush(LocalStorageScope.Type);
            }
            catch (Exception ex) { Print("ATENTIE LocalStorage: " + ex.Message); }
        }

        private void LoadUI()
        {
            _px = PanelX; _py = PanelY; _corner = (int)PanelCorner;
            if (ResetPos) return;
            try
            {
                int v;
                if (int.TryParse(LocalStorage.GetString(UIKey("X"), LocalStorageScope.Type), out v)) _px = Math.Max(0, v);
                if (int.TryParse(LocalStorage.GetString(UIKey("Y"), LocalStorageScope.Type), out v)) _py = Math.Max(0, v);
                if (int.TryParse(LocalStorage.GetString(UIKey("C"), LocalStorageScope.Type), out v) && v >= 0 && v <= 3) _corner = v;
            }
            catch { }
            if (_px > 4000 || _py > 3000) { _px = PanelX; _py = PanelY; }
        }

        // =============================== Persistenta =======================================
        private void Save(St s)
        {
            if (!_useStore) return;
            string v = string.Join("|",
                s.VSl.ToString("R", IC),
                s.VTp.HasValue ? s.VTp.Value.ToString("R", IC) : "",
                s.Lvl.ToString(IC), s.LocksOn ? "1" : "0",
                s.ExpSl.HasValue ? s.ExpSl.Value.ToString("R", IC) : "",
                s.ExpTp.HasValue ? s.ExpTp.Value.ToString("R", IC) : "");
            StoreSet("EMM_ST_" + s.Id, v);
            s.Dirty = false;
        }

        private void SaveDirty() { foreach (var s in _st.Values) if (s.Dirty) Save(s); }

        private St Load(Position p)
        {
            var v = StoreGet("EMM_ST_" + p.Id);
            if (string.IsNullOrEmpty(v)) return null;
            var a = v.Split('|');
            if (a.Length < 6 || !double.TryParse(a[0], NumberStyles.Float, IC, out double vsl)) return null;
            double? D(string x) => double.TryParse(x, NumberStyles.Float, IC, out double d) ? d : (double?)null;
            return new St
            {
                VSl = vsl, VTp = D(a[1]),
                Lvl = int.TryParse(a[2], NumberStyles.Integer, IC, out int l) ? l : 0,
                LocksOn = a[3] != "0", ExpSl = D(a[4]), ExpTp = D(a[5])
            };
        }

        private string StoreGet(string k) { if (!_useStore) return null; try { return LocalStorage.GetString(k, Scope); } catch { return null; } }
        private void StoreSet(string k, string v) { if (!_useStore) return; try { LocalStorage.SetString(k, v, Scope); } catch { } }
        private void StoreRemove(string k) { if (!_useStore) return; try { LocalStorage.Remove(k, Scope); } catch { } }
        private void StoreFlush() { if (!_useStore) return; try { LocalStorage.Flush(Scope); } catch { } }

        // =============================== Utilitare =========================================
        private double R(double x) => Math.Round(Math.Round(x / Symbol.TickSize) * Symbol.TickSize, Symbol.Digits);
        private string F(double x) => x.ToString("F" + Symbol.Digits, IC);
        private bool Eq(double? a, double? b) => a.HasValue == b.HasValue && (!a.HasValue || Math.Abs(a.Value - b.Value) <= _tol);
    }
}
