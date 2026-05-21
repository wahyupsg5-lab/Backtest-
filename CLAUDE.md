# SMC Trading Bot — Claude Code Instructions

Ini adalah project bot trading otomatis berbasis **Smart Money Concepts (SMC)** untuk Bybit Futures.  
Kamu adalah asisten yang membantu mengembangkan, debugging, dan backtest bot ini.

---

## File Utama

| File | Keterangan |
|------|-----------|
| `bott_v4.py` | Bot trading live — deploy di Railway |
| `backtest.py` | Engine backtest — simulasi dengan data historis M5 |
| `backtest_web.py` | Backtest via Bybit API langsung, hasil tampil di browser |
| `CLAUDE.md` | File ini — instruksi untuk Claude Code |

---

## Struktur Bot (`bott_v4.py`)

### Alur strategi SMC (Recursive IDM):
```
BOS H1 → EMA50 Filter → FVG Touch → IDM#1 M5 → BOS M5 (wajib)
  → IDM#2 dalam BOS → WAIT_MSS → MSS=Entry | BOS lagi=IDM#3 → ...
```

### Fungsi-fungsi kunci:
- `find_last_swing_bos(df)` — deteksi swing high/low dan BOS
- `get_internal_gaps(df, stype, bos_idx)` — cari FVG di dalam range BOS
- `replay_m5(df, stype)` — state machine IDM M5 (SINGLE_MOVE → KONSOLIDASI → TUNGGU_SENTUH)
- `check_bos_or_sweep(df, fh, fl, ts, stype)` — deteksi BOS/Sweep M5 setelah IDM
- `find_breaker_block(df, ts, stype)` — cari Breaker Block untuk entry
- `place_limit_order(symbol, side, entry, sl, tp)` — eksekusi order ke Bybit
- `run_bot()` — main loop, jalan setiap M5 close (5 menit)

### State machine pending setup:
```
WAIT_FVG_TOUCH → WAIT_IDM_TOUCH → WAIT_BOS_BREAK → WAIT_IDM_TOUCH → WAIT_MSS → ENTRY
                                                         ↑___________↓ (loop jika BOS lagi)
```

### Flag `inner_idm`:
- `inner_idm = False/absent` → IDM#1 → transisi ke **WAIT_BOS_BREAK** (wajib BOS dulu)
- `inner_idm = True` → IDM#2+ → transisi ke **WAIT_MSS** (bisa MSS atau BOS lagi)

### Pembatalan setup (CHOCH):
- BOS Long → swing low ditembus → setup batal
- BOS Short → swing high ditembus → setup batal

### Risk Management:
- Risk per trade: 1% dari balance (compound)
- TP: 3R (3× jarak SL)
- Leverage: otomatis sesuai limit coin, maks 10×
- Fee: 0.055% per sisi (Bybit taker)

### SYMBOLS — 35 coin aktif:
```python
SYMBOLS = [
    # Batch 1 (21 coin)
    'XVGUSDT', 'BELUSDT', '1000BONKUSDT', 'BERAUSDT',
    '1000PEPEUSDT',
    'ONDOUSDT', 'EIGENUSDT', 'VIRTUALUSDT',
    'ENAUSDT', 'SHIB1000USDT',
    'JUPUSDT', 'SEIUSDT', 'OPUSDT',
    'STXUSDT', 'APEUSDT', 'ALGOUSDT',
    'ORCAUSDT', 'XRPUSDT', 'XAUTUSDT', 'FARTCOINUSDT', 'TAOUSDT',
    # Batch 2 lolos filter (14 coin)
    'SOLUSDT', 'SUIUSDT', 'TIAUSDT',
    'AAVEUSDT', 'GALAUSDT', 'IMXUSDT', 'GMXUSDT',
    'HBARUSDT', 'SANDUSDT', 'AXSUSDT',
    'LTCUSDT', 'DYDXUSDT', 'FLOWUSDT', 'ICPUSDT',
]
```

