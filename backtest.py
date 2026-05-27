"""
BACKTEST ENGINE — SMC Bot v4 (bott_v4.py logic)
================================================
- Data: M5 candle dari file txt Bybit
- H1 di-construct dari M5 (group 12 candle per jam)
- Logika identik: BOS H1 → EMA50 filter → FVG → IDM M5 → BOS/Sweep M5 → MSS → Entry
- TP = 3R, Risk per trade = 1% balance
- Modal awal $30
"""

import pandas as pd
import numpy as np
import os, re
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
INITIAL_BALANCE = 30.0
RISK_PCT        = 0.01      # 1% risk per trade
LEVERAGE        = 10
TAKER_FEE       = 0.00055   # 0.055% per side (Bybit USDT perp)
MIN_RR          = 1.5   # 1:2 = 2.0, 1:3 = 3.0 — cukup untuk contrarian
MIN_DIST_PCT    = 0.002     # minimum SL distance 0.2% (fvg_sbr pakai C1 range, lebih kecil dari 0.5%)

# ── Test variant config (override dari luar untuk testing) ──
ENTRY_MODE   = 'bb_sl'  # 'bb_sl'|'bb_entry'|'fvg_touch'|'fvg_touch_rev'|'fvg_rev_limit'|'idm_touch'|'fvg_confirm'|'fvg_deep'|'fvg_dip'|'fvg_strong'|'fvg_sbr'|'fvg_50pct'|'fvg_limit'
SL_MULT      = 6.2      # SL distance dari titik 0 (dalam R unit = FVG height)
TP_MULT      = 2.0      # TP distance dari titik 0 (dalam R unit)
ENTRY_R      = 8.0      # fvg_rev_limit: level limit entry dari titik 0 (dalam R)
TIME_FILTER  = 0        # max candles FVG→MSS (0 = disabled)
TRAIL_STOP   = 0.50     # trailing SL step dalam R — sinkron dengan bott_v4.py
TRAIL_ACT_R  = 1.5      # trail aktif setelah +TRAIL_ACT_R dari entry (Bybit min ≥ trailingStop)
TRAIL_TIMEOUT_C = 864   # close posisi jika trail SL tidak bergerak selama N candle M5
                        # 864 = 3 hari (72 jam × 12 candle/jam)
TOUCH_VOL_MIN = 0.8     # fvg_strong: touch candle vol min (× avg 20 M5 candle; 0 = no filter)
MAX_GAP_PCT   = 0.006   # fvg_strong: max gap_size / entry_p — sinkron dengan bott_v4.py
APPROACH_R    = 2.0     # fvg_limit: place order saat harga dalam 2R dari entry
REQUIRE_BOS   = True    # True = perlu BOS H1 dulu; False = FVG kuat langsung tanpa BOS
MAX_CONCURRENT = 5      # maks posisi/limit aktif bersamaan lintas semua coin


DATA_DIR = "/home/claude/fulldata"
FILES = {
    '1000BONKUSDT' : [
        '1000BONKUSDT_5m_01-01-2025~31-05-2025.txt',
        '1000BONKUSDT_5m_01-06-2025~30-09-2025.txt',
        '1000BONKUSDT_5m_01-10-2025~31-12-2025.txt',
    ],
    '1000PEPEUSDT' : [
        '1000PEPEUSDT_5m_01-01-2025~31-05-2025.txt',
        '1000PEPEUSDT_5m_01-06-2025~30-09-2025.txt',
        '1000PEPEUSDT_5m_01-10-2025~31-12-2025.txt',
    ],
    'DOGEUSDT'     : [
        'DOGEUSDT_5m_01-01-2025~31-05-2025.txt',
        'DOGEUSDT_5m_01-06-2025~30-09-2025.txt',
        'DOGEUSDT_5m_01-10-2025~31-12-2025.txt',
    ],
    'ENAUSDT'      : [
        'ENAUSDT_5m_01-01-2025~31-05-2025.txt',
        'ENAUSDT_5m_01-06-2025~30-09-2025.txt',
        'ENAUSDT_5m_01-10-2025~31-12-2025.txt',
    ],
    'FARTCOINUSDT' : [
        'FARTCOINUSDT_5m_01-01-2025~31-05-2025.txt',
        'FARTCOINUSDT_5m_01-06-2025~30-09-2025.txt',
        'FARTCOINUSDT_5m_01-10-2025~31-12-2025.txt',
    ],
    'TAOUSDT'      : [
        'TAOUSDT_5m_01-01-2025~31-05-2025.txt',
        'TAOUSDT_5m_01-06-2025~30-09-2025.txt',
        'TAOUSDT_5m_01-10-2025~31-12-2025.txt',
    ],
    'USUALUSDT'    : [
        'USUALUSDT_5m_01-01-2025~31-05-2025.txt',
        'USUALUSDT_5m_01-06-2025~30-09-2025.txt',
        'USUALUSDT_5m_01-10-2025~31-12-2025.txt',
    ],
    'XVGUSDT'      : [
        'XVGUSDT_5m_01-01-2025~31-05-2025.txt',
        'XVGUSDT_5m_01-06-2025~30-09-2025.txt',
        'XVGUSDT_5m_01-10-2025~31-12-2025.txt',
    ],
    '1000FLOKIUSDT': [
        '1000FLOKIUSDT_5m_01-01-2025_31-05-2025.txt',
        '1000FLOKIUSDT_5m_01-06-2025_30-09-2025.txt',
        '1000FLOKIUSDT_5m_01-10-2025_31-12-2025.txt',
    ],
}

# ============================================================
# LOAD DATA
# ============================================================

UPLOAD_DIR = "/mnt/user-data/uploads"

# ATR filter threshold per coin (P25 ATR historis dari backtest)
# backtest_web.py override dict ini dengan nilai live saat runtime
ATR_THRESHOLD = {
    # ATR P25 dari backtest fvg_sbr Jan2025–Apr2026
    'XVGUSDT'       : 0.0028,   # P25=0.283%
    '1000BONKUSDT'  : 0.0031,   # P25=0.308%
    'BERAUSDT'      : 0.0031,   # P25=0.305%
    '1000PEPEUSDT'  : 0.0029,   # P25=0.292%
    'ONDOUSDT'      : 0.0025,   # P25=0.254%
    'EIGENUSDT'     : 0.0033,   # P25=0.331%
    'VIRTUALUSDT'   : 0.0036,   # P25=0.363%
    'ENAUSDT'       : 0.0035,   # P25=0.348%
    'SHIB1000USDT'  : 0.0019,   # P25=0.188%
    'JUPUSDT'       : 0.0028,   # P25=0.278%
    'OPUSDT'        : 0.0028,   # P25=0.277%
    'STXUSDT'       : 0.0023,   # P25=0.229%
    'APEUSDT'       : 0.0024,   # P25=0.241%
    'ALGOUSDT'      : 0.0023,   # P25=0.228%
    'ORCAUSDT'      : 0.0021,   # P25=0.214%
    'XRPUSDT'       : 0.0018,   # P25=0.185%
    'XAUTUSDT'      : 0.0003,   # P25=0.027%
    'FARTCOINUSDT'  : 0.0050,   # P25=0.503%
    'TAOUSDT'       : 0.0031,   # P25=0.313%
    'SUIUSDT'       : 0.0026,   # P25=0.263%
    'AAVEUSDT'      : 0.0026,   # P25=0.259%
    'GALAUSDT'      : 0.0028,   # P25=0.278%
    'IMXUSDT'       : 0.0028,   # P25=0.276%
    'GMXUSDT'       : 0.0020,   # P25=0.203%
    'SANDUSDT'      : 0.0022,   # P25=0.220%
    'AXSUSDT'       : 0.0023,   # P25=0.231%
    'LTCUSDT'       : 0.0018,   # P25=0.178%
    'DYDXUSDT'      : 0.0026,   # P25=0.264%
    'FLOWUSDT'      : 0.0020,   # P25=0.200%
    'ICPUSDT'       : 0.0023,   # P25=0.231%
}

def _parse_one_file(path):
    # Coba path asli dulu, lalu cek uploads
    if not __import__('os').path.exists(path):
        fname = __import__('os').path.basename(path)
        alt = __import__('os').path.join(UPLOAD_DIR, fname)
        if __import__('os').path.exists(alt):
            path = alt
    rows = []
    with open(path, 'rb') as f:
        raw = f.read()
    for bline in raw.split(b'\n'):
        line = bline.decode('utf-8', errors='replace').strip()
        if not line or not line[0].isdigit():
            continue
        parts = line.split('|')
        if len(parts) < 2:
            continue
        try:
            ts_str = parts[0].strip()
            vals   = parts[1].split()
            if len(vals) < 5:
                continue
            o, h, l, c, v = float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]), float(vals[4])
            rows.append({'ts': pd.Timestamp(ts_str), 'open': o, 'high': h,
                         'low': l, 'close': c, 'vol': v})
        except:
            continue
    return rows

def load_m5(symbol, fnames):
    """fnames: string tunggal atau list file — otomatis digabung & sort by ts."""
    if isinstance(fnames, str):
        fnames = [fnames]
    rows = []
    for fname in fnames:
        path = os.path.join(DATA_DIR, fname)
        rows.extend(_parse_one_file(path))
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset='ts').sort_values('ts').reset_index(drop=True)
    df['ts_ms'] = df['ts'].astype('datetime64[s]').astype(np.int64)
    return df


def build_h1(df_m5):
    """Construct H1 candles dari M5 — numpy vectorized (12 candle per jam)."""
    n = len(df_m5)
    if n == 0:
        return pd.DataFrame(columns=['ts','open','high','low','close','vol'])

    opens  = df_m5['open'].to_numpy(dtype=float)
    highs  = df_m5['high'].to_numpy(dtype=float)
    lows   = df_m5['low'].to_numpy(dtype=float)
    closes = df_m5['close'].to_numpy(dtype=float)
    vols   = df_m5['vol'].to_numpy(dtype=float)
    ts_ms  = df_m5['ts_ms'].to_numpy(dtype=np.int64)
    ts_dt  = df_m5['ts'].to_numpy()   # Timestamp array untuk kolom 'ts'

    # Group berdasarkan floor ke jam (ts_ms dalam detik, bukan ms)
    hours = ts_ms // 3600
    unique_hours, first_idx = np.unique(hours, return_index=True)

    h1_rows = []
    for idx, h in enumerate(unique_hours):
        mask = hours == h
        h1_rows.append({
            'ts'   : ts_dt[first_idx[idx]],    # Timestamp (bukan int)
            'open' : float(opens[mask][0]),
            'high' : float(highs[mask].max()),
            'low'  : float(lows[mask].min()),
            'close': float(closes[mask][-1]),
            'vol'  : float(vols[mask].sum()),
        })
    df_h1 = pd.DataFrame(h1_rows)
    # Tambah ts_ms untuk kompatibilitas
    df_h1['ts_ms'] = ts_ms[first_idx]
    return df_h1

# ============================================================
# INDICATORS
# ============================================================

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_atr(df, period=14):
    h, l, pc = df['high'], df['low'], df['close'].shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# ============================================================
# SWING DETECTION
# ============================================================

def find_last_swing_bos(df):
    """Deteksi swing high/low dengan numpy — jauh lebih cepat."""
    h_arr = df['high'].to_numpy(dtype=float)
    l_arr = df['low'].to_numpy(dtype=float)
    n = len(h_arr)
    if n < 5:
        return [], []

    # Swing high: candle[i] lebih tinggi dari 2 tetangga kiri dan 2 kanan (5-candle swing)
    sh_mask = ((h_arr[2:-2] > h_arr[1:-3]) & (h_arr[2:-2] > h_arr[:-4]) &
               (h_arr[2:-2] > h_arr[3:-1]) & (h_arr[2:-2] > h_arr[4:]))
    sl_mask = ((l_arr[2:-2] < l_arr[1:-3]) & (l_arr[2:-2] < l_arr[:-4]) &
               (l_arr[2:-2] < l_arr[3:-1]) & (l_arr[2:-2] < l_arr[4:]))

    sh_idx = np.where(sh_mask)[0] + 2  # +2 karena slice [2:-2]
    sl_idx = np.where(sl_mask)[0] + 2

    ts_arr = df['ts'].to_numpy() if 'ts' in df.columns else np.zeros(n)

    highs = [{'val': float(h_arr[i]), 'idx': int(i), 'ts': ts_arr[i]} for i in sh_idx]
    lows  = [{'val': float(l_arr[i]), 'idx': int(i), 'ts': ts_arr[i]} for i in sl_idx]
    return highs, lows

# ============================================================
# FVG
# ============================================================

def _gap_vol_fields(df, c3_idx):
    """Extract volume + OCL + C1 fields for an FVG (df in H1). C1=c3_idx-2."""
    has_vol  = 'vol' in df.columns
    c2_idx   = c3_idx - 1
    c1_idx   = c3_idx - 2
    c2_close = float(df['close'].iloc[c2_idx]) if c2_idx >= 0 else 0.0
    c3_open  = float(df['open'].iloc[c3_idx])  if c3_idx < len(df) else 0.0
    # C1 candle fields — dipakai untuk SBR entry (SL di C1.low/C1.high)
    c1_open  = float(df['open'].iloc[c1_idx])  if c1_idx >= 0 else 0.0
    c1_close = float(df['close'].iloc[c1_idx]) if c1_idx >= 0 else 0.0
    c1_low   = float(df['low'].iloc[c1_idx])   if c1_idx >= 0 else 0.0
    c1_high  = float(df['high'].iloc[c1_idx])  if c1_idx >= 0 else 0.0
    base = {'c2_close': c2_close, 'c3_open': c3_open,
            'c1_open': c1_open, 'c1_close': c1_close,
            'c1_low': c1_low,   'c1_high': c1_high}
    if not has_vol:
        return {**base, 'c3_vol': 0.0, 'vol_max10h': 0.0}
    c3_vol    = float(df['vol'].iloc[c3_idx])
    avg_start = max(0, c3_idx - 5)
    vol_max   = float(df['vol'].iloc[avg_start:c3_idx].max()) if c3_idx > 0 else 0.0
    return {**base, 'c3_vol': c3_vol, 'vol_max10h': vol_max}

