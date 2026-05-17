import pandas as pd
import numpy as np
from pybit.unified_trading import HTTP
import os
import time
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# LOG SERVER — akses via https://xxx.up.railway.app/logs
# ============================================================
LOG_FILE = "bot.log"

class _Tee:
    """Redirect print() ke stdout DAN file sekaligus, dengan timestamp WIB per baris."""
    def __init__(self):
        self._out     = sys.__stdout__
        self._file    = open(LOG_FILE, 'a', buffering=1, encoding='utf-8')
        self._newline = True
    def write(self, msg):
        import datetime
        out = ''
        for ch in msg:
            if self._newline and ch != '\n':
                out += (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=7)).strftime('[%H:%M:%S] ')
                self._newline = False
            out += ch
            if ch == '\n':
                self._newline = True
        self._out.write(out)
        self._file.write(out)
    def flush(self):
        self._out.flush()
        self._file.flush()

sys.stdout = _Tee()

class _LogHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/logs', '/logs?'):
            self.send_response(404); self.end_headers(); return
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            data = ''.join(lines[-200:]).encode('utf-8')
        except:
            data = b''
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a):
        pass

PORT = int(os.environ.get('PORT', 8080))
threading.Thread(
    target=lambda: HTTPServer(('0.0.0.0', PORT), _LogHandler).serve_forever(),
    daemon=True
).start()
print(f"📡 Log server jalan di port {PORT} → /logs")

# ============================================================
# CONFIG
# ============================================================
API_KEY    = os.environ.get('API_KEY', '')
API_SECRET = os.environ.get('API_SECRET', '')
CATEGORY   = "linear"
TESTNET    = os.environ.get('TESTNET', 'false').lower() == 'true'

if not API_KEY or not API_SECRET:
    raise ValueError("❌ API_KEY dan API_SECRET belum diset!")

session = HTTP(testnet=TESTNET, api_key=API_KEY, api_secret=API_SECRET)

SYMBOLS = [
    # Core (dari backtest run 1)
    'XVGUSDT', 'BELUSDT', '1000BONKUSDT', 'BERAUSDT', 'USUALUSDT',
    '1000PEPEUSDT', 'WIFUSDT', 'PENGUUSDT', 'PNUTUSDT',
    'AVAXUSDT', 'ONDOUSDT', 'EIGENUSDT', 'LINKUSDT', 'VIRTUALUSDT', 'ORCAUSDT',
    # Rehabilitasi (dari backtest run 2 — recursive IDM)
    'DOGEUSDT', 'ARBUSDT', 'NEARUSDT', 'STORJUSDT', 'ENAUSDT', 'ADAUSDT',
    # Baru
    'SHIB1000USDT',
]


# ============================================================
# [v5] HELPER INDICATORS
# ============================================================

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_atr(df, period=14):
    h, l, pc = df['high'], df['low'], df['close'].shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_smart_tp(df_h1, bos_idx, stype, entry_price, atr_val):
    """
    [v5] TP berbasis swing struktural H1 atau minimum 2.5×ATR.
    Menggantikan since_bos high/low yang sering terlalu dekat.
    """
    swings = []
    for i in range(1, bos_idx):
        if stype == "Long":
            h = df_h1["high"].iloc[i]
            if df_h1["high"].iloc[i-1] < h and (i+1 >= len(df_h1) or df_h1["high"].iloc[i+1] < h):
                swings.append(h)
        else:
            l = df_h1["low"].iloc[i]
            if df_h1["low"].iloc[i-1] > l and (i+1 >= len(df_h1) or df_h1["low"].iloc[i+1] > l):
                swings.append(l)
    min_tp_dist = atr_val * 2.5
    if stype == "Long":
        candidates = sorted([s for s in swings if s > entry_price + min_tp_dist])
        return candidates[0] if candidates else entry_price + min_tp_dist
    else:
        candidates = sorted([s for s in swings if s < entry_price - min_tp_dist], reverse=True)
        return candidates[0] if candidates else entry_price - min_tp_dist

pending          = {}
active_positions = {}
instrument_cache = {}


# ============================================================
# FUNGSI DATA
# ============================================================

def get_data(symbol, interval, limit=200):
    try:
        res = session.get_kline(
            category=CATEGORY, symbol=symbol,
            interval=interval, limit=limit
        )
        if res['retCode'] == 0:
            df = pd.DataFrame(
                res['result']['list'],
                columns=['ts','open','high','low','close','vol','turnover']
            )
            df[['open','high','low','close','vol','turnover','ts']] = \
                df[['open','high','low','close','vol','turnover','ts']].apply(pd.to_numeric)
            return df.iloc[::-1].reset_index(drop=True)
        print(f"⚠️ get_data {symbol} {interval}: {res.get('retMsg','')}")
        return None
    except Exception as e:
        print(f"⚠️ get_data {symbol} {interval}: {e}")
        return None


# ============================================================
# INSTRUMENT INFO
# ============================================================

def get_instrument_info(symbol):
    if symbol in instrument_cache:
        return instrument_cache[symbol]
    try:
        res = session.get_instruments_info(category=CATEGORY, symbol=symbol)
        if res['retCode'] == 0:
            info = res['result']['list'][0]
            lot  = info['lotSizeFilter']
            data = {
                'min_qty'    : float(lot['minOrderQty']),
                'qty_step'   : float(lot['qtyStep']),
                'tick_size'  : float(info['priceFilter']['tickSize']),
                'max_leverage': float(info.get('leverageFilter', {}).get('maxLeverage', 10)),
            }
            instrument_cache[symbol] = data
            return data
    except Exception as e:
        print(f"⚠️ instrument_info {symbol}: {e}")
    return {'min_qty': 0.01, 'qty_step': 0.01, 'tick_size': 0.0001}


def round_qty(qty, step):
    step_str  = f'{step:.10f}'.rstrip('0')
    precision = len(step_str.split('.')[-1]) if '.' in step_str else 0
    return round(int(qty / step) * step, precision)


def round_price(price, tick):
    tick_str  = f'{tick:.10f}'.rstrip('0')
    precision = len(tick_str.split('.')[-1]) if '.' in tick_str else 0
    return round(round(price / tick) * tick, precision)


# ============================================================
# FUNGSI SWING
# ============================================================

def find_swings(df, left=2, right=2):
    highs, lows = [], []
    for i in range(left, len(df) - right):
        h, l = df['high'].iloc[i], df['low'].iloc[i]
        if all(df['high'].iloc[i-j] < h for j in range(1, left+1)) and \
           all(df['high'].iloc[i+j] <= h for j in range(1, right+1)):
            highs.append({'val': h, 'idx': i, 'ts': df['ts'].iloc[i]})
        if all(df['low'].iloc[i-j] > l for j in range(1, left+1)) and \
           all(df['low'].iloc[i+j] >= l for j in range(1, right+1)):
            lows.append({'val': l, 'idx': i, 'ts': df['ts'].iloc[i]})
    return highs, lows


# ============================================================
# DETEKSI BOS — LAST SWING HIGH/LOW
# ============================================================