### ATR Filter Adaptif (threshold per coin):
```python
ATR_THRESHOLD = {
    # ATR P25 dari backtest fvg_sbr Jan2025–Apr2026
    'XVGUSDT'       : 0.0028,   # P25=0.283%
    'BELUSDT'       : 0.0021,   # P25=0.214%
    '1000BONKUSDT'  : 0.0031,   # P25=0.308%
    'BERAUSDT'      : 0.0031,   # P25=0.305%
    '1000PEPEUSDT'  : 0.0029,   # P25=0.292%
    'ONDOUSDT'      : 0.0025,   # P25=0.254%
    'EIGENUSDT'     : 0.0033,   # P25=0.331%
    'VIRTUALUSDT'   : 0.0036,   # P25=0.363%
    'ENAUSDT'       : 0.0035,   # P25=0.348%
    'SHIB1000USDT'  : 0.0019,   # P25=0.188%
    'JUPUSDT'       : 0.0028,   # P25=0.278%
    'SEIUSDT'       : 0.0025,   # P25=0.250%
    'OPUSDT'        : 0.0028,   # P25=0.277%
    'STXUSDT'       : 0.0023,   # P25=0.229%
    'APEUSDT'       : 0.0024,   # P25=0.241%
    'ALGOUSDT'      : 0.0023,   # P25=0.228%
    'ORCAUSDT'      : 0.0021,   # P25=0.214%
    'XRPUSDT'       : 0.0018,   # P25=0.185%
    'XAUTUSDT'      : 0.0003,   # P25=0.027%
    'FARTCOINUSDT'  : 0.0050,   # P25=0.503%
    'TAOUSDT'       : 0.0031,   # P25=0.313%
    'SOLUSDT'       : 0.0022,   # P25=0.217%
    'SUIUSDT'       : 0.0026,   # P25=0.263%
    'TIAUSDT'       : 0.0030,   # P25=0.298%
    'AAVEUSDT'      : 0.0026,   # P25=0.259%
    'GALAUSDT'      : 0.0028,   # P25=0.278%
    'IMXUSDT'       : 0.0028,   # P25=0.276%
    'GMXUSDT'       : 0.0020,   # P25=0.203%
    'HBARUSDT'      : 0.0022,   # P25=0.217%
    'SANDUSDT'      : 0.0022,   # P25=0.220%
    'AXSUSDT'       : 0.0023,   # P25=0.231%
    'LTCUSDT'       : 0.0018,   # P25=0.178%
    'DYDXUSDT'      : 0.0026,   # P25=0.264%
    'FLOWUSDT'      : 0.0020,   # P25=0.200%
    'ICPUSDT'       : 0.0023,   # P25=0.231%
}
```
> Threshold = P25 ATR historis → 75% waktu lolos filter, 25% waktu skip (sideways)
> Window: 20 candle M5 terbaru (termasuk candle MSS), ref_price = close MSS

### Environment Variables (Railway):
```
API_KEY      = Bybit API Key
API_SECRET   = Bybit API Secret
TESTNET      = false  (true untuk testnet)
PORT         = 8080   (otomatis dari Railway)
```

---

## Struktur Backtest

### `backtest.py` — engine (identik dengan logika bott_v4.py):
```python
from backtest import load_m5, backtest_coin, FILES, INITIAL_BALANCE

df = load_m5('XVGUSDT', FILES['XVGUSDT'])
trades, final_balance = backtest_coin('XVGUSDT', df, initial_balance=10.0)
```

### `backtest_web.py` — fetch data live dari Bybit API + tampil di browser:
```bash
python backtest_web.py   # buka Railway domain untuk lihat progress
# /readme  → export hasil ke markdown
# /logs    → raw log
```

### Sinkronisasi backtest ↔ live bot:
| Komponen | backtest.py | bott_v4.py |
|----------|------------|-----------|
| Strategy | fvg_sbr (entry C1.close SBR zone) | fvg_sbr (SBR_MODE=True) |
| Entry | C1.close (SBR/RBS level) | sbr_lvl = c1_close |
| SL | C1.low/high ± 10% gap buffer | SL sama, market order |
| Trail stop | aktif setelah +1R (threshold-based) | activePrice = entry+dist (Bybit) |
| ATR window | 20 candle include MSS | get_data(limit=20) |
| Volume window | 20 candle include MSS | tail(20) |
| MSS strength | body/range ≥ 30% | body/range ≥ 30% |
| Fee | 0.055% × 2 (modeled) | tidak dimodel (real Bybit yang potong) |

---

## Workflow Umum

### 1. Tambah coin baru ke bot
```python
# Di bott_v4.py — tambah ke SYMBOLS
SYMBOLS = [..., 'NEWCOINUSDT']

# Di ATR_THRESHOLD (bott_v4.py DAN backtest.py)
ATR_THRESHOLD = {
    ...
    'NEWCOINUSDT': 0.00XX,  # hasil P25 ATR dari backtest_web.py log
}
```