def get_internal_gaps(df, stype, bos_idx, lookback=60):
    gaps = []
    scan_start = max(2, bos_idx - lookback)

    # Pre-BOS FVG  (C1=i-2, C2=i-1, C3=i)
    for i in range(bos_idx - 1, scan_start, -1):
        gap = None
        if stype == "Long" and df['high'].iloc[i-2] < df['low'].iloc[i]:
            # Warna sama: semua 3 candle bullish
            if not (df['close'].iloc[i-2] > df['open'].iloc[i-2] and
                    df['close'].iloc[i-1] > df['open'].iloc[i-1] and
                    df['close'].iloc[i]   > df['open'].iloc[i]):
                continue
            gap = {"top": df['low'].iloc[i], "bottom": df['high'].iloc[i-2], "zone": "pre"}
            gap.update(_gap_vol_fields(df, i))   # C3 = i
        elif stype == "Short" and df['low'].iloc[i-2] > df['high'].iloc[i]:
            # Warna sama: semua 3 candle bearish
            if not (df['close'].iloc[i-2] < df['open'].iloc[i-2] and
                    df['close'].iloc[i-1] < df['open'].iloc[i-1] and
                    df['close'].iloc[i]   < df['open'].iloc[i]):
                continue
            gap = {"top": df['low'].iloc[i-2], "bottom": df['high'].iloc[i], "zone": "pre"}
            gap.update(_gap_vol_fields(df, i))   # C3 = i
        if gap:
            is_fresh = True
            for j in range(i + 1, bos_idx + 1):
                if stype == "Long" and df['close'].iloc[j] < gap['bottom']:
                    is_fresh = False; break
                if stype == "Short" and df['close'].iloc[j] > gap['top']:
                    is_fresh = False; break
            if is_fresh:
                gaps.append(gap)

    # Post-BOS FVG  (C1=i-1, C2=i, C3=i+1)
    post_end = len(df) - 2
    for i in range(bos_idx + 1, post_end):
        if i + 1 >= len(df): continue
        gap = None
        if stype == "Long" and df['high'].iloc[i-1] < df['low'].iloc[i+1]:
            # Warna sama: semua 3 candle bullish
            if not (df['close'].iloc[i-1] > df['open'].iloc[i-1] and
                    df['close'].iloc[i]   > df['open'].iloc[i]   and
                    df['close'].iloc[i+1] > df['open'].iloc[i+1]):
                continue
            gap = {"top": df['low'].iloc[i+1], "bottom": df['high'].iloc[i-1], "zone": "post"}
            gap.update(_gap_vol_fields(df, i + 1))  # C3 = i+1
        elif stype == "Short" and df['low'].iloc[i-1] > df['high'].iloc[i+1]:
            # Warna sama: semua 3 candle bearish
            if not (df['close'].iloc[i-1] < df['open'].iloc[i-1] and
                    df['close'].iloc[i]   < df['open'].iloc[i]   and
                    df['close'].iloc[i+1] < df['open'].iloc[i+1]):
                continue
            gap = {"top": df['low'].iloc[i-1], "bottom": df['high'].iloc[i+1], "zone": "post"}
            gap.update(_gap_vol_fields(df, i + 1))  # C3 = i+1
        if gap:
            is_fresh = True
            for j in range(i + 2, len(df)):
                if stype == "Long" and df['close'].iloc[j] < gap['bottom']:
                    is_fresh = False; break
                if stype == "Short" and df['close'].iloc[j] > gap['top']:
                    is_fresh = False; break
            if is_fresh:
                gaps.append(gap)

    if stype == "Long":
        gaps.sort(key=lambda g: g['top'], reverse=True)
    else:
        gaps.sort(key=lambda g: g['bottom'])
    return gaps


def fvg_fully_broken(candle, fvg, stype):
    if stype == "Long":  return candle['close'] < fvg['bottom']
    else:                return candle['close'] > fvg['top']

def candle_touches_fvg(candle, fvg, stype):
    if stype == "Long":
        return candle['low'] <= fvg['top'] and not fvg_fully_broken(candle, fvg, stype)
    else:
        return candle['high'] >= fvg['bottom'] and not fvg_fully_broken(candle, fvg, stype)

# ============================================================
# IDM (replay_m5) — sudah di-fix
# ============================================================

def replay_m5(df, stype):
    if len(df) < 3:
        return {'phase': 'WAIT_IDM', 'idm_level': None}

    state = 'SINGLE_MOVE'
    candidate_high = None
    candidate_low  = None
    idm_start_idx  = 0

    i = 0
    while i < len(df):
        c = df.iloc[i]

        if stype == "Long":
            if state == 'SINGLE_MOVE':
                if candidate_low is None or c['low'] <= candidate_low:
                    candidate_low = c['low']; candidate_high = c['high']; i += 1
                else:
                    state = 'KONSOLIDASI'

            elif state == 'KONSOLIDASI':
                if c['low'] < candidate_low:
                    idm_high = candidate_high
                    candidate_low = c['low']; candidate_high = idm_high
                    idm_start_idx = i; state = 'TUNGGU_SENTUH'
                i += 1

            elif state == 'TUNGGU_SENTUH':
                if c['low'] < candidate_low:
                    candidate_low = c['low']; candidate_high = c['high']
                    state = 'SINGLE_MOVE'; i += 1
                elif c['high'] >= candidate_high * 0.9995 or float(c['close']) > candidate_high:
                    du = df.iloc[idm_start_idx:i+1]
                    return {
                        'phase': 'IDM_TOUCHED', 'idm_level': candidate_high,
                        'freeze_high': du['high'].max(), 'freeze_low': du['low'].min(),
                        'freeze_ts': c['ts_ms']
                    }
                else:
                    i += 1

        else:  # Short
            if state == 'SINGLE_MOVE':
                if candidate_high is None or c['high'] >= candidate_high:
                    candidate_high = c['high']; candidate_low = c['low']; i += 1
                else:
                    state = 'KONSOLIDASI'

            elif state == 'KONSOLIDASI':
                if c['high'] > candidate_high:
                    idm_low = candidate_low
                    candidate_high = c['high']; candidate_low = idm_low
                    idm_start_idx = i; state = 'TUNGGU_SENTUH'
                i += 1

            elif state == 'TUNGGU_SENTUH':
                if c['low'] <= candidate_low * 1.0005 or float(c['close']) < candidate_low:
                    du = df.iloc[idm_start_idx:i+1]
                    return {
                        'phase': 'IDM_TOUCHED', 'idm_level': candidate_low,
                        'freeze_high': du['high'].max(), 'freeze_low': du['low'].min(),
                        'freeze_ts': c['ts_ms']
                    }
                elif c['high'] > candidate_high:
                    candidate_high = c['high']
                    state = 'SINGLE_MOVE'
                i += 1

    idm_level = candidate_high if stype == "Long" else candidate_low
    return {'phase': 'WAIT_IDM', 'idm_level': idm_level, 'state': state}


# ============================================================
# BOS / SWEEP M5
# ============================================================

def check_bos_or_sweep(df_m5, freeze_high, freeze_low, freeze_ts, stype):
    df_range = df_m5[df_m5['ts_ms'] >= freeze_ts]
    if df_range.empty:
        return {'trigger': None}

    closes = df_range['close'].to_numpy(dtype=float)
    highs  = df_range['high'].to_numpy(dtype=float)
    lows   = df_range['low'].to_numpy(dtype=float)
    ts_ms  = df_range['ts_ms'].to_numpy()
    nfh    = float(df_range['high'].max())
    nfl    = float(df_range['low'].min())

    if stype == "Long":
        for k in range(len(closes)):
            if closes[k] < freeze_low:
                return {'trigger': 'bos',   'ts': int(ts_ms[k]), 'nfh': nfh, 'nfl': nfl}
            if lows[k] < freeze_low and closes[k] >= freeze_low:
                return {'trigger': 'sweep', 'ts': int(ts_ms[k]), 'sweep_low': lows[k], 'nfh': nfh, 'nfl': nfl}
    else:
        for k in range(len(closes)):
            if closes[k] > freeze_high:
                return {'trigger': 'bos',   'ts': int(ts_ms[k]), 'nfh': nfh, 'nfl': nfl}
            if highs[k] > freeze_high and closes[k] <= freeze_high:
                return {'trigger': 'sweep', 'ts': int(ts_ms[k]), 'sweep_high': highs[k], 'nfh': nfh, 'nfl': nfl}
    return {'trigger': None}


# ============================================================
# BREAKER BLOCK
# ============================================================

def find_breaker_block(df_m5, mss_ts_ms, stype):
    pre_mss = df_m5[df_m5['ts_ms'] < mss_ts_ms].tail(20).reset_index(drop=True)
    if pre_mss.empty:
        return None
    opens  = pre_mss['open'].to_numpy(dtype=float)
    closes = pre_mss['close'].to_numpy(dtype=float)
    highs  = pre_mss['high'].to_numpy(dtype=float)
    lows   = pre_mss['low'].to_numpy(dtype=float)
    for k in range(len(opens)-1, -1, -1):
        if stype == "Long" and closes[k] < opens[k]:
            sz = abs(highs[k] - lows[k])
            return {'entry': highs[k], 'sl': lows[k] - sz * 0.1}
        elif stype == "Short" and closes[k] > opens[k]:
            sz = abs(highs[k] - lows[k])
            return {'entry': lows[k], 'sl': highs[k] + sz * 0.1}
    return None


# ============================================================
# SIMULASI EKSEKUSI TRADE
# ============================================================

def simulate_trade(df_m5, entry_idx, entry, sl, tp, stype, balance,
                   _skip_reasons=None, _extra_out=None, trail_ref_dist=None):
    """
    Simulasi trade dari entry_idx+1 sampai TP/SL kena.
    Return: (pnl_usd, outcome, exit_price, exit_ts)
    _extra_out dict gets: max_float_r, trail_engaged, trail_exit_r
    """
    def _skip(reason):
        if _skip_reasons is not None:
            _skip_reasons[reason] = _skip_reasons.get(reason, 0) + 1
        return 0, 'skip', entry, None

    original_dist = abs(entry - sl)
    if original_dist == 0:
        return _skip('dist0')

    # Minimum SL distance 0.5% — widen untuk keperluan qty/fee, tapi R:R tetap pakai original
    dist = original_dist
    min_dist = entry * MIN_DIST_PCT
    if dist < min_dist:
        dist = min_dist
        if stype == "Long":
            sl = entry - dist
        else:
            sl = entry + dist

    # Validasi TP arah
    if stype == "Long" and tp <= entry:   return _skip('tp_dir')
    if stype == "Short" and tp >= entry:  return _skip('tp_dir')

    # R:R check pakai original_dist (sebelum widen) — supaya 1:2, 1:3 dll tidak di-reject
    tp_dist = abs(tp - entry)
    if tp_dist / original_dist < MIN_RR - 1e-9:  return _skip(f'rr_{tp_dist/original_dist:.2f}')

    risk_usd = balance * RISK_PCT
    qty      = risk_usd / dist            # kontrak (qty in coin)
    notional = qty * entry                # nilai posisi (USD)
    # Fee = taker fee dua arah (entry + exit), berbasis notional
    total_fee = 2 * notional * TAKER_FEE

    # Trail dist — decoupled dari SL dist: bisa pakai full-range dist kalau SL lebih ketat
    _td = trail_ref_dist if (trail_ref_dist is not None and trail_ref_dist > dist) else dist

    # Walk forward candle-by-candle
    future           = df_m5.iloc[entry_idx+1:]
    trail_sl         = sl
    peak             = entry
    max_float        = 0.0    # max favorable price move from entry
    trail_engaged    = False  # trailing SL moved to BE or better
    trail_prev_sl    = trail_sl
    trail_no_move    = 0      # candle counter sejak trail_sl terakhir bergerak
    _TRAIL_TIMEOUT_C  = TRAIL_TIMEOUT_C  # dari konstanta module (default 3 hari)
    outcome          = 'timeout'
    exit_p           = float(future.iloc[-1]['close']) if len(future) else entry
    exit_ts          = future.iloc[-1]['ts'] if len(future) else None

    for _, c in future.iterrows():
        h, l = float(c['high']), float(c['low'])
        if stype == "Long":
            adv = h - entry
            if adv > max_float:
                max_float = adv
            cur_sl = trail_sl if TRAIL_STOP > 0 else sl
            # Cek L vs trail_sl LAMA dulu (konservatif: L sebelum H dalam candle)
            if l <= cur_sl:
                exit_p = cur_sl; exit_ts = c['ts']; outcome = 'sl'; break
            # Baru update peak & trail dari H (untuk candle berikutnya)
            if TRAIL_STOP > 0 and h > peak:
                peak = h
                if peak >= entry + TRAIL_ACT_R * _td:
                    new_tsl  = max(entry, peak - TRAIL_STOP * _td)
                    trail_sl = max(trail_sl, new_tsl)
                    trail_engaged = True
            if h >= tp:
                exit_p = tp;    exit_ts = c['ts']; outcome = 'tp'; break
        else:
            adv = entry - l
            if adv > max_float:
                max_float = adv
            cur_sl = trail_sl if TRAIL_STOP > 0 else sl
            # Cek H vs trail_sl LAMA dulu (konservatif: H sebelum L dalam candle)
            if h >= cur_sl:
                exit_p = cur_sl; exit_ts = c['ts']; outcome = 'sl'; break
            # Baru update peak & trail dari L (untuk candle berikutnya)
            if TRAIL_STOP > 0 and l < peak:
                peak = l
                if peak <= entry - TRAIL_ACT_R * _td:
                    new_tsl  = min(entry, peak + TRAIL_STOP * _td)
                    trail_sl = min(trail_sl, new_tsl)
                    trail_engaged = True
            if l <= tp:
                exit_p = tp;    exit_ts = c['ts']; outcome = 'tp'; break
        # Trail timeout: keluar jika trailing SL tidak bergerak selama 24 jam
        if TRAIL_STOP > 0:
            if trail_sl != trail_prev_sl:
                trail_no_move = 0
                trail_prev_sl = trail_sl
            else:
                trail_no_move += 1
            if trail_no_move >= _TRAIL_TIMEOUT_C:
                exit_p = float(c['close']); exit_ts = c['ts']; outcome = 'timeout'; break

    if stype == "Long":
        pnl = (exit_p - entry) * qty - total_fee
    else:
        pnl = (entry - exit_p) * qty - total_fee

    # Trail exit yang menguntungkan → outcome 'tp' (win), bukan 'sl'
    if TRAIL_STOP > 0 and outcome == 'sl':
        if (stype == "Long" and exit_p > entry) or (stype == "Short" and exit_p < entry):
            outcome = 'tp'

    if _extra_out is not None:
        _extra_out['max_float_r']   = max_float / dist if dist > 0 else 0.0
        _extra_out['trail_engaged'] = trail_engaged
        _extra_out['trail_exit_r']  = ((exit_p - entry) / dist if stype == "Long"
                                       else (entry - exit_p) / dist) if dist > 0 else 0.0

    return pnl, outcome, exit_p, exit_ts