def find_last_swing_bos(df):
    """
    Deteksi swing high dan swing low lokal dengan konfirmasi 1 candle.

    Swing High: high[i] lebih tinggi dari high[i-1] dan high[i+1]
    Swing Low : low[i]  lebih rendah dari low[i-1]  dan low[i+1]

    Lebih natural dan fractal dibanding left=N, right=N:
    - Tidak butuh banyak candle konfirmasi
    - Cocok untuk market trending dan ranging
    - Level BOS = last swing high/low yang dilanggar close
    """
    highs, lows = [], []
    for i in range(1, len(df) - 1):
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        if df['high'].iloc[i-1] < h and df['high'].iloc[i+1] < h:
            highs.append({'val': h, 'idx': i, 'ts': df['ts'].iloc[i]})
        if df['low'].iloc[i-1] > l and df['low'].iloc[i+1] > l:
            lows.append({'val': l, 'idx': i, 'ts': df['ts'].iloc[i]})
    return highs, lows


# ============================================================
# FIX BUG #1 — get_internal_gaps() hanya dari dalam range BOS
# + freshness hanya dicek sampai candle BOS, bukan post-BOS
# ============================================================

def get_internal_gaps(df, stype, bos_idx, lookback=60):
    """
    FVG dicari dalam dua range:
    1. PRE-BOS  : [bos_idx-lookback .. bos_idx]
       Imbalance yang terbentuk sebelum BOS — zona klasik SMC.
    2. POST-BOS : [bos_idx .. len(df)-2]
       Imbalance yang terbentuk saat impuls setelah BOS (e.g. 0.21668
       di chart yang tidak terdeteksi sebelumnya). Harga sering pullback
       ke zona ini sebelum lanjut ke arah BOS.

    Freshness pakai CLOSE bukan wick:
    FVG yang di-wick tapi close masih di luar zona = masih valid.

    Hasil diurutkan dari yang paling dekat harga (paling relevan):
    Long  → top tertinggi dulu  (terdekat dari atas)
    Short → bottom terendah dulu (terdekat dari bawah)
    """
    gaps = []

    # ── 1. Pre-BOS FVG ───────────────────────────────────────
    scan_start = max(2, bos_idx - lookback)
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

    # ── 2. Post-BOS FVG (imbalance saat impuls BOS) ──────────
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

    # Urutkan dari yang paling dekat harga (paling relevan untuk entry)
    if stype == "Long":
        gaps.sort(key=lambda g: g['top'], reverse=True)
    else:
        gaps.sort(key=lambda g: g['bottom'])

    return gaps


# ============================================================
# FIX BUG #2 — swing_ts diganti bos_ts agar M5 sinkron
# ============================================================
# swing_ts (ts swing high/low H1) bisa berbeda jauh dengan ts BOS.
# Akibatnya window M5 yang direplay salah — bisa terlalu jauh ke depan
# atau ke belakang. Solusi: gunakan bos_ts (ts candle BOS H1) sebagai
# anchor M5, karena IDM yang dicari harus terbentuk SETELAH BOS terjadi.


# ============================================================
# FUNGSI IDM (replay_m5) — tidak berubah, sudah benar
# ============================================================

