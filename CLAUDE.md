# SMC Trading Bot — Claude Code Instructions

Ini adalah project bot trading otomatis berbasis **Smart Money Concepts (SMC)** untuk Bybit Futures.  
Kamu adalah asisten yang membantu mengembangkan, debugging, dan backtest bot ini.

---

## File Utama

| File | Keterangan |
|------|-----------|
| `bott_v4.py` | Bot trading live — deploy di Railway |
| `backtest.py` | Engine backtest — simulasi dengan data historis M5 |
| `CLAUDE.md` | File ini — instruksi untuk Claude Code |

---

## Struktur Bot (`bott_v4.py`)

### Alur strategi SMC:
```
BOS H1 → EMA50 Filter → FVG Touch → IDM M5 → BOS/Sweep M5 → MSS → Entry
```

### Fungsi-fungsi kunci:
- `find_last_swing_bos(df)` — deteksi swing high/low dan BOS
- `get_internal_gaps(df, stype, bos_idx)` — cari FVG di dalam range BOS
- `replay_m5(df, stype)` — state machine IDM M5 (SINGLE_MOVE → KONSOLIDASI → TUNGGU_SENTUH)
- `check_bos_or_sweep(df, fh, fl, ts, stype)` — deteksi BOS/Sweep M5 setelah IDM
- `find_breaker_block(df, ts, stype)` — cari Breaker Block untuk entry
- `place_limit_order(symbol, side, entry, sl, tp)` — eksekusi order ke Bybit
- `replay_h1(df_h1)` — scan setup baru dari H1 (return state dict)
- `run_bot()` — main loop, jalan setiap M5 close (5 menit)

### State machine pending setup:
```
WAIT_FVG_TOUCH → WAIT_IDM_TOUCH → WAIT_BOS_BREAK → WAIT_MSS → ENTRY
```

### Pembatalan setup (CHOCH):
- BOS Long → swing low ditembus → setup batal
- BOS Short → swing high ditembus → setup batal
- Harga ke swing high baru tanpa FVG → BOS tetap valid, update FVG list

### Risk Management:
- Risk per trade: 1% dari balance (compound)
- TP: 3R (3× jarak SL)
- Leverage: otomatis sesuai limit coin

### ATR Filter Adaptif (threshold per coin):
```python
ATR_THRESHOLD = {
    'FARTCOINUSDT'  : 0.0056,   # P25=0.556%
    'XVGUSDT'       : 0.0030,   # P25=0.303%
    '1000PEPEUSDT'  : 0.0031,   # P25=0.306%
    'DOGEUSDT'      : 0.0024,   # P25=0.242%
    '1000FLOKIUSDT' : 0.0030,   # P25=0.296%
    '1000BONKUSDT'  : 0.0035,   # P25=0.348%
    'BELUSDT'       : 0.0024,   # P25=0.238%
    'TAOUSDT'       : 0.0032,   # P25=0.316%
    'USUALUSDT'     : 0.0034,   # P25=0.340%
    'BERAUSDT'      : 0.0035,
}
```
> Threshold = P25 ATR historis → 75% waktu lolos filter, 25% waktu skip (sideways)

### Environment Variables (Railway):
```
API_KEY      = Bybit API Key
API_SECRET   = Bybit API Secret
TESTNET      = false  (true untuk testnet)
PORT         = 8080   (otomatis dari Railway)
```

---

## Struktur Backtest (`backtest.py`)

### Cara pakai:
```python
from backtest import load_m5, backtest_coin, FILES, INITIAL_BALANCE

# Load data
df = load_m5('FARTCOINUSDT', FILES['FARTCOINUSDT'])

# Jalankan backtest
trades, final_balance = backtest_coin('FARTCOINUSDT', df, initial_balance=15.0)
```

### Format data input (txt dari Bybit):
```
========================================
         BYBIT OHLC DATA
========================================
Symbol     : FARTCOINUSDT
...
2025-01-01 00:00:00      | 0.8750      0.8800      0.8700      0.8760      1234567.0
```

### FILES dict — daftar file per coin:
```python
FILES = {
    'FARTCOINUSDT': [
        'FARTCOINUSDT_5m_01-01-2025~31-05-2025.txt',
        'FARTCOINUSDT_5m_01-06-2025~30-09-2025.txt',
        'FARTCOINUSDT_5m_01-10-2025~31-12-2025.txt',
    ],
    # ... coin lainnya
}
```

### DATA_DIR — lokasi file data:
```python
DATA_DIR = "/home/claude/fulldata"   # atau sesuaikan
UPLOAD_DIR = "/mnt/user-data/uploads"  # fallback
```