# ============================================================
# BACKTEST PER COIN
# ============================================================

def backtest_coin(symbol, df_m5_full, initial_balance, _fvg_events=None):
    """
    Walk-forward backtest — scan per 12 candle (1 jam H1).
    Optimasi: skip besar saat tidak ada setup, in-trade skip.
    """
    trades = []
    balance = initial_balance
    in_trade_until_idx = -1

    WARMUP_M5 = 2400   # 200 jam warmup
    H1_WINDOW = 100    # 100 jam H1 untuk analisis

    total = len(df_m5_full)
    # Rolling BOS state — tidak ada timeout, hanya CHOCH yang cancel
    active_bos_key = None
    active_gaps    = []
    active_choch   = None
    active_stype   = None
    active_bos_extreme = None  # low/high dari candle BOS (swing baru yang ngebreak)

    # Counters untuk debug gap DIAG vs trade
    c_mss_found  = 0   # MSS terdeteksi di dalam backtest (setelah in-trade skip)
    c_dir_fail   = 0   # SL direction validation gagal
    c_sim_skip   = 0   # simulate_trade return 'skip'
    c_simskip_reasons = {}   # debug: kenapa simulate_trade skip

    i = WARMUP_M5
    while i < total - 50:

        # Skip saat posisi aktif
        if i <= in_trade_until_idx:
            i += 12; continue

        # Bangun H1
        m5_window = df_m5_full.iloc[max(0, i - H1_WINDOW*12): i].reset_index(drop=True)
        df_h1 = build_h1(m5_window)
        if len(df_h1) < 52:
            i += 12; continue

        # Deteksi BOS H1
        sh_h1, sl_h1 = find_last_swing_bos(df_h1)
        if not sh_h1 or not sl_h1:
            i += 12; continue

        closed_h1 = df_h1.iloc[-2]
        curr_h1   = df_h1.iloc[-1]

        # 3-kandidat swing — Short menang jika keduanya fire (sama dengan bott_v4.py)
        is_long = False; is_short = False; swing_val = None; bos_idx = None
        for sh in sh_h1[-3:]:
            if closed_h1['close'] > sh['val']:
                is_long   = True
                swing_val = sh['val']
                bos_idx   = sl_h1[-1]['idx'] if sl_h1 else sh['idx']
        for sl in sl_h1[-3:]:
            if closed_h1['close'] < sl['val']:
                is_short  = True
                swing_val = sl['val']
                bos_idx   = sh_h1[-1]['idx'] if sh_h1 else sl['idx']

        # Jika ada BOS baru → update active state (replace BOS lama)
        if (is_long or is_short) and swing_val is not None:
            stype_new = "Short" if is_short else "Long"
            bos_key   = (stype_new, round(swing_val, 8))

            if bos_key != active_bos_key:
                # CHOCH level untuk BOS baru
                if stype_new == "Long":
                    sl_below  = [s for s in sl_h1 if s['val'] < swing_val]
                    choch_new = sl_below[-1]['val'] if sl_below else None
                else:
                    sh_above  = [s for s in sh_h1 if s['val'] > swing_val]
                    choch_new = sh_above[-1]['val'] if sh_above else None

                # fvg_strong: CHOCH wajib ada
                if ENTRY_MODE == 'fvg_strong' and choch_new is None:
                    i += 12; continue

                # FVG: semua FVG fresh di H1 (tidak perlu dari range BOS tertentu)
                gaps_new = get_internal_gaps(df_h1, stype_new, len(df_h1) - 1)
                if choch_new:
                    if stype_new == "Long":
                        gaps_new = [g for g in gaps_new if g['bottom'] >= choch_new]
                    else:
                        gaps_new = [g for g in gaps_new if g['top'] <= choch_new]
                # fvg_strong/fvg_sbr/fvg_50pct: hanya pakai FVG kuat (C3 vol > avg 20H)
                if ENTRY_MODE == 'fvg_strong':
                    gaps_new = [g for g in gaps_new
                                if g.get('c3_vol', 0) > g.get('vol_max10h', 0) > 0
                                and g.get('c3_open', 0) > 0]
                elif ENTRY_MODE in ('fvg_sbr', 'fvg_limit'):
                    gaps_new = [g for g in gaps_new
                                if g.get('c3_vol', 0) > g.get('vol_max10h', 0) > 0
                                and g.get('c1_close', 0) > 0]
                elif ENTRY_MODE == 'fvg_50pct':
                    gaps_new = [g for g in gaps_new
                                if g.get('c3_vol', 0) > g.get('vol_max10h', 0) > 0]

                active_bos_key     = bos_key
                active_gaps        = gaps_new
                active_choch       = choch_new
                active_stype       = stype_new
                # Swing baru yg dibentuk candle BOS — dipakai sebagai TP di fvg_strong
                active_bos_extreme = float(closed_h1['low']) if stype_new == "Short" else float(closed_h1['high'])

        # Tidak ada setup aktif → lanjut 1 jam
        if not active_gaps:
            i += 12; continue

        # CHOCH check: close terakhir dalam blok H1 ini
        blk_end_m5      = min(i + 12, total)
        blk_close_slice = df_m5_full['close'].iloc[i:blk_end_m5]
        if len(blk_close_slice) > 0:
            blk_c_last = float(blk_close_slice.iloc[-1])
            if active_choch is not None:
                if active_stype == "Long"  and blk_c_last < active_choch:
                    active_bos_key = None; active_gaps = []
                    active_choch   = None; active_stype = None; active_bos_extreme = None
                    i += 12; continue
                if active_stype == "Short" and blk_c_last > active_choch:
                    active_bos_key = None; active_gaps = []
                    active_choch   = None; active_stype = None; active_bos_extreme = None
                    i += 12; continue

        # Hapus FVG yang sudah dilanggar (close menembus body FVG)
        last_c_blk  = float(df_m5_full['close'].iloc[blk_end_m5 - 1]) if blk_end_m5 > i else 0.0
        active_gaps = [
            g for g in active_gaps
            if not (active_stype == "Long"  and last_c_blk < float(g['bottom']))
            and not (active_stype == "Short" and last_c_blk > float(g['top']))
        ]
        if not active_gaps:
            i += 12; continue

        # Scan M5 dalam blok H1 ini untuk FVG touch / OCL fill
        found_fvg_idx = -1
        used_fvg      = None

        if ENTRY_MODE == 'fvg_limit':
            # Limit order: langsung pick FVG pertama saat BOS — tidak tunggu zone touch
            for fvg in active_gaps:
                if float(fvg.get('c1_close', 0)) > 0:
                    found_fvg_idx = i
                    used_fvg = fvg
                    break
        else:
            for fvg in active_gaps:
                fvg_top = float(fvg['top']); fvg_bot = float(fvg['bottom'])
                # fvg_strong: trigger di OCL (C2 close), bukan zona FVG
                if ENTRY_MODE == 'fvg_strong':
                    ocl = float(fvg.get('c3_open', fvg_bot if active_stype == 'Short' else fvg_top))
                    trig_long  = ocl
                    trig_short = ocl
                else:
                    trig_long  = fvg_top
                    trig_short = fvg_bot
                for k in range(i, blk_end_m5):
                    ck = df_m5_full.iloc[k]
                    if active_stype == "Long"  and float(ck['low'])  <= trig_long:
                        found_fvg_idx = k; used_fvg = fvg; break
                    if active_stype == "Short" and float(ck['high']) >= trig_short:
                        found_fvg_idx = k; used_fvg = fvg; break
                if found_fvg_idx >= 0: break

        if found_fvg_idx < 0:
            i += 12; continue

        # LOG event untuk analisis eksternal
        if _fvg_events is not None:
            touch_c = df_m5_full.iloc[found_fvg_idx]
            _fvg_events.append({
                'idx'      : found_fvg_idx,
                'ts'       : touch_c['ts'],
                'stype'    : active_stype,
                'open'     : float(touch_c['open']),
                'high'     : float(touch_c['high']),
                'low'      : float(touch_c['low']),
                'close'    : float(touch_c['close']),
                'fvg_top'  : float(used_fvg['top']),
                'fvg_bot'  : float(used_fvg['bottom']),
                'choch'    : active_choch,
                'bos_level': active_bos_key[1] if active_bos_key else None,
            })

        bos_swing_lvl = active_bos_key[1] if active_bos_key else None    # swing lama yg di-break
        bos_tp_lvl    = active_bos_extreme                               # swing baru (candle BOS extreme)
        stype       = active_stype
        choch_level = active_choch
        active_bos_key = None; active_gaps = []
        active_choch   = None; active_stype = None; active_bos_extreme = None

        # ── Shared entry variables ──
        _entry_idx   = None
        _entry_price = None
        _sl_price        = None
        _final_tp        = None
        _dist            = None
        _trail_ref_dist  = None   # trail dist override — lebih besar dari _dist untuk fvg_limit
        _fvg_d           = None   # FVG height = 1R dari titik 0 (untuk MAE)
        _trigger_str = ENTRY_MODE
        _depth_val   = 0
        _trade_stype = stype   # arah trade aktual — bisa di-flip oleh fvg_touch_rev
        _mss_body_ratio = 0.0; _vol_ratio = 0.0; _atr_ratio = 0.0; _touch_vol_ratio = 0.0

        # ════════════════════════════════════════════════════════
        # OPSI B: Entry langsung di FVG touch
        # ════════════════════════════════════════════════════════
        if ENTRY_MODE in ('fvg_touch', 'fvg_deep', 'fvg_touch_rev'):
            ep = float(df_m5_full.iloc[found_fvg_idx]['close'])
            if stype == "Long":
                sl_nat = float(used_fvg['bottom'])
                d = ep - sl_nat
            else:
                sl_nat = float(used_fvg['top'])
                d = sl_nat - ep
            # fvg_deep: close harus ada di dalam FVG (di bawah midpoint untuk Long)
            fvg_mid = (float(used_fvg['top']) + float(used_fvg['bottom'])) / 2
            if ENTRY_MODE == 'fvg_deep':
                if stype == "Long"  and ep > fvg_mid:
                    c_dir_fail += 1; i += 12; continue
                if stype == "Short" and ep < fvg_mid:
                    c_dir_fail += 1; i += 12; continue
            # fvg_touch_rev: arah trade dibalik (fade FVG touch)
            if ENTRY_MODE == 'fvg_touch_rev':
                _trade_stype = "Short" if stype == "Long" else "Long"
            if d > 0 and d >= ep * MIN_DIST_PCT:
                _entry_idx   = found_fvg_idx
                _entry_price = ep
                _sl_price    = ep - SL_MULT * d if _trade_stype == "Long" else ep + SL_MULT * d
                _final_tp    = ep + TP_MULT * d if _trade_stype == "Long" else ep - TP_MULT * d
                _dist        = SL_MULT * d
                _fvg_d       = d
            else:
                c_dir_fail += 1; i += 12; continue

        # ════════════════════════════════════════════════════════
        # OPSI B2: Entry di candle konfirmasi setelah FVG touch
        # Tunggu 1 candle setelah touch — masuk hanya jika close
        # searah setup (bullish close untuk Long, bearish untuk Short)
        # SL tetap di FVG edge, dist dihitung ulang dari entry baru
        # ════════════════════════════════════════════════════════
        elif ENTRY_MODE == 'fvg_confirm':
            confirm_idx = found_fvg_idx + 1
            if confirm_idx >= total:
                c_dir_fail += 1; i += 12; continue
            touch_close = float(df_m5_full.iloc[found_fvg_idx]['close'])
            conf_close  = float(df_m5_full.iloc[confirm_idx]['close'])
            if stype == "Long":
                sl_nat = float(used_fvg['bottom'])
                if conf_close <= touch_close:          # tidak konfirmasi naik
                    c_dir_fail += 1; i += 12; continue
                d = conf_close - sl_nat
            else:
                sl_nat = float(used_fvg['top'])
                if conf_close >= touch_close:          # tidak konfirmasi turun
                    c_dir_fail += 1; i += 12; continue
                d = sl_nat - conf_close
            if d > 0 and d >= conf_close * MIN_DIST_PCT:
                _entry_idx   = confirm_idx
                _entry_price = conf_close
                _sl_price    = sl_nat
                _final_tp    = conf_close + d * TP_MULT if stype == "Long" else conf_close - d * TP_MULT
                _dist        = d
            else:
                c_dir_fail += 1; i += 12; continue

        # ════════════════════════════════════════════════════════
        # OPSI B3b: fvg_rev_limit — fade FVG touch dengan limit entry
        # Tunggu harga bounce ENTRY_R dari titik 0, lalu entry berlawanan.
        # SL di SL_MULT*R dari titik 0, TP di TP_MULT*R dari titik 0
        # (TP di sisi berlawanan arah trade dari titik 0)
        # ════════════════════════════════════════════════════════
        elif ENTRY_MODE == 'fvg_rev_limit':
            ep = float(df_m5_full.iloc[found_fvg_idx]['close'])
            if stype == "Long":
                d = ep - float(used_fvg['bottom'])
                _trade_stype  = "Short"
                entry_limit   = ep + ENTRY_R  * d   # +8R dari titik 0
                sl_abs        = ep + SL_MULT  * d   # +9.5R dari titik 0
                tp_abs        = ep - TP_MULT  * d   # -8.2R dari titik 0
            else:
                d = float(used_fvg['top']) - ep
                _trade_stype  = "Long"
                entry_limit   = ep - ENTRY_R  * d   # -8R dari titik 0
                sl_abs        = ep - SL_MULT  * d   # -9.5R dari titik 0
                tp_abs        = ep + TP_MULT  * d   # +8.2R dari titik 0

            if d <= 0:
                c_dir_fail += 1; i += 12; continue

            # Scan forward: tunggu price trigger limit entry (max 48 jam)
            limit_idx = None
            scan_end  = min(total - 1, found_fvg_idx + 576)
            for k in range(found_fvg_idx + 1, scan_end + 1):
                ck_h = float(df_m5_full.iloc[k]['high'])
                ck_l = float(df_m5_full.iloc[k]['low'])
                if _trade_stype == "Short" and ck_h >= entry_limit: limit_idx = k; break
                if _trade_stype == "Long"  and ck_l <= entry_limit: limit_idx = k; break

            if limit_idx is None:
                c_dir_fail += 1; i += 12; continue

            dist_risk = abs(sl_abs - entry_limit)
            if dist_risk > 0 and dist_risk >= entry_limit * MIN_DIST_PCT:
                _entry_idx   = limit_idx
                _entry_price = entry_limit
                _sl_price    = sl_abs
                _final_tp    = tp_abs
                _dist        = dist_risk
                _fvg_d       = d
            else:
                c_dir_fail += 1; i += 12; continue

        # ════════════════════════════════════════════════════════
        # OPSI B4: fvg_strong — FVG kuat (C3 volume > avg 20H)
        # Entry limit di batas FVG (fvg_top Long / fvg_bot Short)
        # SL = SL_MULT × gap dari entry, TP = TP_MULT × gap dari entry
        # ════════════════════════════════════════════════════════
        elif ENTRY_MODE == 'fvg_strong':
            # Volume filter sudah di active_gaps (BOS time), tidak perlu cek lagi
            fvg_top  = float(used_fvg['top'])
            fvg_bot  = float(used_fvg['bottom'])
            gap_size = fvg_top - fvg_bot
            if gap_size <= 0:
                c_dir_fail += 1; i += 12; continue

            # Entry di OCL = C3 open (boundary C2-C3, sisi kanan FVG)
            entry_p = float(used_fvg.get('c3_open',
                            fvg_bot if stype == 'Short' else fvg_top))
            if entry_p > 0 and MAX_GAP_PCT > 0 and gap_size / entry_p > MAX_GAP_PCT:
                c_dir_fail += 1; i += 12; continue

            if stype == "Long":
                sl_p = entry_p - SL_MULT * gap_size
                tp_p = entry_p + TP_MULT * gap_size
            else:
                sl_p = entry_p + SL_MULT * gap_size
                tp_p = entry_p - TP_MULT * gap_size

            d = SL_MULT * gap_size
            if d > 0 and d >= entry_p * MIN_DIST_PCT:
                # Touch candle volume check — volume M5 saat harga sentuh OCL
                if 'vol' in df_m5_full.columns:
                    t_vol  = float(df_m5_full.iloc[found_fvg_idx]['vol'])
                    avg_s  = max(0, found_fvg_idx - 20)
                    avg_tv = float(df_m5_full.iloc[avg_s:found_fvg_idx]['vol'].mean()) \
                             if found_fvg_idx > 0 else 0.0
                    _touch_vol_ratio = round(t_vol / avg_tv, 4) if avg_tv > 0 else 0.0
                else:
                    _touch_vol_ratio = 0.0
                if TOUCH_VOL_MIN > 0 and 0 < _touch_vol_ratio < TOUCH_VOL_MIN:
                    c_dir_fail += 1; i += 12; continue

                _entry_idx   = found_fvg_idx
                _entry_price = entry_p
                _sl_price    = sl_p
                _final_tp    = tp_p if TRAIL_STOP == 0 else (
                    entry_p + 3 * d if stype == "Long" else entry_p - 3 * d)
                _dist        = d
                _fvg_d       = gap_size
                # FVG vol strength (C3 at formation) and gap size for analysis
                _c3_vol  = float(used_fvg.get('c3_vol', 0.0))
                _va20h   = float(used_fvg.get('vol_max10h', 1.0))
                _vol_ratio = round(_c3_vol / _va20h, 4) if _va20h > 0 else 0.0
                _atr_ratio = round(gap_size / entry_p, 6) if entry_p > 0 else 0.0
            else:
                c_dir_fail += 1; i += 12; continue

        # ════════════════════════════════════════════════════════
        # OPSI B5: fvg_sbr — SBR/RBS entry di C1.close (demand/supply zone)
        # OCL touch = sinyal; entry limit di C1.close (lebih dalam dari OCL).
        # SL di C1.low (Long) / C1.high (Short) + 10% buffer — natural structure SL.
        # R:R = trail (dist = C1.close ↔ C1.low/high, lebih kecil dari 6.2×gap).
        # ════════════════════════════════════════════════════════
        elif ENTRY_MODE == 'fvg_sbr':
            fvg_top  = float(used_fvg['top'])
            fvg_bot  = float(used_fvg['bottom'])
            gap_size = fvg_top - fvg_bot
            c1_close = float(used_fvg.get('c1_close', fvg_bot))
            c1_low   = float(used_fvg.get('c1_low',   fvg_bot - gap_size * 0.5))
            c1_high  = float(used_fvg.get('c1_high',  fvg_top + gap_size * 0.5))
            if gap_size <= 0 or c1_close <= 0:
                c_dir_fail += 1; i += 12; continue

            if stype == "Long":
                entry_limit = c1_close                      # entry di top of C1 body
                sl_nat      = c1_low - gap_size * 0.1      # SL di bawah C1 wick + 10% buffer
                if entry_limit <= sl_nat:
                    c_dir_fail += 1; i += 12; continue
                d = entry_limit - sl_nat
            else:
                entry_limit = c1_close                      # entry di bottom of C1 body (bearish)
                sl_nat      = c1_high + gap_size * 0.1     # SL di atas C1 wick + 10% buffer
                if sl_nat <= entry_limit:
                    c_dir_fail += 1; i += 12; continue
                d = sl_nat - entry_limit

            if d <= 0 or d < entry_limit * MIN_DIST_PCT:
                c_dir_fail += 1; i += 12; continue

            # Scan forward dari OCL touch — tunggu fill ke C1.close (max 48 jam)
            fill_idx = None
            scan_end = min(total - 1, found_fvg_idx + 576)
            for k in range(found_fvg_idx, scan_end):
                ck = df_m5_full.iloc[k]
                if stype == "Long" and float(ck['low']) <= entry_limit:
                    # FVG broken: close di bawah gap bottom → sinkron live bot
                    if float(ck['close']) < fvg_bot:
                        break
                    fill_idx = k; break
                if stype == "Short" and float(ck['high']) >= entry_limit:
                    # FVG broken: close di atas gap top → sinkron live bot
                    if float(ck['close']) > fvg_top:
                        break
                    fill_idx = k; break
            if fill_idx is None:
                c_dir_fail += 1; i += 12; continue

            # Touch volume filter di fill candle (sinkron dengan live bot SBR_MODE)
            if 'vol' in df_m5_full.columns:
                t_vol   = float(df_m5_full.iloc[fill_idx]['vol'])
                avg_s   = max(0, fill_idx - 20)
                avg_tv  = float(df_m5_full.iloc[avg_s:fill_idx]['vol'].mean()) \
                          if fill_idx > 0 else 0.0
                _touch_vol_ratio = round(t_vol / avg_tv, 4) if avg_tv > 0 else 0.0
            else:
                _touch_vol_ratio = 0.0
            if TOUCH_VOL_MIN > 0 and 0 < _touch_vol_ratio < TOUCH_VOL_MIN:
                c_dir_fail += 1; i += 12; continue

            tp_nat = (entry_limit + 3 * d) if stype == "Long" else (entry_limit - 3 * d)
            _entry_idx   = fill_idx; _entry_price = entry_limit
            _sl_price    = sl_nat
            _final_tp    = tp_nat
            _dist        = d; _fvg_d = gap_size
            _vol_ratio   = round(float(used_fvg.get('c3_vol',0)) /
                                 max(float(used_fvg.get('vol_max10h',1)), 1e-9), 4)
            _atr_ratio   = round(gap_size / entry_limit, 6) if entry_limit > 0 else 0.0

        # ════════════════════════════════════════════════════════
        # OPSI B5b: fvg_limit — limit order langsung saat BOS H1 terdeteksi
        # Entry = C1.close (SBR/RBS zone), SL = C1.low/high + 10% buffer.
        # Perbedaan vs fvg_sbr: tidak ada volume filter, tidak perlu FVG zone
        # touch dulu — order langsung aktif dari titik BOS.
        # CHOCH selama fill wait → cancel (limit dibatalkan).
        # ════════════════════════════════════════════════════════
        elif ENTRY_MODE == 'fvg_limit':
            fvg_top  = float(used_fvg['top'])
            fvg_bot  = float(used_fvg['bottom'])
            gap_size = fvg_top - fvg_bot
            c1_close = float(used_fvg.get('c1_close', fvg_bot))
            c1_low   = float(used_fvg.get('c1_low',   fvg_bot - gap_size * 0.5))
            c1_high  = float(used_fvg.get('c1_high',  fvg_top + gap_size * 0.5))
            if gap_size <= 0 or c1_close <= 0:
                c_dir_fail += 1; i += 12; continue

            # Entry di OCL (c1_close), SL di c1_mid
            c1_mid_v = (c1_high + c1_low) / 2
            if stype == "Long":
                entry_limit = c1_close
                d           = max(c1_close - c1_mid_v, 0.0)
                sl_nat      = c1_close - d
                if d <= 0: c_dir_fail += 1; i += 12; continue
                d_trail     = d
            else:
                entry_limit = c1_close
                d           = max(c1_mid_v - c1_close, 0.0)
                sl_nat      = c1_close + d
                if d <= 0: c_dir_fail += 1; i += 12; continue
                d_trail     = d

            if d <= 0 or d < entry_limit * MIN_DIST_PCT:
                c_dir_fail += 1; i += 12; continue

            # Fase 1: tunggu harga mendekati dalam APPROACH_R dari entry
            approach_thr = APPROACH_R * d
            approach_idx = None
            scan_end     = min(total - 1, i + 576)
            for k in range(i, scan_end):
                ck = df_m5_full.iloc[k]
                if k > i and (k - i) % 12 == 0 and choch_level is not None:
                    ck_c = float(ck['close'])
                    if stype == "Long"  and ck_c < choch_level: break
                    if stype == "Short" and ck_c > choch_level: break
                if stype == "Long"  and float(ck['low'])  <= entry_limit + approach_thr:
                    approach_idx = k; break
                if stype == "Short" and float(ck['high']) >= entry_limit - approach_thr:
                    approach_idx = k; break

            if approach_idx is None:
                c_dir_fail += 1; i += 12; continue

            # Fase 2: dari approach, tunggu fill. Batalkan jika harga keluar range.
            fill_idx = None
            for k in range(approach_idx, scan_end):
                ck = df_m5_full.iloc[k]
                if k > approach_idx and (k - approach_idx) % 12 == 0 and choch_level is not None:
                    ck_c = float(ck['close'])
                    if stype == "Long"  and ck_c < choch_level: break
                    if stype == "Short" and ck_c > choch_level: break
                # Harga mundur keluar approach range → order dibatalkan
                if stype == "Long"  and float(ck['close']) > entry_limit + approach_thr: break
                if stype == "Short" and float(ck['close']) < entry_limit - approach_thr: break
                # Fill
                if stype == "Long"  and float(ck['low'])  <= entry_limit: fill_idx = k; break
                if stype == "Short" and float(ck['high']) >= entry_limit: fill_idx = k; break

            if fill_idx is None:
                c_dir_fail += 1; i += 12; continue

            tp_nat = (entry_limit + 3 * d) if stype == "Long" else (entry_limit - 3 * d)
            _entry_idx        = fill_idx; _entry_price = entry_limit
            _sl_price         = sl_nat
            _final_tp         = tp_nat
            _dist             = d; _fvg_d = gap_size
            _trail_ref_dist   = d_trail
            _vol_ratio        = round(float(used_fvg.get('c3_vol', 0)) /
                                      max(float(used_fvg.get('vol_max10h', 1)), 1e-9), 4)
            _atr_ratio        = round(gap_size / entry_limit, 6) if entry_limit > 0 else 0.0

        # ════════════════════════════════════════════════════════
        # OPSI B6: fvg_50pct — entry limit di 50% tengah FVG gap
        # OCL touch = sinyal; entry limit di midpoint FVG.
        # SL di fvg_bot (Long) / fvg_top (Short) - 10% buffer.
        # dist = 0.6×gap  →  R:R jauh lebih baik dari OCL entry.
        # ════════════════════════════════════════════════════════
        elif ENTRY_MODE == 'fvg_50pct':
            fvg_top  = float(used_fvg['top'])
            fvg_bot  = float(used_fvg['bottom'])
            gap_size = fvg_top - fvg_bot
            if gap_size <= 0:
                c_dir_fail += 1; i += 12; continue

            mid      = (fvg_top + fvg_bot) / 2.0   # entry limit 50%
            buf      = gap_size * 0.1               # 10% gap buffer

            if stype == "Long":
                entry_limit = mid
                sl_nat      = fvg_bot - buf
                d           = entry_limit - sl_nat   # = 0.5*gap + 0.1*gap = 0.6*gap
            else:
                entry_limit = mid
                sl_nat      = fvg_top + buf
                d           = sl_nat - entry_limit   # = 0.5*gap + 0.1*gap = 0.6*gap

            if d <= 0 or d < entry_limit * MIN_DIST_PCT:
                c_dir_fail += 1; i += 12; continue

            # Scan forward dari OCL touch — tunggu fill ke midpoint (max 24 jam)
            fill_idx = None
            scan_end = min(total - 1, found_fvg_idx + 288)
            for k in range(found_fvg_idx, scan_end):
                ck = df_m5_full.iloc[k]
                if stype == "Long"  and float(ck['low'])  <= entry_limit: fill_idx = k; break
                if stype == "Short" and float(ck['high']) >= entry_limit: fill_idx = k; break
            if fill_idx is None:
                c_dir_fail += 1; i += 12; continue

            tp_nat = (entry_limit + 3 * d) if stype == "Long" else (entry_limit - 3 * d)
            _entry_idx   = fill_idx; _entry_price = entry_limit
            _sl_price    = sl_nat
            _final_tp    = tp_nat
            _dist        = d; _fvg_d = gap_size
            _vol_ratio   = round(float(used_fvg.get('c3_vol',0)) /
                                 max(float(used_fvg.get('vol_max10h',1)), 1e-9), 4)
            _atr_ratio   = round(gap_size / entry_limit, 6) if entry_limit > 0 else 0.0

        # ════════════════════════════════════════════════════════
        # OPSI B3: fvg_dip — tunggu harga DIP ke FVG edge dulu
        # sebelum +1R bounce. Entry limit di FVG bottom/top.
        # SL = entry - SL_MULT*sl_dist, TP = ep + TP_MULT*sl_dist
        # ════════════════════════════════════════════════════════
        elif ENTRY_MODE == 'fvg_dip':
            ep = float(df_m5_full.iloc[found_fvg_idx]['close'])   # titik 0
            if stype == "Long":
                sl_dist    = ep - float(used_fvg['bottom'])
                dip_lvl    = float(used_fvg['bottom'])             # -1R dari titik 0
                bounce_lvl = ep + sl_dist                          # +1R dari titik 0
            else:
                sl_dist    = float(used_fvg['top']) - ep
                dip_lvl    = float(used_fvg['top'])                # -1R untuk Short
                bounce_lvl = ep - sl_dist                          # +1R untuk Short

            if sl_dist <= 0 or sl_dist < ep * MIN_DIST_PCT:
                c_dir_fail += 1; i += 12; continue

            # Scan forward: cari dip ke FVG edge sebelum +1R — max 48 jam
            dip_idx    = None
            bounce_idx = None
            scan_end   = min(total - 1, found_fvg_idx + 576)
            for k in range(found_fvg_idx + 1, scan_end + 1):
                ck_h = float(df_m5_full.iloc[k]['high'])
                ck_l = float(df_m5_full.iloc[k]['low'])
                if stype == "Long":
                    if dip_idx    is None and ck_l <= dip_lvl:    dip_idx    = k
                    if bounce_idx is None and ck_h >= bounce_lvl: bounce_idx = k
                else:
                    if dip_idx    is None and ck_h >= dip_lvl:    dip_idx    = k
                    if bounce_idx is None and ck_l <= bounce_lvl: bounce_idx = k
                if dip_idx is not None and bounce_idx is not None:
                    break

            # Skip jika bounce duluan atau tidak ada dip
            if dip_idx is None or (bounce_idx is not None and bounce_idx < dip_idx):
                c_dir_fail += 1; i += 12; continue

            # Entry limit di FVG edge (titik -1R)
            if stype == "Long":
                e_entry = dip_lvl
                e_sl    = dip_lvl - SL_MULT * sl_dist
                e_tp    = ep      + TP_MULT * sl_dist
            else:
                e_entry = dip_lvl
                e_sl    = dip_lvl + SL_MULT * sl_dist
                e_tp    = ep      - TP_MULT * sl_dist

            d = abs(e_entry - e_sl)
            if d > 0 and d >= e_entry * MIN_DIST_PCT:
                _entry_idx   = dip_idx
                _entry_price = e_entry
                _sl_price    = e_sl
                _final_tp    = e_tp
                _dist        = d
            else:
                c_dir_fail += 1; i += 12; continue

        else:
            # ════════════════════════════════════════════════════
            # IDM M5 setelah FVG touch (max 48 jam)
            # ════════════════════════════════════════════════════
            idm_end   = min(total - 1, found_fvg_idx + 12 * 48)
            df_m5_idm = df_m5_full.iloc[found_fvg_idx: idm_end].reset_index(drop=True)
            if len(df_m5_idm) < 5: i += 12; continue

            m5_state = replay_m5(df_m5_idm, stype)
            if m5_state['phase'] != 'IDM_TOUCHED': i += 12 * 24; continue

            freeze_high = m5_state['freeze_high']
            freeze_low  = m5_state['freeze_low']
            freeze_ts   = m5_state['freeze_ts']

            freeze_mask = df_m5_full['ts_ms'] == freeze_ts
            if not freeze_mask.any(): i += 12; continue
            freeze_m5_idx = df_m5_full[freeze_mask].index[0]

            # ════════════════════════════════════════════════════
            # OPSI A: Entry langsung di IDM touch
            # ════════════════════════════════════════════════════
            if ENTRY_MODE == 'idm_touch':
                ep = float(df_m5_full.iloc[freeze_m5_idx]['close'])
                if stype == "Long":
                    sl_nat = freeze_low
                    d = ep - sl_nat
                else:
                    sl_nat = freeze_high
                    d = sl_nat - ep
                if d > 0 and d >= ep * MIN_DIST_PCT:
                    _entry_idx   = freeze_m5_idx
                    _entry_price = ep
                    _sl_price    = sl_nat
                    _final_tp    = ep + d * TP_MULT if stype == "Long" else ep - d * TP_MULT
                    _dist        = d
                else:
                    c_dir_fail += 1; i += 12; continue

            else:
                # ════════════════════════════════════════════════
                # BOS/Sweep M5 → Recursive IDM → MSS
                # ════════════════════════════════════════════════
                bos_end = min(total - 1, freeze_m5_idx + 12 * 12)
                df_bos  = df_m5_full.iloc[freeze_m5_idx: bos_end].reset_index(drop=True)
                result  = check_bos_or_sweep(df_bos, freeze_high, freeze_low, freeze_ts, stype)
                if result['trigger'] is None: i += 12 * 12; continue

                trigger_ts = result['ts']
                trig_mask  = df_m5_full['ts_ms'] == trigger_ts
                if not trig_mask.any(): i += 12; continue
                trigger_m5_idx = df_m5_full[trig_mask].index[0]

                mss_candle = None; mss_m5_idx = -1
                anchor_idx = trigger_m5_idx

                for _depth_val in range(8):
                    idm_in_end  = min(total - 1, anchor_idx + 12 * 48)
                    df_m5_inner = df_m5_full.iloc[anchor_idx:idm_in_end].reset_index(drop=True)
                    if len(df_m5_inner) < 5: break

                    m5_inner = replay_m5(df_m5_inner, stype)
                    if m5_inner['phase'] != 'IDM_TOUCHED': break

                    inner_fh  = m5_inner['freeze_high']
                    inner_fl  = m5_inner['freeze_low']
                    inner_fts = m5_inner['freeze_ts']

                    inner_mask = df_m5_full['ts_ms'] == inner_fts
                    if not inner_mask.any(): break
                    inner_m5_idx = int(df_m5_full[inner_mask].index[0])

                    wait_end = min(total - 1, inner_m5_idx + 12 * 24)
                    df_wait  = df_m5_full.iloc[inner_m5_idx:wait_end]
                    c_arr    = df_wait['close'].to_numpy(float)

                    if stype == "Long":
                        mss_hits = np.where(c_arr > inner_fh)[0]
                        bos_hits = np.where(c_arr < inner_fl)[0]
                    else:
                        mss_hits = np.where(c_arr < inner_fl)[0]
                        bos_hits = np.where(c_arr > inner_fh)[0]

                    first_mss = int(mss_hits[0]) if len(mss_hits) else len(c_arr)
                    first_bos = int(bos_hits[0]) if len(bos_hits) else len(c_arr)

                    if len(mss_hits) and first_mss <= first_bos:
                        mss_candle = df_wait.iloc[first_mss]
                        mss_m5_idx = inner_m5_idx + first_mss
                        break
                    elif len(bos_hits) and first_bos < first_mss:
                        anchor_idx = inner_m5_idx + first_bos
                    else:
                        break

                if mss_candle is None or mss_m5_idx < 0: i += 12 * 6; continue

                # OPSI C: Time filter — MSS harus dalam TIME_FILTER candle dari FVG
                if TIME_FILTER > 0 and mss_m5_idx - found_fvg_idx > TIME_FILTER:
                    c_dir_fail += 1; i += 12; continue

                c_mss_found += 1

                mss_body  = abs(float(mss_candle['close']) - float(mss_candle['open']))
                mss_range = abs(float(mss_candle['high'])  - float(mss_candle['low']))
                _mss_body_ratio = round(mss_body / mss_range, 4) if mss_range > 0 else 0.0

                vol_window = df_m5_full.iloc[max(0, mss_m5_idx - 19): mss_m5_idx + 1]
                avg_vol    = vol_window['vol'].mean()
                _vol_ratio = round(float(mss_candle['vol']) / avg_vol, 4) if avg_vol > 0 else 0.0

                atr_thresh = ATR_THRESHOLD.get(symbol, 0.0035)
                atr_window = df_m5_full.iloc[max(0, mss_m5_idx - 19): mss_m5_idx + 1]
                _atr_ratio = 0.0
                if len(atr_window) >= 5:
                    h_ = atr_window['high']; l_ = atr_window['low']
                    pc_ = atr_window['close'].shift(1)
                    tr_ = pd.concat([h_-l_, (h_-pc_).abs(), (l_-pc_).abs()], axis=1).max(axis=1)
                    atr_val   = tr_.mean()
                    ref_price = float(mss_candle['close'])
                    if atr_thresh > 0 and ref_price > 0:
                        _atr_ratio = round((atr_val / ref_price) / atr_thresh, 3)

                mss_close   = float(mss_candle['close'])
                _trigger_str = result['trigger']

                df_bb = df_m5_full.iloc[max(0, mss_m5_idx - 20): mss_m5_idx + 1].reset_index(drop=True)
                bb    = find_breaker_block(df_bb, int(mss_candle['ts_ms']), stype)
                if bb is None: c_dir_fail += 1; i += 12; continue

                limit_entry = bb['sl'] if ENTRY_MODE == 'bb_sl' else bb['entry']
                dist_ref    = abs(mss_close - limit_entry)
                if dist_ref == 0: i += 12; continue
                if dist_ref < limit_entry * MIN_DIST_PCT: c_dir_fail += 1; i += 12; continue

                if stype == "Long":
                    sl_mss = mss_close - dist_ref * SL_MULT
                    tp_mss = mss_close + dist_ref * TP_MULT
                else:
                    sl_mss = mss_close + dist_ref * SL_MULT
                    tp_mss = mss_close - dist_ref * TP_MULT

                if ENTRY_MODE == 'market':
                    _entry_idx = mss_m5_idx; _entry_price = mss_close
                elif ENTRY_MODE == 'bb_entry_imm':
                    _entry_idx = mss_m5_idx; _entry_price = limit_entry
                else:
                    FILL_TIMEOUT = 60; fill_idx = None
                    for j in range(mss_m5_idx + 1, min(mss_m5_idx + 1 + FILL_TIMEOUT, len(df_m5_full))):
                        cj = df_m5_full.iloc[j]
                        if stype == "Long":
                            if float(cj['high']) >= tp_mss: break
                            if float(cj['low'])  <= limit_entry: fill_idx = j; break
                        else:
                            if float(cj['low'])  <= tp_mss: break
                            if float(cj['high']) >= limit_entry: fill_idx = j; break
                    if fill_idx is None: c_dir_fail += 1; i += 12; continue
                    _entry_idx = fill_idx; _entry_price = limit_entry

                _sl_price = sl_mss; _final_tp = tp_mss; _dist = dist_ref

        # ════════════════════════════════════════════════════════
        # Eksekusi trade (semua mode)
        # ════════════════════════════════════════════════════════
        if _entry_idx is None: i += 12; continue

        _extra = {}
        pnl, outcome, exit_p, exit_ts = simulate_trade(
            df_m5_full, _entry_idx, _entry_price, _sl_price, _final_tp, _trade_stype, balance,
            _skip_reasons=c_simskip_reasons, _extra_out=_extra,
            trail_ref_dist=_trail_ref_dist
        )
        if outcome == 'skip':
            c_sim_skip += 1; i = _entry_idx + 1; continue

        balance += pnl

        if exit_ts is not None:
            exit_rows = df_m5_full[df_m5_full['ts'] == exit_ts].index
            in_trade_until_idx = int(exit_rows[0]) if len(exit_rows) else _entry_idx + 300
        else:
            in_trade_until_idx = _entry_idx + 300

        # SL→TP DIAG + CHOCH + MAE + MFE untuk semua losing trade
        sl_then_tp = False; sl_choch = False; mae_r = 0.0; mfe_r = 0.0
        mae_unit = _fvg_d if _fvg_d else _dist   # 1R = FVG height dari titik 0
        if outcome == 'sl' and _dist and _dist > 0:
            scan_end = min(in_trade_until_idx + 1 + 500, len(df_m5_full))
            tp_hit_idx = None
            for k in range(in_trade_until_idx + 1, scan_end):
                ck = df_m5_full.iloc[k]
                if _trade_stype == "Long":
                    if float(ck['high']) >= _final_tp: sl_then_tp = True; tp_hit_idx = k; break
                else:
                    if float(ck['low'])  <= _final_tp: sl_then_tp = True; tp_hit_idx = k; break
            if sl_then_tp and tp_hit_idx is not None:
                win = df_m5_full.iloc[_entry_idx : tp_hit_idx + 1]
                if _trade_stype == "Long":
                    mae_r = (_entry_price - float(win['low'].min()))  / mae_unit
                else:
                    mae_r = (float(win['high'].max()) - _entry_price) / mae_unit

            # CHOCH post-SL: struktur beneran balik (hanya jika TIDAK sl_then_tp)
            if not sl_then_tp and choch_level is not None:
                for k in range(in_trade_until_idx + 1, scan_end):
                    ck = df_m5_full.iloc[k]
                    # Long SL → CHOCH jika close di bawah choch_level (bearish confirmed)
                    if _trade_stype == "Long"  and float(ck['close']) < choch_level:
                        sl_choch = True; break
                    # Short SL → CHOCH jika close di atas choch_level (bullish confirmed)
                    if _trade_stype == "Short" and float(ck['close']) > choch_level:
                        sl_choch = True; break

        # MFE: seberapa jauh harga bergerak ke arah TP dari entry (dalam R titik 0)
        if outcome in ('sl', 'timeout') and mae_unit and mae_unit > 0:
            scan_window = df_m5_full.iloc[_entry_idx : in_trade_until_idx + 1]
            if len(scan_window):
                if _trade_stype == "Long":
                    mfe_r = (float(scan_window['high'].max()) - _entry_price) / mae_unit
                else:
                    mfe_r = (_entry_price - float(scan_window['low'].min()))  / mae_unit
                mfe_r = max(mfe_r, 0.0)

        trades.append({
            'symbol'         : symbol,
            'type'           : _trade_stype,
            'setup_type'     : stype,
            'entry_ts'       : df_m5_full.iloc[_entry_idx]['ts'],
            'exit_ts'        : exit_ts,
            'entry'          : round(_entry_price, 8),
            'sl'             : round(_sl_price, 8),
            'tp'             : round(_final_tp, 8),
            'exit_price'     : round(exit_p, 8),
            'outcome'        : outcome,
            'pnl_usd'        : round(pnl, 4),
            'balance'        : round(balance, 4),
            'trigger'        : _trigger_str,
            'idm_depth'      : _depth_val,
            'mss_body_ratio' : _mss_body_ratio,
            'vol_ratio'      : _vol_ratio,
            'atr_ratio'      : _atr_ratio,
            'touch_vol_ratio': _touch_vol_ratio,
            'sl_dist_pct'    : round(_dist / _entry_price, 6) if _entry_price > 0 else 0.0,
            'sl_then_tp'     : sl_then_tp,
            'sl_choch'       : sl_choch,
            'mae_r'          : round(mae_r, 2),
            'mfe_r'          : round(mfe_r, 2),
            'is_reverse'     : False,
        })

        # ════════════════════════════════════════════════════════
        # Reverse posisi saat SL kena — max 2 kali (fvg_strong + trailing stop)
        # Long → SL → Short (rev1) → SL → Long (rev2)
        # Kondisi: immediate SL (no float) ATAU trailing SL di BE+
        # ════════════════════════════════════════════════════════
        if TRAIL_STOP > 0 and ENTRY_MODE in ('fvg_strong', 'fvg_sbr', 'fvg_50pct', 'fvg_limit'):
            _r_outcome  = outcome
            _r_extra    = _extra
            _r_exit_p   = exit_p
            _r_dist     = _dist
            _r_type     = _trade_stype
            _r_until    = in_trade_until_idx

            for _rev_n in range(2):
                _imm_sl    = _r_outcome == 'sl' and _r_extra.get('max_float_r', 1.0) < 0.1
                _trail_hit = _r_extra.get('trail_engaged', False)
                if not (_imm_sl or _trail_hit):
                    break

                _rev_type     = "Short" if _r_type == "Long" else "Long"
                _rev_entry    = _r_exit_p
                _rev_dist     = _r_dist
                _rev_open_idx = _r_until
                _rev_open_ts  = df_m5_full.iloc[_rev_open_idx]['ts'] \
                                if _rev_open_idx < total else None
                if _rev_type == "Long":
                    _rev_sl = _rev_entry - _rev_dist
                    _rev_tp = _rev_entry + 1000 * _rev_dist
                else:
                    _rev_sl = _rev_entry + _rev_dist
                    _rev_tp = _rev_entry - 1000 * _rev_dist

                _rev_extra = {}
                rev_pnl, rev_outcome, rev_exit_p, rev_exit_ts = simulate_trade(
                    df_m5_full, _rev_open_idx, _rev_entry, _rev_sl, _rev_tp,
                    _rev_type, balance, _skip_reasons=c_simskip_reasons, _extra_out=_rev_extra
                )
                if rev_outcome == 'skip':
                    break

                balance += rev_pnl
                if rev_exit_ts is not None:
                    rev_rows = df_m5_full[df_m5_full['ts'] == rev_exit_ts].index
                    in_trade_until_idx = int(rev_rows[0]) if len(rev_rows) \
                                         else _rev_open_idx + 300
                else:
                    in_trade_until_idx = _rev_open_idx + 300

                _rev_reason = f"rev{_rev_n+1}_{'imm' if _imm_sl else 'trail'}"
                trades.append({
                    'symbol'         : symbol,
                    'type'           : _rev_type,
                    'setup_type'     : f'Reverse{_rev_n+1}',
                    'entry_ts'       : _rev_open_ts,
                    'exit_ts'        : rev_exit_ts,
                    'entry'          : round(_rev_entry, 8),
                    'sl'             : round(_rev_sl, 8),
                    'tp'             : round(_rev_tp, 8),
                    'exit_price'     : round(rev_exit_p, 8),
                    'outcome'        : rev_outcome,
                    'pnl_usd'        : round(rev_pnl, 4),
                    'balance'        : round(balance, 4),
                    'trigger'        : _rev_reason,
                    'idm_depth'      : 0,
                    'mss_body_ratio' : 0.0,
                    'vol_ratio'      : _vol_ratio,
                    'atr_ratio'      : _atr_ratio,
                    'touch_vol_ratio': _touch_vol_ratio,
                    'sl_dist_pct'    : round(_rev_dist / _rev_entry, 6) if _rev_entry > 0 else 0.0,
                    'sl_then_tp'     : False,
                    'sl_choch'       : False,
                    'mae_r'          : 0.0,
                    'mfe_r'          : 0.0,
                    'is_reverse'     : True,
                })

                # siapkan iterasi berikutnya
                _r_outcome = rev_outcome
                _r_extra   = _rev_extra
                _r_exit_p  = rev_exit_p
                _r_type    = _rev_type
                _r_until   = in_trade_until_idx

        i = in_trade_until_idx + 1

    c_traded    = len(trades)
    c_intrade   = c_mss_found - c_dir_fail - c_sim_skip - c_traded
    return trades, balance, {
        'mss_found'       : c_mss_found,
        'traded'          : c_traded,
        'dir_fail'        : c_dir_fail,
        'sim_skip'        : c_sim_skip,
        'intrade'         : max(0, c_intrade),
        'simskip_reasons' : c_simskip_reasons,
    }