def replay_m5(df, stype):
    """
    State machine IDM M5 dengan deteksi SWEEP.

    Dua skenario setelah IDM disentuh:
    1. BOS klasik : close menembus freeze_low/high → lanjut ke WAIT_MSS
    2. SWEEP      : wick menembus freeze_low/high tapi CLOSE kembali di dalam →
                    "struktur kuat" — likuiditas sudah diambil tanpa break struktur.
                    Ini juga valid sebagai trigger, langsung cari MSS.

    Return dict dengan key tambahan:
    - 'trigger': 'bos' | 'sweep'
    """
    if len(df) < 3:
        return {'phase': 'WAIT_IDM', 'idm_level': None}

    state = 'SINGLE_MOVE'
    candidate_high = None
    candidate_low  = None
    idm_start_idx  = 0

    i = 0
    while i < len(df) - 1:
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
                # Trigger jika: high wick menyentuh level, ATAU close sudah di atas level
                elif c['high'] >= candidate_high * 0.9995 or float(c['close']) > candidate_high:
                    du = df.iloc[idm_start_idx:i+1]
                    return {
                        'phase': 'IDM_TOUCHED', 'idm_level': candidate_high,
                        'freeze_high': du['high'].max(), 'freeze_low': du['low'].min(),
                        'freeze_ts': c['ts']
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
                # Trigger jika: low wick menyentuh level, ATAU close sudah di bawah level
                # (harga melewati dari atas ke bawah tanpa wick yang terdeteksi)
                if c['low'] <= candidate_low * 1.0005 or float(c['close']) < candidate_low:
                    du = df.iloc[idm_start_idx:i+1]
                    return {
                        'phase': 'IDM_TOUCHED', 'idm_level': candidate_low,
                        'freeze_high': du['high'].max(), 'freeze_low': du['low'].min(),
                        'freeze_ts': c['ts']
                    }
                elif c['high'] > candidate_high:
                    # Reset state tapi JANGAN ubah candidate_low — IDM level tetap
                    candidate_high = c['high']
                    state = 'SINGLE_MOVE'
                i += 1

    idm_level = candidate_high if stype == "Long" else candidate_low
    return {'phase': 'WAIT_IDM', 'idm_level': idm_level, 'state': state}


def check_bos_or_sweep(df_m5, freeze_high, freeze_low, freeze_ts, stype):
    """
    Setelah IDM tersentuh, cek apakah terjadi BOS atau SWEEP.

    BOS   : close menembus freeze_low (Long) / freeze_high (Short)
    SWEEP : wick menembus level tsb tapi close kembali di dalam range
            → "Struktur Kuat" — likuiditas diambil tanpa break struktur.

    Return:
    {
        'trigger': 'bos' | 'sweep' | None,
        'ts': timestamp candle trigger,
        'sweep_low': float (hanya untuk sweep Long),
        'sweep_high': float (hanya untuk sweep Short),
        'nfh': float,  # range untuk cari MSS
        'nfl': float,
    }
    """
    df_after = df_m5[df_m5['ts'] > freeze_ts]
    if df_after.empty:
        return {'trigger': None}

    for _, c in df_after.iterrows():
        if stype == "Long":
            # BOS: close break bawah
            if float(c['close']) < freeze_low:
                df_range = df_m5[(df_m5['ts'] > freeze_ts) & (df_m5['ts'] <= c['ts'])]
                return {
                    'trigger'    : 'bos',
                    'ts'         : int(c['ts']),
                    'nfh'        : float(df_range['high'].max()),
                    'nfl'        : float(df_range['low'].min()),
                }
            # SWEEP: wick break bawah tapi close di atas freeze_low
            if float(c['low']) < freeze_low and float(c['close']) >= freeze_low:
                df_range = df_m5[(df_m5['ts'] > freeze_ts) & (df_m5['ts'] <= c['ts'])]
                return {
                    'trigger'    : 'sweep',
                    'ts'         : int(c['ts']),
                    'sweep_low'  : float(c['low']),
                    'nfh'        : float(df_range['high'].max()),
                    'nfl'        : float(df_range['low'].min()),
                }
        else:  # Short
            # BOS: close break atas
            if float(c['close']) > freeze_high:
                df_range = df_m5[(df_m5['ts'] > freeze_ts) & (df_m5['ts'] <= c['ts'])]
                return {
                    'trigger'    : 'bos',
                    'ts'         : int(c['ts']),
                    'nfh'        : float(df_range['high'].max()),
                    'nfl'        : float(df_range['low'].min()),
                }
            # SWEEP: wick break atas tapi close di bawah freeze_high
            if float(c['high']) > freeze_high and float(c['close']) <= freeze_high:
                df_range = df_m5[(df_m5['ts'] > freeze_ts) & (df_m5['ts'] <= c['ts'])]
                return {
                    'trigger'     : 'sweep',
                    'ts'          : int(c['ts']),
                    'sweep_high'  : float(c['high']),
                    'nfh'         : float(df_range['high'].max()),
                    'nfl'         : float(df_range['low'].min()),
                }

    return {'trigger': None}


# ============================================================
# FVG TOUCH HELPERS
# ============================================================

def price_in_fvg(price_high, price_low, fvg):
    return price_low <= fvg['top'] and price_high >= fvg['bottom']

def candle_touches_fvg(candle, fvg, stype):
    """
    Wick menyentuh atau menembus zona FVG dari arah yang benar.
    Long  : low pullback ke zona FVG (low <= top FVG) dan tidak close di bawah bottom
    Short : high bounce ke zona FVG (high >= bottom FVG) dan tidak close di atas top
    Syarat >= bottom / <= top dihapus — jika wick lewat bawah tapi tidak broken, tetap valid.
    """
    if stype == "Long":
        return candle['low'] <= fvg['top'] and not fvg_fully_broken(candle, fvg, stype)
    else:
        return candle['high'] >= fvg['bottom'] and not fvg_fully_broken(candle, fvg, stype)

def fvg_fully_broken(candle, fvg, stype):
    """FVG invalid jika close menembus sepenuhnya melewati zona."""
    if stype == "Long":  return candle['close'] < fvg['bottom']
    else:                return candle['close'] > fvg['top']


# ============================================================
# BREAKER BLOCK — entry terbaik setelah MSS
# ============================================================

def find_breaker_block(df_m5, mss_ts, stype):
    """
    Cari Breaker Block M5: candle berlawanan arah terakhir sebelum MSS.

    Long  → cari candle BEARISH terakhir sebelum MSS
            Entry  : high candle bearish (limit order, tunggu pullback ke sini)
            SL     : di bawah low candle bearish + buffer 50% candle size
                     (cukup dalam agar tidak kena noise)

    Short → cari candle BULLISH terakhir sebelum MSS
            Entry  : low candle bullish (limit order, tunggu pullback ke sini)
            SL     : di atas HIGH candle bullish + buffer 50% candle size
                     (di luar struktur, bukan pakai body 10% yang terlalu ketat)

    Contoh dari chart DOGE:
    - Candle bullish: low=0.10860, high=0.10890
    - Entry Short: 0.10860 (batas bawah candle bullish)
    - SL: 0.10890 + buffer = ~0.10910 (di luar high, bukan di 0.10881)
    """
    pre_mss = df_m5[df_m5['ts'] < mss_ts].tail(20).reset_index(drop=True)
    if pre_mss.empty:
        return None

    for _, c in pre_mss.iloc[::-1].iterrows():
        if stype == "Long":
            if float(c['close']) < float(c['open']):   # candle bearish
                candle_size = abs(float(c['high']) - float(c['low']))
                return {
                    'entry'  : float(c['high']),
                    'sl'     : round(float(c['low']) - candle_size * 0.1, 8),
                    'bb_high': float(c['high']),
                    'bb_low' : float(c['low']),
                    'ts'     : int(c['ts']),
                }
        else:
            if float(c['close']) > float(c['open']):   # candle bullish
                candle_size = abs(float(c['high']) - float(c['low']))
                return {
                    'entry'  : float(c['low']),
                    'sl'     : round(float(c['high']) + candle_size * 0.1, 8),
                    'bb_high': float(c['high']),
                    'bb_low' : float(c['low']),
                    'ts'     : int(c['ts']),
                }
    return None


# ============================================================
# FUNGSI ORDER
# ============================================================

def place_limit_order(symbol, side, entry, sl, tp):
    """Market order — entry langsung saat MSS terkonfirmasi."""
    try:
        info     = get_instrument_info(symbol)
        res_bal  = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        balance  = float(res_bal['result']['list'][0]['totalEquity'])
        risk_usd = balance * 0.01
        dist     = abs(entry - sl)
        if dist == 0:
            print(f"⚠️ {symbol}: dist entry-SL = 0, skip.")
            return False

        # Minimum SL distance 0.5% dari harga entry
        # Mencegah qty raksasa saat SL terlalu dekat
        min_dist = entry * 0.005
        if dist < min_dist:
            print(f"⚠️ {symbol}: SL terlalu dekat ({dist:.8f} < min {min_dist:.8f}), diperlebar ke 0.5%")
            dist = min_dist

        # [v5] FIX #1: Validasi TP arah benar
        if side == "Buy"  and tp <= entry:
            print(f"⚠️ {symbol}: TP ({tp}) ≤ entry ({entry}) untuk Long — skip.")
            return False
        if side == "Sell" and tp >= entry:
            print(f"⚠️ {symbol}: TP ({tp}) ≥ entry ({entry}) untuk Short — skip.")
            return False

        # [v5.4b-1R] R:R check: TP sudah di-set ke 1R, hanya validasi minimal 0.8
        tp_dist = abs(tp - entry)
        rr_check = tp_dist / dist if dist > 0 else 0
        if rr_check < 0.8:
            print(f"⚠️ {symbol}: R:R sangat rendah ({rr_check:.2f} < 0.8) — skip.")
            return False

        raw_qty = risk_usd / dist
        qty     = round_qty(raw_qty, info['qty_step'])
        if qty < info['min_qty']:
            print(f"⚠️ {symbol}: Qty {qty} < minOrderQty {info['min_qty']}, skip.")
            return False

        sl_r = round_price(sl,  info['tick_size'])
        tp_r = round_price(tp,  info['tick_size'])

        # Set leverage ke minimum dari (10x, maxLeverage coin)
        # Bybit error 110013 muncul saat leverage melebihi maxLeverage coin
        try:
            max_lev = float(info.get('max_leverage', 10))
            lev     = str(int(min(10, max_lev)))
            session.set_leverage(
                category=CATEGORY, symbol=symbol,
                buyLeverage=lev, sellLeverage=lev
            )
        except Exception:
            pass  # Kalau gagal set leverage, lanjut saja

        print(f"   Balance:{balance:.2f} Risk:{risk_usd:.2f} Dist:{dist:.6f} Qty:{qty}")
        res = session.place_order(
            category=CATEGORY, symbol=symbol, side=side,
            orderType="Market", qty=str(qty),
            stopLoss=str(sl_r), takeProfit=str(tp_r),
            timeInForce="IOC"
        )
        if res['retCode'] == 0:
            return True
        print(f"⚠️ {symbol}: Order ditolak → {res.get('retMsg','')} (code:{res['retCode']})")
        return False
    except Exception as e:
        print(f"⚠️ {symbol}: place_order error → {e}")
        return False


def get_open_position(symbol):
    try:
        res = session.get_positions(category=CATEGORY, symbol=symbol)
        if res['retCode'] == 0:
            for pos in res['result']['list']:
                if float(pos['size']) > 0:
                    return pos
        return None
    except:
        return None


def move_sl(symbol, new_sl):
    try:
        res = session.set_trading_stop(
            category=CATEGORY, symbol=symbol,
            stopLoss=str(new_sl), positionIdx=0
        )
        return res['retCode'] == 0
    except:
        return False


# ============================================================
# TRAILING SL
# ============================================================

def check_trailing_sl(coin):
    """
    [v5.4b-1R] Time-Based Break-Even ONLY.
    TP sudah di-set tepat di 1R — tidak perlu trailing kompleks.
    Satu-satunya intervensi: jika setelah 100 menit harga tidak maju
    minimal 0.5R, geser SL ke entry (exit breakeven = $0 loss).
    Ini menyelamatkan slow SL yang nyaris BEtapi akhirnya loss.
    """
    import time as _time
    if coin not in active_positions: return
    p = active_positions[coin]
    if p.get('sl_moved'): return
    pos = get_open_position(coin)
    if pos is None:
        print(f"📭 {coin}: Posisi tutup (TP/SL hit).")
        del active_positions[coin]
        return
    entry   = p['entry']
    side    = p['side']
    sl_dist = p.get('sl_dist', abs(entry - p['sl']))
    try:
        curr = float(pos['markPrice'])
    except:
        return

    elapsed = _time.time() - p.get('entry_time', _time.time())
    if elapsed < 6000:   # Belum 100 menit → tidak ada aksi
        return

    if side == "Buy":
        progress = curr - entry
    else:
        progress = entry - curr

    # Time-BE: 100+ menit tanpa progress 0.5R → geser SL ke entry
    if progress < sl_dist * 0.5:
        new_sl = round(entry, 8)
        if move_sl(coin, new_sl):
            active_positions[coin]['sl_moved'] = True
            print(f"⏱️ {coin} {side} Time-BE aktif: {elapsed/60:.0f} mnt | progress={progress:.6f} < {sl_dist*0.5:.6f} | SL → entry {new_sl}")


# ============================================================
# CEK TREN H1 BERUBAH
# ============================================================

def h1_trend_broken(curr_h1, setup, sh_h1, sl_h1):
    """
    Setup batal HANYA jika harga sudah menembus tp_val yang disimpan saat BOS.
    Menggunakan tp_val dari setup (fixed), bukan swing live yang bisa bergeser
    setiap loop — terutama penting saat left/right swing besar (20,20) karena
    swing high baru yang lebih rendah bisa terdeteksi dan salah membatalkan setup.
    """
    tp = setup.get('tp')
    if tp is None:
        return False
    if setup['type'] == "Long"  and tp > 0 and curr_h1['close'] >= tp:
        return True
    if setup['type'] == "Short" and tp > 0 and curr_h1['close'] <= tp:
        return True
    return False


# ============================================================
# KONEKSI
# ============================================================

def test_connection():
    try:
        res = session.get_server_time()
        if res['retCode'] == 0:
            print(f"✅ Koneksi Bybit OK | Server time: {res['result']['timeSecond']}")
            return True
        print(f"❌ Bybit error: {res}")
        return False
    except Exception as e:
        print(f"❌ Gagal konek: {e}")
        return False


# ============================================================
# REPLAY H1 — reconstruct state saat startup
# FIX BUG #2: gunakan bos_ts sebagai anchor M5, bukan swing_ts
# FIX BUG #1: get_internal_gaps hanya dalam range BOS
# FIX BUG #3: FVG touch memakai candle_touches_fvg, bukan wick_only
# ============================================================

def replay_h1(coin, df_h1):
    sh_h1, sl_h1 = find_last_swing_bos(df_h1)
    if not sh_h1 or not sl_h1:
        return None

    closed_h1 = df_h1.iloc[-2]

    # Coba last 3 swing kandidat — pilih paling baru yang valid
    is_long = False; is_short = False
    swing_val = None; bos_idx = None; ref_idx = None

    for sh in sh_h1[-3:]:
        if closed_h1['close'] > sh['val']:
            is_long   = True
            swing_val = sh['val']
            ref_idx   = sl_h1[-1]['idx'] if sl_h1 else sh['idx']
            bos_idx   = ref_idx

    for sl in sl_h1[-3:]:
        if closed_h1['close'] < sl['val']:
            is_short  = True
            swing_val = sl['val']
            ref_idx   = sh_h1[-1]['idx'] if sh_h1 else sl['idx']
            bos_idx   = ref_idx

    if not (is_long or is_short):
        return None

    stype = "Long" if is_long else "Short"
    if swing_val is None or bos_idx is None:
        return None

    # FIX #1: FVG hanya dari dalam range BOS
    df_snap = df_h1.copy()
    gaps    = get_internal_gaps(df_snap, stype, bos_idx)
    if not gaps:
        return None

    # [v5.4b-1R] tp_val = placeholder (TP dihitung ulang dari actual entry saat order)
    bos_ts = df_snap['ts'].iloc[bos_idx]
    tp_val = 0  # placeholder

    # CHOCH level:
    # Long → swing low di BAWAH swing_val (jika ditembus ke bawah → CHOCH)
    # Short → swing high di ATAS swing_val (jika ditembus ke atas → CHOCH)
    # Jangan pakai sh_h1[-1] / sl_h1[-1] mentah — bisa Lower High/Higher Low di dalam range
    if stype == "Long":
        sl_below = [s for s in sl_h1 if s['val'] < swing_val]
        choch_level = sl_below[-1]['val'] if sl_below else None
    else:
        sh_above = [s for s in sh_h1 if s['val'] > swing_val]
        choch_level = sh_above[-1]['val'] if sh_above else None

    state = {
        'type': stype, 'df_h1': df_snap,
        'fvg_list': gaps, 'fvg_idx': 0,
        'tp': tp_val, 'bos_ts': bos_ts,
        'bos_idx': bos_idx,
        'swing_val': swing_val,
        'choch_level': choch_level,
        'phase': "WAIT_FVG_TOUCH", 'fvg_touch_ts': bos_ts,
        'm5_freeze_high': None, 'm5_freeze_low': None, 'm5_freeze_ts': None,
        'idm_list': [], 'idm_touched_val': None,
    }

    fvg_idx = 0; fvg_touch_ts = 0; phase = "WAIT_FVG_TOUCH"

    # Replay candle H1 setelah BOS
    for _, candle in df_snap.iloc[bos_idx + 1:-1].iterrows():
        if fvg_idx >= len(gaps):
            return None
        fvg = gaps[fvg_idx]

        if phase == "WAIT_FVG_TOUCH":
            if stype == "Long" and tp_val and candle['close'] >= tp_val: return None
            if stype == "Short" and tp_val and candle['close'] <= tp_val: return None
            if fvg_fully_broken(candle, fvg, stype):
                fvg_idx += 1; continue
            if candle_touches_fvg(candle, fvg, stype):
                phase = "WAIT_IDM_TOUCH"; fvg_touch_ts = candle['ts']
        elif phase in ("WAIT_IDM_TOUCH", "WAIT_BOS_BREAK", "WAIT_MSS"):
            if stype == "Long" and tp_val and candle['close'] >= tp_val: return None
            if stype == "Short" and tp_val and candle['close'] <= tp_val: return None

    # Jika masih di WAIT_FVG_TOUCH, cari fvg_idx yang paling relevan:
    # skip semua FVG yang sudah dilewati harga
    if phase == "WAIT_FVG_TOUCH":
        last_close = df_snap.iloc[-2]['close']
        while fvg_idx < len(gaps):
            fvg = gaps[fvg_idx]
            if stype == "Long" and last_close > fvg['top']:
                fvg_idx += 1; continue
            if stype == "Short" and last_close < fvg['bottom']:
                fvg_idx += 1; continue
            break
        # Kalau semua FVG dilewati: tetap return state dengan fvg_idx=0
        # Loop utama yang akan refresh FVG list (termasuk post-BOS FVG baru)
        # dan handle logika skip lebih lanjut
        if fvg_idx >= len(gaps):
            fvg_idx = 0

    state['fvg_idx'] = fvg_idx
    state['phase']   = phase
    state['fvg_touch_ts'] = fvg_touch_ts

    if stype == "Long":
        sl_below = [s for s in sl_h1 if s['val'] < swing_val]
        choch_r  = sl_below[-1]['val'] if sl_below else None
    else:
        sh_above = [s for s in sh_h1 if s['val'] > swing_val]
        choch_r  = sh_above[-1]['val'] if sh_above else None
    choch_r_s    = f"{choch_r:.6g}" if choch_r else "—"
    print(f"\n📊 {coin}: BOS {stype} | Swing: {swing_val:.6g} | Phase: {phase}")
    print(f"   ⛔ CHOCH batal     : {choch_r_s}  ({'tutup < ' if stype=='Long' else 'tutup > '}{choch_r_s})")
    for gi, g in enumerate(gaps):
        marker = "◀" if gi == fvg_idx else " "
        print(f"   {marker} FVG {gi+1}: bottom:{g['bottom']:.6g}  top:{g['top']:.6g}")
    return state


def reconstruct_state():
    for coin in SYMBOLS:
        try:
            time.sleep(1)
            df_h1 = get_data(coin, "60", limit=100)
            if df_h1 is None: continue
            state = replay_h1(coin, df_h1)
            if state:
                pending[coin] = state
        except Exception as e:
            print(f"⚠️ Replay {coin}: {e}")
    print(f"🔍 Selesai. {len(pending)} coin dimonitor.\n")


# ============================================================
# CORE LOOP
# FIX BUG #1 & #2 & #3 diterapkan di sini juga:
# - get_internal_gaps() pakai bos_idx
# - M5 anchor = bos_ts bukan swing_ts
# - FVG touch = candle_touches_fvg (wick masuk zona)
# ============================================================

def run_bot():
    print("BEG MONEY CONCEPTS")
    if not test_connection():
        print("⛔ Tidak bisa konek ke Bybit.")
        return
    reconstruct_state()

    while True:
        # Tunggu sampai candle M5 berikutnya close
        # M5 close setiap detik ke-0 dari menit 0,5,10,15,...
        now      = time.time()
        sec      = now % 300          # posisi dalam siklus 5 menit
        wait_sec = 300 - sec + 2      # +2 detik buffer agar candle benar-benar closed
        if wait_sec > 300: wait_sec = 2
        print(f"⏱️  Tunggu candle M5 close: {wait_sec:.0f} detik...")
        time.sleep(wait_sec)

        for coin in list(active_positions.keys()):
            try:
                check_trailing_sl(coin)
            except Exception as e:
                print(f"⚠️ Trailing SL {coin}: {e}")

        for coin in SYMBOLS:
            try:
                time.sleep(3)

                df_h1_live = get_data(coin, "60", limit=100)
                if df_h1_live is None: continue

                sh_h1, sl_h1 = find_last_swing_bos(df_h1_live)
                if not sh_h1 or not sl_h1: continue

                curr_h1   = df_h1_live.iloc[-1]
                closed_h1 = df_h1_live.iloc[-2]

                # ── PROSES SETUP PENDING ──────────────────────────────
                if coin in pending:
                    setup    = pending[coin]
                    stype     = setup['type']
                    fvg_idx   = setup['fvg_idx']
                    bos_idx   = setup.get('bos_idx', 0)
                    swing_val = setup.get('swing_val')

                    # Refresh FVG list + TP setiap loop pakai H1 terbaru
                    if bos_idx >= len(df_h1_live):
                        print(f"⚠️ {coin}: bos_idx {bos_idx} >= len H1 {len(df_h1_live)}, skip refresh")
                        fresh_gaps = []
                    else:
                        fresh_gaps = get_internal_gaps(df_h1_live, stype, bos_idx)
                    if fresh_gaps:
                        pending[coin]['fvg_list'] = fresh_gaps
                    fvg_list = pending[coin]['fvg_list']

                    # [v5.4b-1R] TP placeholder tetap 0 sampai entry tahu harga actual
                    pending[coin]['tp'] = 0
                    setup['tp']        = 0

                    # ── CEK CHOCH DULU: pembalikan struktur → setup batal ──────
                    # Cek sebelum print apapun agar tidak ada output spurious sebelum cancel.
                    choch_level = setup.get('choch_level')
                    if choch_level:
                        if stype == "Long" and curr_h1['close'] < choch_level:
                            print(f"🔄 {coin}: CHOCH — swing low {choch_level:.6f} ditembus. "
                                  f"BOS Long batal, struktur berganti Short.")
                            del pending[coin]; continue
                        if stype == "Short" and curr_h1['close'] > choch_level:
                            print(f"🔄 {coin}: CHOCH — swing high {choch_level:.6f} ditembus. "
                                  f"BOS Short batal, struktur berganti Long.")
                            del pending[coin]; continue

                    # Update fvg_idx: skip FVG yang sudah dilewati harga saat ini
                    if setup['phase'] == "WAIT_FVG_TOUCH":
                        curr_close = curr_h1['close']
                        new_idx    = fvg_idx
                        while new_idx < len(fvg_list):
                            fvg = fvg_list[new_idx]
                            if stype == "Long"  and curr_close > fvg['top']:    new_idx += 1; continue
                            if stype == "Short" and curr_close < fvg['bottom']: new_idx += 1; continue
                            break
                        if new_idx != fvg_idx:
                            pending[coin]['fvg_idx'] = new_idx
                            fvg_idx = new_idx
                        if fvg_idx >= len(fvg_list):
                            # Harga sudah melewati semua FVG — naik ke swing high baru.
                            # BOS tetap valid. FVG baru akan terbentuk dari leg naik ini.
                            # fresh_gaps sudah di-refresh dari H1 terbaru di atas,
                            # jadi FVG list sudah termasuk FVG dari leg terbaru.
                            # Reset ke FVG pertama yang masih valid (paling dekat harga).
                            pending[coin]['fvg_idx'] = 0
                            fvg_idx = 0
                            new_fvg_count = len(fvg_list)
                            # Update choch_level: hanya swing di luar range swing_val
                            if stype == "Long" and sl_h1:
                                sl_below = [s for s in sl_h1 if s['val'] < swing_val]
                                if sl_below:
                                    pending[coin]['choch_level'] = sl_below[-1]['val']
                            elif stype == "Short" and sh_h1:
                                sh_above = [s for s in sh_h1 if s['val'] > swing_val]
                                if sh_above:
                                    pending[coin]['choch_level'] = sh_above[-1]['val']
                            print(f"⏳ {coin}: Harga di atas semua FVG ({new_fvg_count} FVG tersedia). "
                                  f"BOS tetap valid — nunggu pullback ke FVG terbaru. "
                                  f"CHOCH level: {pending[coin].get('choch_level', '-')}")

                    # Timeout 24 jam sejak FVG disentuh
                    if setup['phase'] != "WAIT_FVG_TOUCH":
                        fvg_ts = setup.get('fvg_touch_ts') or 0
                        now_ms = int(__import__('time').time() * 1000)
                        elapsed_h = (now_ms - fvg_ts) / 3600000
                        if fvg_ts > 0 and elapsed_h > 24:
                            print(f"⏰ {coin}: Timeout 24 jam sejak FVG disentuh ({elapsed_h:.1f}j). Setup batal.")
                            del pending[coin]; continue

                    if fvg_idx >= len(fvg_list):
                        print(f"🗑️ {coin}: Semua FVG habis.")
                        del pending[coin]; continue

                    active_fvg = fvg_list[fvg_idx]

                    # ── PHASE 1: TUNGGU FVG H1 DISENTUH ──────────────
                    if setup['phase'] == "WAIT_FVG_TOUCH":
                        fvg_dir = "pullback ke" if stype == "Long" else "bounce ke"
                        print(f"⏳ {coin}: Nunggu {fvg_dir} FVG {fvg_idx+1}/{len(fvg_list)} "
                              f"[{active_fvg['bottom']} – {active_fvg['top']}] | "
                              f"Harga: {curr_h1['close']}")

                        if fvg_fully_broken(closed_h1, active_fvg, stype):
                            print(f"❌ {coin}: FVG {fvg_idx+1} ditembus → coba berikutnya.")
                            pending[coin]['fvg_idx'] += 1; continue

                        if candle_touches_fvg(closed_h1, active_fvg, stype):
                            bos_ts_ref   = setup.get('bos_ts', 0)
                            df_after_bos = df_h1_live[df_h1_live['ts'] > bos_ts_ref].iloc[:-1]
                            if not df_after_bos.empty:
                                lanjut_level = df_after_bos['low'].min() if stype == "Short" else df_after_bos['high'].max()
                                lanjut_str   = f"{lanjut_level:.6g}"
                            else:
                                lanjut_str   = "—"
                            print(f"✅ {coin}: FVG {fvg_idx+1} disentuh. Masuk M5.")
                            print(f"   🚀 Lanjut H1 batal : {lanjut_str}  ({'close < ' if stype == 'Short' else 'close > '}{lanjut_str} → konfirmasi lanjut {stype})")
                            pending[coin]['phase']        = "WAIT_IDM_TOUCH"
                            pending[coin]['fvg_touch_ts'] = closed_h1['ts']
                        else:
                            if stype == "Long" and setup['tp'] and curr_h1['close'] >= setup['tp']:
                                print(f"🗑️ {coin}: TP kena sebelum FVG."); del pending[coin]
                            elif stype == "Short" and setup['tp'] and curr_h1['close'] <= setup['tp']:
                                print(f"🗑️ {coin}: TP kena sebelum FVG."); del pending[coin]
                        continue

                    # ── AMBIL DATA M5 ─────────────────────────────────
                    time.sleep(3)

                    # Hitung limit dinamis: ambil candle dari anchor_ts sampai sekarang
                    # 1 candle M5 = 5 menit = 300 detik
                    anchor_ts = setup.get("fvg_touch_ts") or setup["bos_ts"]
                    now_ms    = int(time.time() * 1000)
                    elapsed_candles = max(100, int((now_ms - anchor_ts) / (5 * 60 * 1000)) + 50)
                    m5_limit  = min(elapsed_candles, 1000)  # Bybit max 1000

                    df_m5_live = get_data(coin, "5", limit=m5_limit)
                    if df_m5_live is None: continue

                    # Slice dari anchor_ts agar replay_m5 punya konteks lengkap
                    df_m5 = df_m5_live[df_m5_live["ts"] >= anchor_ts].reset_index(drop=True)
                    if len(df_m5) < 5:
                        # anchor_ts terlalu lama (> limit), pakai semua data yang ada
                        df_m5 = df_m5_live.reset_index(drop=True)

                    curr_m5 = df_m5.iloc[-2] if len(df_m5) >= 2 else df_m5.iloc[-1]

                    # ── PHASE 2: TUNGGU IDM TERSENTUH ────────────────
                    if setup['phase'] == "WAIT_IDM_TOUCH":
                        m5_state = replay_m5(df_m5, stype)

                        if m5_state['phase'] == 'WAIT_IDM':
                            idm_level = m5_state.get('idm_level')
                            if idm_level:
                                print(f"⏳ {coin}: IDM M5 @ {idm_level} | Harga M5: {curr_m5['close']} | Menunggu sentuhan...")
                            else:
                                print(f"⏳ {coin}: IDM M5 belum terbentuk | Harga M5: {curr_m5['close']}")
                            if stype == "Long" and setup['tp'] and curr_m5['close'] >= setup['tp']:
                                print(f"🗑️ {coin}: TP kena tanpa IDM."); del pending[coin]
                            elif stype == "Short" and setup['tp'] and curr_m5['close'] <= setup['tp']:
                                print(f"🗑️ {coin}: TP kena tanpa IDM."); del pending[coin]
                            continue

                        idm_level   = m5_state['idm_level']
                        freeze_high = m5_state['freeze_high']
                        freeze_low  = m5_state['freeze_low']
                        freeze_ts   = m5_state['freeze_ts']

                        # IDM#1 (inner_idm absent) → wajib BOS dulu → WAIT_BOS_BREAK
                        # IDM#2+ (inner_idm=True) → langsung bisa MSS → WAIT_MSS
                        next_phase = "WAIT_MSS" if setup.get('inner_idm') else "WAIT_BOS_BREAK"

                        if next_phase == "WAIT_BOS_BREAK":
                            print(f"💧 {coin}: IDM#1 tersentuh @ {idm_level} → tunggu BOS M5 dulu.")
                            print(f"   → Target BOS M5: {freeze_low if stype=='Long' else freeze_high}")
                        else:
                            print(f"💧 {coin}: IDM dalam BOS tersentuh @ {idm_level} → bisa MSS atau BOS lagi.")
                            print(f"   → Target BOS M5: {freeze_low if stype=='Long' else freeze_high}")
                            print(f"   → Target MSS   : {freeze_high if stype=='Long' else freeze_low}")

                        pending[coin]['phase']           = next_phase
                        pending[coin]['inner_idm']       = True
                        pending[coin]['idm_touched_val'] = idm_level
                        pending[coin]['m5_freeze_high']  = freeze_high
                        pending[coin]['m5_freeze_low']   = freeze_low
                        pending[coin]['m5_freeze_ts']    = freeze_ts
                        continue

                    # ── PHASE 3: TUNGGU BOS / SWEEP M5 ───────────────
                    if setup['phase'] == "WAIT_BOS_BREAK":
                        freeze_low  = setup['m5_freeze_low']
                        freeze_high = setup['m5_freeze_high']
                        freeze_ts   = setup['m5_freeze_ts']

                        # IDM pertama: wajib BOS dulu sebelum bisa entry
                        if stype == "Long":
                            print(f"⏳ {coin}: Nunggu BOS/Sweep M5 < {freeze_low:.6f} | MSS: {freeze_high:.6f} | Harga: {curr_m5['close']}")
                        else:
                            print(f"⏳ {coin}: Nunggu BOS/Sweep M5 > {freeze_high:.6f} | MSS: {freeze_low:.6f} | Harga: {curr_m5['close']}")

                        # Pastikan BOS M5 hanya dicari SETELAH fvg_touch_ts
                        fvg_ts_anchor = setup.get('fvg_touch_ts') or setup['bos_ts']
                        df_m5_fresh   = df_m5[df_m5['ts'] >= fvg_ts_anchor].reset_index(drop=True)
                        result = check_bos_or_sweep(df_m5_fresh, freeze_high, freeze_low, freeze_ts, stype)

                        if result['trigger'] is not None:
                            trigger    = result['trigger']
                            trigger_ts = result['ts']
                            new_fh     = result['nfh']
                            new_fl     = result['nfl']

                            if trigger == 'bos':
                                print(f"📉 {coin}: BOS M5 @ [{trigger_ts}] — cari IDM baru [{new_fl:.6g}–{new_fh:.6g}].")
                            else:
                                sweep_val = result.get('sweep_low') or result.get('sweep_high')
                                print(f"💫 {coin}: SWEEP M5 @ {sweep_val:.6f} — cari IDM baru [{new_fl:.6g}–{new_fh:.6g}].")

                            # Setelah BOS terbentuk → cari IDM baru di dalam range BOS
                            # IDM baru tersentuh nanti → baru bisa MSS (entry) atau BOS lagi
                            pending[coin].update({
                                'phase'          : "WAIT_IDM_TOUCH",
                                'fvg_touch_ts'   : trigger_ts,
                                'm5_freeze_high' : new_fh,
                                'm5_freeze_low'  : new_fl,
                                'm5_freeze_ts'   : trigger_ts,
                                'idm_touched_val': None,
                            })
                        else:
                            if stype == "Long" and setup['tp'] and curr_m5['close'] >= setup['tp']:
                                print(f"🗑️ {coin}: TP kena tanpa BOS/Sweep M5."); del pending[coin]
                            elif stype == "Short" and setup['tp'] and curr_m5['close'] <= setup['tp']:
                                print(f"🗑️ {coin}: TP kena tanpa BOS/Sweep M5."); del pending[coin]
                        continue

                    # ── PHASE 4: TUNGGU MSS ───────────────────────────
                    if setup['phase'] == "WAIT_MSS":
                        freeze_low  = setup['m5_freeze_low']
                        freeze_high = setup['m5_freeze_high']
                        freeze_ts   = setup['m5_freeze_ts']

                        if stype == "Long":
                            print(f"⏳ {coin}: Nunggu MSS break atas {freeze_high} | Harga M5: {curr_m5['close']}")
                        else:
                            print(f"⏳ {coin}: Nunggu MSS break bawah {freeze_low} | Harga M5: {curr_m5['close']}")

                        df_after = df_m5[df_m5['ts'] > freeze_ts]
                        if df_after.empty: continue

                        mss_candle = None; reset_to_idm = False
                        for _, c in df_after.iterrows():
                            if stype == "Long":
                                if c['close'] > freeze_high:
                                    mss_candle = c; break
                                elif c['close'] < freeze_low:
                                    reset_to_idm = True
                                    print(f"🔄 {coin}: Break bawah lagi. Cari IDM baru.")
                                    pending[coin].update({
                                        'phase': "WAIT_IDM_TOUCH",
                                        'fvg_touch_ts': int(c['ts']),
                                        'm5_freeze_high': None, 'm5_freeze_low': None, 'm5_freeze_ts': None
                                    }); break
                            else:
                                if c['close'] < freeze_low:
                                    mss_candle = c; break
                                elif c['close'] > freeze_high:
                                    reset_to_idm = True
                                    print(f"🔄 {coin}: Break atas lagi. Cari IDM baru.")
                                    # Anchor maju ke SETELAH candle yang break atas
                                    # Bukan curr_m5['ts'] — itu candle live terakhir yang sama terus
                                    # Pakai ts candle yang break agar replay M5 mulai dari sana
                                    pending[coin].update({
                                        'phase': "WAIT_IDM_TOUCH",
                                        'fvg_touch_ts': int(c['ts']),
                                        'm5_freeze_high': None, 'm5_freeze_low': None, 'm5_freeze_ts': None
                                    }); break

                        if reset_to_idm or mss_candle is None:
                            if not reset_to_idm:
                                if stype == "Long" and setup['tp'] and curr_m5['close'] >= setup['tp']:
                                    print(f"🗑️ {coin}: TP kena tanpa MSS."); del pending[coin]
                                elif stype == "Short" and setup['tp'] and curr_m5['close'] <= setup['tp']:
                                    print(f"🗑️ {coin}: TP kena tanpa MSS."); del pending[coin]
                            continue

                        # ─── [v5.4b] FIX #1: MSS CANDLE STRENGTH ────────────
                        # Fast SL root cause: MSS dipicu candle lemah (wick/doji).
                        # Candle MSS harus punya body >= 40% dari range (genuine momentum).
                        mss_body  = abs(float(mss_candle['close']) - float(mss_candle['open']))
                        mss_range = abs(float(mss_candle['high'])  - float(mss_candle['low']))
                        if mss_range > 0 and mss_body / mss_range < 0.30:
                            print(f"⚠️ {coin}: MSS candle terlalu lemah (body {mss_body/mss_range*100:.0f}% < 30%), skip.")
                            del pending[coin]
                            continue

                        # ─── [v5.4b] FIX #2: VOLUME RATIO FILTER ────────────
                        # Trades saat vol < 0.40× rata-rata = net negatif secara kolektif.
                        mss_vol     = float(mss_candle.get('vol', 0))
                        recent_vols = df_m5['vol'].tail(20)
                        avg_vol     = recent_vols.mean()
                        if avg_vol > 0 and mss_vol / avg_vol < 0.25:
                            print(f"⚠️ {coin}: Volume MSS terlalu rendah ({mss_vol/avg_vol:.2f}x < 0.25x), skip.")
                            del pending[coin]
                            continue

                        # ── ATR Filter Adaptif ──────────────────────────────
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
                        atr_thresh = ATR_THRESHOLD.get(coin, 0.0035)
                        df_atr_m5  = get_data(coin, "5", limit=20)
                        if df_atr_m5 is not None and len(df_atr_m5) >= 5:
                            hh = df_atr_m5['high']; ll = df_atr_m5['low']
                            pc = df_atr_m5['close'].shift(1)
                            tr = pd.concat([hh-ll, (hh-pc).abs(), (ll-pc).abs()], axis=1).max(axis=1)
                            atr_m5_val = tr.mean()
                            ref_price  = float(df_atr_m5['close'].iloc[-1])
                            if ref_price > 0 and (atr_m5_val / ref_price) < atr_thresh:
                                print(f"⚠️ {coin}: ATR {atr_m5_val/ref_price*100:.3f}%"
                                      f" < threshold {atr_thresh*100:.2f}% — sideways, skip.")
                                continue

                        # MSS confirmed — cari entry terbaik
                        # Prioritas: Breaker Block > FVG H1
                        side_order = "Buy" if stype == "Long" else "Sell"

                        bb = find_breaker_block(df_m5, mss_candle['ts'], stype)

                        if bb is not None:
                            # Gunakan Breaker Block sebagai entry
                            entry_price = bb['entry']
                            sl_price    = bb['sl']
                            print(f"🧱 {coin}: Breaker Block @ {entry_price:.6f} | SL {sl_price:.6f}")
                        else:
                            # Fallback: FVG H1 jika Breaker Block tidak ditemukan
                            entry_fvg = None; entry_price = None
                            for fvg in fvg_list:
                                if price_in_fvg(mss_candle['high'], mss_candle['low'], fvg):
                                    entry_fvg   = fvg
                                    entry_price = fvg['top'] if stype == "Long" else fvg['bottom']
                                    break

                            if entry_fvg is None:
                                # Tidak ada BB dan tidak ada FVG → gunakan nfh/nfl sebagai RBS
                                entry_price = freeze_high if stype == "Long" else freeze_low
                                print(f"↩️ {coin}: No BB/FVG, fallback RBS @ {entry_price:.6f}")

                            # SL di ujung MSS candle — Low untuk Long, High untuk Short
                            sl_price = mss_candle['low'] if stype == "Long" else mss_candle['high']
                            print(f"🎯 {coin}: FVG/RBS entry @ {entry_price} | SL {sl_price}")

                        if entry_price is None or sl_price is None:
                            print(f"⚠️ {coin}: Tidak bisa tentukan entry, skip.")
                            continue

                        dist = abs(entry_price - sl_price)
                        if dist == 0:
                            print(f"⚠️ {coin}: Entry = SL, skip.")
                            continue

                        # [v5.5-3R] TP = 3R dari entry
                        # Backtest 10 coin Jan-Jun 2025: +$11.84 (+39.5% ROI), PF 3.25, MaxDD 4.4%
                        # vs 1R: +$5.06 (+16.9%), WR turun 78%→56% tapi PnL 134% lebih besar
                        tp_dist_3r = abs(entry_price - sl_price) * 3
                        if tp_dist_3r == 0:
                            tp_dist_3r = entry_price * 0.015
                        if stype == "Long":
                            final_tp = round(entry_price + tp_dist_3r, 8)
                        else:
                            final_tp = round(entry_price - tp_dist_3r, 8)

                        print(f"🎯 {coin}: {side_order} @ {entry_price} | SL {sl_price} | TP {final_tp}")

                        if place_limit_order(coin, side_order, entry_price, sl_price, final_tp):
                            print(f"✅ {coin}: ORDER TERPASANG!")
                            import time as _time
                            active_positions[coin] = {
                                'side'       : side_order,
                                'entry'      : entry_price,
                                'sl'         : sl_price,
                                'sl_dist'    : dist,
                                'tp'         : setup['tp'],
                                'sl_moved'   : False,
                                'entry_time' : _time.time(),   # [v5.4b] untuk Time-BE
                            }
                            del pending[coin]
                        else:
                            print(f"⚠️ {coin}: Gagal pasang order. Setup dibatalkan agar tidak retry terus.")
                            del pending[coin]
                    continue

                # ── SCAN BOS H1 BARU — last 3 swing kandidat ──────────
                is_long = False; is_short = False
                swing_val = None; bos_idx = None; ref_idx = None

                for sh in sh_h1[-3:]:
                    if closed_h1['close'] > sh['val']:
                        is_long   = True
                        swing_val = sh['val']
                        ref_idx   = sl_h1[-1]['idx'] if sl_h1 else sh['idx']
                        bos_idx   = ref_idx
                for sl in sl_h1[-3:]:
                    if closed_h1['close'] < sl['val']:
                        is_short  = True
                        swing_val = sl['val']
                        ref_idx   = sh_h1[-1]['idx'] if sh_h1 else sl['idx']
                        bos_idx   = ref_idx

                if not (is_long or is_short): continue
                if swing_val is None or bos_idx is None: continue
                stype = "Short" if is_short else "Long"

                # [v5] FIX #3: TREND FILTER EMA50 H1
                ema50 = calc_ema(df_h1_live['close'], 50).iloc[-1]
                if stype == "Long"  and curr_h1['close'] < ema50:
                    continue
                if stype == "Short" and curr_h1['close'] > ema50:
                    continue

                df_h1_snap = df_h1_live.copy()
                gaps = get_internal_gaps(df_h1_snap, stype, bos_idx)
                if not gaps:
                    print(f"⚠️ {coin}: BOS {stype} tapi tidak ada FVG di dalam range.")
                    continue

                # [v5] FIX #5: Smart TP berbasis swing struktural H1
                atr_h1_now = calc_atr(df_h1_snap, 14).iloc[-1]
                if pd.isna(atr_h1_now) or atr_h1_now <= 0: continue
                # FIX #2: anchor M5 dari bos_ts
                bos_ts    = df_h1_snap['ts'].iloc[bos_idx]
                # tp_val sementara pakai ATR — akan direset saat entry tahu entry_price
                tp_val    = None  # dihitung ulang saat MSS + entry dikonfirmasi

                # Deduplikasi: jangan overwrite pending kalau swing_val sama
                # (swing idx berubah tiap fetch, tapi value stabil)
                existing = pending.get(coin)
                if existing and existing.get('swing_val') == swing_val and existing.get('type') == stype:
                    continue  # BOS yang sama, skip

                if stype == "Long":
                    sl_below    = [s for s in sl_h1 if s['val'] < swing_val]
                    choch_level = sl_below[-1]['val'] if sl_below else None
                else:
                    sh_above    = [s for s in sh_h1 if s['val'] > swing_val]
                    choch_level = sh_above[-1]['val'] if sh_above else None

                pending[coin] = {
                    'type': stype, 'df_h1': df_h1_snap,
                    'fvg_list': gaps, 'fvg_idx': 0,
                    'tp': tp_val, 'bos_ts': bos_ts, 'bos_idx': bos_idx,
                    'swing_val': swing_val,
                    'choch_level': choch_level,
                    'phase': "WAIT_FVG_TOUCH", 'fvg_touch_ts': bos_ts,
                    'm5_freeze_high': None, 'm5_freeze_low': None, 'm5_freeze_ts': None,
                    'idm_list': [], 'idm_touched_val': None,
                }
                choch_str    = f"{choch_level:.6g}" if choch_level else "—"
                print(f"\n📊 {coin} | Swing: {swing_val:.6g} | C: {curr_h1['close']:.6g}")
                print(f"🎯 {coin}: BOS {stype} | {len(gaps)} FVG")
                print(f"   ⛔ CHOCH batal     : {choch_str}  ({'tutup < ' if stype=='Long' else 'tutup > '}{choch_str})")
                for i, g in enumerate(gaps):
                    print(f"   FVG {i+1}: bottom:{g['bottom']:.6g}  top:{g['top']:.6g}")

            except Exception as e:
                print(f"⚠️ Error {coin}: {e}"); continue

        # Tidak perlu sleep — timing dihandle di awal loop (tunggu M5 close)


if __name__ == "__main__":
    run_bot()
