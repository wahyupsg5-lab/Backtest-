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
MIN_RR          = 2.8
MIN_DIST_PCT    = 0.005     # minimum SL distance 0.5%

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
    'BELUSDT'      : [
        'BELUSDT_5m_01-01-2025~31-05-2025.txt',
        'BELUSDT_5m_01-06-2025~30-09-2025.txt',
        'BELUSDT_5m_01-10-2025~31-12-2025.txt',
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
    'XVGUSDT'       : 0.0030,   # P25=0.303%
    '1000PEPEUSDT'  : 0.0031,   # P25=0.306%
    '1000BONKUSDT'  : 0.0035,   # P25=0.348%
    'BELUSDT'       : 0.0024,   # P25=0.238%
    'USUALUSDT'     : 0.0034,   # P25=0.340%
    'BERAUSDT'      : 0.0032,   # P25=0.322%
    'WIFUSDT'       : 0.0038,   # P25=0.378%
    'PENGUUSDT'     : 0.0040,   # P25=0.397%
    'PNUTUSDT'      : 0.0036,   # P25=0.357%
    'AVAXUSDT'      : 0.0025,   # P25=0.251%
    'ONDOUSDT'      : 0.0027,   # P25=0.270%
    'EIGENUSDT'     : 0.0037,   # P25=0.369%
    'LINKUSDT'      : 0.0025,   # P25=0.253%
    'VIRTUALUSDT'   : 0.0040,   # P25=0.402%
    'ORCAUSDT'      : 0.0024,   # P25=0.237%
    'DOGEUSDT'      : 0.0024,   # P25=0.242%
    'ARBUSDT'       : 0.0028,   # P25=0.279%
    'NEARUSDT'      : 0.0029,   # P25=0.287%
    'STORJUSDT'     : 0.0017,   # P25=0.172%
    'ENAUSDT'       : 0.0039,   # P25=0.388%
    'ADAUSDT'       : 0.0025,   # P25=0.247%
    'SHIB1000USDT'  : 0.0020,   # P25=0.197%
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
    if n < 3:
        return [], []

    # Swing high: candle[i] lebih tinggi dari kiri dan kanan
    sh_mask = (h_arr[1:-1] > h_arr[:-2]) & (h_arr[1:-1] > h_arr[2:])
    sl_mask = (l_arr[1:-1] < l_arr[:-2]) & (l_arr[1:-1] < l_arr[2:])

    sh_idx = np.where(sh_mask)[0] + 1  # +1 karena slice [1:-1]
    sl_idx = np.where(sl_mask)[0] + 1

    ts_arr = df['ts'].to_numpy() if 'ts' in df.columns else np.zeros(n)

    highs = [{'val': float(h_arr[i]), 'idx': int(i), 'ts': ts_arr[i]} for i in sh_idx]
    lows  = [{'val': float(l_arr[i]), 'idx': int(i), 'ts': ts_arr[i]} for i in sl_idx]
    return highs, lows

# ============================================================
# FVG
# ============================================================

def get_internal_gaps(df, stype, bos_idx, lookback=60):
    gaps = []
    scan_start = max(2, bos_idx - lookback)

    # Pre-BOS FVG
    for i in range(bos_idx - 1, scan_start, -1):
        gap = None
        if stype == "Long" and df['high'].iloc[i-2] < df['low'].iloc[i]:
            gap = {"top": df['low'].iloc[i], "bottom": df['high'].iloc[i-2], "zone": "pre"}
        elif stype == "Short" and df['low'].iloc[i-2] > df['high'].iloc[i]:
            gap = {"top": df['low'].iloc[i-2], "bottom": df['high'].iloc[i], "zone": "pre"}
        if gap:
            is_fresh = True
            for j in range(i + 1, bos_idx + 1):
                if stype == "Long" and df['close'].iloc[j] < gap['bottom']:
                    is_fresh = False; break
                if stype == "Short" and df['close'].iloc[j] > gap['top']:
                    is_fresh = False; break
            if is_fresh:
                gaps.append(gap)

    # Post-BOS FVG
    post_end = len(df) - 2
    for i in range(bos_idx + 1, post_end):
        if i + 1 >= len(df): continue
        gap = None
        if stype == "Long" and df['high'].iloc[i-1] < df['low'].iloc[i+1]:
            gap = {"top": df['low'].iloc[i+1], "bottom": df['high'].iloc[i-1], "zone": "post"}
        elif stype == "Short" and df['low'].iloc[i-1] > df['high'].iloc[i+1]:
            gap = {"top": df['low'].iloc[i-1], "bottom": df['high'].iloc[i+1], "zone": "post"}
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

def simulate_trade(df_m5, entry_idx, entry, sl, tp, stype, balance):
    """
    Simulasi trade dari entry_idx+1 sampai TP/SL kena.
    Return: (pnl_usd, outcome, exit_price, exit_ts)
    """
    dist = abs(entry - sl)
    if dist == 0:
        return 0, 'skip', entry, None

    # Minimum SL distance 0.5%
    min_dist = entry * MIN_DIST_PCT
    if dist < min_dist:
        dist = min_dist
        if stype == "Long":
            sl = entry - dist
        else:
            sl = entry + dist

    # Validasi TP arah
    if stype == "Long" and tp <= entry:   return 0, 'skip', entry, None
    if stype == "Short" and tp >= entry:  return 0, 'skip', entry, None

    # R:R check
    tp_dist = abs(tp - entry)
    if tp_dist / dist < MIN_RR:           return 0, 'skip', entry, None

    risk_usd = balance * RISK_PCT
    qty      = risk_usd / dist            # kontrak (qty in coin)
    notional = qty * entry                # nilai posisi (USD)
    # Fee = taker fee dua arah (entry + exit), berbasis notional
    total_fee = 2 * notional * TAKER_FEE

    # Walk forward candle-by-candle
    future = df_m5.iloc[entry_idx+1:entry_idx+1000]  # max 1000 candle (~83 jam)
    for _, c in future.iterrows():
        h, l = float(c['high']), float(c['low'])
        if stype == "Long":
            if l <= sl:
                exit_p = sl
                pnl    = (exit_p - entry) * qty - total_fee
                return pnl, 'sl', exit_p, c['ts']
            if h >= tp:
                exit_p = tp
                pnl    = (exit_p - entry) * qty - total_fee
                return pnl, 'tp', exit_p, c['ts']
        else:
            if h >= sl:
                exit_p = sl
                pnl    = (entry - exit_p) * qty - total_fee
                return pnl, 'sl', exit_p, c['ts']
            if l <= tp:
                exit_p = tp
                pnl    = (entry - exit_p) * qty - total_fee
                return pnl, 'tp', exit_p, c['ts']

    # Timeout — close at last candle
    exit_p = float(future.iloc[-1]['close']) if len(future) else entry
    if stype == "Long":
        pnl = (exit_p - entry) * qty - total_fee
    else:
        pnl = (entry - exit_p) * qty - total_fee
    return pnl, 'timeout', exit_p, future.iloc[-1]['ts'] if len(future) else None


# ============================================================
# BACKTEST PER COIN
# ============================================================

def backtest_coin(symbol, df_m5_full, initial_balance):
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
    last_bos_key = None

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

        if not (is_long or is_short) or swing_val is None:
            i += 12; continue

        stype = "Short" if is_short else "Long"

        # EMA50 filter (DISABLED — sinkron live bot)
        ema50 = calc_ema(df_h1['close'], 50).iloc[-1]
        # if stype == "Long"  and curr_h1['close'] < ema50: i += 12; continue
        # if stype == "Short" and curr_h1['close'] > ema50: i += 12; continue

        bos_key = (stype, round(swing_val, 8))
        if bos_key == last_bos_key:
            i += 12; continue
        last_bos_key = bos_key

        # CHOCH level dulu — agar bisa filter FVG yang straddle CHOCH
        if stype == "Long":
            sl_below    = [s for s in sl_h1 if s['val'] < swing_val]
            choch_level = sl_below[-1]['val'] if sl_below else None
        else:
            sh_above    = [s for s in sh_h1 if s['val'] > swing_val]
            choch_level = sh_above[-1]['val'] if sh_above else None

        # FVG — filter FVG yang straddle CHOCH (bottom < CHOCH untuk Long / top > CHOCH untuk Short)
        gaps = get_internal_gaps(df_h1, stype, bos_idx)
        if choch_level:
            if stype == "Long":
                gaps = [g for g in gaps if g['bottom'] >= choch_level]
            else:
                gaps = [g for g in gaps if g['top'] <= choch_level]
        if not gaps:
            i += 12; continue

        # ── Scan FVG touch di M5 — per blok H1 (max 96 jam) ──
        scan_end = min(total - 1, i + 12 * 96)
        scan_slice = df_m5_full.iloc[i:scan_end]
        seg_h = scan_slice['high'].to_numpy(dtype=float)
        seg_l = scan_slice['low'].to_numpy(dtype=float)
        seg_c = scan_slice['close'].to_numpy(dtype=float)
        seg_o = scan_slice['open'].to_numpy(dtype=float)
        seg_len = len(seg_h)
        found_fvg_idx = -1
        used_fvg = None
        choch_triggered = False

        for fvg in gaps:
            fvg_top = float(fvg['top']); fvg_bot = float(fvg['bottom'])
            blk_i = 0
            while blk_i < seg_len:
                blk_end = min(blk_i + 12, seg_len)
                blk_h   = seg_h[blk_i:blk_end].max()
                blk_l   = seg_l[blk_i:blk_end].min()
                blk_c   = seg_c[blk_end - 1]
                # CHOCH: struktur berbalik → setup batal
                if choch_level:
                    if stype == "Long"  and blk_c < choch_level:
                        choch_triggered = True; break
                    if stype == "Short" and blk_c > choch_level:
                        choch_triggered = True; break
                # Broken FVG?
                if stype == "Long"  and blk_c < fvg_bot: break
                if stype == "Short" and blk_c > fvg_top: break
                # Touch?
                if stype == "Long"  and blk_l <= fvg_top:
                    found_fvg_idx = i + blk_i; used_fvg = fvg; break
                if stype == "Short" and blk_h >= fvg_bot:
                    found_fvg_idx = i + blk_i; used_fvg = fvg; break
                blk_i += 12
            if choch_triggered or found_fvg_idx >= 0: break

        if choch_triggered:
            i += 12; continue
        if found_fvg_idx < 0:
            i += 12 * 24; continue   # tidak ada FVG touch, lompat 24 jam

        # ── IDM M5 setelah FVG touch (max 24 jam) ──
        idm_end = min(total - 1, found_fvg_idx + 12 * 48)  # diperlebar: 48 jam
        df_m5_idm = df_m5_full.iloc[found_fvg_idx: idm_end].reset_index(drop=True)
        if len(df_m5_idm) < 5:
            i += 12; continue

        m5_state = replay_m5(df_m5_idm, stype)
        if m5_state['phase'] != 'IDM_TOUCHED':
            i += 12 * 24; continue

        freeze_high = m5_state['freeze_high']
        freeze_low  = m5_state['freeze_low']
        freeze_ts   = m5_state['freeze_ts']

        # Temukan index M5 dari freeze_ts
        freeze_mask = df_m5_full['ts_ms'] == freeze_ts
        if not freeze_mask.any():
            i += 12; continue
        freeze_m5_idx = df_m5_full[freeze_mask].index[0]

        # ── BOS/Sweep M5 (max 12 jam setelah IDM) ──
        bos_end = min(total - 1, freeze_m5_idx + 12 * 12)
        df_bos  = df_m5_full.iloc[freeze_m5_idx: bos_end].reset_index(drop=True)
        result  = check_bos_or_sweep(df_bos, freeze_high, freeze_low, freeze_ts, stype)
        if result['trigger'] is None:
            i += 12 * 12; continue

        trigger_ts = result['ts']
        new_fh = result['nfh']
        new_fl = result['nfl']

        # Temukan index M5 dari trigger_ts
        trig_mask = df_m5_full['ts_ms'] == trigger_ts
        if not trig_mask.any():
            i += 12; continue
        trigger_m5_idx = df_m5_full[trig_mask].index[0]

        # ── Recursive IDM loop setelah BOS pertama ──
        # IDM#1 → mandatory BOS → IDM#n (dalam BOS) → WAIT_MSS
        # WAIT_MSS: MSS (close balik) = entry | BOS lagi = cari IDM#n+1 (loop)
        mss_candle = None
        mss_m5_idx = -1
        anchor_idx = trigger_m5_idx

        for _depth in range(8):
            idm_in_end  = min(total - 1, anchor_idx + 12 * 48)
            df_m5_inner = df_m5_full.iloc[anchor_idx:idm_in_end].reset_index(drop=True)
            if len(df_m5_inner) < 5:
                break

            m5_inner = replay_m5(df_m5_inner, stype)
            if m5_inner['phase'] != 'IDM_TOUCHED':
                break

            inner_fh  = m5_inner['freeze_high']
            inner_fl  = m5_inner['freeze_low']
            inner_fts = m5_inner['freeze_ts']

            inner_mask = df_m5_full['ts_ms'] == inner_fts
            if not inner_mask.any():
                break
            inner_m5_idx = int(df_m5_full[inner_mask].index[0])

            # WAIT_MSS: scan close — MSS (balik arah) atau BOS lagi (lanjut tren)
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
                anchor_idx = inner_m5_idx + first_bos   # BOS lagi → cari IDM baru
            else:
                break  # timeout dalam WAIT_MSS

        if mss_candle is None or mss_m5_idx < 0:
            i += 12 * 6; continue

        # Filter MSS strength (DISABLED — sinkron live bot)
        mss_body  = abs(float(mss_candle['close']) - float(mss_candle['open']))
        mss_range = abs(float(mss_candle['high'])  - float(mss_candle['low']))
        # if mss_range > 0 and mss_body / mss_range < 0.30:
        #     i += 12; continue
        _mss_body_ratio = round(mss_body / mss_range, 4) if mss_range > 0 else 0.0

        # Filter volume (DISABLED — sinkron live bot)
        vol_window = df_m5_full.iloc[max(0, mss_m5_idx - 19): mss_m5_idx + 1]
        avg_vol = vol_window['vol'].mean()
        _vol_ratio = round(float(mss_candle['vol']) / avg_vol, 4) if avg_vol > 0 else 0.0
        # if avg_vol > 0 and float(mss_candle['vol']) / avg_vol < 0.25:
        #     i += 12; continue

        # Filter ATR (DISABLED — sinkron live bot)
        atr_thresh = ATR_THRESHOLD.get(symbol, 0.0035)
        atr_window = df_m5_full.iloc[max(0, mss_m5_idx - 19): mss_m5_idx + 1]
        _atr_ratio = 0.0
        if len(atr_window) >= 5:
            h = atr_window['high']; l = atr_window['low']
            pc = atr_window['close'].shift(1)
            tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
            atr_val = tr.mean()
            ref_price = float(mss_candle['close'])
            if atr_thresh > 0 and ref_price > 0:
                _atr_ratio = round((atr_val / ref_price) / atr_thresh, 3)
            # if ref_price > 0 and (atr_val / ref_price) < atr_thresh:
            #     i += 12; continue

        # ── Entry: Limit order di Breaker Block (realistic SMC execution) ──
        # Setelah MSS, harga biasanya pullback ke zona BB sebelum lanjut.
        # Pasang limit order di bb['entry'], tunggu fill. Skip jika timeout (30 candle ~2.5 jam).
        df_bb = df_m5_full.iloc[max(0, mss_m5_idx - 20): mss_m5_idx + 1].reset_index(drop=True)
        bb = find_breaker_block(df_bb, int(mss_candle['ts_ms']), stype)

        if bb is None:
            i += 12; continue  # tidak ada BB → tidak bisa pasang limit

        bb_entry = bb['entry']
        sl_price = bb['sl']
        dist     = abs(bb_entry - sl_price)
        if dist == 0:
            i += 12; continue

        # Scan forward: cari candle pertama harga menyentuh BB (limit fill)
        FILL_TIMEOUT = 30  # candle (~2.5 jam)
        fill_idx = None
        for j in range(mss_m5_idx + 1, min(mss_m5_idx + 1 + FILL_TIMEOUT, len(df_m5_full))):
            candle_j = df_m5_full.iloc[j]
            low_j    = float(candle_j['low'])
            high_j   = float(candle_j['high'])
            if stype == "Long":
                if low_j <= sl_price:   # SL ditembus sebelum fill → skip
                    break
                if low_j <= bb_entry:   # harga pullback ke BB → fill
                    fill_idx = j
                    break
            else:  # Short
                if high_j >= sl_price:  # SL ditembus sebelum fill → skip
                    break
                if high_j >= bb_entry:  # harga bounce ke BB → fill
                    fill_idx = j
                    break

        if fill_idx is None:
            i += 12; continue  # tidak fill dalam timeout atau SL duluan

        entry_price = bb_entry
        tp_dist     = dist * 3
        final_tp    = entry_price + tp_dist if stype == "Long" else entry_price - tp_dist

        # ── Simulasi (dari fill_idx — TP/SL tracking mulai setelah limit fill) ──
        pnl, outcome, exit_p, exit_ts = simulate_trade(
            df_m5_full, fill_idx, entry_price, sl_price, final_tp, stype, balance
        )
        if outcome == 'skip':
            i += 12; continue

        balance += pnl

        # Cari exit index
        if exit_ts is not None:
            exit_rows = df_m5_full[df_m5_full['ts'] == exit_ts].index
            in_trade_until_idx = int(exit_rows[0]) if len(exit_rows) else mss_m5_idx + 300
        else:
            in_trade_until_idx = mss_m5_idx + 300

        trades.append({
            'symbol'         : symbol,
            'type'           : stype,
            'entry_ts'       : df_m5_full.iloc[fill_idx]['ts'],
            'exit_ts'        : exit_ts,
            'entry'          : round(entry_price, 8),
            'sl'             : round(sl_price, 8),
            'tp'             : round(final_tp, 8),
            'exit_price'     : round(exit_p, 8),
            'outcome'        : outcome,
            'pnl_usd'        : round(pnl, 4),
            'balance'        : round(balance, 4),
            'trigger'        : result['trigger'],
            'idm_depth'      : _depth,
            'mss_body_ratio' : _mss_body_ratio,
            'vol_ratio'      : _vol_ratio,
            'atr_ratio'      : _atr_ratio,
            'entry_type'     : 'breaker' if bb is not None else 'fvg',
            'sl_dist_pct'    : round(dist / entry_price, 6) if entry_price > 0 else 0.0,
        })

        i = in_trade_until_idx + 1

    return trades, balance


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

            trades, final_bal = backtest_coin(symbol, df_m5, INITIAL_BALANCE)

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

            print(f"   Trade:{n} | W:{len(wins)} L:{len(losses)} | WR:{wr:.1f}% | PnL:${total_pnl:.2f} | ROI:{roi:.1f}% | MaxDD:{max_dd:.1f}%")

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