### 2. Cek ATR P25 coin baru
```python
import numpy as np, pandas as pd
from backtest import load_m5, FILES

df = load_m5('NEWCOIN', FILES['NEWCOIN'])
c = df['close'].to_numpy(float)
h = df['high'].to_numpy(float)
l = df['low'].to_numpy(float)
pc = np.roll(c,1); pc[0]=c[0]
tr = np.maximum.reduce([h-l, np.abs(h-pc), np.abs(l-pc)])
atr14 = pd.Series(tr).rolling(14).mean().to_numpy()
atr_pct = np.where(c>0, atr14/c*100, 0)[14:]

p25 = np.percentile(atr_pct[atr_pct>0], 25)
print(f'P25={p25:.3f}%')
# Gunakan P25 sebagai ATR_THRESHOLD untuk coin ini
```

### 3. Backtest coin baru via backtest_web.py
```python
# Edit COINS di backtest_web.py, deploy Railway
# ATR P25 dihitung otomatis dari data live Bybit
```

---

## Hasil Backtest Terkini

**Jan 2025 → Apr 2026 | Modal $10 | Risk 1% compound | Trail 0.15R aktif +1R | 35 Coin | fvg_sbr**

| Coin | Trade | WR% | PnL Compound | ROI% | MaxDD% | PF | Avg R:R |
|------|------:|----:|-------------:|-----:|-------:|---:|--------:|
| JUPUSDT | 66 | 62.1% | +$10,553 | +105527% | 4.8% | 1.81 | 1.39:1 |
| TAOUSDT | 51 | 74.5% | +$9,988 | +99881% | 2.1% | 3.13 | 1.29:1 |
| ENAUSDT | 79 | 72.2% | +$6,011 | +60109% | 4.3% | 2.29 | 1.09:1 |
| SANDUSDT | 59 | 62.7% | +$6,461 | +64605% | 6.7% | 1.47 | 1.11:1 |
| FLOWUSDT | 66 | 65.2% | +$6,782 | +67815% | 2.6% | 2.02 | 1.36:1 |
| OPUSDT | 41 | 68.3% | +$6,827 | +68270% | 3.4% | 1.80 | 1.05:1 |
| FARTCOINUSDT | 58 | 62.1% | +$5,568 | +55684% | 5.4% | 1.71 | 1.22:1 |
| ORCAUSDT | 47 | 63.8% | +$5,734 | +57336% | 4.3% | 2.56 | 1.72:1 |
| XRPUSDT | 68 | 63.2% | +$5,193 | +51932% | 3.3% | 1.55 | 1.26:1 |
| SUIUSDT | 67 | 71.6% | +$5,168 | +51679% | 2.8% | 2.65 | 1.35:1 |
| APEUSDT | 52 | 63.5% | +$4,683 | +46826% | 5.0% | 1.79 | 1.34:1 |
| DYDXUSDT | 51 | 56.9% | +$4,102 | +41023% | 6.4% | 1.43 | 1.34:1 |
| ALGOUSDT | 69 | 65.2% | +$4,002 | +40020% | 3.7% | 1.79 | 1.25:1 |
| STXUSDT | 51 | 68.6% | +$3,064 | +30637% | 2.1% | 2.03 | 1.21:1 |
| TIAUSDT | 53 | 66.0% | +$3,279 | +32792% | 6.5% | 1.57 | 1.00:1 |
| XVGUSDT | 48 | 64.6% | +$3,209 | +32089% | 4.3% | 1.84 | 1.24:1 |
| IMXUSDT | 54 | 61.1% | +$3,183 | +31834% | 4.8% | 1.51 | 1.17:1 |
| ONDOUSDT | 69 | 55.1% | +$3,258 | +32577% | 3.7% | 1.29 | 1.36:1 |
| AAVEUSDT | 34 | 67.6% | +$3,006 | +30063% | 2.9% | 2.04 | 1.25:1 |
| SHIB1000USDT | 54 | 61.1% | +$2,958 | +29578% | 7.3% | 1.31 | 1.20:1 |
| 1000PEPEUSDT | 65 | 63.1% | +$2,790 | +27896% | 4.2% | 1.51 | 1.11:1 |
| ICPUSDT | 64 | 64.1% | +$2,636 | +26356% | 5.8% | 1.56 | 1.08:1 |
| 1000BONKUSDT | 41 | 68.3% | +$1,774 | +17739% | 3.2% | 2.06 | 1.17:1 |
| XAUTUSDT | 32 | 56.2% | +$1,586 | +15861% | 3.6% | 1.26 | 1.77:1 |
| AXSUSDT | 62 | 62.9% | +$1,614 | +16142% | 3.6% | 1.72 | 1.24:1 |
| GALAUSDT | 69 | 66.7% | +$1,581 | +15812% | 2.4% | 2.19 | 1.30:1 |
| SOLUSDT | 69 | 68.1% | +$1,352 | +13521% | 2.6% | 2.07 | 1.34:1 |
| GMXUSDT | 64 | 65.6% | +$1,325 | +13248% | 4.1% | 2.51 | 1.75:1 |
| BELUSDT | 56 | 62.5% | +$1,072 | +10722% | 5.0% | 1.88 | 1.45:1 |
| BERAUSDT | 44 | 61.4% | +$1,096 | +10960% | 5.8% | 1.55 | 1.18:1 |
| LTCUSDT | 55 | 67.3% | +$908 | +9083% | 4.2% | 1.89 | 1.23:1 |
| HBARUSDT | 59 | 64.4% | +$247 | +2465% | 4.9% | 1.96 | 1.46:1 |
| VIRTUALUSDT | 69 | 72.5% | +$496 | +4959% | 2.4% | 2.70 | 1.24:1 |
| SEIUSDT | 60 | 63.3% | -$23 | -231% | 4.9% | 1.45 | 1.05:1 |
| EIGENUSDT | 54 | 70.4% | -$2,298 | -22975% | 5.1% | 2.39 | 1.20:1 |
| **TOTAL** | **2000** | **65.0%** | **+$119,184** | **+1,191,837%** | — | — | **1.27:1** |

