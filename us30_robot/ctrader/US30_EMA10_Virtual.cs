// =====================================================================================================
//  US30_EMA10_Virtual  v1.7  —  indicator cTrader (IC Markets), plecat de la US30_EMA_Lines v1.3
// -----------------------------------------------------------------------------------------------------
//  v1.7: TIMEFRAME SECUNDAR (implicit m2) + SEMNAL FINAL de convergenta + panou restructurat.
//        - pe panou apar cele 3 EMA (2 / 5 / 10) calculate pe timeframe-ul secundar, indiferent de grafic:
//            EMA2 peste EMA5 si peste EMA10  = SELL (▼ rosu)        [sens „Revenire”, implicit]
//            EMA2 coboara sub EMA5           = stop SELL (schimbare trend, ▶ gri)
//            EMA2 si sub EMA10               = BUY (▲ verde)
//            EMA2 urca peste EMA5            = stop BUY (schimbare trend, ▶ gri)   … si tot asa.
//          Sensul se poate inversa din parametri („Trend”: EMA2 sus = BUY).
//        - SEMNAL FINAL = starea m2 + contextul graficului (distanta pretului fata de EMA10, blocari).
//          Test pe US30 M1 ICMarkets, iun–nov 2026 (m2 + m5 reconstruite, ~7700 semnale m2, 07–21 UTC):
//            · semnalul m2 SINGUR nu are avantaj masurabil (miscarea medie dupa semnal < 1 punct, sub spread);
//            · singura zona cu miscare favorabila in AMBELE jumatati ale perioadei: pretul la 1,0–1,5 ATR
//              dincolo de EMA10 de pe m5 (+3…+6 pct in iun–aug, +0,7…+3,5 pct in sep–nov, la 4–20 min);
//            · peste 1,5 ATR rezultatul e instabil (+11 / −7 pct) → fara intrare.
//          De aceea „CONFIRMAT” cere zona 1,0–1,5 ATR (setabila). Avantajul e mic si pe un esantion redus
//          (~300 de cazuri pe perioada) — foloseste-l ca filtru, nu ca garantie.
//        - panoul are acum 3 zone: SEMNAL FINAL · timeframe secundar · grafic; detaliile modelului si
//          statistica sunt sub butonul „Detalii”.
//  1) Liniile EMA 1 / 2 / 3 (2 / 5 / 10 implicit), shift, tip medie, istoric, sageti la cross EMA1/EMA2
//     cu pragul de validare al robotului FAST — ca in US30_EMA_Lines v1.3.
//  2) EMA 10 VIRTUALA: proiectia EMA 10 de la lumanarea curenta, H lumanari in viitor (linie punctata).
//     - pretul viitor e estimat de un model kNN cu autoinvatare (ca la EMA_Proiectie_Bot): pentru fiecare
//       lumanare inchisa se retine „amprenta” (distanta pret-EMA, panta EMA, EMA1-EMA2, impuls, corp,
//       ER, volatilitate, bare pe aceeasi parte) si ce a facut pretul in urmatoarele 5 lumanari;
//     - EMA viitoare = recursia exacta a EMA (alfa = 2/(n+1)) aplicata pretului estimat;
//     - orizontul H (3, 4 sau 5 lumanari) e ales AUTOMAT: modelul se testeaza walk-forward pe istoric
//       (fiecare predictie foloseste doar trecutul) si se pastreaza orizontul cu castigul cel mai mare
//       fata de proiectia naiva (pret constant); daca modelul nu bate proiectia naiva, trece singur pe ea.
//  3) PANOU (stil DASTAN_PANOU): non-stop, in timp real, distanta in puncte si pips (+/-):
//       linia de pret (EMA 1 = EMA 2) → EMA 10   si   linia de pret → EMA 10 virtuala;
//       zona distantei fata de istoric (percentila, x ATR), probabilitatea de revenire la EMA 10,
//       „⚠ Atentie! Schimbare de trend!” la intersectia EMA 1 / EMA 2 (2 / 5),
//       statistica istoricului incarcat: medie, mediana, P90/P95, maxime peste / sub EMA 10,
//       extreme High/Low, revenire pe trepte de distanta (scrisa si in Log).
//  v1.6: ETICHETA DE SEMNAL refacuta dupa backtestul EMA10_Revenire_Bot (4 luni, M1):
//        in zona 0,5–2 ATR atingerea EMA10 in BARA URMATOARE are sub 70% in 100% din cazuri (99% sub 50%),
//        deci semnalul pe 1 bara nu e tranzactionabil. Eticheta foloseste acum orizontul de 5 BARE, unde
//        statistica istorica e mare si stabila (M1 / M5, 5 luni): 0,5–1 ATR ≈ 80%, 1–1,5 ATR ≈ 65%.
//          SELL / BUY spre EMA10 = distanta 0,5–1,5 ATR si rata istorica ≤5 bare >= prag (65%), fara
//                                  schimbare de trend recenta contra;
//          BLOCARE = rata istorica < 45% (practic > 2 ATR) sau schimbare de trend EMA2 x EMA5 contra;
//          ASTEAPTA = in rest. Probabilitatea modelului pe 1 bara ramane doar informativa.
//        Filtrul de schimbare de trend NU a fost inca testat in backtest (e o masura de prudenta).
//  v1.5: - avertismentul de trend: ▲ verde (ascendent) / ▼ rosu (descendent), text in aceeasi culoare;
//        - ETICHETA DE SEMNAL din concluziile studiului (M1 + M5, walk-forward):
//            SELL / BUY spre EMA10 = probabilitatea REALA (calibrata) de atingere in bara urmatoare >= prag
//                                    si distanta in zona utila 0,5 – 2 ATR (TP = EMA10);
//            BLOCARE = probabilitate <= prag de blocare (pretul se departeaza) sau distanta > 2 ATR (trend);
//            ASTEAPTA = in rest (cu motivul).
//  v1.4: pe orizontul util se afiseaza ORICE estimare a modelului, prin calibrarea ei verificata
//        (pe ≤1 bara modelul e calibrat si sub 50%: 4%→4,5%, 25%→23%, 45%→44% – US30 M1, n≈10000);
//        se ascunde doar daca zona respectiva are sub 30 de verificari.
//  v1.3: revenirea se afiseaza pe ORIZONTUL unde modelul bate istoricul (ales automat din verificare;
//        pe US30 M1 / M5 = ≤1 bara, +5,7% / +7,1% Brier); ≤5 bare = rata istorica (acolo istoricul e mai bun);
//        estimarea modelului sub 50% nu se foloseste (necalibrata) – se afiseaza rata istorica;
//        implicit 154 zile istoric, memorie 30000, validare 10000 (valorile testate, v1.5).
//  v1.2: VERIFICARE walk-forward a probabilitatii de revenire a modelului (≤5 bare):
//        - fiecare predictie e facuta doar cu trecutul si comparata ulterior cu ce s-a intamplat;
//        - reper = rata istorica pe treapta de distanta (tot walk-forward, aceleasi 5 trepte ca pe panou);
//        - scor Brier model vs reper + tabel de calibrare (cand modelul spune 80–90%, cat s-a realizat);
//        - pe panou: probabilitatea modelului → probabilitatea REALA calibrata + verdict (MODEL UTIL / istoric).
//  v1.1: sageata de trend langa EMA2 → EMA10: ▲ verde EMA2 > EMA5 > EMA10, ▼ rosu invers,
//        ▶ gri = lateral (ordine amestecata sau EMA-uri prea apropiate); m1 / h1 afisate corect.
// =====================================================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Indicators
{
    public enum VeColt { StangaSus, DreaptaSus, StangaJos, DreaptaJos }
    public enum VeOrizont { Auto, Bare3, Bare4, Bare5 }
    public enum VeLinie { EMA1, PretCurent }
    public enum VeSens { Revenire, Trend }

    [Indicator(IsOverlay = true, AccessRights = AccessRights.None, TimeZone = TimeZones.UTC)]
    public class US30_EMA10_Virtual : Indicator
    {
        // ---------------- EMA-uri (ca US30_EMA_Lines v1.3) ----------------
        [Parameter("Afiseaza EMA 1", DefaultValue = true, Group = "EMA 1 (rapida FAST)")] public bool Show1 { get; set; }
        [Parameter("Perioada", DefaultValue = 2, MinValue = 1, Group = "EMA 1 (rapida FAST)")] public int Period1 { get; set; }
        [Parameter("Shift (bare)", DefaultValue = 0, MinValue = -500, MaxValue = 500, Group = "EMA 1 (rapida FAST)")] public int Shift1 { get; set; }

        [Parameter("Afiseaza EMA 2", DefaultValue = true, Group = "EMA 2 (lenta FAST)")] public bool Show2 { get; set; }
        [Parameter("Perioada", DefaultValue = 5, MinValue = 1, Group = "EMA 2 (lenta FAST)")] public int Period2 { get; set; }
        [Parameter("Shift (bare)", DefaultValue = 0, MinValue = -500, MaxValue = 500, Group = "EMA 2 (lenta FAST)")] public int Shift2 { get; set; }

        [Parameter("Afiseaza EMA 3", DefaultValue = true, Group = "EMA 3 (optional)")] public bool Show3 { get; set; }
        [Parameter("Perioada", DefaultValue = 10, MinValue = 1, Group = "EMA 3 (optional)")] public int Period3 { get; set; }
        [Parameter("Shift (bare)", DefaultValue = 0, MinValue = -500, MaxValue = 500, Group = "EMA 3 (optional)")] public int Shift3 { get; set; }

        [Parameter("Sursa pret", Group = "Calcul")] public DataSeries Source { get; set; }
        [Parameter("Tip medie", DefaultValue = MovingAverageType.Exponential, Group = "Calcul")] public MovingAverageType MaType { get; set; }

        [Parameter("Zile de istoric de incarcat", DefaultValue = 154, MinValue = 1, MaxValue = 730, Group = "Istoric")] public int DaysBack { get; set; }

        [Parameter("Sageti la cross EMA 1 / EMA 2", DefaultValue = true, Group = "Cross (ca robotul FAST)")] public bool Arrows { get; set; }
        [Parameter("Cross valid de la (puncte intre EMA-uri)", DefaultValue = 0.5, MinValue = 0, Group = "Cross (ca robotul FAST)")] public double FsGap { get; set; }
        [Parameter("Avertisment activ (bare dupa cross)", DefaultValue = 3, MinValue = 1, MaxValue = 50, Group = "Cross (ca robotul FAST)")] public int WarnBars { get; set; }
        [Parameter("Trend: lateral daca distanta intre EMA-uri < (x ATR)", DefaultValue = 0.1, MinValue = 0, Step = 0.05, Group = "Cross (ca robotul FAST)")] public double TrendMinAtr { get; set; }
        [Parameter("Sageata BUY", DefaultValue = "#FF26C978", Group = "Cross (ca robotul FAST)")] public Color CArrUp { get; set; }
        [Parameter("Sageata SELL", DefaultValue = "#FFEF5350", Group = "Cross (ca robotul FAST)")] public Color CArrDn { get; set; }

        // ---------------- timeframe secundar + convergenta ----------------
        [Parameter("Afiseaza timeframe-ul secundar", DefaultValue = true, Group = "Timeframe secundar (m2)")] public bool ShowFast { get; set; }
        [Parameter("Timeframe secundar", DefaultValue = "Minute2", Group = "Timeframe secundar (m2)")] public TimeFrame FastTf { get; set; }
        [Parameter("EMA rapida", DefaultValue = 2, MinValue = 1, Group = "Timeframe secundar (m2)")] public int FastP1 { get; set; }
        [Parameter("EMA medie", DefaultValue = 5, MinValue = 2, Group = "Timeframe secundar (m2)")] public int FastP2 { get; set; }
        [Parameter("EMA lenta", DefaultValue = 10, MinValue = 3, Group = "Timeframe secundar (m2)")] public int FastP3 { get; set; }
        [Parameter("Prag anti-palpaire intre EMA-uri (puncte)", DefaultValue = 0.3, MinValue = 0, Step = 0.1, Group = "Timeframe secundar (m2)")] public double FastGap { get; set; }
        [Parameter("Sens semnal (Revenire: EMA rapida sus = SELL)", DefaultValue = VeSens.Revenire, Group = "Timeframe secundar (m2)")] public VeSens FastSense { get; set; }
        [Parameter("CONFIRMAT de la distanta (x ATR grafic)", DefaultValue = 1.0, MinValue = 0, Step = 0.1, Group = "Semnal final (convergenta)")] public double ConvMinAtr { get; set; }
        [Parameter("CONFIRMAT pana la distanta (x ATR grafic)", DefaultValue = 1.5, MinValue = 0.1, Step = 0.1, Group = "Semnal final (convergenta)")] public double ConvMaxAtr { get; set; }

        // ---------------- EMA 10 virtuala ----------------
        [Parameter("Perioada EMA de referinta", DefaultValue = 10, MinValue = 2, Group = "EMA 10 virtuala")] public int RefPeriod { get; set; }
        [Parameter("Linia de pret pentru distanta", DefaultValue = VeLinie.EMA1, Group = "EMA 10 virtuala")] public VeLinie PriceLine { get; set; }
        [Parameter("Orizont proiectie", DefaultValue = VeOrizont.Auto, Group = "EMA 10 virtuala")] public VeOrizont Horizon { get; set; }
        [Parameter("Deseneaza EMA virtuala", DefaultValue = true, Group = "EMA 10 virtuala")] public bool DrawProj { get; set; }
        [Parameter("Culoare EMA virtuala", DefaultValue = "#FFFFA500", Group = "EMA 10 virtuala")] public Color CProj { get; set; }
        [Parameter("Grosime EMA virtuala", DefaultValue = 2, MinValue = 1, MaxValue = 5, Group = "EMA 10 virtuala")] public int ProjThick { get; set; }

        // ---------------- invatare ----------------
        [Parameter("Memorie max (mostre)", DefaultValue = 30000, MinValue = 500, Group = "Invatare")] public int MaxSamples { get; set; }
        [Parameter("Mostre minime pentru model", DefaultValue = 300, MinValue = 50, Group = "Invatare")] public int MinSamples { get; set; }
        [Parameter("Vecini K", DefaultValue = 40, MinValue = 5, MaxValue = 200, Group = "Invatare")] public int K { get; set; }
        [Parameter("Validare walk-forward (bare)", DefaultValue = 10000, MinValue = 200, Group = "Invatare")] public int ValidBars { get; set; }
        [Parameter("Revenire: castig minim model fata de istoric (%)", DefaultValue = 3.0, MinValue = 0, Step = 0.5, Group = "Invatare")] public double MinGainPct { get; set; }
        [Parameter("Semnal: rata istorica minima ≤5 bare (%)", DefaultValue = 65, MinValue = 40, MaxValue = 99, Group = "Semnal (≤5 bare, istoric)")] public double SigEnterPct { get; set; }
        [Parameter("Semnal: blocare sub rata istorica (%)", DefaultValue = 45, MinValue = 1, MaxValue = 60, Group = "Semnal (≤5 bare, istoric)")] public double SigBlockPct { get; set; }
        [Parameter("Semnal: distanta minima fata de EMA (x ATR)", DefaultValue = 0.5, MinValue = 0, Step = 0.1, Group = "Semnal (≤5 bare, istoric)")] public double SigMinAtr { get; set; }
        [Parameter("Semnal: distanta maxima fata de EMA (x ATR)", DefaultValue = 1.5, MinValue = 0.5, Step = 0.1, Group = "Semnal (≤5 bare, istoric)")] public double SigMaxAtr { get; set; }
        [Parameter("Semnal: blocare la schimbare de trend contra", DefaultValue = true, Group = "Semnal (≤5 bare, istoric)")] public bool SigTrendBlock { get; set; }
        [Parameter("Forta corectie (0-1)", DefaultValue = 1.0, MinValue = 0, MaxValue = 1, Step = 0.1, Group = "Invatare")] public double LearnStrength { get; set; }
        [Parameter("Perioada ATR", DefaultValue = 14, MinValue = 2, Group = "Invatare")] public int AtrPeriod { get; set; }
        [Parameter("Perioada ATR lung", DefaultValue = 100, MinValue = 10, Group = "Invatare")] public int AtrLongPeriod { get; set; }

        // ---------------- panou (ca DASTAN_PANOU) ----------------
        [Parameter("Titlu panou", DefaultValue = "EMA10 VIRTUAL", Group = "Panou")] public string Title { get; set; }
        [Parameter("Colt initial", DefaultValue = VeColt.DreaptaSus, Group = "Panou")] public VeColt PanelCorner { get; set; }
        [Parameter("Distanta X initiala fata de colt", DefaultValue = 300, MinValue = 0, Group = "Panou")] public int PanelX { get; set; }
        [Parameter("Distanta Y initiala fata de colt", DefaultValue = 5, MinValue = 0, Group = "Panou")] public int PanelY { get; set; }
        [Parameter("Ignora pozitia salvata", DefaultValue = false, Group = "Panou")] public bool ResetPos { get; set; }
        [Parameter("Font panou (8-16)", DefaultValue = 10, MinValue = 8, MaxValue = 16, Group = "Panou")] public int PanelFont { get; set; }
        [Parameter("Latime panou (px)", DefaultValue = 380, MinValue = 250, MaxValue = 900, Group = "Panou")] public int PanelWidth { get; set; }
        [Parameter("Reimprospatare (ms)", DefaultValue = 500, MinValue = 200, MaxValue = 5000, Group = "Panou")] public int RefreshMs { get; set; }

        [Parameter("Fundal", DefaultValue = "#EB12161C", Group = "Culori")] public Color CBg { get; set; }
        [Parameter("Chenar", DefaultValue = "#FF374150", Group = "Culori")] public Color CBorder { get; set; }
        [Parameter("Text", DefaultValue = "#FFDCE1E8", Group = "Culori")] public Color CText { get; set; }
        [Parameter("Text estompat", DefaultValue = "#FF828C9B", Group = "Culori")] public Color CMuted { get; set; }
        [Parameter("Verde (peste EMA)", DefaultValue = "#FF26C978", Group = "Culori")] public Color CGreen { get; set; }
        [Parameter("Rosu (sub EMA)", DefaultValue = "#FFEF5350", Group = "Culori")] public Color CRed { get; set; }
        [Parameter("Portocaliu (intins / avertisment)", DefaultValue = "#FFFFA726", Group = "Culori")] public Color COrange { get; set; }
        [Parameter("Neutru", DefaultValue = "#FFC8C8C8", Group = "Culori")] public Color CMid { get; set; }
        [Parameter("Butoane", DefaultValue = "#FF2D3746", Group = "Culori")] public Color CBtn { get; set; }

        // ---------------- iesiri ----------------
        [Output("EMA 1", LineColor = "#66CCFF", Thickness = 1)] public IndicatorDataSeries Ema1 { get; set; }
        [Output("EMA 2", LineColor = "#39FF14", Thickness = 2)] public IndicatorDataSeries Ema2 { get; set; }
        [Output("EMA 3", LineColor = "#FF2020", Thickness = 2)] public IndicatorDataSeries Ema3 { get; set; }

        // =====================================================================================
        private const int NF = 8, HMAX = 5, LOOK = 20, MoveStep = 20;
        private static readonly double[] FW = { 2.0, 1.5, 1.0, 1.0, 0.5, 1.0, 0.5, 1.0 };   // ponderi amprenta
        private static readonly string[] CornerName = { "stanga-sus", "dreapta-sus", "stanga-jos", "dreapta-jos" };
        private readonly CultureInfo _ci = CultureInfo.GetCultureInfo("ro-RO");

        private MovingAverage _m1, _m2, _m3;

        // serii pe lumanari INCHISE (index = index bara)
        private readonly List<double> _c = new List<double>(), _h = new List<double>(), _l = new List<double>(), _o = new List<double>();
        private readonly List<double> _e = new List<double>(), _f1 = new List<double>(), _f2 = new List<double>();
        private readonly List<double> _tr = new List<double>(), _a = new List<double>(), _al = new List<double>();
        private readonly List<int> _run = new List<int>();
        private int _n;                          // numar de bare inchise procesate
        private int _warm, _validFrom = int.MaxValue;
        private double _al0, _al1, _al2;         // alfa EMA ref / EMA1 / EMA2
        private double _trSum, _trSumL;

        // memorie kNN (inel)
        private double[] _sf; private float[] _sd; private byte[] _stc;
        private int _sCount, _sHead;

        // validare walk-forward
        private class Pend { public double[] M = new double[HMAX], N = new double[HMAX], P = new double[HMAX], B = new double[HMAX]; public bool HasP; }

        // verificare probabilitate revenire (walk-forward)
        private readonly double[] _rTot = new double[5];                 // reper: mostre pe treapta
        private readonly double[,] _rHit = new double[5, HMAX];          // reper: atingeri in <= h+1 bare
        private readonly double[] _brM = new double[HMAX], _brB = new double[HMAX], _brN = new double[HMAX];
        private readonly double[,] _calN = new double[HMAX, 10], _calP = new double[HMAX, 10], _calY = new double[HMAX, 10];
        private bool _calPrinted;
        private int _hb = -1;                                             // orizontul de revenire unde modelul e util (0 = ≤1 bara)
        private static int Bucket(double dAtr) => dAtr < 0.5 ? 0 : dAtr < 1 ? 1 : dAtr < 1.5 ? 2 : dAtr < 2 ? 3 : 4;
        private readonly Dictionary<int, Pend> _pend = new Dictionary<int, Pend>();
        private readonly double[] _errM = new double[HMAX + 1], _errN = new double[HMAX + 1];
        private double _vCnt;

        // cross EMA1 / EMA2
        private int _xSign, _lastCrossBar = -1, _lastCrossDir;

        // statistica istoric
        private double[] _absSorted = new double[0];
        private readonly double[] _bTouch5 = new double[5], _bN = new double[5], _bMed = new double[5];
        private string[] _statLines = new string[0];
        private int _statAt = -1;
        private bool _printed;

        // timeframe secundar (EMA-uri pe bare inchise + stare)
        private Bars _fb;
        private int _fn, _fr25, _fr210, _fCode, _fLastMain, _fStateBar = -1;
        private double _g1, _g2, _g3, _fa1, _fa2, _fa3;
        private TextBlock _tFinal, _tFinalSub, _tFastHdr, _tFast, _tFastSub, _tChartHdr;

        // panou
        private StackPanel _root, _body, _moveRow, _statBox;
        private Border _main;
        private Button _bMin, _bTitle, _bCorner, _bStat;
        private TextBlock _tSig, _tCal, _tArrow, _tD1, _tD2, _tSub, _tZone, _tRev, _tWarn, _tModel, _tMoveHint;
        private readonly List<TextBlock> _tStat = new List<TextBlock>();
        private int _px, _py, _corner;
        private bool _min, _showStat = true, _mouseHooked, _blink;
        private DateTime _lastUi = DateTime.MinValue;

        // =====================================================================================
        protected override void Initialize()
        {
            if (Bars.Count > 0)
            {
                DateTime want = Bars.OpenTimes.LastValue.AddDays(-DaysBack);
                int guard = 0;
                while (Bars.OpenTimes[0] > want && guard++ < 500)
                    if (Bars.LoadMoreHistory() <= 0) break;
            }

            if (Show1) _m1 = Indicators.MovingAverage(Source, Period1, MaType);
            if (Show2) _m2 = Indicators.MovingAverage(Source, Period2, MaType);
            if (Show3) _m3 = Indicators.MovingAverage(Source, Period3, MaType);

            _al0 = 2.0 / (RefPeriod + 1); _al1 = 2.0 / (Period1 + 1); _al2 = 2.0 / (Period2 + 1);
            _warm = Math.Max(Math.Max(AtrLongPeriod + 5, 3 * RefPeriod), 30);
            _sf = new double[MaxSamples * NF]; _sd = new float[MaxSamples * HMAX]; _stc = new byte[MaxSamples];

            if (ShowFast)
            {
                try
                {
                    _fb = MarketData.GetBars(FastTf);
                    _fa1 = 2.0 / (FastP1 + 1); _fa2 = 2.0 / (FastP2 + 1); _fa3 = 2.0 / (FastP3 + 1);
                }
                catch (Exception ex) { Print("Timeframe secundar indisponibil: " + ex.Message); _fb = null; }
            }

            LoadUI();
            BuildPanel();
            ApplyPos();
            ApplyVisibility();
            Timer.Start(TimeSpan.FromMilliseconds(RefreshMs));
        }

        public override void Calculate(int index)
        {
            Ema1[index] = Val(_m1, index, Shift1);
            Ema2[index] = Val(_m2, index, Shift2);
            Ema3[index] = Val(_m3, index, Shift3);

            if (!IsLastBar) return;
            if ((DateTime.UtcNow - _lastUi).TotalMilliseconds < 200) return;
            Live();
        }

        protected override void OnTimer() => Live();

        private static double Val(MovingAverage ma, int index, int shift)
        {
            if (ma == null) return double.NaN;
            int src = index - shift;
            if (src < 0 || src > index) return double.NaN;
            return ma.Result[src];
        }

        // =============================== procesare bare inchise ===============================
        private void Sync()
        {
            int lastClosed = Bars.Count - 2;
            if (lastClosed < 0) return;
            if (_validFrom == int.MaxValue) _validFrom = Math.Max(_warm, lastClosed - ValidBars);
            while (_n <= lastClosed) ProcessBar(_n);
            if (_statAt < 0 || _n - _statAt >= 10) ComputeStats();
        }

        private void ProcessBar(int i)
        {
            double c = Bars.ClosePrices[i], h = Bars.HighPrices[i], l = Bars.LowPrices[i], o = Bars.OpenPrices[i];
            double e = i == 0 ? c : _e[i - 1] + _al0 * (c - _e[i - 1]);
            double f1 = i == 0 ? c : _f1[i - 1] + _al1 * (c - _f1[i - 1]);
            double f2 = i == 0 ? c : _f2[i - 1] + _al2 * (c - _f2[i - 1]);
            double tr = i == 0 ? h - l : Math.Max(h, _c[i - 1]) - Math.Min(l, _c[i - 1]);

            _trSum += tr; if (i >= AtrPeriod) _trSum -= _tr[i - AtrPeriod];
            _trSumL += tr; if (i >= AtrLongPeriod) _trSumL -= _tr[i - AtrLongPeriod];
            double a = _trSum / Math.Min(i + 1, AtrPeriod), al = _trSumL / Math.Min(i + 1, AtrLongPeriod);

            int run = i == 0 ? 1 : Math.Sign(c - e) == Math.Sign(_c[i - 1] - _e[i - 1]) ? _run[i - 1] + 1 : 1;

            _c.Add(c); _h.Add(h); _l.Add(l); _o.Add(o); _e.Add(e); _f1.Add(f1); _f2.Add(f2);
            _tr.Add(tr); _a.Add(Math.Max(a, Symbol.TickSize)); _al.Add(Math.Max(al, Symbol.TickSize)); _run.Add(run);
            _n = i + 1;

            // cross EMA1 / EMA2 (prag de validare ca robotul FAST)
            double d12 = f1 - f2;
            if (_xSign == 0) { if (Math.Abs(d12) >= FsGap && d12 != 0) _xSign = Math.Sign(d12); }
            else if (Math.Sign(d12) == -_xSign && Math.Abs(d12) >= FsGap)
            {
                _xSign = -_xSign; _lastCrossBar = i; _lastCrossDir = _xSign;
                if (Arrows && i > _warm)
                {
                    if (_xSign > 0) Chart.DrawIcon("EV_x_" + i, ChartIconType.UpArrow, Bars.OpenTimes[i], l - 0.3 * _a[i], CArrUp);
                    else Chart.DrawIcon("EV_x_" + i, ChartIconType.DownArrow, Bars.OpenTimes[i], h + 0.3 * _a[i], CArrDn);
                }
            }

            // invatare: mostra pentru bara i-5 (rezultatul e acum cunoscut)
            if (i - HMAX >= _warm) AddSample(i - HMAX);

            // validare: comparam predictiile facute acum 1..5 bare cu EMA realizata
            for (int k = 1; k <= HMAX; k++)
            {
                if (!_pend.TryGetValue(i - k, out var p)) continue;
                double d = 0.9995;
                if (k == 1) { for (int j = 1; j <= HMAX; j++) { _errM[j] *= d; _errN[j] *= d; } _vCnt = _vCnt * d + 1; }
                _errM[k] += Math.Abs(p.M[k - 1] - e);
                _errN[k] += Math.Abs(p.N[k - 1] - e);
                if (k == HMAX) _pend.Remove(i - k);
            }
            if (i >= _validFrom && _sCount >= MinSamples)
            {
                var f = new double[NF];
                if (Feat(i, c, e, f1, f2, f))
                {
                    Predict(f, out var mu, out var pt, out _);
                    var p = new Pend();
                    Path(e, c, _a[i], mu, p.M);
                    Path(e, c, _a[i], null, p.N);
                    int rb = Bucket(Math.Abs(f[0]));
                    for (int q = 0; q < HMAX; q++)
                    {
                        p.P[q] = pt[q];
                        p.B[q] = _rTot[rb] > 0 ? _rHit[rb, q] / _rTot[rb] : 0.5;
                    }
                    p.HasP = true;
                    _pend[i] = p;
                }
            }
        }

        // amprenta: i = bara (inchisa sau curenta), c/e/f1/f2 = valorile la pretul dat
        private bool Feat(int i, double c, double e, double f1, double f2, double[] f)
        {
            if (i < 12 || i - 1 >= _n) return false;
            int ai = Math.Min(i, _n - 1);
            double atr = _a[ai];
            double o = i < _n ? _o[i] : Bars.OpenPrices[i];
            double path = 0, prev = c;
            for (int j = i; j > i - 10; j--)
            {
                double cj = j == i ? c : _c[j], cp = _c[j - 1];
                path += Math.Abs(cj - cp);
            }
            double er = path > 0 ? (c - _c[i - 10]) / path : 0;
            int run = Math.Sign(c - e) == Math.Sign(_c[i - 1] - _e[i - 1]) ? _run[i - 1] + 1 : 1;
            f[0] = (c - e) / atr;
            f[1] = (e - _e[i - 3]) / (3 * atr);
            f[2] = (f1 - f2) / atr;
            f[3] = (c - _c[i - 3]) / atr;
            f[4] = (c - o) / atr;
            f[5] = er;
            f[6] = atr / _al[ai] - 1;
            f[7] = Math.Sign(c - e) * Math.Min(run, 30) / 10.0;
            return true;
        }

        private void AddSample(int i)
        {
            var f = new double[NF];
            if (!Feat(i, _c[i], _e[i], _f1[i], _f2[i], f)) return;
            double atr = _a[i];
            int slot = _sHead;
            for (int j = 0; j < NF; j++) _sf[slot * NF + j] = f[j];
            int s0 = Math.Sign(_c[i] - _e[i]);
            byte touch = 0;
            for (int k = 1; k <= HMAX; k++)
            {
                _sd[slot * HMAX + k - 1] = (float)((_c[i + k] - _c[i]) / atr);
                if (touch == 0 && Touched(i + k, s0)) touch = (byte)k;
            }
            _stc[slot] = touch;

            // verificare: predictia facuta la bara i (doar cu trecutul) vs ce s-a intamplat
            if (_pend.TryGetValue(i, out var pd) && pd.HasP)
                for (int h = 0; h < HMAX; h++)
                {
                    double y = touch > 0 && touch <= h + 1 ? 1 : 0;
                    _brM[h] += (pd.P[h] - y) * (pd.P[h] - y);
                    _brB[h] += (pd.B[h] - y) * (pd.B[h] - y);
                    _brN[h]++;
                    int cb = Math.Min(9, (int)(pd.P[h] * 10));
                    _calN[h, cb]++; _calP[h, cb] += pd.P[h]; _calY[h, cb] += y;
                }
            // reperul istoric se actualizeaza DUPA verificare (nu vede viitorul)
            int rb = Bucket(Math.Abs(f[0]));
            _rTot[rb]++;
            for (int h = 0; h < HMAX; h++) if (touch > 0 && touch <= h + 1) _rHit[rb, h]++;

            _sHead = (_sHead + 1) % MaxSamples;
            if (_sCount < MaxSamples) _sCount++;
        }

        // pretul a atins / traversat EMA ref pe bara j (s0 = partea initiala)
        private bool Touched(int j, int s0) =>
            (_l[j] <= _e[j] && _e[j] <= _h[j]) || (s0 != 0 && Math.Sign(_c[j] - _e[j]) == -s0);

        // kNN: deplasarea medie a pretului (ATR) pe 1..5 bare + probabilitatea atingerii EMA in <= H bare
        private void Predict(double[] f, out double[] mu, out double[] pTouch, out double avgD)
        {
            mu = new double[HMAX]; pTouch = new double[HMAX]; avgD = 0;
            int k = Math.Min(K, _sCount);
            if (k == 0) return;
            var bd = new double[k]; var bi = new int[k]; int cnt = 0;
            for (int s = 0; s < _sCount; s++)
            {
                double d = 0; int b = s * NF;
                for (int j = 0; j < NF; j++) { double x = f[j] - _sf[b + j]; d += FW[j] * x * x; }
                if (cnt < k) { int p = cnt++; while (p > 0 && bd[p - 1] > d) { bd[p] = bd[p - 1]; bi[p] = bi[p - 1]; p--; } bd[p] = d; bi[p] = s; }
                else if (d < bd[k - 1]) { int p = k - 1; while (p > 0 && bd[p - 1] > d) { bd[p] = bd[p - 1]; bi[p] = bi[p - 1]; p--; } bd[p] = d; bi[p] = s; }
            }
            double sw = 0;
            for (int q = 0; q < cnt; q++)
            {
                double w = 1.0 / (Math.Sqrt(bd[q]) + 0.05);
                sw += w; avgD += Math.Sqrt(bd[q]);
                int s = bi[q];
                for (int h = 0; h < HMAX; h++)
                {
                    mu[h] += w * _sd[s * HMAX + h];
                    if (_stc[s] > 0 && _stc[s] <= h + 1) pTouch[h] += w;
                }
            }
            for (int h = 0; h < HMAX; h++)
            {
                mu[h] = Math.Max(-3, Math.Min(3, mu[h] / sw * LearnStrength));
                pTouch[h] /= sw;
            }
            avgD /= cnt;
        }

        // recursia EMA pe pretul estimat (mu = null => pret constant = proiectie naiva)
        private void Path(double e0, double c0, double atr, double[] mu, double[] outE)
        {
            double e = e0;
            for (int k = 0; k < HMAX; k++)
            {
                double c = c0 + (mu == null ? 0 : mu[k] * atr);
                e += _al0 * (c - e);
                outE[k] = e;
            }
        }

        private double Skill(int h) => _errN[h] > 0 ? 1 - _errM[h] / _errN[h] : 0;

        private int ChooseH(out bool naive)
        {
            naive = false;
            if (Horizon == VeOrizont.Bare3) return Fix(3, out naive);
            if (Horizon == VeOrizont.Bare4) return Fix(4, out naive);
            if (Horizon == VeOrizont.Bare5) return Fix(5, out naive);
            if (_vCnt < 200) return 4;
            int best = 3; double bs = Skill(3);
            for (int h = 4; h <= 5; h++) if (Skill(h) >= bs - 0.02) { best = h; bs = Math.Max(bs, Skill(h)); }
            naive = bs <= 0;
            return best;
        }

        private int Fix(int h, out bool naive) { naive = _vCnt >= 200 && Skill(h) <= 0; return h; }

        // =============================== timeframe secundar ===============================
        private int Rel(double g, int prev) => g > FastGap ? 1 : g < -FastGap ? -1 : prev;

        //  +1 = EMA rapida peste ambele · -1 = sub ambele · 2 = intre ele (stop: schimbare de trend) · 0 = nedefinit
        private static int FastCode(int r25, int r210) =>
            r25 > 0 && r210 > 0 ? 1 : r25 < 0 && r210 < 0 ? -1 : (r25 != 0 || r210 != 0) ? 2 : 0;

        private void SyncFast()
        {
            if (_fb == null) return;
            int lastClosed = _fb.Count - 2;
            while (_fn <= lastClosed)
            {
                double c = _fb.ClosePrices[_fn];
                if (_fn == 0) { _g1 = _g2 = _g3 = c; }
                else { _g1 += _fa1 * (c - _g1); _g2 += _fa2 * (c - _g2); _g3 += _fa3 * (c - _g3); }
                if (_fn >= 3 * FastP3)
                {
                    _fr25 = Rel(_g1 - _g2, _fr25); _fr210 = Rel(_g1 - _g3, _fr210);
                    int code = FastCode(_fr25, _fr210);
                    if (code != _fCode || _fStateBar < 0) { _fCode = code; _fStateBar = _fn; }
                    if (Math.Abs(code) == 1) _fLastMain = code;
                }
                _fn++;
            }
        }

        // directia semnalului pentru o stare: +1 BUY, -1 SELL, 0 = stop / nedefinit
        private int FastDir(int code) => Math.Abs(code) != 1 ? 0 : FastSense == VeSens.Revenire ? -code : code;
        // directia care tocmai s-a oprit (pentru „stop SELL” / „stop BUY”)
        private int FastStopped(int code) => code != 2 ? 0 : FastDir(_fLastMain);

        // =============================== statistica istoric ===============================
        private void ComputeStats()
        {
            _statAt = _n;
            var abs = new List<double>(); var absA = new List<double>();
            double sumAbs = 0, sumUp = 0, sumDn = 0, maxUp = 0, maxDn = 0, hiMax = 0, loMax = 0, exc = 0;
            int nUp = 0, nDn = 0, cnt = 0;
            var med = new List<int>[5]; for (int b = 0; b < 5; b++) { med[b] = new List<int>(); _bTouch5[b] = 0; _bN[b] = 0; }

            for (int i = _warm; i < _n; i++)
            {
                double d = _c[i] - _e[i];
                abs.Add(Math.Abs(d)); absA.Add(Math.Abs(d) / _a[i]);
                sumAbs += Math.Abs(d); cnt++;
                if (d > 0) { sumUp += d; nUp++; maxUp = Math.Max(maxUp, d); } else if (d < 0) { sumDn += d; nDn++; maxDn = Math.Min(maxDn, d); }
                double hi = _h[i] - _e[i], lo = _e[i] - _l[i];
                hiMax = Math.Max(hiMax, hi); loMax = Math.Max(loMax, lo);
                exc += Math.Max(Math.Abs(hi), Math.Abs(lo));

                if (i + LOOK >= _n) continue;
                int s0 = Math.Sign(d);
                if (s0 == 0) continue;
                double da = Math.Abs(d) / _a[i];
                int bk = da < 0.5 ? 0 : da < 1 ? 1 : da < 1.5 ? 2 : da < 2 ? 3 : 4;
                int first = 0;
                for (int k = 1; k <= LOOK; k++) if (Touched(i + k, s0)) { first = k; break; }
                _bN[bk]++;
                if (first > 0 && first <= HMAX) _bTouch5[bk]++;
                if (first > 0) med[bk].Add(first);
            }
            if (cnt == 0) { _statLines = new[] { "Istoric insuficient" }; return; }

            abs.Sort(); absA.Sort();
            _absSorted = abs.ToArray();
            for (int b = 0; b < 5; b++)
            {
                _bTouch5[b] = _bN[b] > 0 ? _bTouch5[b] / _bN[b] : double.NaN;
                med[b].Sort();
                _bMed[b] = med[b].Count > 0 ? med[b][med[b].Count / 2] : double.NaN;
            }
            double days = (Bars.OpenTimes[_n - 1] - Bars.OpenTimes[_warm]).TotalDays;
            string Bk(int b) => double.IsNaN(_bTouch5[b]) ? "–" : $"{_bTouch5[b] * 100:0}%";
            _statLines = new[]
            {
                $"Istoric {days.ToString("0", _ci)} zile · {TfShort(TimeFrame)} · {cnt} bare · Close − EMA{RefPeriod}",
                $"Medie |d| {N1(sumAbs / cnt)} · mediana {N1(Q(abs, 0.5))} · P90 {N1(Q(abs, 0.9))} · P95 {N1(Q(abs, 0.95))} · P99 {N1(Q(abs, 0.99))}",
                $"Max peste {S1(maxUp)} · max sub {S1(maxDn)} · medie peste {S1(nUp > 0 ? sumUp / nUp : 0)} · sub {S1(nDn > 0 ? sumDn / nDn : 0)}",
                $"Extreme High/Low: +{N1(hiMax)} / −{N1(loMax)} · excursie medie {N1(exc / cnt)}",
                $"In ATR: medie {N2(absA.Average())} · P90 {N2(Q(absA, 0.9))} · P95 {N2(Q(absA, 0.95))} · max {N2(absA[absA.Count - 1])}",
                $"Revenire la EMA{RefPeriod} in ≤{HMAX} bare: <0,5 ATR {Bk(0)} · 0,5–1 {Bk(1)} · 1–1,5 {Bk(2)} · 1,5–2 {Bk(3)} · >2 {Bk(4)}"
            };
            if (!_printed)
            {
                _printed = true;
                Print("===== STATISTICA " + SymbolName + " " + TfShort(TimeFrame) + " – pret fata de EMA" + RefPeriod + " =====");
                foreach (var s in _statLines) Print(s);
                for (int b = 0; b < 5; b++)
                    Print($"  treapta {b}: n={_bN[b]:0} · atinge EMA in ≤{HMAX} bare {Bk(b)} · mediana bare pana la atingere {(double.IsNaN(_bMed[b]) ? "–" : _bMed[b].ToString("0"))}");
            }
        }

        private static double Q(List<double> sorted, double q) => sorted.Count == 0 ? 0 : sorted[Math.Min(sorted.Count - 1, (int)(q * (sorted.Count - 1)))];

        private string CalLine()
        {
            int HR = _hb >= 0 ? _hb : HMAX - 1;
            var parts = new List<string>();
            for (int cb = 1; cb <= 9; cb += 2)
                if (_calN[HR, cb] >= 30)
                    parts.Add($"{cb * 10}–{cb * 10 + 10}%→{_calY[HR, cb] / _calN[HR, cb] * 100:0}%");
            return $"Calibrare model (prezis → real, ≤{HR + 1} bare): " + (parts.Count == 0 ? "in curs" : string.Join(" · ", parts));
        }

        private void PrintCalibration()
        {
            _calPrinted = true;
            Print("===== VERIFICARE walk-forward – probabilitatea de revenire la EMA" + RefPeriod + " =====");
            for (int h = 0; h < HMAX; h++)
            {
                double bsk = _brB[h] > 0 ? 1 - _brM[h] / _brB[h] : 0;
                Print($"  ≤{h + 1} bare: n={_brN[h]:0} · Brier model {_brM[h] / Math.Max(1, _brN[h]):0.0000} · istoric {_brB[h] / Math.Max(1, _brN[h]):0.0000} · castig {bsk * 100:+0.0;-0.0;0.0}%");
            }
            foreach (int hh in new[] { 0, HMAX - 1 })
            {
                Print($"  Calibrare ≤{hh + 1} bare (prezis → realizat):");
                for (int cb = 0; cb < 10; cb++)
                    if (_calN[hh, cb] > 0)
                        Print($"    {cb * 10,3}–{cb * 10 + 10,3}%: prezis mediu {_calP[hh, cb] / _calN[hh, cb] * 100:0.0}% · realizat {_calY[hh, cb] / _calN[hh, cb] * 100:0.0}% · n={_calN[hh, cb]:0}");
            }
        }

        private double Percentile(double x)
        {
            if (_absSorted.Length == 0) return double.NaN;
            int lo = 0, hi = _absSorted.Length;
            while (lo < hi) { int m = (lo + hi) / 2; if (_absSorted[m] < x) lo = m + 1; else hi = m; }
            return 100.0 * lo / _absSorted.Length;
        }

        // =============================== timp real ===============================
        private void Live()
        {
            _lastUi = DateTime.UtcNow;
            Sync();
            if (_body == null) return;
            if (_n < _warm + 20 || _n < 15)
            {
                _tD1.Text = "Se incarca istoricul…"; return;
            }

            int i = _n;                                           // bara curenta (in formare)
            double c = Bars.ClosePrices.LastValue;
            double e = _e[_n - 1] + _al0 * (c - _e[_n - 1]);
            double f1 = _f1[_n - 1] + _al1 * (c - _f1[_n - 1]);
            double f2 = _f2[_n - 1] + _al2 * (c - _f2[_n - 1]);
            double atr = _a[_n - 1];
            double line = PriceLine == VeLinie.EMA1 ? f1 : c;
            string lineName = PriceLine == VeLinie.EMA1 ? "EMA" + Period1 : "Pret";

            // EMA virtuala
            double[] mu = null, pT = null; double avgD = 0;
            bool model = _sCount >= MinSamples;
            var f = new double[NF];
            if (model && Feat(i, c, e, f1, f2, f)) Predict(f, out mu, out pT, out avgD); else model = false;
            int H = ChooseH(out bool naive);
            var ep = new double[HMAX];
            Path(e, c, atr, model && !naive ? mu : null, ep);
            double ev = ep[H - 1];

            double d1 = line - e, d2 = line - ev, dB1 = c - e, dB2 = c - ev;
            double pct = Percentile(Math.Abs(c - e));
            double dAtr = Math.Abs(c - e) / atr;

            _tD1.Text = $"{lineName} → EMA{RefPeriod}:  {S1(d1)} pct · {Pips(d1)} pips";
            _tD1.ForegroundColor = ZoneColor(d1, pct);

            // sageata de trend: EMA1 > EMA2 > EMA ref (2 > 5 > 10) / invers / lateral
            double gMin = TrendMinAtr * atr, g12 = f1 - f2, g2r = f2 - e;
            if (g12 >= gMin && g2r >= gMin && g12 > 0 && g2r > 0) { _tArrow.Text = "▲"; _tArrow.ForegroundColor = CGreen; }
            else if (g12 <= -gMin && g2r <= -gMin && g12 < 0 && g2r < 0) { _tArrow.Text = "▼"; _tArrow.ForegroundColor = CRed; }
            else { _tArrow.Text = "▶"; _tArrow.ForegroundColor = Color.Gray; }
            _tD2.Text = $"{lineName} → EMA{RefPeriod} virtuala (+{H}):  {S1(d2)} pct · {Pips(d2)} pips";
            _tD2.ForegroundColor = COrange;
            _tSub.Text = $"Pret → EMA{RefPeriod} {S1(dB1)} · → virtuala {S1(dB2)}   |   EMA{RefPeriod} {F(e)} → {F(ev)} ({S1(ev - e)})";

            string zone = pct >= 95 ? "FOARTE INTINS" : pct >= 90 ? "INTINS" : pct >= 50 ? "departat" : "aproape";
            _tZone.Text = $"Distanta: P{pct:0} din istoric · {N2(dAtr)} ATR · {zone}";
            _tZone.ForegroundColor = pct >= 90 ? COrange : pct >= 50 ? CText : CMuted;

            int bk = dAtr < 0.5 ? 0 : dAtr < 1 ? 1 : dAtr < 1.5 ? 2 : dAtr < 2 ? 3 : 4;
            string hist = double.IsNaN(_bTouch5[bk]) ? "–" : $"{_bTouch5[bk] * 100:0}% (≤{HMAX}, n={_bN[bk]:0})";
            const int HR = HMAX - 1;
            // orizontul cu cel mai mare castig verificat (Brier) fata de istoric
            _hb = -1; double bestG = MinGainPct / 100.0;
            for (int q = 0; q < HMAX; q++)
            {
                if (_brN[q] < 300 || _brB[q] <= 0) continue;
                double g = 1 - _brM[q] / _brB[q];
                if (g >= bestG) { bestG = g; _hb = q; }
            }

            // partea A: model pe orizontul util (sau nimic)
            string partA = "";
            double pSig = double.NaN;                                     // probabilitatea reala calibrata (orizontul util)
            double shown = !double.IsNaN(_bTouch5[bk]) ? _bTouch5[bk] : 0;
            if (_hb >= 0)
            {
                double histH = _rTot[bk] > 0 ? _rHit[bk, _hb] / _rTot[bk] : double.NaN;
                string hs = double.IsNaN(histH) ? "–" : $"{histH * 100:0}%";
                int cb = model ? Math.Min(9, (int)(pT[_hb] * 10)) : 0;
                double rn = model ? _calN[_hb, cb] : 0;
                if (model && rn >= 30)
                {
                    double real = _calY[_hb, cb] / rn;
                    partA = $"≤{_hb + 1} {(_hb == 0 ? "bara" : "bare")}: model {pT[_hb] * 100:0}% → real {real * 100:0}% (istoric {hs})";
                    shown = real; pSig = real;
                }
                else partA = $"≤{_hb + 1} {(_hb == 0 ? "bara" : "bare")}: istoric {hs}" + (model ? $" (model {pT[_hb] * 100:0}% – zona neverificata)" : "");
                partA += "  |  ";
            }
            _tRev.Text = $"Revenire la EMA{RefPeriod}: {partA}≤{HMAX} bare: istoric {hist}" + (double.IsNaN(_bMed[bk]) ? "" : $" · mediana {_bMed[bk]:0} bare");
            _tRev.ForegroundColor = shown >= 0.75 ? CGreen : shown >= 0.55 ? CMid : COrange;

            // verificare
            if (_brN[HR] < 300) { _tCal.Text = "Verificare walk-forward: in curs"; _tCal.ForegroundColor = CMuted; }
            else
            {
                var gs = new List<string>();
                for (int q = 0; q < HMAX; q++) gs.Add($"≤{q + 1}: {(1 - _brM[q] / Math.Max(1e-12, _brB[q])) * 100:+0.0;-0.0;0.0}%");
                _tCal.Text = (_hb >= 0 ? $"MODEL UTIL pe ≤{_hb + 1} {(_hb == 0 ? "bara" : "bare")} (+{bestG * 100:0.0}%)" : "Modelul NU bate istoricul – foloseste rata istorica")
                             + $" · castig fata de istoric {string.Join(" · ", gs)} (n={_brN[HR]:0})";
                _tCal.ForegroundColor = _hb >= 0 ? CGreen : COrange;
            }
            if (!_calPrinted && _brN[HR] >= 300) PrintCalibration();

            // ETICHETA DE SEMNAL – orizont 5 bare, rata istorica pe treapta de distanta
            int cSide = Math.Sign(c - e);                                 // pentru semnalul final
            int cKind = 0;                                                // 2 intrare · 1 asteapta · -1 blocare · 0 nedefinit
            string cWhy = "";
            {
                int side = Math.Sign(c - e);                              // +1 pret peste EMA → SELL spre EMA
                string sd = side > 0 ? "SELL" : "BUY";
                double h5 = _bTouch5[bk];
                string hs = double.IsNaN(h5) ? "–" : $"{h5 * 100:0}%";
                string med = double.IsNaN(_bMed[bk]) ? "" : $" · mediana {_bMed[bk]:0} bare";
                string tpTxt = $"TP EMA{RefPeriod} {F(e)} ({S1(e - c)} pct)";
                string trendNote = (_tArrow.Text == "▲" && side > 0) || (_tArrow.Text == "▼" && side < 0) ? " · contra trendului EMA" : "";

                // schimbare de trend EMA1 x EMA2 contra directiei spre EMA (in formare sau recenta)
                double g = f1 - f2;
                bool frm = _xSign != 0 && Math.Sign(g) == -_xSign && Math.Abs(g) >= FsGap;
                int sc = _lastCrossBar >= 0 ? (_n - 1) - _lastCrossBar : int.MaxValue;
                int cdir = frm ? Math.Sign(g) : sc < WarnBars ? _lastCrossDir : 0;
                bool against = side != 0 && cdir != 0 && cdir == side;   // pret peste EMA + cross ascendent = se departeaza

                if (side == 0) { _tSig.Text = "● ASTEAPTA – pretul e pe EMA" + RefPeriod; _tSig.ForegroundColor = CMuted; }
                else if (double.IsNaN(h5)) { _tSig.Text = "● ASTEAPTA – statistica istorica in calcul"; _tSig.ForegroundColor = CMuted; }
                else if (h5 * 100 < SigBlockPct)
                {
                    _tSig.Text = $"⛔ BLOCARE {sd} – {N2(dAtr)} ATR de EMA: revine in ≤5 bare doar {hs} (miscare de trend)";
                    _tSig.ForegroundColor = COrange;
                    cKind = -1; cWhy = $"{N2(dAtr)} ATR de EMA{RefPeriod}: revine rar ({hs})";
                }
                else if (SigTrendBlock && against)
                {
                    _tSig.Text = $"⛔ BLOCARE {sd} – schimbare de trend {(cdir > 0 ? "ASCENDENT" : "DESCENDENT")} contra (pretul se departeaza de EMA)";
                    _tSig.ForegroundColor = COrange;
                    cKind = -1; cWhy = $"schimbare de trend {(cdir > 0 ? "ascendent" : "descendent")} pe {TfShort(TimeFrame)}";
                }
                else if (dAtr >= SigMinAtr && dAtr <= SigMaxAtr && h5 * 100 >= SigEnterPct)
                {
                    _tSig.Text = $"{(side > 0 ? "▼ SELL" : "▲ BUY")} spre EMA{RefPeriod} – revine in ≤5 bare {hs} (istoric, n={_bN[bk]:0}){med} · {tpTxt}{trendNote}";
                    _tSig.ForegroundColor = side > 0 ? CRed : CGreen;
                    cKind = 2;
                }
                else
                {
                    cKind = 1;
                    string why = dAtr < SigMinAtr ? $"prea aproape de EMA ({N2(dAtr)} ATR < {N1(SigMinAtr)}), TP prea mic"
                               : dAtr > SigMaxAtr ? $"{N2(dAtr)} ATR > {N1(SigMaxAtr)}: revine in ≤5 bare doar {hs}"
                               : $"revine in ≤5 bare {hs} (< {SigEnterPct:0}%)";
                    _tSig.Text = $"● ASTEAPTA {sd} – {why}";
                    _tSig.ForegroundColor = CMid;
                }
            }

            // avertisment schimbare de trend (EMA1 x EMA2)
            double d12 = f1 - f2;
            bool forming = _xSign != 0 && Math.Sign(d12) == -_xSign && Math.Abs(d12) >= FsGap;
            int since = _lastCrossBar >= 0 ? (_n - 1) - _lastCrossBar : int.MaxValue;
            bool recent = since < WarnBars;
            _blink = !_blink;
            if (forming || recent)
            {
                int dir = forming ? Math.Sign(d12) : _lastCrossDir;
                _tWarn.Text = $"{(dir > 0 ? "▲" : "▼")} ⚠ Atentie! Schimbare de trend {(dir > 0 ? "ASCENDENT" : "DESCENDENT")}!  EMA{Period1} {(dir > 0 ? "↑ peste" : "↓ sub")} EMA{Period2}"
                              + (forming ? " · in formare" : since == 0 ? " · confirmat" : $" · confirmat acum {since} bare");
                _tWarn.ForegroundColor = dir > 0 ? CGreen : CRed;
                _tWarn.IsVisible = true;
            }
            else _tWarn.IsVisible = false;

            UpdateFast(c, e, atr, dAtr, cSide, cKind, cWhy);

            string sk = _vCnt >= 200 ? $"{Skill(H) * 100:+0;-0}% fata de naiv · eroare ~{N1(_errM[H] / Math.Max(1e-9, _vCnt))} pct" : "validare in curs";
            _tModel.Text = $"Model: {_sCount} mostre · H={H} {(Horizon == VeOrizont.Auto ? "auto" : "fix")} · {sk}"
                           + (naive ? " · NAIV (modelul nu bate pretul constant)" : "")
                           + (model ? $" · similaritate {N2(avgD)}" : "");

            if (_showStat)
            {
                for (int k = 0; k < _tStat.Count; k++) _tStat[k].Text = k < _statLines.Length ? _statLines[k] : "";
                _tStat[_tStat.Count - 1].Text = CalLine();
            }

            if (DrawProj) DrawProjection(e, ep, H);
        }

        // timeframe secundar + SEMNAL FINAL (convergenta cu graficul)
        private void UpdateFast(double c, double e, double atr, double dAtr, int cSide, int cKind, string cWhy)
        {
            if (_tFinal == null) return;
            string ftf = TfShort(FastTf), ctf = TfShort(TimeFrame);
            if (_fb == null)
            {
                _tFinal.Text = "● Timeframe secundar indisponibil"; _tFinal.ForegroundColor = CMuted;
                _tFinalSub.Text = ""; _tFast.Text = "–"; _tFastSub.Text = "";
                return;
            }
            SyncFast();
            if (_fn <= 3 * FastP3 + 1 || _fStateBar < 0)
            {
                _tFinal.Text = $"● Se incarca {ftf}…"; _tFinal.ForegroundColor = CMuted;
                _tFinalSub.Text = ""; _tFast.Text = "…"; _tFast.ForegroundColor = CMuted; _tFastSub.Text = "";
                return;
            }

            // valori in timp real (bara secundara in formare)
            double px = _fb.ClosePrices.LastValue;
            double l1 = _g1 + _fa1 * (px - _g1), l2 = _g2 + _fa2 * (px - _g2), l3 = _g3 + _fa3 * (px - _g3);
            int code = FastCode(Rel(l1 - l2, _fr25), Rel(l1 - l3, _fr210));
            bool forming = code != _fCode;
            int dir = FastDir(code), stopped = FastStopped(code);

            string name;
            if (dir < 0) { name = "▼ SELL"; _tFast.ForegroundColor = CRed; }
            else if (dir > 0) { name = "▲ BUY"; _tFast.ForegroundColor = CGreen; }
            else if (stopped != 0) { name = $"▶ stop {(stopped < 0 ? "SELL" : "BUY")} (schimbare trend)"; _tFast.ForegroundColor = Color.Gray; }
            else { name = "▶ nedefinit"; _tFast.ForegroundColor = Color.Gray; }

            string age;
            if (forming) age = "in formare";
            else
            {
                int bars = _fn - _fStateBar;                               // bare inchise in aceasta stare
                double min = (Server.Time - _fb.OpenTimes[_fStateBar]).TotalMinutes;
                age = $"de {bars} {(bars == 1 ? "bara" : "bare")} (~{Math.Max(0, min):0} min)";
            }
            _tFast.Text = $"{name}  ·  {age}";
            _tFastSub.Text = $"EMA{FastP1} {F(l1)}  ·  EMA{FastP2} {F(l2)} ({S1(l1 - l2)})  ·  EMA{FastP3} {F(l3)} ({S1(l1 - l3)})";
            _tFastSub.ForegroundColor = CText;

            // ---------------- SEMNAL FINAL ----------------
            string dn = dir < 0 ? "SELL" : "BUY";
            Color dc = dir < 0 ? CRed : CGreen;
            const string ok = "✔", no = "✖";
            if (dir == 0)
            {
                if (stopped != 0)
                {
                    string sn = stopped < 0 ? "SELL" : "BUY";
                    _tFinal.Text = $"▶ STOP {sn} · nu intra";
                    _tFinalSub.Text = $"{ftf}: schimbare de trend – daca esti in {sn}, ia in calcul iesirea; asteapta urmatorul semnal";
                }
                else { _tFinal.Text = "● ASTEAPTA"; _tFinalSub.Text = $"{ftf}: fara directie clara"; }
                _tFinal.ForegroundColor = Color.Gray; _tFinalSub.ForegroundColor = CMuted;
                return;
            }

            string tp = $"TP EMA{RefPeriod} {ctf} {F(e)} ({S1(e - c)} pct)";
            if (FastSense == VeSens.Revenire)
            {
                bool agree = cSide != 0 && -cSide == dir;                  // pretul e pe partea din care se revine spre EMA
                bool inZone = dAtr >= ConvMinAtr && dAtr <= ConvMaxAtr;
                bool blocked = agree && cKind < 0;
                string chk = $"{ftf} {dn} {ok} · pret {(cSide > 0 ? "peste" : cSide < 0 ? "sub" : "pe")} EMA{RefPeriod} {ctf} {(agree ? ok : no)}"
                             + $" · distanta {N2(dAtr)} ATR {(inZone ? ok : no)} (zona {N1(ConvMinAtr)}–{N1(ConvMaxAtr)})";
                if (blocked)
                {
                    _tFinal.Text = $"⛔ FARA INTRARE · {ftf} {dn}, {ctf} blocheaza"; _tFinal.ForegroundColor = COrange;
                    _tFinalSub.Text = $"{cWhy} · {chk}";
                }
                else if (agree && inZone)
                {
                    _tFinal.Text = $"{(dir < 0 ? "▼▼" : "▲▲")} {dn} CONFIRMAT · {ftf} + {ctf}"; _tFinal.ForegroundColor = dc;
                    _tFinalSub.Text = $"{chk} · {tp}";
                }
                else if (agree && dAtr >= SigMinAtr && dAtr < ConvMinAtr)
                {
                    _tFinal.Text = $"{(dir < 0 ? "▼" : "▲")} {dn} slab · doar {ftf}"; _tFinal.ForegroundColor = CMid;
                    _tFinalSub.Text = $"{chk} · {tp}";
                }
                else
                {
                    string why = !agree ? $"pretul e pe partea opusa a EMA{RefPeriod} {ctf}"
                               : dAtr < SigMinAtr ? $"prea aproape de EMA{RefPeriod} {ctf} (TP prea mic)"
                               : $"peste {N1(ConvMaxAtr)} ATR – miscare de trend, risc mare";
                    _tFinal.Text = $"● ASTEAPTA · {ftf} {dn}"; _tFinal.ForegroundColor = CMuted;
                    _tFinalSub.Text = $"{why} · {chk}";
                }
            }
            else
            {
                // sens Trend: confirmare = EMA-urile graficului aliniate in aceeasi directie, fara cross contra
                int ct = _tArrow.Text == "▲" ? 1 : _tArrow.Text == "▼" ? -1 : 0;
                bool crossAgainst = _tWarn.IsVisible && ((_tWarn.Text.StartsWith("▲") && dir < 0) || (_tWarn.Text.StartsWith("▼") && dir > 0));
                string chk = $"{ftf} {dn} {ok} · trend {ctf} {(ct == dir ? ok : no)} · fara schimbare contra {(crossAgainst ? no : ok)}";
                if (ct == -dir || crossAgainst)
                {
                    _tFinal.Text = $"⛔ FARA INTRARE · {ftf} {dn}, {ctf} contra"; _tFinal.ForegroundColor = COrange;
                }
                else if (ct == dir)
                {
                    _tFinal.Text = $"{(dir < 0 ? "▼▼" : "▲▲")} {dn} CONFIRMAT · {ftf} + {ctf}"; _tFinal.ForegroundColor = dc;
                }
                else { _tFinal.Text = $"{(dir < 0 ? "▼" : "▲")} {dn} slab · doar {ftf}"; _tFinal.ForegroundColor = CMid; }
                _tFinalSub.Text = chk;
            }
            _tFinalSub.ForegroundColor = CText;
        }

        private void DrawProjection(double e0, double[] ep, int H)
        {
            int last = Bars.Count - 1;
            TimeSpan span = BarSpan();
            DateTime t0 = Bars.OpenTimes[last];
            double y0 = e0;
            for (int k = 1; k <= HMAX; k++)
            {
                string nm = "EV_proj_" + k;
                if (k > H) { Chart.RemoveObject(nm); continue; }
                DateTime t1 = t0.AddTicks(span.Ticks * k);
                Chart.DrawTrendLine(nm, t0.AddTicks(span.Ticks * (k - 1)), y0, t1, ep[k - 1], CProj, ProjThick, LineStyle.Dots);
                y0 = ep[k - 1];
            }
            DateTime tH = t0.AddTicks(span.Ticks * H);
            Chart.DrawIcon("EV_proj_pt", ChartIconType.Circle, tH, ep[H - 1], CProj);
            var tx = Chart.DrawText("EV_proj_tx", $" EMA{RefPeriod}v {F(ep[H - 1])}", tH, ep[H - 1], CProj);
            tx.VerticalAlignment = VerticalAlignment.Center;
            tx.HorizontalAlignment = HorizontalAlignment.Right;
        }

        private TimeSpan BarSpan()
        {
            long best = long.MaxValue;
            for (int j = Bars.Count - 1; j > Math.Max(0, Bars.Count - 25); j--)
            {
                long d = (Bars.OpenTimes[j] - Bars.OpenTimes[j - 1]).Ticks;
                if (d > 0 && d < best) best = d;
            }
            return best == long.MaxValue ? TimeSpan.FromMinutes(1) : TimeSpan.FromTicks(best);
        }

        private Color ZoneColor(double d, double pct) => pct >= 90 ? COrange : pct >= 50 ? (d > 0 ? CGreen : CRed) : CMid;

        private string F(double v) => v.ToString("F" + Symbol.Digits, _ci);
        private string S1(double v) => v.ToString("+0.0;-0.0;0.0", _ci);
        private string N1(double v) => v.ToString("0.0", _ci);
        private string N2(double v) => v.ToString("0.00", _ci);
        private string Pips(double v) => (v / Symbol.PipSize).ToString("+#,##0;-#,##0;0", _ci);

        private static string TfShort(TimeFrame tf)
        {
            string s = tf.ToString();
            if (s == "Minute") return "m1";
            if (s == "Hour") return "h1";
            return s.Replace("Minute", "m").Replace("Hour", "h").Replace("Daily", "D1").Replace("Day", "D").Replace("Weekly", "W1");
        }

        // =============================== panou (stil DASTAN_PANOU) ===============================
        private TextBlock T(string text, int delta = 0, Color color = null, bool bold = false) => new TextBlock
        {
            Text = text, FontSize = Math.Max(7, PanelFont + delta), ForegroundColor = color ?? CText,
            FontWeight = bold ? FontWeight.Bold : FontWeight.Normal, Margin = new Thickness(0, 1, 0, 1), TextWrapping = TextWrapping.Wrap
        };

        private Button Btn(string text, Color bg) => new Button
        {
            Text = text, FontSize = PanelFont, BackgroundColor = bg, ForegroundColor = Color.White,
            Padding = new Thickness(6, 2, 6, 2), Margin = new Thickness(0, 0, 4, 0)
        };

        private void BuildPanel()
        {
            _root = new StackPanel { Orientation = Orientation.Horizontal };
            _main = new Border
            {
                BackgroundColor = CBg, BorderColor = CBorder, BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(6), Width = PanelWidth, VerticalAlignment = VerticalAlignment.Top
            };
            var outer = new StackPanel { Margin = new Thickness(8, 6, 8, 8) };

            var header = new StackPanel { Orientation = Orientation.Horizontal };
            _bMin = Btn("–", CBtn);
            _bMin.Click += a => { _min = !_min; ApplyVisibility(); SaveUI(); };
            header.AddChild(_bMin);
            _bTitle = new Button
            {
                Text = Title + " · " + SymbolName + " · " + TfShort(TimeFrame) + (ShowFast ? " + " + TfShort(FastTf) : "") + " ⇱",
                FontSize = PanelFont + 1, FontWeight = FontWeight.Bold, BackgroundColor = CBg, ForegroundColor = CText,
                Padding = new Thickness(3, 1, 3, 1), Margin = new Thickness(0, 0, 4, 0)
            };
            _bTitle.Click += a => ToggleMove();
            header.AddChild(_bTitle);
            _bStat = Btn("Detalii", CBtn);
            _bStat.Click += a => { _showStat = !_showStat; ApplyVisibility(); SaveUI(); };
            header.AddChild(_bStat);
            outer.AddChild(header);

            _moveRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 0), IsVisible = false };
            _bCorner = Btn("Colt: " + CornerName[_corner], CBtn);
            _bCorner.Click += a => NextCorner();
            _moveRow.AddChild(_bCorner);
            _moveRow.AddChild(MoveBtn("◄", -MoveStep, 0));
            _moveRow.AddChild(MoveBtn("▲", 0, -MoveStep));
            _moveRow.AddChild(MoveBtn("▼", 0, MoveStep));
            _moveRow.AddChild(MoveBtn("►", MoveStep, 0));
            var bOk = Btn("OK", Color.FromArgb(255, 25, 120, 75));
            bOk.Click += a => ToggleMove();
            _moveRow.AddChild(bOk);
            outer.AddChild(_moveRow);
            _tMoveHint = T("Click pe grafic = panoul se muta acolo (coltul stanga-sus). Sagetile = reglaj fin. OK = fixeaza.", -1, COrange);
            _tMoveHint.IsVisible = false;
            outer.AddChild(_tMoveHint);

            _body = new StackPanel { Margin = new Thickness(0, 4, 0, 0) };
            _tD1 = T("", 3, CText, true);
            _tD2 = T("", 3, COrange, true);
            _tSub = T("", 0, CText);
            _tZone = T("", 1, CText, true);
            _tRev = T("", 1, CMid, true);
            _tWarn = T("", 3, COrange, true); _tWarn.IsVisible = false;
            _tModel = T("", -1, CMuted);
            _tCal = T("", 0, CMuted, true);
            _tArrow = T("▶", 5, CMuted, true); _tArrow.Margin = new Thickness(0, 0, 6, 0); _tArrow.TextWrapping = TextWrapping.NoWrap;
            var r1 = new StackPanel { Orientation = Orientation.Horizontal };
            r1.AddChild(_tArrow); r1.AddChild(_tD1);
            _tSig = T("", 2, CMid, true);
            _tSig.Margin = new Thickness(0, 2, 0, 3);

            // --- zona 1: SEMNAL FINAL ---
            _tFinal = T("", 6, CMuted, true); _tFinal.Margin = new Thickness(0, 2, 0, 0);
            _tFinalSub = T("", 0, CText); _tFinalSub.Margin = new Thickness(0, 0, 0, 2);
            // --- zona 2: timeframe secundar ---
            _tFastHdr = T($"── {TfShort(FastTf)} · EMA {FastP1} / {FastP2} / {FastP3} ──", -1, CMuted, true); _tFastHdr.Margin = new Thickness(0, 6, 0, 0);
            _tFast = T("", 4, CMuted, true);
            _tFastSub = T("", 0, CText);
            // --- zona 3: graficul curent ---
            _tChartHdr = T($"── {TfShort(TimeFrame)} (grafic) · revenire la EMA{RefPeriod} ──", -1, CMuted, true); _tChartHdr.Margin = new Thickness(0, 6, 0, 0);
            if (ShowFast)
            {
                _body.AddChild(_tFinal); _body.AddChild(_tFinalSub);
                _body.AddChild(_tFastHdr); _body.AddChild(_tFast); _body.AddChild(_tFastSub);
                _body.AddChild(_tChartHdr);
            }
            _body.AddChild(_tSig);
            _body.AddChild(r1); _body.AddChild(_tD2); _body.AddChild(_tZone);
            _body.AddChild(_tRev); _body.AddChild(_tWarn);

            // --- detalii (sub buton): model, verificare, statistica ---
            _statBox = new StackPanel { Margin = new Thickness(0, 6, 0, 0) };
            _statBox.AddChild(_tSub); _statBox.AddChild(_tCal); _statBox.AddChild(_tModel);
            for (int k = 0; k < 7; k++) { var t = T("", -1, k == 0 ? CText : CMid, k == 0); _tStat.Add(t); _statBox.AddChild(t); }
            _body.AddChild(_statBox);
            outer.AddChild(_body);

            _main.Child = outer;
            _root.AddChild(_main);
            Chart.AddControl(_root);
        }

        private void ApplyVisibility()
        {
            if (_body == null) return;
            _body.IsVisible = !_min;
            _statBox.IsVisible = _showStat;
            _bMin.Text = _min ? "+" : "–";
            _bStat.Text = _showStat ? "Detalii ▴" : "Detalii ▾";
        }

        private bool CornerRight => _corner == (int)VeColt.DreaptaSus || _corner == (int)VeColt.DreaptaJos;
        private bool CornerBottom => _corner == (int)VeColt.StangaJos || _corner == (int)VeColt.DreaptaJos;

        private Button MoveBtn(string text, int dx, int dy)
        {
            var b = Btn(text, CBtn);
            b.Click += a => MoveBy(dx, dy);
            return b;
        }

        private void ApplyPos()
        {
            if (_root == null) return;
            bool r = CornerRight, b = CornerBottom;
            _root.HorizontalAlignment = r ? HorizontalAlignment.Right : HorizontalAlignment.Left;
            _root.VerticalAlignment = b ? VerticalAlignment.Bottom : VerticalAlignment.Top;
            _root.Margin = new Thickness(r ? 0 : _px, b ? 0 : _py, r ? _px : 0, b ? _py : 0);
        }

        private void ClampPanel()
        {
            double w = 0, h = 0;
            try { w = Chart.Width; h = Chart.Height; } catch { }
            if (w > 120) _px = Math.Min(_px, (int)w - 100);
            if (h > 60) _py = Math.Min(_py, (int)h - 40);
            _px = Math.Max(0, _px); _py = Math.Max(0, _py);
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
            _corner = _corner == (int)VeColt.StangaSus ? (int)VeColt.DreaptaSus
                    : _corner == (int)VeColt.DreaptaSus ? (int)VeColt.DreaptaJos
                    : _corner == (int)VeColt.DreaptaJos ? (int)VeColt.StangaJos
                    : (int)VeColt.StangaSus;
            _px = 10; _py = CornerBottom ? 10 : 30;
            _bCorner.Text = "Colt: " + CornerName[_corner];
            ClampPanel();
        }

        private void ToggleMove()
        {
            _moveRow.IsVisible = !_moveRow.IsVisible;
            _tMoveHint.IsVisible = _moveRow.IsVisible;
            if (_moveRow.IsVisible)
            {
                _bCorner.Text = "Colt: " + CornerName[_corner];
                if (!_mouseHooked) { Chart.MouseDown += OnChartMouseDownMove; _mouseHooked = true; }
            }
            else
            {
                if (_mouseHooked) { Chart.MouseDown -= OnChartMouseDownMove; _mouseHooked = false; }
                SaveUI();
            }
        }

        private void OnChartMouseDownMove(ChartMouseEventArgs a)
        {
            if (_moveRow == null || !_moveRow.IsVisible) return;
            _corner = (int)VeColt.StangaSus;
            _px = (int)Math.Round(a.MouseX); _py = (int)Math.Round(a.MouseY);
            _bCorner.Text = "Colt: " + CornerName[_corner];
            ClampPanel();
        }

        private string UIKey(string k) =>
            "EV10UI" + new string((SymbolName + TimeFrame).Where(char.IsLetterOrDigit).ToArray()) + k;

        private void SaveUI()
        {
            try
            {
                LocalStorage.SetString(UIKey("X"), _px.ToString(CultureInfo.InvariantCulture), LocalStorageScope.Type);
                LocalStorage.SetString(UIKey("Y"), _py.ToString(CultureInfo.InvariantCulture), LocalStorageScope.Type);
                LocalStorage.SetString(UIKey("C"), _corner.ToString(CultureInfo.InvariantCulture), LocalStorageScope.Type);
                LocalStorage.SetString(UIKey("M"), _min ? "1" : "0", LocalStorageScope.Type);
                LocalStorage.SetString(UIKey("S"), _showStat ? "1" : "0", LocalStorageScope.Type);
                LocalStorage.Flush(LocalStorageScope.Type);
            }
            catch (Exception ex) { Print("ATENTIE LocalStorage: " + ex.Message); }
        }

        private void LoadUI()
        {
            _px = PanelX; _py = PanelY; _corner = (int)PanelCorner; _min = false; _showStat = true;
            if (ResetPos) return;
            try
            {
                int v;
                if (int.TryParse(LocalStorage.GetString(UIKey("X"), LocalStorageScope.Type), out v)) _px = Math.Max(0, v);
                if (int.TryParse(LocalStorage.GetString(UIKey("Y"), LocalStorageScope.Type), out v)) _py = Math.Max(0, v);
                if (int.TryParse(LocalStorage.GetString(UIKey("C"), LocalStorageScope.Type), out v) && v >= 0 && v <= 3) _corner = v;
                _min = LocalStorage.GetString(UIKey("M"), LocalStorageScope.Type) == "1";
                _showStat = LocalStorage.GetString(UIKey("S"), LocalStorageScope.Type) != "0";
            }
            catch { }
            if (_px > 4000 || _py > 3000) { _px = PanelX; _py = PanelY; }
        }
    }
}