# ============================================================
# CONCURRENT MULTI-COIN BACKTEST
# ============================================================

def _diag_month(monthly_diag: dict, ts_s, key: str, n: int = 1) -> None:
    """Tambah n ke monthly_diag[(year,month)][key] berdasarkan unix-seconds ts."""
    dt = pd.Timestamp(ts_s, unit='s')
    k  = (dt.year, dt.month)
    if k not in monthly_diag:
        monthly_diag[k] = {'setup': 0, 'choch': 0, 'slot_ok': 0, 'slot_blocked': 0}
    monthly_diag[k][key] += n


def _bt_conc_detect_bos(state: dict, active_slots: set,
                         ts_ms: int = 0, monthly_diag: dict = None) -> None:
    """
    Deteksi setup dari rolling H1.
    REQUIRE_BOS=True : BOS H1 → FVG kuat (mode default/live).
    REQUIRE_BOS=False: FVG kuat saja tanpa BOS (mode eksperimen backtest).
    """
    h1_completed = state['h1_completed']
    if len(h1_completed) < 20:
        return

    h1_df = pd.DataFrame(h1_completed)

    # ── Pilih mode deteksi ────────────────────────────────────────────────────
    if REQUIRE_BOS:
        # --- BOS-based detection (default) ---
        sh_h1, sl_h1 = find_last_swing_bos(h1_df)
        if not sh_h1 or not sl_h1:
            return

        closed_h1 = h1_df.iloc[-2]
        is_long = False; is_short = False
        swing_val = None

        for sh in sh_h1[-3:]:
            if closed_h1['close'] > sh['val']:
                is_long = True; swing_val = sh['val']
        for sl in sl_h1[-3:]:
            if closed_h1['close'] < sl['val']:
                is_short = True; swing_val = sl['val']

        if not (is_long or is_short) or swing_val is None:
            return

        stype   = "Short" if is_short else "Long"
        bos_key = (stype, round(swing_val, 8))

        existing = state['pending']
        if existing and existing.get('bos_key') == bos_key:
            return

        # CHOCH level
        if stype == 'Long':
            sl_below    = [s for s in sl_h1 if s['val'] < swing_val]
            choch_level = sl_below[-1]['val'] if sl_below else None
        else:
            sh_above    = [s for s in sh_h1 if s['val'] > swing_val]
            choch_level = sh_above[-1]['val'] if sh_above else None

        if choch_level is not None:
            if stype == 'Long'  and closed_h1['close'] < choch_level: return
            if stype == 'Short' and closed_h1['close'] > choch_level: return

        # FVG kuat
        gaps = get_internal_gaps(h1_df, stype, len(h1_df) - 1)
        gaps = [g for g in gaps
                if g.get('c3_vol', 0) > g.get('vol_max10h', 0) > 0
                and g.get('c1_close', 0) > 0]
        if choch_level is not None:
            if stype == 'Long':
                gaps = [g for g in gaps if g['bottom'] >= choch_level]
            else:
                gaps = [g for g in gaps if g['top'] <= choch_level]
        if not gaps:
            return

        chosen = None
        for g in gaps:
            c1_c_g = float(g.get('c1_close', 0))
            c1_l_g = float(g.get('c1_low',   0))
            c1_h_g = float(g.get('c1_high',  0))
            if c1_c_g <= 0 or c1_h_g <= c1_l_g: continue
            c1_mid_g = (c1_h_g + c1_l_g) / 2.0
            if stype == 'Long'  and c1_c_g <= c1_mid_g: continue
            if stype == 'Short' and c1_c_g >= c1_mid_g: continue
            chosen = g; break
        if not chosen:
            return

    else:
        # --- FVG-only detection (eksperimen, tanpa BOS) ---
        existing  = state['pending']
        chosen    = None; stype = None; choch_level = None
        best_c3i  = -1

        for s in ['Long', 'Short']:
            all_gaps = get_internal_gaps(h1_df, s, len(h1_df) - 1)
            strong   = [g for g in all_gaps
                        if g.get('c3_vol', 0) > g.get('vol_max10h', 0) > 0
                        and g.get('c1_close', 0) > 0]
            for g in reversed(strong):  # paling recent dulu
                c1_c_g = float(g.get('c1_close', 0))
                c1_l_g = float(g.get('c1_low',   0))
                c1_h_g = float(g.get('c1_high',  0))
                if c1_c_g <= 0 or c1_h_g <= c1_l_g: continue
                c1_mid_g = (c1_h_g + c1_l_g) / 2.0
                if s == 'Long'  and c1_c_g <= c1_mid_g: continue
                if s == 'Short' and c1_c_g >= c1_mid_g: continue
                gap_sz = float(g['top']) - float(g['bottom'])
                if c1_c_g > 0 and MAX_GAP_PCT > 0 and gap_sz / c1_c_g > MAX_GAP_PCT: continue
                c3i = g.get('c3_idx', 0)
                if c3i > best_c3i:
                    best_c3i = c3i; chosen = g; stype = s
                break

        if not chosen or stype is None:
            return

        swing_val = float(chosen['c1_close'])
        bos_key   = ('fvg_only', round(swing_val, 8))
        if existing and existing.get('bos_key') == bos_key:
            return

    # ── Bagian bersama: hitung entry/SL dari chosen FVG ──────────────────────
    c1_c = float(chosen['c1_close'])
    c1_l = float(chosen['c1_low'])
    c1_h = float(chosen['c1_high'])

    # SL di c1_mid
    c1_mid_v = (c1_h + c1_l) / 2
    if stype == 'Long':
        dist = max(c1_c - c1_mid_v, 0.0)
    else:
        dist = max(c1_mid_v - c1_c, 0.0)
    d_trail    = dist
    sl_pending = c1_c - dist if stype == 'Long' else c1_c + dist

    if dist < c1_c * MIN_DIST_PCT:
        return

    # OCL flip check: key sama + OCL sama → entry dibalik
    done      = state['done_bos']
    stype_eff = stype
    choch_eff = choch_level
    if done is not None and done.get('bos_key') == bos_key:
        used_ocl = done.get('used_ocl', 0)
        if used_ocl > 0 and c1_c > 0 and abs(c1_c - used_ocl) / c1_c < 0.001:
            stype_eff  = 'Short' if stype == 'Long' else 'Long'
            sl_pending = c1_c + dist if stype_eff == 'Short' else c1_c - dist
            choch_eff  = None

    existing = state['pending']
    if existing and existing.get('phase') == 'WAIT_FILL':
        active_slots.discard(state['sym'])

    if monthly_diag is not None and ts_ms:
        _diag_month(monthly_diag, ts_ms, 'setup')

    state['pending'] = {
        'bos_key'     : bos_key,
        'phase'       : 'WAIT_APPROACH',
        'entry'       : c1_c,           # OCL = entry limit
        'ocl'         : c1_c,
        'sl'          : sl_pending,     # 76% range c1 dari OCL
        'dist'        : dist,
        'd_trail'     : d_trail,
        'stype'       : stype_eff,
        'choch_level' : choch_eff,
        'swing_val'   : swing_val,
    }