### Output backtest:
```python
trades = [
    {
        'symbol'     : 'FARTCOINUSDT',
        'entry_ts'   : Timestamp,
        'exit_ts'    : Timestamp,
        'type'       : 'Long' / 'Short',
        'outcome'    : 'tp' / 'sl' / 'timeout',
        'entry'      : float,
        'sl'         : float,
        'tp'         : float,
        'exit_price' : float,
        'pnl_usd'    : float,
        'balance'    : float,
        'trigger'    : 'bos' / 'sweep',
    }
]
```

---

## Workflow Umum

### 1. Backtest coin baru
```bash
# 1. Siapkan data M5 dari Bybit (format txt)
# 2. Tambah ke FILES dict di backtest.py
# 3. Jalankan backtest
python -c "
from backtest import load_m5, backtest_coin, FILES
df = load_m5('NEWCOIN', FILES['NEWCOIN'])
trades, bal = backtest_coin('NEWCOIN', df, 15.0)
print(f'{len(trades)} trade, balance: \${bal:.2f}')
"
```

### 2. Cek ATR coin baru
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
p50 = np.percentile(atr_pct[atr_pct>0], 50)
skip = np.sum(atr_pct < p25) / len(atr_pct) * 100
print(f'P25={p25:.3f}%  P50={p50:.3f}%  Skip={skip:.1f}%')
# Gunakan P25 sebagai ATR_THRESHOLD untuk coin ini
```

### 3. Tambah coin ke bot
```python
# Di bott_v4.py — tambah ke SYMBOLS
SYMBOLS = [..., 'NEWCOINUSDT']

# Di ATR_THRESHOLD (dalam bott_v4.py dan backtest.py)
ATR_THRESHOLD = {
    ...
    'NEWCOINUSDT': 0.00XX,  # hasil P25 ATR
}
```

### 4. Ambil data Bybit kline via script
```python
from pybit.unified_trading import HTTP

session = HTTP(testnet=False)
res = session.get_kline(
    symbol='NEWCOINUSDT',
    category='linear',
    interval=5,
    limit=1000,
    # start=timestamp_ms,
    # end=timestamp_ms,
)
# res['result']['list'] = [[ts, open, high, low, close, vol, turnover], ...]
```

---

## Hasil Backtest (Referensi)

**Full Year 2025 | Modal $15 | Risk 1% compound | TP 3R | 9 Coin**

| Coin | Trade | WR% | PnL | PF |
|------|------:|----:|----:|---:|
| FARTCOINUSDT | 36 | 75% | +$69.38 | 12.14 |
| TAOUSDT | 23 | 70% | +$40.58 | 9.50 |
| 1000BONKUSDT | 24 | 62% | +$27.65 | 3.80 |
| XVGUSDT | 13 | 69% | +$25.72 | 7.81 |
| BELUSDT | 11 | 73% | +$19.97 | 7.19 |
| USUALUSDT | 23 | 48% | +$16.29 | 2.62 |
| 1000PEPEUSDT | 20 | 55% | +$15.67 | 2.61 |
| DOGEUSDT | 13 | 46% | +$8.14 | 1.98 |
| 1000FLOKIUSDT | 24 | 46% | +$2.54 | 1.17 |
| **TOTAL** | **187** | **61%** | **+$225.96** | **4.17** |

**$15 → $240.96 dalam setahun (+1506% ROI)**

### Per Kuartal:
| Kuartal | Trade | WR% | PnL | Bal Awal → Akhir |
|---------|------:|----:|----:|:----------------:|
| Q1 | 59 | 63% | +$20.11 | $15 → $35.11 |
| Q2 | 50 | 54% | +$24.95 | $35.11 → $60.06 |
| Q3 | 31 | 65% | +$44.94 | $60.06 → $105.00 |
| Q4 | 47 | 64% | +$135.96 | $105.00 → $240.96 |

---

## Coin yang Dikeluarkan

- **ENAUSDT** — bearish 3 dari 4 kuartal 2025, ATR tinggi justru choppy.  
  Karakteristik berlawanan dengan coin yang berhasil.

---

## Kapasitas Bot

- Sleep per coin: 3 detik → maks ~36 coin (worst case)
- Bybit API limit: 600 req/5 menit → jauh di atas kebutuhan
- Railway free tier: cukup (512MB RAM, 1 vCPU)
- **Rekomendasi: maks 15–20 coin** untuk headroom yang nyaman

---

## Catatan Penting

1. **Selalu backtest dulu** sebelum tambah coin ke bot live
2. **Cek ATR P25** untuk tentukan threshold yang tepat per coin
3. **Data M5 minimal setahun** untuk backtest yang valid
4. **CHOCH level** di-update otomatis saat harga melewati swing high baru
5. **IDM fix**: trigger jika `close < candidate_low` (bukan hanya wick) — sudah diimplementasi
6. **TP guard**: semua cek TP pakai `and setup['tp']` agar tidak false trigger saat tp=0
