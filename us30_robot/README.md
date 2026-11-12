# US30 M1 – Robot cu matrice de pattern-uri și auto-învățare (cTrader / ICMarkets)

Pornește de la cheat-sheet-ul **„Institutional Price Action & Liquidity – Master Cheat Sheet”** (91 de structuri).

1. **scanează în timp real** M1 US30 (doar lumânări închise, fără repaint) pentru **toate cele 91 de pattern-uri**,
2. propune **BUY/SELL** cu SL/TP și o explicație scurtă a convergenței,
3. urmărește fiecare semnal până la **confirmare / infirmare** și scrie verdictul post-mortem,
4. **învață accelerat** din fiecare rezultat (și din cele netranzacționate),
5. execută în cTrader în modurile **MANUAL / HIBRID / AUTO / ROBOT**.

> ⚠️ Testează întâi pe **cont DEMO**. Rezultatele pe date sintetice nu dovedesc un edge real.

## Arhitectură

```
 cTrader (ICMarkets)                         Python  (run.py serve)
┌──────────────────────────┐   HTTP local   ┌───────────────────────────────────────────┐
│ US30MatrixBridge.cs      │ ─ bară M1 ───► │ MarketState M1 + M15 (structură, zone,    │
│  • trimite bare închise  │                │   lichiditate, sesiuni DST, spread)       │
│  • execută ordine (risc, │ ◄─ acțiuni ──  │ 91 detectori ► Matrice de confluență      │
│    leverage 1:30)        │                │ Learner ► P(succes), expectanță (R)       │
│  • desenează semnale     │ ─ evenimente ► │ ModeController ► EXECUTĂ/AȘTEAPTĂ/NOTIFICĂ│
│  • butoane mod + aprobare│                │ RiskManager ► limite zilnice, sizing      │
│  • export istoric CSV    │                │ Evaluator ► confirmare/infirmare ► învățare│
└──────────────────────────┘                └───────────────────────────────────────────┘
                                               dashboard: http://127.0.0.1:8765/
```

## Cele 4 moduri

| Mod | Ce face |
|---|---|
| **MANUAL** | Doar propune (grafic + dashboard + sunet). Execuți tu. Robotul învață oricum. |
| **HIBRID** | Semnalele cu încredere mare (P ≥ 60% și expectanță ≥ 0,4R) se execută singure; restul așteaptă **✔ Aprob / ✖ Refuz** (expiră în 3 min sau dacă prețul a plecat > 0,3R). |
| **AUTO** | Execută toate semnalele care trec filtrele normale. |
| **ROBOT** | Pilot automat când nu ești online: filtre stricte (P ≥ 55%, ≥ 0,3R), **risc la jumătate**, oprire la −2%/zi sau 3 pierderi la rând. |

**Prezența** se detectează automat: mișcarea mouse-ului pe grafic, butoanele din cBot sau dashboard-ul.
După 20 de minute fără prezență, MANUAL/HIBRID/AUTO trec automat în **ROBOT**.
Când revii, se întorc la modul ales. Opțiunea se dezactivează din `ModeConfig.auto_robot_offline`.

## Calibrare ICMarkets

- **Spread**: 0,7 pct în sesiunea NYSE, 1,2 pct în rest (spread-ul live din cTrader are prioritate) – inclus în expectanță.
- **Ore**: cBot-ul rulează în UTC; sesiunile (Londra, NY open 09:30 ET, NY) se ajustează automat la ora de vară/iarnă (SUA și UE separat).
- **Leverage 1:30**: volumul e limitat ca marja să nu depășească 80% din marja liberă.
- **Sizing**: risc % din sold (implicit **1%**, în ROBOT 0,5%), calculat cu `TickValue/TickSize` reale ale simbolului.
  Parametrul cBot-ului „Risc maxim %” (implicit 2%) e o limită de siguranță peste setarea din Python.

## Instalare

**1. Python** (Windows: python.org, 3.9+; fără alte pachete)
```bat
cd us30_robot
python run.py serve --mode MANUAL
```
Deschide `http://127.0.0.1:8765/` pentru dashboard.

**2. cTrader**: *Automate → cBots → New* → lipește `ctrader/US30MatrixBridge.cs` → **Build** → atașează pe graficul **US30**.
La „Access rights” acceptă FullAccess (îi trebuie pentru conexiunea locală și exportul CSV).
La pornire trimite 5000 de bare de warm-up, ca robotul să învețe din istoric.

**3. Istoric pentru backtest**: pornește cBot-ul cu `Export istoric CSV la pornire = Yes`.
Fișierul apare în `Documente\US30MX\US30_M1_UTC.csv`, apoi:
```bat
python run.py backtest --csv "%USERPROFILE%\Documents\US30MX\US30_M1_UTC.csv" --mode AUTO
```
Backtestul pre-antrenează starea din `state/`, pe care `serve` o folosește apoi live.