def _bt_conc_update_trade(trade: dict, h: float, l: float, c: float,
                           ts, balance: float):
    """
    Update active trade untuk satu M5 candle.
    Returns (outcome, exit_p, exit_ts, pnl_usd) jika trade close, else None.
    """
    _TRAIL_TIMEOUT_C = TRAIL_TIMEOUT_C  # dari konstanta module (default 3 hari)

    stype    = trade['stype']
    entry    = trade['entry']
    dist     = trade['dist']
    d_trail  = trade['d_trail']
    trail_sl = trade['trail_sl']
    peak     = trade['peak']
    sl_orig  = trade['sl_orig']
    tp       = trade['tp']
    risk_usd = balance * RISK_PCT
    # fee = 2×taker (open+close) — diambil dari entry time agar tetap saat balance berubah
    fee      = trade.get('fee_usd', 2 * TAKER_FEE * entry * risk_usd / dist if dist > 0 else 0.0)

    if TRAIL_STOP > 0:
        if stype == 'Long':
            # Cek LOW vs trail_sl LAMA dulu (konservatif: L sebelum H dalam candle)
            if l <= trail_sl:
                r = (trail_sl - entry) / dist
                return ('tp' if trail_sl > entry else 'sl'), trail_sl, ts, r * risk_usd - fee
            # Baru update peak & trail dari HIGH (untuk candle berikutnya)
            if h > peak:
                peak = h; trade['peak'] = peak
                if peak >= entry + TRAIL_ACT_R * dist:
                    new_tsl = max(entry, peak - TRAIL_STOP * d_trail)
                    if new_tsl > trail_sl:
                        trail_sl = new_tsl; trade['trail_sl'] = trail_sl
            if h >= tp:
                r = (tp - entry) / dist
                return 'tp', tp, ts, r * risk_usd - fee
        else:  # Short
            # Cek HIGH vs trail_sl LAMA dulu (konservatif: H sebelum L dalam candle)
            if h >= trail_sl:
                r = (entry - trail_sl) / dist
                return ('tp' if trail_sl < entry else 'sl'), trail_sl, ts, r * risk_usd - fee
            # Baru update peak & trail dari LOW (untuk candle berikutnya)
            if l < peak:
                peak = l; trade['peak'] = peak
                if peak <= entry - TRAIL_ACT_R * dist:
                    new_tsl = min(entry, peak + TRAIL_STOP * d_trail)
                    if new_tsl < trail_sl:
                        trail_sl = new_tsl; trade['trail_sl'] = trail_sl
            if l <= tp:
                r = (entry - tp) / dist
                return 'tp', tp, ts, r * risk_usd - fee
    else:
        if stype == 'Long':
            if l <= sl_orig: return 'sl', sl_orig, ts, -risk_usd - fee
            if h >= tp:
                r = (tp - entry) / dist
                return 'tp', tp, ts, r * risk_usd - fee
        else:
            if h >= sl_orig: return 'sl', sl_orig, ts, -risk_usd - fee
            if l <= tp:
                r = (entry - tp) / dist
                return 'tp', tp, ts, r * risk_usd - fee

    # Trail timeout
    if TRAIL_STOP > 0:
        if trade['trail_sl'] != trade.get('trail_prev_sl', sl_orig):
            trade['trail_no_move'] = 0
            trade['trail_prev_sl'] = trade['trail_sl']
        else:
            trade['trail_no_move'] = trade.get('trail_no_move', 0) + 1
        if trade['trail_no_move'] >= _TRAIL_TIMEOUT_C:
            r = (c - entry) / dist if stype == 'Long' else (entry - c) / dist
            return 'timeout', c, ts, r * risk_usd - fee

    return None