**$10 → $119,194 dalam 16 bulan**

### Per Kuartal:
| Kuartal | Trade | WR% | PnL | Bal Awal → Akhir |
|---------|------:|----:|----:|:----------------:|
| Q1 2025 | 334 | 60.5% | +$21 | $10 → $31 |
| Q2 2025 | 407 | 65.8% | +$154 | $31 → $184 |
| Q3 2025 | 380 | 64.5% | +$885 | $184 → $1,070 |
| Q4 2025 | 343 | 66.8% | +$7,669 | $1,070 → $8,738 |
| Q1 2026 | 397 | 65.7% | +$55,891 | $8,738 → $64,629 |
| Q2 2026 | 139 | 69.1% | +$54,564 | $64,629 → $119,194 |

---

## Coin yang Dikeluarkan

### Batch 2 tidak lolos filter (PF < 1.40 atau compound negatif):
| Coin | PF | Alasan |
|------|---:|--------|
| INJUSDT | 1.33 | PF di bawah threshold |
| CFXUSDT | 1.38 | PF di bawah threshold |
| CRVUSDT | 1.36 | PF di bawah threshold |
| APTUSDT | 1.08 | PF terlalu rendah |
| UNIUSDT | — | Compound negatif |
| RNDRUSDT | — | Data tidak tersedia |

### Catatan EIGENUSDT:
- WR 70.4%, PF 2.39 — strategy profitable
- Compound -$2,298 karena timing buruk (loss terjadi saat balance besar di Q4 2025/Q1 2026)
- **Tetap dipertahankan** — PF jauh di atas 1.0, jangka panjang positif

---

## Kapasitas Bot

- Sleep per coin: 3 detik → maks ~36 coin (worst case)
- Bybit API limit: 600 req/5 menit → aman
- Railway free tier: cukup (512MB RAM, 1 vCPU)
- **Sekarang: 35 coin** — mendekati batas nyaman, masih aman

---

## Catatan Penting

1. **Selalu backtest dulu** sebelum tambah coin ke bot live
2. **ATR P25** tersedia di log backtest_web.py — langsung pakai nilai itu
3. **fvg_sbr strategy**: Entry market di C1.close (SBR zone), SL di C1.low/high ± 10% gap, trail 0.15R aktif setelah +1R
4. **Trail stop**: backtest pakai threshold `peak ≥ entry+dist`, live bot pakai `activePrice = entry+dist` di Bybit
5. **CHOCH**: cek dilakukan SEBELUM print apapun agar tidak ada log spurious
6. **EIGENUSDT**: WR 70.4% PF 2.39 tapi compound negatif karena timing — **jangan dibuang**, strategy-nya profitable
7. **Compound growth dominan di kuartal akhir**: bukan karena WR lebih tinggi, tapi balance sudah besar → tiap 1% = lebih banyak dollar
8. **35 coin mendekati batas kapasitas** (maks ~36): jangan tambah coin tanpa backtest dulu