**Telegram** (o singură dată):
1. În Telegram scrie-i lui **@BotFather** `/newbot`, alege un nume și copiază token-ul primit.
2. `python run.py telegram-setup --tg-token <TOKEN>`, apoi trimite `/start` botului tău.
   Token-ul și chat id-ul se salvează local în `state/telegram.json` (nu ajung în git).
3. `python run.py serve` pornește automat și Telegram.

Primești fiecare semnal cu explicația, butoane **✔ Aprob / ✖ Refuz** în HIBRID, execuțiile, rezultatul cu verdictul
(mesajul inițial se actualizează), închiderile cu profit/pierdere, oprirea la limita zilnică și trecerea automată în ROBOT.
Comenzi: `/status`, `/mod AUTO`, `/online`, `/risc 1.0`, `/prag 0.60 0.40`, `/robot 0.55 0.30`, `/setari`, `/set <cheie> <valoare>`.
Doar chat-ul tău e ascultat. Orice mesaj sau buton apăsat te marchează „online”.
Pentru a primi doar semnalele executate sau de aprobat: `serve --tg-only-actionable`.

**Setări** – modificabile din dashboard (secțiunea „Setări”), din Telegram sau din `state/settings.json`;
se păstrează la repornire și au limite de siguranță (ex. risc 0,05–3%):

| Cheie | Implicit | Ce face |
|---|---|---|
| `risk_pct` | 1.0 | risc % pe tranzacție |
| `hybrid_auto_prob` / `hybrid_auto_exp` | 0.60 / 0.40 | HIBRID: prag pentru execuție fără aprobare |
| `approval_timeout_bars` | 3 | minute pentru aprobare |
| `robot_min_prob` / `robot_min_exp` | 0.55 / 0.30 | praguri ROBOT |
| `robot_risk_factor` | 0.5 | ROBOT riscă jumătate |
| `max_daily_loss_pct` / `max_consecutive_losses` / `max_trades_day` | 2 / 3 / 10 | siguranțe zilnice |
| `offline_after_min` / `auto_robot_offline` | 20 / da | trecerea automată în ROBOT |

**De pe telefon** (aceeași rețea Wi-Fi): `python run.py serve --host 0.0.0.0 --token PAROLA`
→ `http://IP-PC:8765/?t=PAROLA`. Setează același token în parametrul cBot-ului.

## Pattern-uri (91/91 cu detector)

`python run.py catalog` listează toate. Pe familii:

| Familie | Exemple de reguli obiective |
|---|---|
| QM (1–8) | H→L→HH→LL, retest QML; rapid/târziu/re-intrare/QMTR/continuare/inversare/DM shadow |
| Fakeout (9, 13–15, 21, 50, 51, 91) | închidere dincolo de nivel apoi înapoi în ≤5 bare; EQH, retest, diamond |
| Lichiditate (37–47, 78, 79, 88) | sweep cu fitil ≥40% peste PDH/PWH/sesiune/EQH/pool/range; liquidity run cu deplasare |
| Structură (48, 73, 74, 82–84) | BOS/CHOCH pe închidere, MSS cu deplasare, displacement + reclaim, scări |
| Zone (29–35, 80, 81, 87) | OB, breaker, mitigation, supply/demand (bază + impuls), FVG, void, fitil, VI, gap |
| Context (36, 85, 86) | OTE 62–85%, zonă M15, confluență M15 + CHOCH M1 |
| Clasice (16, 22–28, 57–72) | regresie pe swing-uri: triunghiuri, pene, megafon, diamant, rounding (parabolă R²≥0,7), H&S, double/triple |
| Wyckoff (52–56) | range ≥40 bare după trend, spring/UTAD, SOS/SOW, LPS |
| Elliott (75–77) | reguli de impuls (2 nu depășește 0, 3 nu cea mai scurtă, 4 fără suprapunere), ABC, WXY |

Pattern-urile subiective sunt traduse în reguli euristice. **Learner-ul decide** pentru fiecare celulă (pattern × direcție × sesiune × aliniere M15) cât valorează de fapt.
În imagine, numerele 19 și 37 apar de două ori; aici Can-Can = 18 și Premium/Discount = 36.

## Cum învață „accelerat”

| Mecanism | Efect |
|---|---|
| **Shadow trades** | fiecare detecție e evaluată, nu doar semnalele → zeci de ori mai multe exemple |
| **Ținte multiple** | fiecare detecție e etichetată la 1R/1,5R/2R/3R → RR optim per celulă |
| **Prior ierarhic** | o celulă nouă pornește de la statistica familiei ei, nu de la zero |
| **Regresie logistică online** | învață *de ce* funcționează (aliniere M15, sesiune, premium/discount…) |
| **Uitare exponențială** | se adaptează la schimbări de regim |
| **Post-mortem → acțiune** | „stop vânat apoi ținta atinsă” lărgește stop-ul acelei celule |
| **Thompson sampling** (`--explore`) | explorare controlată în paper trading |

## Teste

```bash
python -m unittest discover -s tests -v
```