def backtest_concurrent(coins_data: dict,
                         initial_balance: float = INITIAL_BALANCE,
                         max_concurrent: int = MAX_CONCURRENT) -> tuple:
    """
    Event-driven multi-coin backtest: semua coin diproses bersamaan dalam urutan
    timestamp. Shared balance (1% risk dari balance saat itu) dan slot limit
    (maks max_concurrent posisi + WAIT_FILL order sekaligus).

    coins_data: {symbol: df_m5}   — df sudah di-filter rentang waktu
    Returns: (all_trades, final_balance, monthly_diag)
    """
    import heapq

    WARMUP = 2400    # 200 jam warmup per coin (identik backtest_coin)
    H1_WIN = 100     # 100 H1 dalam rolling window

    balance      = initial_balance
    all_trades   = []
    active_slots = set()    # symbols yang sedang WAIT_FILL atau active trade
    monthly_diag = {}       # {(yr,mo): {setup, choch, slot_ok, slot_blocked}}

    # ── Init per-coin state ───────────────────────────────────────────────
    states = {}
    heap   = []

    for sym, df in coins_data.items():
        df = df.reset_index(drop=True)
        total = len(df)
        if total < WARMUP + 12:
            continue

        # Pre-build H1 dari warmup (untuk BOS detection setelah WARMUP)
        h1_pre = []
        for k in range(0, WARMUP - (WARMUP % 12), 12):
            sl = df.iloc[k: k + 12]
            if len(sl) < 12:
                continue
            h1_pre.append({
                'ts'   : sl['ts'].iloc[0],
                'ts_ms': int(sl['ts_ms'].iloc[0]),
                'open' : float(sl['open'].iloc[0]),
                'high' : float(sl['high'].max()),
                'low'  : float(sl['low'].min()),
                'close': float(sl['close'].iloc[-1]),
                'vol'  : float(sl['vol'].sum()) if 'vol' in sl.columns else 0.0,
            })
        if len(h1_pre) > H1_WIN:
            h1_pre = h1_pre[-H1_WIN:]

        states[sym] = {
            'sym'          : sym,
            'df'           : df,
            'total'        : total,
            'h1_m5_buf'    : [],        # M5 accumulating current H1
            'h1_completed' : h1_pre,    # rolling list of completed H1 candles
            'pending'      : None,      # WAIT_APPROACH atau WAIT_FILL setup
            'trade'        : None,      # active trade dict
            'done_bos'     : None,      # (stype, swing_val) terakhir ditrade
        }
        heapq.heappush(heap, (int(df['ts_ms'].iloc[WARMUP]), WARMUP, sym))

    # ── Main event loop ───────────────────────────────────────────────────
    while heap:
        ts_ms_ev, idx, sym = heapq.heappop(heap)
        state = states[sym]
        row   = state['df'].iloc[idx]

        h_p = float(row['high'])
        l_p = float(row['low'])
        c_p = float(row['close'])
        o_p = float(row['open'])
        ts  = row['ts']
        v_p = float(row['vol']) if 'vol' in row.index else 0.0

        # ── 1. Active trade update ────────────────────────────────────────
        if state['trade'] is not None:
            trade  = state['trade']
            result = _bt_conc_update_trade(trade, h_p, l_p, c_p, ts, balance)
            if result is not None:
                outcome, exit_p, exit_ts, pnl_usd = result
                balance = max(0.0, balance + pnl_usd)
                entry   = trade['entry']
                stype   = trade['stype']
                rev_count = trade.get('rev_count', 0)
                all_trades.append({
                    'symbol'    : sym,
                    'type'      : stype,
                    'entry_ts'  : trade['entry_ts'],
                    'exit_ts'   : exit_ts,
                    'entry'     : round(entry, 8),
                    'sl'        : round(trade['sl_orig'], 8),
                    'tp'        : round(trade['tp'], 8),
                    'exit_price': round(exit_p, 8),
                    'outcome'   : outcome,
                    'pnl_usd'   : round(pnl_usd, 4),
                    'fee_usd'   : round(trade.get('fee_usd', 0.0), 6),
                    'balance'   : round(balance, 4),
                    'dist'      : trade['dist'],
                    'slot_skip' : False,
                    'rev_count' : rev_count,
                })
                if outcome == 'sl' and rev_count < 2:
                    # Buka reverse trade — slot tetap aktif
                    rev_stype  = 'Short' if stype == 'Long' else 'Long'
                    rev_entry  = exit_p
                    rev_dist   = trade['dist']
                    rev_sl     = rev_entry + rev_dist if rev_stype == 'Short' else rev_entry - rev_dist
                    rev_tp     = rev_entry - 3 * rev_dist if rev_stype == 'Short' else rev_entry + 3 * rev_dist
                    _rev_fee   = 2 * TAKER_FEE * rev_entry * (balance * RISK_PCT) / rev_dist if rev_dist > 0 else 0.0
                    state['trade'] = {
                        'entry'         : rev_entry,
                        'sl_orig'       : rev_sl,
                        'trail_sl'      : rev_sl,
                        'peak'          : rev_entry,
                        'tp'            : rev_tp,
                        'dist'          : rev_dist,
                        'd_trail'       : rev_dist,
                        'stype'         : rev_stype,
                        'entry_ts'      : ts,
                        'done_key'      : trade.get('done_key'),
                        'trail_no_move' : 0,
                        'trail_prev_sl' : rev_sl,
                        'rev_count'     : rev_count + 1,
                        'orig_ocl'      : trade.get('orig_ocl', trade['entry']),
                        'fee_usd'       : _rev_fee,
                    }
                    # Slot tetap di active_slots (tidak discard)
                else:
                    active_slots.discard(sym)
                    state['done_bos'] = {
                        'bos_key' : trade.get('done_key'),
                        'used_ocl': trade.get('orig_ocl', trade['entry']),
                    }
                    state['trade'] = None

        # ── 2. Pending setup handling ─────────────────────────────────────
        elif state['pending'] is not None:
            pending = state['pending']
            stype   = pending['stype']
            choch   = pending.get('choch_level')
            entry   = pending['entry']
            dist    = pending['dist']

            # CHOCH check setiap M5
            choch_hit = (choch is not None and (
                (stype == 'Long'  and c_p < choch) or
                (stype == 'Short' and c_p > choch)
            ))
            if choch_hit:
                active_slots.discard(sym)
                state['pending']  = None
                state['done_bos'] = None   # structure reset → BOS baru bisa detect
                _diag_month(monthly_diag, ts_ms_ev, 'choch')

            elif pending['phase'] == 'WAIT_APPROACH':
                thr = APPROACH_R * dist
                if (stype == 'Long'  and l_p <= entry + thr) or \
                   (stype == 'Short' and h_p >= entry - thr):
                    if len(active_slots) < max_concurrent:
                        pending['phase'] = 'WAIT_FILL'
                        active_slots.add(sym)
                        if not pending.get('_slot_ok_counted'):
                            pending['_slot_ok_counted'] = True
                            _diag_month(monthly_diag, ts_ms_ev, 'slot_ok')
                    else:
                        if not pending.get('_slot_blocked_counted'):
                            pending['_slot_blocked_counted'] = True
                            _diag_month(monthly_diag, ts_ms_ev, 'slot_blocked')

            elif pending['phase'] == 'WAIT_FILL':
                thr = APPROACH_R * dist
                # Harga mundur → cancel, kembali WAIT_APPROACH
                if (stype == 'Long'  and c_p > entry + thr) or \
                   (stype == 'Short' and c_p < entry - thr):
                    pending['phase'] = 'WAIT_APPROACH'
                    active_slots.discard(sym)
                # Fill check
                elif (stype == 'Long'  and l_p <= entry) or \
                     (stype == 'Short' and h_p >= entry):
                    d       = dist
                    d_trail = pending.get('d_trail', dist)
                    sl_nat  = pending['sl']
                    tp_nat  = entry + 3 * d if stype == 'Long' else entry - 3 * d
                    _fee    = 2 * TAKER_FEE * entry * (balance * RISK_PCT) / d if d > 0 else 0.0
                    state['trade'] = {
                        'entry'         : entry,
                        'sl_orig'       : sl_nat,
                        'trail_sl'      : sl_nat,
                        'peak'          : entry,
                        'tp'            : tp_nat,
                        'dist'          : d,
                        'd_trail'       : d_trail,
                        'stype'         : stype,
                        'entry_ts'      : ts,
                        'done_key'      : pending['bos_key'],
                        'trail_no_move' : 0,
                        'trail_prev_sl' : sl_nat,
                        'orig_ocl'      : pending.get('ocl', entry),  # OCL asli (c1_close) bukan adjusted entry
                        'fee_usd'       : _fee,
                    }
                    state['done_bos'] = pending['bos_key']
                    state['pending']  = None
                    # slot tetap aktif (akan di-discard saat trade close)

            # Selalu akumulasi H1 saat pending (untuk data fresh post-CHOCH)
            state['h1_m5_buf'].append({
                'ts': ts, 'ts_ms': int(ts_ms_ev),
                'open': o_p, 'high': h_p, 'low': l_p, 'close': c_p, 'vol': v_p,
            })
            if len(state['h1_m5_buf']) >= 12:
                h1c = {
                    'ts'   : state['h1_m5_buf'][0]['ts'],
                    'ts_ms': state['h1_m5_buf'][0]['ts_ms'],
                    'open' : state['h1_m5_buf'][0]['open'],
                    'high' : max(c['high'] for c in state['h1_m5_buf']),
                    'low'  : min(c['low']  for c in state['h1_m5_buf']),
                    'close': state['h1_m5_buf'][-1]['close'],
                    'vol'  : sum(c['vol']  for c in state['h1_m5_buf']),
                }
                state['h1_completed'].append(h1c)
                state['h1_m5_buf'] = []
                if len(state['h1_completed']) > H1_WIN:
                    state['h1_completed'] = state['h1_completed'][-H1_WIN:]

        # ── 3. Idle: akumulasi H1 + BOS detection ────────────────────────
        else:
            state['h1_m5_buf'].append({
                'ts': ts, 'ts_ms': int(ts_ms_ev),
                'open': o_p, 'high': h_p, 'low': l_p, 'close': c_p, 'vol': v_p,
            })
            if len(state['h1_m5_buf']) >= 12:
                h1c = {
                    'ts'   : state['h1_m5_buf'][0]['ts'],
                    'ts_ms': state['h1_m5_buf'][0]['ts_ms'],
                    'open' : state['h1_m5_buf'][0]['open'],
                    'high' : max(c['high'] for c in state['h1_m5_buf']),
                    'low'  : min(c['low']  for c in state['h1_m5_buf']),
                    'close': state['h1_m5_buf'][-1]['close'],
                    'vol'  : sum(c['vol']  for c in state['h1_m5_buf']),
                }
                state['h1_completed'].append(h1c)
                state['h1_m5_buf'] = []
                if len(state['h1_completed']) > H1_WIN:
                    state['h1_completed'] = state['h1_completed'][-H1_WIN:]
                if len(state['h1_completed']) >= 20:
                    _bt_conc_detect_bos(state, active_slots, ts_ms_ev, monthly_diag)

        # ── Push candle berikutnya untuk coin ini ──────────────────────
        nxt = idx + 1
        if nxt < state['total']:
            heapq.heappush(heap, (int(state['df']['ts_ms'].iloc[nxt]), nxt, sym))

    return all_trades, balance, monthly_diag


