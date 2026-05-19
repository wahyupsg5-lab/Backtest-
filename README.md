# SMC Trading Bot — fvg_strong Strategy

Bot trading otomatis berbasis **Smart Money Concepts (SMC)** untuk Bybit Futures (USDT Perpetual).
Deploy di [Railway](https://railway.app).

---

## Strategi fvg_strong

```
BOS H1 → FVG (C3 volume > avg20H) → OCL touch M5 → Market order entry
```

| Parameter | Nilai |
|-----------|-------|
| Entry | Market order saat harga sentuh OCL (C2 close dari FVG) |
| SL | 6.2× gap_size dari entry |
| Trailing Stop | Aktif sejak entry, jarak 2.0× dist |
| Break Even | Saat harga capai entry + 2× dist |
| Touch Volume | ≥ 0.8× avg 20 candle M5 |
| Max FVG Gap | ≤ 0.60% dari harga |
| Risk per trade | 1% dari balance (compound) |
| Leverage | Otomatis, maks 10× |

---

## Hasil Backtest — Full Year 2025

**34 coin ditest → 23 lolos (compound positif)**  
Modal: $10 | Risk: 1%/trade compound | Period: Jan–Des 2025

| Metric | Nilai |
|--------|-------|
| Total Trade | 2.915 |
| Win Rate | 36.1% |
| **Compound** | **$10 → $11.060** |
| **ROI** | **+110.507%** |

### Per Kuartal

| Kuartal | Trade | WR% | PnL | Balance |
|---------|------:|----:|----:|---------|
| Q1 | 702 | 36.6% | +$92 | $10 → $102 |
| Q2 | 793 | 39.3% | +$1.984 | $102 → $2.086 |
| Q3 | 796 | 33.9% | +$2.667 | $2.086 → $4.754 |
| Q4 | 624 | 34.0% | +$6.307 | $4.754 → $11.061 |

---

## 23 Coin Aktif (Compound Positif)

| Coin | Trade | WR% | Compound | MaxDD% | PF | R:R | ATR P25 |
|------|------:|----:|---------:|-------:|---:|----:|--------:|
| JUPUSDT | 86 | 38.4% | +$1.950 | 11.1% | 1.56 | 2.33 | 0.0030 |
| BELUSDT | 105 | 40.0% | +$1.703 | 13.9% | 1.28 | 1.83 | 0.0024 |
| DOTUSDT | 87 | 41.4% | +$1.600 | 12.8% | 1.60 | 2.12 | 0.0023 |
| SEIUSDT | 69 | 34.8% | +$1.016 | 6.7% | 1.62 | 2.91 | 0.0028 |
| ENAUSDT | 99 | 40.4% | +$974 | 7.6% | 1.50 | 2.00 | 0.0039 |
| 1000PEPEUSDT | 71 | 45.1% | +$845 | 4.7% | 2.06 | 2.50 | 0.0031 |
| ARBUSDT | 85 | 32.9% | +$705 | 7.3% | 1.32 | 2.59 | 0.0028 |
| OPUSDT | 105 | 39.0% | +$688 | 11.1% | 1.21 | 1.92 | 0.0029 |
| SHIB1000USDT | 86 | 32.6% | +$651 | 16.5% | 1.02 | 2.02 | 0.0020 |
| 1000BONKUSDT | 100 | 40.0% | +$587 | 8.7% | 1.59 | 2.29 | 0.0035 |
| RUNEUSDT | 93 | 38.7% | +$512 | 12.6% | 1.18 | 1.75 | 0.0022 |
| ATOMUSDT | 94 | 36.2% | +$372 | 15.7% | 1.05 | 1.89 | 0.0021 |
| ONDOUSDT | 116 | 32.8% | +$345 | 16.2% | 1.05 | 2.20 | 0.0027 |
| LDOUSDT | 88 | 36.4% | +$335 | 9.4% | 1.17 | 2.08 | 0.0031 |
| STXUSDT | 64 | 34.4% | +$317 | 10.1% | 1.20 | 2.26 | 0.0025 |
| 1000FLOKIUSDT | 94 | 35.1% | +$313 | 13.0% | 1.02 | 1.88 | 0.0030 |
| EIGENUSDT | 76 | 36.8% | +$287 | 10.7% | 1.21 | 2.12 | 0.0037 |
| XVGUSDT | 78 | 44.9% | +$278 | 8.5% | 1.36 | 1.74 | 0.0030 |
| ALGOUSDT | 93 | 35.5% | +$228 | 13.3% | 1.12 | 2.11 | 0.0024 |
| VIRTUALUSDT | 78 | 29.5% | +$143 | 10.7% | 1.10 | 2.47 | 0.0040 |
| PNUTUSDT | 54 | 29.6% | +$100 | 8.0% | 1.28 | 2.71 | 0.0036 |
| BERAUSDT | 83 | 32.5% | +$77 | 14.7% | 1.11 | 2.44 | 0.0032 |
| APEUSDT | 95 | 38.9% | +$22 | 13.8% | 1.24 | 2.03 | 0.0024 |

---

## Coin Dibuang (Compound Negatif)

| Coin | Compound | PF | Alasan |
|------|--------:|---:|--------|
| INJUSDT | -$566 | 0.89 | PF < 1, 58% CHOCH |
| STORJUSDT | -$504 | 1.21 | MaxDD 18.5%, timing losses di Q4 |
| SUIUSDT | -$435 | 1.04 | PF marginal, compound negatif |
| PYTHUSDT | -$354 | 1.17 | Timing losses saat balance besar |
| WIFUSDT | -$274 | 1.32 | 52% CHOCH, losses di Q4 |
| ICPUSDT | -$238 | 1.01 | MaxDD 17.4%, PF marginal |
| DOGEUSDT | -$233 | 0.82 | PF < 1 |
| ORCAUSDT | -$196 | 2.72 | PF bagus tapi timing compound sangat buruk |
| SOLUSDT | -$115 | 1.45 | Losses terkonsentrasi di Q4 saat balance besar |
| MASKUSDT | -$74 | 1.16 | Timing buruk |
| GRTUSDT | -$12 | 1.19 | Borderline negatif |

---

## File Utama

| File | Fungsi |
|------|--------|
| `bott_v4.py` | Bot live — deploy di Railway |
| `backtest.py` | Engine backtest (logika identik dengan bot live) |
| `backtest_web.py` | Backtest via Bybit API, hasil di browser |
| `CLAUDE.md` | Instruksi untuk Claude Code |

## Environment Variables (Railway)

```
API_KEY    = Bybit API Key
API_SECRET = Bybit API Secret
TESTNET    = false
PORT       = 8080
```

Start command: `python bott_v4.py`

## Backtest

```bash
python backtest_web.py
# Buka Railway domain → lihat progress real-time
# /readme → export hasil ke markdown
# /logs   → raw log
```
