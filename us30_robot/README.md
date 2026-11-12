# US30 M1 – Robot cu matrice de pattern-uri și auto-învățare

Pornește de la cheat-sheet-ul **„Institutional Price Action & Liquidity – Master Cheat Sheet”**
(91 de structuri). Robotul:

1. scanează **în timp real** graficul M1 US30 (doar lumânări închise, fără repaint),
2. recunoaște pattern-urile și propune **BUY/SELL** cu SL/TP și o explicație scurtă a convergenței,
3. urmărește apoi fiecare semnal până la **confirmare / infirmare** și scrie un verdict post-mortem,
4. **învață accelerat** din fiecare rezultat și își ajustează scorurile, stop-urile și țintele.

> Doar semnale (paper trading). Nu plasează ordine. Rezultatele pe date sintetice NU dovedesc un edge real.

## Arhitectură

```
feed M1 ─► MarketState (ATR, ZigZag HH/HL/LH/LL, BOS/CHOCH, OB/FVG/Breaker,
           │            PDH/PDL, sesiuni Asia/Londra/NY, EQH/EQL, premium/discount)
           ├► HTF M15 (agregat din M1) ─► bias de trend
           ▼
      Detectori (patterns.py) ─► Detection(entry, SL, TP, motiv)
           ▼
      MATRICEA DE CONFLUENȚĂ (matrix.py)
        rânduri  = pattern × direcție            (91 × 2)
        coloane  = sesiune × aliniere M15         (5 × 3)
        + caracteristici continue: premium/discount, deplasare, volatilitate, RR, nivelul lichidității
           ▼
      Learner ─► P(succes), expectanță în R (cu spread) ─► Semnal + explicație
           ▼
      Evaluator: SL / TP / timeout, MFE/MAE, rezultat la 1R/1.5R/2R/3R, verdict
           └──────────────► feedback în Learner + stop adaptiv per celulă
```

## Pattern-uri cu detector activ (31/91)

| Familie | Pattern-uri (id din cheat-sheet) |
|---|---|
| Quasimodo | 1 QM Quick Retest, 2 QM Late Retest, 6 Reversal at QM |
| Lichiditate | 37 EQH, 38 EQL, 39 Liquidity Sweep, 40 SFP, 41 Stop Hunt, 43 Session Liquidity, 44 PDH/PDL |
| Wyckoff / capcane | 50 Bear Trap, 51 Bull Trap, 54 Spring, 55 UTAD |
| Structură | 82 BOS, 83 CHOCH, 84 MSS, 48 Displacement, 89 Retest & Continuation |
| Zone | 31 Order Block, 32 Breaker, 34 FVG |
| Clasice | 27/28 Triple Top/Bottom, 59/60 Double Top/Bottom, 57/58 (Inverse) H&S |
| Altele | 17 3 Drive, 19/20 Compression (+ Liquidity) |

Restul sunt în `CATALOG` (rulează `python run.py catalog`). Premium/Discount (36) și HTF/MTF (85/86)
sunt folosite ca **coloane de context** în matrice, nu ca declanșatoare.
Notă: în imagine numerele 19 și 37 apar de două ori; aici Can-Can = 18 și Premium/Discount = 36.

## Cum învață „accelerat”

| Mecanism | Efect |
|---|---|
| **Shadow trades** | fiecare detecție e evaluată, chiar dacă nu a devenit semnal → de ~25× mai multe etichete |
| **Ținte multiple** | fiecare detecție e etichetată la 1R/1.5R/2R/3R → robotul alege RR-ul cu cea mai bună expectanță per celulă |
| **Prior ierarhic (empirical Bayes)** | o celulă nouă pornește de la statistica familiei ei (ex. toate LIQUIDITY\|SELL), nu de la zero |
| **Regresie logistică online** | învață *de ce* funcționează (aliniere M15, sesiune, premium/discount …); ponderile se afișează |
| **Uitare exponențială** | half-life 400 eșantioane → se adaptează la schimbări de regim |
| **Post-mortem → acțiune** | „stop vânat apoi ținta atinsă” lărgește stop-ul acelei celule; câștigurile îl strâng la loc |
| **Thompson sampling** (`--explore`) | în paper trading explorează celulele incerte ca să învețe mai repede |

## Rulare

```bash
cd us30_robot
python run.py demo                                  # date sintetice, toată bucla
python run.py backtest --csv US30_M1.csv --tz-shift -2   # export MT5, server GMT+2 → UTC
python run.py live --symbol US30 --tz-shift -2      # MT5 pe Windows: pip install MetaTrader5
python -m unittest discover -s tests -v
```

Starea învățată se salvează în `state/` (`learner.json`, `adaptive.json`, `journal.json`) și se reîncarcă
la pornire, deci un backtest pe istoric „pre-antrenează” robotul înainte de live.

Exemplu de semnal:

```
[2026-01-16 13:22] SEMNAL #59 SELL @ 42813.4 SL 42840.4 TP 42759.3
VÂNZARE (SELL) – P(succes)=45%, expectanță=+0.31R
  • #34 FVG / Imbalance: BOS DN confirmat, retragere în FVG 42821.8-42836.2 și lumânare de respingere
  Context: sesiune london, în direcția trendului M15, zonă nefavorabilă.
  Istoric celulă [34|SELL|london|with]: win-rate 59% din 22 cazuri (ponderat).
   ↳ #59 WIN +1.95R după 31 min – CONFIRMAT după presiune adversă de 0.8R
```

## Parametri (EngineConfig)

`min_prob`, `min_expectancy_r`, `spread_points` (2.5), `timeout_bars` (60 min), `cooldown_bars`,
`allowed_sessions` (implicit Londra + NY), `sessions` (ore UTC; vara se mută cu 1h), `half_life`.

## Limitări

- Fără dependențe externe (Python 3.9+ standard), deci rulează oriunde; live doar prin MT5.
- Pe M1 spread-ul contează mult: expectanța include costul real (`spread_points / risc`).
- Pattern-urile subiective (Elliott, wedges, diamond, Can-Can) nu au încă detector obiectiv.
