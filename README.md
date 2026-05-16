# 🤖 SMC Trading Bot v4

Bot trading otomatis berbasis **Smart Money Concepts (SMC)** untuk Bybit Futures (USDT Perpetual).  
Deploy di [Railway](https://railway.app) — tinggal isi API key, langsung jalan.

---

## 📐 Strategi

Bot mengikuti alur SMC multi-timeframe secara otomatis:

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
- Risk per trade: **1% dari balance** (compound — naik/turun mengikuti balance)
- TP: **3R** (3× jarak SL dari entry)
- Leverage: otomatis sesuai limit coin, maks 10×
- SL: ujung candle MSS atau Breaker Block

**Pembatalan Setup (CHOCH):**
- BOS Long → harga tembus swing low referensi → setup batal, struktur berganti Short
- BOS Short → harga tembus swing high referensi → setup batal, struktur berganti Long
- Jika harga ke swing high baru tanpa sentuh FVG → BOS tetap valid, tunggu pullback ke FVG terbaru

---

## 📊 Hasil Backtest — Full Year 2025

> Modal $15 | Risk 1% compound | TP 3R | ATR Filter Adaptif  
> Awal: risk $0.15/trade → akhir tahun: risk ~$2.41/trade

**9 Coin | Full Year Jan–Des 2025**

| Coin | Trade | W | L | WR% | PnL ($) | ROI% | PF | MDD% |
|------|------:|--:|--:|----:|--------:|-----:|---:|-----:|
| FARTCOINUSDT | 36 | 27 | 9 | 75% | +$69.38 | +462.6% | 12.14 | 4.7% |
| TAOUSDT | 23 | 16 | 7 | 70% | +$40.58 | +270.5% | 9.50 | 7.3% |
| 1000BONKUSDT | 24 | 15 | 9 | 62% | +$27.65 | +184.4% | 3.80 | 12.9% |
| XVGUSDT | 13 | 9 | 4 | 69% | +$25.72 | +171.5% | 7.81 | 13.6% |
| BELUSDT | 11 | 8 | 3 | 73% | +$19.97 | +133.1% | 7.19 | 7.4% |
| USUALUSDT | 23 | 11 | 12 | 48% | +$16.29 | +108.6% | 2.62 | 12.8% |
| 1000PEPEUSDT | 20 | 11 | 9 | 55% | +$15.67 | +104.4% | 2.61 | 14.5% |
| DOGEUSDT | 13 | 6 | 7 | 46% | +$8.14 | +54.3% | 1.98 | 25.3% |
| 1000FLOKIUSDT | 24 | 11 | 13 | 46% | +$2.54 | +17.0% | 1.17 | 30.1% |
| **TOTAL** | **187** | **114** | **73** | **61%** | **+$225.96** | **+1506.4%** | **4.17** | — |

### Statistik Gabungan

| Metrik | Nilai |
|--------|------:|
| Modal Awal | $15.00 |
| Final Balance | **$240.96** |
| Total Trade | 187 |
| Win Rate | **61.0%** |
| Total PnL | **+$225.96** |
| ROI Setahun | **+1506.4%** |
| Avg Win / trade | +$2.61 |
| Avg Loss / trade | −$0.98 |
| Profit Factor | **4.17** |
| Expectancy / trade | **+$1.21** |
| Max Drawdown (portfolio) | **6.3%** |
| Max Consecutive Loss | 5 |

### Pertumbuhan per Kuartal

| Kuartal | Trade | WR% | PnL ($) | ROI Kuartal | Bal Awal | Bal Akhir | MDD% |
|---------|------:|----:|--------:|:-----------:|:--------:|:---------:|-----:|
| Q1 | 59 | 63% | +$20.11 | +134.1% | $15.00 | $35.11 | 5.2% |
| Q2 | 50 | 54% | +$24.95 | +71.1% | $35.11 | $60.06 | 5.0% |
| Q3 | 31 | 65% | +$44.94 | +74.8% | $60.06 | $105.00 | 4.2% |
| Q4 | 47 | 64% | +$135.96 | +129.5% | $105.00 | $240.96 | 5.4% |

> Q4 paling eksplosif (+$135.96) karena balance sudah besar — efek compound bekerja penuh.

### Long vs Short

| Arah | Trade | WR% | PnL ($) |
|------|------:|----:|--------:|
| Long | 91 | 64.8% | +$119.76 |
| Short | 96 | 57.3% | +$106.20 |

### Equity Milestones

| Target | Tercapai | Trade ke- |
|-------:|:--------:|:---------:|
| $20 | 27 Jan 2025 | #13 |
| $25 | 12 Feb 2025 | #30 |
| $30 | 25 Feb 2025 | #40 |
| $40 | 8 Mei 2025 | #77 |
| $50 | 6 Jun 2025 | #96 |
| $75 | 24 Jul 2025 | #120 |
| $100 | 30 Agt 2025 | #138 |
| $240 | 31 Des 2025 | #187 |

### Catatan Coin

- **FARTCOINUSDT** — coin terbaik, 36 trade, WR 75%, PF 12.14. Volatilitas tinggi dan trending cocok dengan SMC.
- **TAOUSDT & BELUSDT** — paling konsisten, MDD rendah, PF tinggi (7–9.5).
- **DOGEUSDT, USUALUSDT & 1000FLOKIUSDT** — WR di bawah 50% tapi tetap profit karena Avg Win ≈ 2.3× Avg Loss.
- **1000FLOKIUSDT** — ATR median 0.402%, threshold 0.30%. Q1 dan Q3 bagus (WR 67–60%), Q4 lemah karena crash −51.7%.
- **ENAUSDT** — dikeluarkan: bearish 3 dari 4 kuartal, ATR tinggi justru choppy (bukan trending).

---

## 🔧 ATR Filter Adaptif

Setiap coin punya threshold ATR minimum berbeda sesuai karakter volatilitasnya:

| Coin | Threshold | Median ATR | Lolos Filter |
|------|:---------:|:----------:|:------------:|
| FARTCOINUSDT | 0.56% | 0.78% | 75% waktu |
| XVGUSDT | 0.30% | 0.42% | 75% waktu |
| 1000PEPEUSDT | 0.31% | 0.41% | 75% waktu |
| 1000FLOKIUSDT | 0.30% | 0.40% | 75% waktu |
| DOGEUSDT | 0.24% | 0.33% | 75% waktu |
| Lainnya (default) | 0.35% | — | — |

Filter ini mencegah entry saat market sideways/momentum lemah. Threshold ditetapkan di P25 ATR historis masing-masing coin.

---

## 🚀 Deploy ke Railway

### 1. Clone repo

```bash
git clone https://github.com/username/bot-smc.git
cd bot-smc
```

### 2. Buat project di Railway

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Pilih repo ini

### 3. Set Environment Variables

| Variable | Wajib | Keterangan |
|----------|:-----:|-----------|
| `API_KEY` | ✅ | Bybit API Key |
| `API_SECRET` | ✅ | Bybit API Secret |
| `TESTNET` | ❌ | `true` untuk Testnet, default `false` |

> ⚠️ API Key Bybit harus punya permission: **Trade** dan **Read**

### 4. Deploy

Railway otomatis deploy saat push ke GitHub. Bot berjalan sebagai **worker**.

---

## 📡 Monitoring Log

```
https://<nama-project>.up.railway.app/logs
```

---

## ⚙️ Daftar Coin

```python
SYMBOLS = [
    'XVGUSDT', 'BELUSDT', 'TAOUSDT', '1000BONKUSDT', 'BERAUSDT',
    'DOGEUSDT', 'USUALUSDT',
    'FARTCOINUSDT', '1000PEPEUSDT', '1000FLOKIUSDT',
]
```

---

## 📦 Dependencies

```
pandas
numpy
pybit
```

---

## ⚠️ Disclaimer

Bot ini untuk keperluan pribadi. Trading crypto mengandung risiko tinggi.  
Hasil backtest tidak menjamin performa di masa depan.
