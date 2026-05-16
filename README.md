# 🤖 SMC Trading Bot v4

Bot trading otomatis berbasis **Smart Money Concepts (SMC)** untuk Bybit Futures (USDT Perpetual).  
Deploy di [Railway](https://railway.app) — isi API key, langsung jalan.

---

## 📐 Strategi

```
BOS H1 → EMA50 Filter → FVG Touch → IDM M5 → BOS/Sweep M5 → MSS → Entry
```

| Langkah | Keterangan |
|---------|-----------|
| **BOS H1** | Break of Structure timeframe 1 jam sebagai bias arah |
| **EMA50 Filter** | Harga harus di atas EMA50 (Long) atau di bawah (Short) |
| **FVG H1** | Fair Value Gap sebagai zona pullback |
| **IDM M5** | Inducement M5 — konfirmasi likuiditas diambil |
| **BOS/Sweep M5** | Konfirmasi pergerakan M5 setelah IDM |
| **MSS** | Market Structure Shift — sinyal entry final |
| **Entry** | Breaker Block (prioritas) atau FVG fallback |

**Risk Management:**
- Risk per trade: **1% dari balance** (compound — tiap trade risk ikut balance live saat itu)
- TP: **3R** (3× jarak SL dari entry)
- Leverage: otomatis sesuai limit coin, maks 10×
- SL: ujung candle MSS atau Breaker Block

**Pembatalan Setup (CHOCH):**
- BOS Long → harga tutup di bawah swing low referensi → setup batal
- BOS Short → harga tutup di atas swing high referensi → setup batal

---

## 📊 Hasil Backtest — Full Year 2025

> Modal $10 | Risk 1%/trade compound | TP 3R | ATR Filter Adaptif  
> **18 Coin | Data Bybit Perpetual USDT | M5 + H1 | Jan–Des 2025**

### Per Coin

| Coin | Trade | W | L | WR% | PnL Compound | MaxDD% | PF | ATR P25 |
|------|------:|--:|--:|----:|-------------:|-------:|---:|--------:|
| EIGENUSDT | 38 | 25 | 13 | 65.8% | +$4,236.22 | 4.6% | 4.96 | 0.0037 |
| FARTCOINUSDT | 50 | 34 | 16 | 68.0% | +$3,448.10 | 4.5% | 5.19 | 0.0056 |
| BERAUSDT | 31 | 21 | 10 | 67.7% | +$3,356.16 | 3.5% | 5.10 | 0.0032 |
| TAOUSDT | 23 | 15 | 8 | 65.2% | +$2,937.63 | 4.5% | 4.73 | 0.0032 |
| AVAXUSDT | 18 | 12 | 6 | 66.7% | +$2,802.83 | 2.3% | 4.80 | 0.0025 |
| PENGUUSDT | 40 | 31 | 9 | 77.5% | +$2,606.85 | 4.6% | 7.19 | 0.0040 |
| USUALUSDT | 33 | 18 | 15 | 54.5% | +$2,306.61 | 6.7% | 2.84 | 0.0034 |
| XVGUSDT | 24 | 13 | 11 | 54.2% | +$2,244.74 | 4.7% | 2.81 | 0.0030 |
| LINKUSDT | 25 | 15 | 10 | 60.0% | +$1,747.00 | 4.7% | 3.62 | 0.0025 |
| BELUSDT | 21 | 16 | 5 | 76.2% | +$1,375.16 | 2.4% | 7.18 | 0.0024 |
| SUIUSDT | 22 | 16 | 6 | 72.7% | +$1,006.84 | 2.4% | 5.69 | 0.0029 |
| WIFUSDT | 28 | 16 | 12 | 57.1% | +$901.59 | 4.6% | 3.16 | 0.0038 |
| ONDOUSDT | 22 | 17 | 5 | 77.3% | +$763.48 | 3.4% | 7.63 | 0.0027 |
| 1000BONKUSDT | 28 | 18 | 10 | 64.3% | +$644.72 | 3.3% | 4.37 | 0.0035 |
| 1000PEPEUSDT | 21 | 14 | 7 | 66.7% | +$625.52 | 2.3% | 4.75 | 0.0031 |
| ORCAUSDT | 21 | 13 | 8 | 61.9% | +$623.95 | 2.2% | 3.81 | 0.0024 |
| VIRTUALUSDT | 25 | 19 | 6 | 76.0% | +$474.37 | 2.3% | 7.45 | 0.0040 |
| PNUTUSDT | 31 | 18 | 13 | 58.1% | +$32.56 | 3.4% | 3.29 | 0.0036 |
| **TOTAL** | **501** | **331** | **170** | **66.1%** | **+$32,134.34** | — | — | — |

**$10.00 → $32,144.34 dalam setahun (+321,343% ROI)**

> _PnL Compound = kontribusi tiap coin ke 1 pot bersama (risk 1% dari balance live per trade).  
> Ini sama persis dengan cara bot live bekerja: tiap trade, risk ikut balance Bybit saat itu._

### Statistik Gabungan

| Metrik | Nilai |
|--------|------:|
| Modal Awal | $10.00 |
| Final Balance | **$32,144.34** |
| Total Trade | 501 |
| Win Rate | **66.1%** |
| Total PnL | **+$32,134.34** |
| ROI Setahun | **+321,343%** |
| Max Drawdown (per coin) | maks 6.7% |

### Per Kuartal

| Kuartal | Trade | WR% | PnL ($) | Bal Awal | Bal Akhir |
|---------|------:|----:|--------:|:--------:|:---------:|
| Q1 | 147 | 68% | +$109.83 | $10.00 | $119.83 |
| Q2 | 141 | 70% | +$1,346.19 | $119.83 | $1,466.02 |
| Q3 | 99 | 57% | +$3,515.23 | $1,466.02 | $4,981.25 |
| Q4 | 114 | 67% | +$27,163.09 | $4,981.25 | $32,144.34 |

> Balance per kuartal = semua trade diurutkan waktu, risk 1% dari balance berjalan.  
> Ini cara kerja bot live yang sesungguhnya — tiap trade, risk ikut balance Bybit saat itu.

---

## 🔧 ATR Filter Adaptif

Setiap coin punya threshold ATR minimum berbeda (P25 ATR historis = 75% waktu lolos filter):

| Coin | Threshold |
|------|:---------:|
| FARTCOINUSDT | 0.56% |
| PENGUUSDT / VIRTUALUSDT | 0.40% |
| WIFUSDT | 0.38% |
| EIGENUSDT | 0.37% |
| PNUTUSDT | 0.36% |
| 1000BONKUSDT | 0.35% |
| USUALUSDT | 0.34% |
| BERAUSDT / TAOUSDT | 0.32% |
| 1000PEPEUSDT | 0.31% |
| XVGUSDT | 0.30% |
| SUIUSDT | 0.29% |
| ONDOUSDT | 0.27% |
| LINKUSDT / AVAXUSDT | 0.25% |
| BELUSDT / ORCAUSDT | 0.24% |

---

## ⚙️ Daftar Coin (18 coin aktif)

```python
SYMBOLS = [
    'XVGUSDT', 'BELUSDT', 'TAOUSDT', '1000BONKUSDT', 'BERAUSDT',
    'USUALUSDT',
    'FARTCOINUSDT', '1000PEPEUSDT',
    'WIFUSDT', 'PENGUUSDT', 'PNUTUSDT',
    'SUIUSDT', 'AVAXUSDT', 'ONDOUSDT', 'EIGENUSDT',
    'LINKUSDT',
    'VIRTUALUSDT', 'ORCAUSDT',
]
```

### Coin yang Tidak Dimasukkan

| Coin | Alasan |
|------|--------|
| JUPUSDT | WR 48.4%, PF 2.16, MaxDD 7.9% — compound negatif |
| WLDUSDT | WR 48.1%, PF 2.34, MaxDD 7.7% — WR di bawah 50% |
| DOGEUSDT | WR 46%, PF 2.02 — profit tapi weak |
| 1000FLOKIUSDT | WR 45.8%, PF 1.92 — borderline |
| ENAUSDT | Bearish 3/4 kuartal, ATR tinggi tapi choppy |
| INJUSDT | WR 40.7%, PF 1.62 |
| ICPUSDT | Hanya 9 trade/tahun |
| ARBUSDT | WR 40%, PF 1.57 |
| TONUSDT | PF 0.82 (losing) |
| ADAUSDT | 9 trade/tahun |
| STORJUSDT | 5 trade/tahun |
| NEARUSDT | WR 44% |

---

## 🚀 Deploy ke Railway

### Set Environment Variables

| Variable | Wajib | Keterangan |
|----------|:-----:|-----------|
| `API_KEY` | ✅ | Bybit API Key (permission: Trade + Read) |
| `API_SECRET` | ✅ | Bybit API Secret |
| `TESTNET` | ❌ | `true` untuk testnet, default `false` |

### Monitoring Log

```
https://<nama-project>.up.railway.app/logs
```

---

## 📦 Dependencies

```
pandas>=2.0
numpy>=1.24
pybit>=5.0
```

---

> ⚠️ **Disclaimer**: Bot ini untuk keperluan pribadi. Trading crypto mengandung risiko tinggi.  
> Hasil backtest tidak menjamin performa di masa depan.