# ============================================================
# MAIN — jalankan semua coin
# ============================================================

def main():
    print("=" * 60)
    print("  BACKTEST SMC Bot v4 — Modal $30 | Risk 1%/trade | TP=3R | FULL YEAR 2025")
    print("=" * 60)

    all_trades = []
    coin_results = []

    for symbol, fname in FILES.items():
        print(f"\n▶ {symbol} ...")
        try:
            df_m5 = load_m5(symbol, fname)
            if len(df_m5) < 3000:
                print(f"   ⚠ Data terlalu sedikit ({len(df_m5)} candle), skip.")
                continue

            date_from = df_m5['ts'].iloc[0].strftime('%Y-%m-%d')
            date_to   = df_m5['ts'].iloc[-1].strftime('%Y-%m-%d')
            print(f"   Data: {len(df_m5)} candle M5 | {date_from} → {date_to}")

            trades, final_bal, dbg = backtest_coin(symbol, df_m5, INITIAL_BALANCE)

            n = len(trades)
            if n == 0:
                print(f"   Tidak ada trade.")
                coin_results.append({
                    'symbol': symbol, 'trades': 0, 'win': 0, 'loss': 0,
                    'wr': 0, 'pnl': 0, 'final_bal': INITIAL_BALANCE,
                    'roi': 0, 'max_dd': 0, 'avg_pnl': 0
                })
                continue

            wins   = [t for t in trades if t['outcome'] == 'tp']
            losses = [t for t in trades if t['outcome'] == 'sl']
            total_pnl = sum(t['pnl_usd'] for t in trades)
            wr = len(wins) / n * 100

            # Max Drawdown
            peak = INITIAL_BALANCE
            max_dd = 0
            running = INITIAL_BALANCE
            for t in trades:
                running += t['pnl_usd']
                if running > peak: peak = running
                dd = (peak - running) / peak * 100
                if dd > max_dd: max_dd = dd

            roi = total_pnl / INITIAL_BALANCE * 100
            avg_pnl = total_pnl / n

            n_sl      = len(losses)
            sl_tp     = sum(1 for t in trades if t.get('sl_then_tp'))
            sl_choch  = sum(1 for t in trades if t.get('sl_choch'))
            sl_drift  = n_sl - sl_tp - sl_choch
            sl_str    = (f" | SL→TP:{sl_tp} CHOCH:{sl_choch} Drift:{sl_drift}"
                         f" ({sl_choch*100//n_sl if n_sl else 0}% CHOCH)") if n_sl else ""
            mss_gap   = dbg['mss_found'] - n
            print(f"   Trade:{n} | W:{len(wins)} L:{n_sl} | WR:{wr:.1f}% | PnL:${total_pnl:.2f} | ROI:{roi:.1f}% | MaxDD:{max_dd:.1f}%{sl_str}")
            print(f"   MSS→Trade: {dbg['mss_found']} ditemukan → {n} traded"
                  f" | skip: InTrade:{dbg['intrade']} DirFail:{dbg['dir_fail']} SimSkip:{dbg['sim_skip']}")
            # MAE bucket untuk sl_then_tp trades
            mae_trades = [t['mae_r'] for t in trades if t.get('sl_then_tp') and t.get('mae_r', 0) > 0]
            if mae_trades:
                buckets = {}
                for r in mae_trades:
                    lo = int(r); key = f"{lo}-{lo+1}R"
                    buckets[key] = buckets.get(key, 0) + 1
                bkt_str = "  ".join(f"{k}:{v}" for k, v in sorted(buckets.items(), key=lambda x: int(x[0].split('-')[0])))
                print(f"   MAE (SL→TP={sl_tp}): {bkt_str}")

            # MFE bucket untuk semua losing trades (SL + timeout/drift)
            mfe_trades = [t['mfe_r'] for t in trades if t['outcome'] in ('sl','timeout') and not t.get('sl_then_tp') and t.get('mfe_r',0) >= 0]
            if mfe_trades:
                mbuckets = {}
                for r in mfe_trades:
                    lo = int(r); key = f"{lo}-{lo+1}R"
                    mbuckets[key] = mbuckets.get(key, 0) + 1
                mkt_str = "  ".join(f"{k}:{v}" for k, v in sorted(mbuckets.items(), key=lambda x: int(x[0].split('-')[0])))
                print(f"   MFE (Dr={sl_drift} n={len(mfe_trades)}): {mkt_str}")

            coin_results.append({
                'symbol': symbol, 'trades': n, 'win': len(wins), 'loss': len(losses),
                'wr': wr, 'pnl': total_pnl, 'final_bal': final_bal,
                'roi': roi, 'max_dd': max_dd, 'avg_pnl': avg_pnl
            })
            all_trades.extend(trades)

        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback; traceback.print_exc()

    # ============================================================
    # STATISTIK GABUNGAN
    # ============================================================
    print("\n" + "=" * 60)
    print("  RINGKASAN STATISTIK GABUNGAN")
    print("=" * 60)

    if not all_trades:
        print("Tidak ada trade sama sekali.")
        return

    total_trades = len(all_trades)
    total_wins   = sum(1 for t in all_trades if t['outcome'] == 'tp')
    total_losses = sum(1 for t in all_trades if t['outcome'] == 'sl')
    total_pnl    = sum(t['pnl_usd'] for t in all_trades)
    wr_total     = total_wins / total_trades * 100
    avg_win      = np.mean([t['pnl_usd'] for t in all_trades if t['outcome'] == 'tp']) if total_wins else 0
    avg_loss     = np.mean([t['pnl_usd'] for t in all_trades if t['outcome'] == 'sl']) if total_losses else 0

    # Profit factor
    gross_win  = sum(t['pnl_usd'] for t in all_trades if t['pnl_usd'] > 0)
    gross_loss = abs(sum(t['pnl_usd'] for t in all_trades if t['pnl_usd'] < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')

    # Max drawdown gabungan (simulasi portfolio $30 per coin digabung)
    # Hitung equity curve dengan urutan timestamp
    all_trades_sorted = sorted(all_trades, key=lambda t: t['entry_ts'])
    peak = INITIAL_BALANCE * len(FILES)
    running_eq = peak
    max_dd_portfolio = 0
    for t in all_trades_sorted:
        running_eq += t['pnl_usd']
        if running_eq > peak: peak = running_eq
        dd = (peak - running_eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd_portfolio: max_dd_portfolio = dd

    roi_total = total_pnl / INITIAL_BALANCE * 100

    # Consecutive wins/losses
    outcomes = [t['outcome'] for t in all_trades_sorted]
    max_consec_win = max_consec_loss = cur_w = cur_l = 0
    for o in outcomes:
        if o == 'tp': cur_w += 1; cur_l = 0
        else: cur_l += 1; cur_w = 0
        max_consec_win  = max(max_consec_win,  cur_w)
        max_consec_loss = max(max_consec_loss, cur_l)

    # Expectancy per trade
    expectancy = (wr_total/100 * avg_win) + ((1 - wr_total/100) * avg_loss)

    print(f"\n{'Metric':<28} {'Value':>15}")
    print("-" * 44)
    print(f"{'Modal Awal':<28} {'$30.00':>15}")
    print(f"{'Total Trade':<28} {total_trades:>15}")
    print(f"{'Win':<28} {total_wins:>15}")
    print(f"{'Loss':<28} {total_losses:>15}")
    print(f"{'Win Rate':<28} {wr_total:>14.1f}%")
    print(f"{'Total PnL':<28} {'${:.2f}'.format(total_pnl):>15}")
    print(f"{'ROI (vs modal $30)':<28} {'{:.1f}%'.format(roi_total):>15}")
    print(f"{'Avg Win per trade':<28} {'${:.4f}'.format(avg_win):>15}")
    print(f"{'Avg Loss per trade':<28} {'${:.4f}'.format(avg_loss):>15}")
    print(f"{'Profit Factor':<28} {pf:>15.2f}")
    print(f"{'Expectancy/trade':<28} {'${:.4f}'.format(expectancy):>15}")
    print(f"{'Max Consec. Win':<28} {max_consec_win:>15}")
    print(f"{'Max Consec. Loss':<28} {max_consec_loss:>15}")
    print(f"{'Max Drawdown (portfolio)':<28} {'{:.1f}%'.format(max_dd_portfolio):>15}")

    print(f"\n{'=' * 60}")
    print("  PER-COIN BREAKDOWN")
    print(f"{'=' * 60}")
    print(f"{'Coin':<18} {'Tr':>4} {'W':>4} {'L':>4} {'WR%':>6} {'PnL$':>8} {'ROI%':>7} {'MaxDD%':>7}")
    print("-" * 60)
    for r in coin_results:
        if r['trades'] == 0:
            print(f"{r['symbol']:<18} {'—':>4} {'—':>4} {'—':>4} {'—':>6} {'—':>8} {'—':>7} {'—':>7}")
        else:
            print(f"{r['symbol']:<18} {r['trades']:>4} {r['win']:>4} {r['loss']:>4} "
                  f"{r['wr']:>5.1f}% {r['pnl']:>7.2f} {r['roi']:>6.1f}% {r['max_dd']:>6.1f}%")

    # Long vs Short breakdown
    longs  = [t for t in all_trades if t['type'] == 'Long']
    shorts = [t for t in all_trades if t['type'] == 'Short']
    l_wr = sum(1 for t in longs if t['outcome']=='tp') / len(longs) * 100 if longs else 0
    s_wr = sum(1 for t in shorts if t['outcome']=='tp') / len(shorts) * 100 if shorts else 0
    l_pnl = sum(t['pnl_usd'] for t in longs)
    s_pnl = sum(t['pnl_usd'] for t in shorts)

    print(f"\n{'Direction':<12} {'Trades':>6} {'WR%':>7} {'PnL$':>9}")
    print("-" * 36)
    print(f"{'Long':<12} {len(longs):>6} {l_wr:>6.1f}% {l_pnl:>8.2f}")
    print(f"{'Short':<12} {len(shorts):>6} {s_wr:>6.1f}% {s_pnl:>8.2f}")

    # BOS vs Sweep
    bos_trades   = [t for t in all_trades if t.get('trigger') == 'bos']
    sweep_trades = [t for t in all_trades if t.get('trigger') == 'sweep']
    b_wr = sum(1 for t in bos_trades if t['outcome']=='tp') / len(bos_trades) * 100 if bos_trades else 0
    sw_wr = sum(1 for t in sweep_trades if t['outcome']=='tp') / len(sweep_trades) * 100 if sweep_trades else 0

    print(f"\n{'Trigger':<12} {'Trades':>6} {'WR%':>7} {'PnL$':>9}")
    print("-" * 36)
    print(f"{'BOS':<12} {len(bos_trades):>6} {b_wr:>6.1f}% {sum(t['pnl_usd'] for t in bos_trades):>8.2f}")
    print(f"{'Sweep':<12} {len(sweep_trades):>6} {sw_wr:>6.1f}% {sum(t['pnl_usd'] for t in sweep_trades):>8.2f}")

    # Save trade log CSV
    df_trades = pd.DataFrame(all_trades)
    out_csv = '/mnt/user-data/outputs/backtest_trades.csv'
    df_trades.to_csv(out_csv, index=False)
    print(f"\n📄 Trade log disimpan: {out_csv}")

    return coin_results, all_trades


if __name__ == '__main__':
    main()
