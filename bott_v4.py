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

# ── Strategy params (sinkron dengan backtest.py) ─────────────
SL_MULT       = 6.2     # SL = SL_MULT × gap_size dari entry (fallback)
TRAIL_STOP    = 0.15    # trailing distance = TRAIL_STOP × dist (tight trail = capture besar)
SBR_MODE      = True    # True = SBR entry di C1.close + SL di C1.low, False = OCL entry lama
ENTRY_MODE    = 'fvg_limit'  # 'fvg_sbr' (market saat touch) | 'fvg_limit' (limit langsung di BOS)
TOUCH_VOL_MIN = 0.8     # touch candle volume min (× avg 20 M5 candle) — hanya dipakai fvg_sbr
MAX_GAP_PCT   = 0.006   # max gap_size / entry_price (FVG ≤ 0.60%)

SYMBOLS = [
    # Batch 1 (17 coin — removed: JUP, SEI, APE, XAUT)
    'XVGUSDT', 'BELUSDT', '1000BONKUSDT', 'BERAUSDT',
    '1000PEPEUSDT',
    'ONDOUSDT', 'EIGENUSDT', 'VIRTUALUSDT',
    'ENAUSDT', 'SHIB1000USDT',
    'OPUSDT', 'STXUSDT', 'ALGOUSDT',
    'ORCAUSDT', 'XRPUSDT', 'FARTCOINUSDT', 'TAOUSDT',
    # Batch 2 (7 coin — removed: TIA, AAVE, GALA, GMX, HBAR, AXS, DYDX)
    'SOLUSDT', 'SUIUSDT', 'IMXUSDT',
    'SANDUSDT', 'LTCUSDT', 'FLOWUSDT', 'ICPUSDT',
]

ATR_THRESHOLD = {
    # ATR P25 dari backtest Jan2025–Apr2026
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
    'OPUSDT'        : 0.0028,   # P25=0.277%
    'STXUSDT'       : 0.0023,   # P25=0.229%
    'ALGOUSDT'      : 0.0023,   # P25=0.228%
    'ORCAUSDT'      : 0.0021,   # P25=0.214%
    'XRPUSDT'       : 0.0018,   # P25=0.185%
    'FARTCOINUSDT'  : 0.0050,   # P25=0.503%
    'TAOUSDT'       : 0.0031,   # P25=0.313%
    'SOLUSDT'       : 0.0022,   # P25=0.217%
    'SUIUSDT'       : 0.0026,   # P25=0.263%
    'IMXUSDT'       : 0.0028,   # P25=0.276%
    'SANDUSDT'      : 0.0022,   # P25=0.220%
    'LTCUSDT'       : 0.0018,   # P25=0.178%
    'FLOWUSDT'      : 0.0020,   # P25=0.200%
    'ICPUSDT'       : 0.0023,   # P25=0.231%
}

pending          = {}
active_positions = {}
instrument_cache = {}
done_setups      = {}   # coin -> (swing_val, type) — cegah re-entry di BOS yang sama


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
                'min_qty'     : float(lot['minOrderQty']),
                'qty_step'    : float(lot['qtyStep']),
                'tick_size'   : float(info['priceFilter']['tickSize']),
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
    highs, lows = [], []
    for i in range(2, len(df) - 2):
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        if (df['high'].iloc[i-2] < h and df['high'].iloc[i-1] < h and
                df['high'].iloc[i+1] < h and df['high'].iloc[i+2] < h):
            highs.append({'val': h, 'idx': i, 'ts': df['ts'].iloc[i]})
        if (df['low'].iloc[i-2] > l and df['low'].iloc[i-1] > l and
                df['low'].iloc[i+1] > l and df['low'].iloc[i+2] > l):
            lows.append({'val': l, 'idx': i, 'ts': df['ts'].iloc[i]})
    return highs, lows


# ============================================================
# FVG — dengan volume fields untuk fvg_strong
# ============================================================

def _gap_vol_fields(df, c3_idx):
    """Extract volume + OCL + C1 fields untuk FVG (df dalam H1). C1=c3_idx-2."""
    c2_idx   = c3_idx - 1
    c1_idx   = c3_idx - 2
    c2_close = float(df['close'].iloc[c2_idx]) if c2_idx >= 0 else 0.0
    c3_open  = float(df['open'].iloc[c3_idx])  if c3_idx < len(df) else 0.0
    c1_open  = float(df['open'].iloc[c1_idx])  if c1_idx >= 0 else 0.0
    c1_close = float(df['close'].iloc[c1_idx]) if c1_idx >= 0 else 0.0
    c1_low   = float(df['low'].iloc[c1_idx])   if c1_idx >= 0 else 0.0
    c1_high  = float(df['high'].iloc[c1_idx])  if c1_idx >= 0 else 0.0
    base = {'c2_close': c2_close, 'c3_open': c3_open,
            'c1_open': c1_open, 'c1_close': c1_close,
            'c1_low': c1_low,   'c1_high': c1_high}
    if 'vol' not in df.columns:
        return {**base, 'c3_vol': 0.0, 'vol_avg20h': 0.0}
    c3_vol    = float(df['vol'].iloc[c3_idx])
    avg_start = max(0, c3_idx - 20)
    vol_avg   = float(df['vol'].iloc[avg_start:c3_idx].mean()) if c3_idx > 0 else 0.0
    return {**base, 'c3_vol': c3_vol, 'vol_avg20h': vol_avg}


def get_internal_gaps(df, stype, bos_idx, lookback=60):
    gaps = []
    scan_start = max(2, bos_idx - lookback)

    # Pre-BOS FVG  (C1=i-2, C2=i-1, C3=i)
    for i in range(bos_idx - 1, scan_start, -1):
        gap = None
        if stype == "Long" and df['high'].iloc[i-2] < df['low'].iloc[i]:
            if not (df['close'].iloc[i-2] > df['open'].iloc[i-2] and
                    df['close'].iloc[i-1] > df['open'].iloc[i-1] and
                    df['close'].iloc[i]   > df['open'].iloc[i]):
                continue
            gap = {"top": df['low'].iloc[i], "bottom": df['high'].iloc[i-2], "zone": "pre"}
            gap.update(_gap_vol_fields(df, i))
        elif stype == "Short" and df['low'].iloc[i-2] > df['high'].iloc[i]:
            if not (df['close'].iloc[i-2] < df['open'].iloc[i-2] and
                    df['close'].iloc[i-1] < df['open'].iloc[i-1] and
                    df['close'].iloc[i]   < df['open'].iloc[i]):
                continue
            gap = {"top": df['low'].iloc[i-2], "bottom": df['high'].iloc[i], "zone": "pre"}
            gap.update(_gap_vol_fields(df, i))
        if gap:
            is_fresh = True
            for j in range(i + 1, bos_idx + 1):
                if stype == "Long"  and df['close'].iloc[j] < gap['bottom']: is_fresh = False; break
                if stype == "Short" and df['close'].iloc[j] > gap['top']:    is_fresh = False; break
            if is_fresh:
                gaps.append(gap)

    # Post-BOS FVG  (C1=i-1, C2=i, C3=i+1)
    post_end = len(df) - 2
    for i in range(bos_idx + 1, post_end):
        if i + 1 >= len(df): continue
        gap = None
        if stype == "Long" and df['high'].iloc[i-1] < df['low'].iloc[i+1]:
            if not (df['close'].iloc[i-1] > df['open'].iloc[i-1] and
                    df['close'].iloc[i]   > df['open'].iloc[i]   and
                    df['close'].iloc[i+1] > df['open'].iloc[i+1]):
                continue
            gap = {"top": df['low'].iloc[i+1], "bottom": df['high'].iloc[i-1], "zone": "post"}
            gap.update(_gap_vol_fields(df, i + 1))
        elif stype == "Short" and df['low'].iloc[i-1] > df['high'].iloc[i+1]:
            if not (df['close'].iloc[i-1] < df['open'].iloc[i-1] and
                    df['close'].iloc[i]   < df['open'].iloc[i]   and
                    df['close'].iloc[i+1] < df['open'].iloc[i+1]):
                continue
            gap = {"top": df['low'].iloc[i-1], "bottom": df['high'].iloc[i+1], "zone": "post"}
            gap.update(_gap_vol_fields(df, i + 1))
        if gap:
            is_fresh = True
            for j in range(i + 2, len(df)):
                if stype == "Long"  and df['close'].iloc[j] < gap['bottom']: is_fresh = False; break
                if stype == "Short" and df['close'].iloc[j] > gap['top']:    is_fresh = False; break
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


def _get_strong_fvgs(df_h1, stype, bos_idx, choch_level=None):
    """FVG kuat: C3 vol > avg20H, c3_open ada, c1_close ada, CHOCH filter, MAX_GAP_PCT filter."""
    gaps = get_internal_gaps(df_h1, stype, bos_idx)
    # Hanya FVG dengan volume kuat + C1/C3 fields valid
    gaps = [g for g in gaps
            if g.get('c3_vol', 0) > g.get('vol_avg20h', 0) > 0
            and g.get('c3_open', 0) > 0
            and g.get('c1_close', 0) > 0]
    # Filter FVG yang straddle CHOCH
    if choch_level:
        if stype == "Long":
            gaps = [g for g in gaps if g['bottom'] >= choch_level]
        else:
            gaps = [g for g in gaps if g['top'] <= choch_level]
    # MAX_GAP_PCT: gap tidak boleh terlalu besar
    result = []
    for g in gaps:
        gap_size = g['top'] - g['bottom']
        ocl      = float(g.get('c3_open', g['bottom'] if stype == 'Short' else g['top']))
        if ocl > 0 and MAX_GAP_PCT > 0 and gap_size / ocl > MAX_GAP_PCT:
            continue
        result.append(g)
    return result


# ============================================================
# FUNGSI ORDER
# ============================================================

def place_market_order(symbol, side, entry, sl, trail_dist):
    """
    Market order dengan trailing stop.
    trail_dist = jarak trailing dalam harga (= TRAIL_STOP × dist).
    SL awal = entry - dist (Long) / entry + dist (Short).
    """
    try:
        info     = get_instrument_info(symbol)
        res_bal  = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        balance  = float(res_bal['result']['list'][0]['totalEquity'])
        risk_usd = balance * 0.01
        dist     = abs(entry - sl)
        if dist == 0:
            print(f"⚠️ {symbol}: dist entry-SL = 0, skip.")
            return None

        min_dist = entry * 0.002   # 0.2% — sinkron dengan outer check dan backtest MIN_DIST_PCT
        if dist < min_dist:
            dist = min_dist
            sl   = entry - dist if side == "Buy" else entry + dist

        raw_qty = risk_usd / dist
        qty     = round_qty(raw_qty, info['qty_step'])
        if qty < info['min_qty']:
            print(f"⚠️ {symbol}: Qty {qty} < minOrderQty {info['min_qty']}, skip.")
            return None

        sl_r         = round_price(sl,         info['tick_size'])
        trail_dist_r = round_price(trail_dist,  info['tick_size'])
        if trail_dist_r <= 0:
            trail_dist_r = round_price(dist * TRAIL_STOP, info['tick_size'])

        lev_int = 10
        try:
            max_lev = float(info.get('max_leverage', 10))
            lev_int = int(min(10, max_lev))
            res_lev = session.set_leverage(category=CATEGORY, symbol=symbol,
                                           buyLeverage=str(lev_int), sellLeverage=str(lev_int))
            if res_lev.get('retCode', -1) not in (0, 110043):
                print(f"   ⚠️ {symbol}: set_leverage gagal: {res_lev.get('retMsg','')} "
                      f"(code:{res_lev.get('retCode')}) — coba lanjut")
        except Exception as e:
            print(f"   ⚠️ {symbol}: set_leverage error: {e} — coba lanjut")

        required_margin = (qty * entry) / lev_int
        if required_margin > balance * 0.9:
            print(f"⚠️ {symbol}: Margin tidak cukup — butuh ~${required_margin:.2f} "
                  f"(lev {lev_int}x), balance ${balance:.2f}. Skip.")
            return None

        print(f"   Balance:{balance:.2f} Risk:{risk_usd:.2f} Dist:{dist:.6f} "
              f"Trail:{trail_dist:.6f} Qty:{qty} SL:{sl_r} Lev:{lev_int}x "
              f"Margin:~${required_margin:.2f}")

        res = session.place_order(
            category=CATEGORY, symbol=symbol, side=side,
            orderType="Market", qty=str(qty),
            stopLoss=str(sl_r),
            positionIdx=0,
            timeInForce="IOC"
        )
        if res['retCode'] == 0:
            return res['result']['orderId']
        print(f"⚠️ {symbol}: Order ditolak → {res.get('retMsg','')} (code:{res['retCode']})")
        return None
    except Exception as e:
        print(f"⚠️ {symbol}: place_order error → {e}")
        return None


def place_limit_order(symbol, side, entry_p, sl_p):
    """
    Limit order GTC di entry_p, SL di sl_p.
    Trail dipasang setelah fill terdeteksi via WAIT_FILL loop.
    """
    try:
        info     = get_instrument_info(symbol)
        res_bal  = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        balance  = float(res_bal['result']['list'][0]['totalEquity'])
        risk_usd = balance * 0.01
        dist     = abs(entry_p - sl_p)
        if dist == 0:
            print(f"⚠️ {symbol}: dist entry-SL = 0, skip.")
            return None

        min_dist = entry_p * 0.002
        if dist < min_dist:
            dist  = min_dist
            sl_p  = entry_p - dist if side == "Buy" else entry_p + dist

        raw_qty = risk_usd / dist
        qty     = round_qty(raw_qty, info['qty_step'])
        if qty < info['min_qty']:
            print(f"⚠️ {symbol}: Qty {qty} < minOrderQty {info['min_qty']}, skip.")
            return None

        entry_r = round_price(entry_p, info['tick_size'])
        sl_r    = round_price(sl_p,    info['tick_size'])

        lev_int = 10
        try:
            max_lev = float(info.get('max_leverage', 10))
            lev_int = int(min(10, max_lev))
            res_lev = session.set_leverage(category=CATEGORY, symbol=symbol,
                                           buyLeverage=str(lev_int), sellLeverage=str(lev_int))
            if res_lev.get('retCode', -1) not in (0, 110043):   # 110043 = sudah di leverage ini
                print(f"   ⚠️ {symbol}: set_leverage gagal: {res_lev.get('retMsg','')} "
                      f"(code:{res_lev.get('retCode')}) — coba lanjut")
        except Exception as e:
            print(f"   ⚠️ {symbol}: set_leverage error: {e} — coba lanjut")

        # Pre-check margin: qty × entry / leverage harus < 90% balance
        required_margin = (qty * entry_p) / lev_int
        if required_margin > balance * 0.9:
            print(f"⚠️ {symbol}: Margin tidak cukup — butuh ~${required_margin:.2f} "
                  f"(lev {lev_int}x), balance ${balance:.2f}. Skip.")
            return None

        print(f"   Balance:{balance:.2f} Risk:{risk_usd:.2f} Dist:{dist:.6f} "
              f"Qty:{qty} LimitEntry:{entry_r} SL:{sl_r} Lev:{lev_int}x "
              f"Margin:~${required_margin:.2f}")

        res = session.place_order(
            category=CATEGORY, symbol=symbol, side=side,
            orderType="Limit", qty=str(qty),
            price=str(entry_r),
            stopLoss=str(sl_r),
            positionIdx=0,
            timeInForce="GTC"
        )
        if res['retCode'] == 0:
            return res['result']['orderId']
        print(f"⚠️ {symbol}: Limit order ditolak → {res.get('retMsg','')} (code:{res['retCode']})")
        return None
    except Exception as e:
        print(f"⚠️ {symbol}: place_limit_order error → {e}")
        return None


def cancel_order(symbol, order_id):
    """Batalkan pending order di Bybit."""
    try:
        res = session.cancel_order(category=CATEGORY, symbol=symbol, orderId=order_id)
        if res['retCode'] == 0:
            print(f"   ✅ {symbol}: Order {order_id[:8]}… dibatalkan.")
        else:
            print(f"   ⚠️ {symbol}: Cancel gagal → {res.get('retMsg','')} (code:{res['retCode']})")
    except Exception as e:
        print(f"   ⚠️ {symbol}: cancel_order error → {e}")


def _order_exists(symbol, order_id):
    """True jika limit order masih aktif (belum filled/cancelled) di Bybit."""
    try:
        res = session.get_open_orders(category=CATEGORY, symbol=symbol, orderId=order_id)
        if res['retCode'] == 0:
            return len(res['result']['list']) > 0
    except Exception:
        pass
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


def move_sl(symbol, new_sl, side="Buy"):
    try:
        res = session.set_trading_stop(
            category=CATEGORY, symbol=symbol,
            stopLoss=str(new_sl),
            positionIdx=0
        )
        return res['retCode'] == 0
    except:
        return False


# ============================================================
# TRAILING SL + REVERSE POSITION
# ============================================================

def _get_actual_exit_price(symbol):
    """
    Query Bybit closed PnL untuk ambil harga exit actual posisi terakhir.
    Lebih akurat dari last_price (mark price di cek sebelumnya).
    """
    try:
        res = session.get_closed_pnl(category=CATEGORY, symbol=symbol, limit=1)
        if res['retCode'] == 0 and res['result']['list']:
            last = res['result']['list'][0]
            exit_p = float(last.get('avgExitPrice', 0))
            if exit_p > 0:
                return exit_p
    except Exception as e:
        print(f"⚠️ {symbol}: get_closed_pnl error: {e}")
    return None


def check_trailing_sl(coin):
    """
    Dipanggil setiap M5 close.

    Reverse logic:
    - Bot cek setiap M5 (5 menit). SL bisa kena kapan saja dalam candle.
    - Saat posisi tutup terdeteksi, query get_closed_pnl untuk harga exit actual
      (bukan last_price yang hanya mark price dari cek sebelumnya).
    - Reverse dibuka sebagai market order di harga pasar saat itu.
    - SL reverse = exit_actual ± dist (sama dengan dist trade asli).
    """
    if coin not in active_positions:
        return

    p   = active_positions[coin]
    pos = get_open_position(coin)

    if pos is None:
        # Posisi sudah tutup — ambil harga exit actual dari Bybit
        entry     = p['entry']
        side      = p['side']
        dist      = p.get('dist', 0)
        rev_count = p.get('rev_count', 0)

        # Harga exit actual dari Bybit closed PnL
        actual_exit = _get_actual_exit_price(coin)
        last_price  = p.get('last_price', entry)

        if TRAIL_STOP > 0 and dist > 0 and rev_count < 2:
            # Gunakan actual_exit jika ada, fallback ke last_price/sl
            if actual_exit:
                exit_price = actual_exit
            else:
                exit_price = last_price

            moved      = (exit_price - entry) if side == "Buy" else (entry - exit_price)
            imm_sl     = moved < -0.9 * dist          # keluar dekat SL awal, belum sempat bergerak
            trail_hit  = p.get('trail_engaged', False) # pernah capai BE atau lebih

            print(f"📊 {coin}: Posisi tutup | entry:{entry:.6f} exit:{exit_price:.6f} "
                  f"moved:{moved/dist:.2f}R | imm_sl={imm_sl} trail={trail_hit}")

            if imm_sl or trail_hit:
                rev_side  = "Sell" if side == "Buy" else "Buy"
                # SL reverse = jarak dist dari harga exit actual
                rev_sl    = exit_price - dist if rev_side == "Buy" else exit_price + dist
                rev_trail = TRAIL_STOP * dist
                reason    = "imm" if imm_sl else "trail"
                print(f"🔄 {coin}: Reverse {rev_side} @ market "
                      f"(exit actual:{exit_price:.6f}) SL:{rev_sl:.6f} (rev#{rev_count+1})")

                order_id = place_market_order(coin, rev_side, exit_price, rev_sl, rev_trail)
                if order_id:
                    active_positions[coin] = {
                        'side'          : rev_side,
                        'entry'         : exit_price,
                        'sl'            : rev_sl,
                        'dist'          : dist,
                        'trail_dist'    : rev_trail,
                        'trail_engaged' : False,
                        'trail_set'     : False,
                        'last_price'    : exit_price,
                        'rev_count'     : rev_count + 1,
                        'entry_time'    : time.time(),
                    }
                    return

        pnl_str = f"{actual_exit:.6f}" if actual_exit else "?"
        print(f"📭 {coin}: Posisi tutup @ {pnl_str}.")
        done_setups[coin] = (p.get('swing_val'), p.get('bos_type'))
        del active_positions[coin]
        return

    # Posisi masih buka — update last_price dan cek trail_engaged
    try:
        curr_price = float(pos['markPrice'])
        active_positions[coin]['last_price'] = curr_price

        entry = p['entry']
        dist  = p.get('dist', 0)
        side  = p['side']

        # Pasang trailing stop via set_trading_stop saat pertama posisi terdeteksi
        # activePrice = entry + dist (Long) / entry - dist (Short) → trail aktif setelah +1R profit
        # Sinkron dengan backtest: trail hanya bergerak setelah peak >= entry + dist
        if TRAIL_STOP > 0 and dist > 0 and not p.get('trail_set', False):
            trail_dist = p.get('trail_dist', TRAIL_STOP * dist)
            info       = get_instrument_info(coin)
            tick       = info.get('tick_size', 0.0001)
            trail_r    = round_price(trail_dist, tick)
            active_p   = round_price(entry + dist if side == "Buy" else entry - dist, tick)
            if trail_r > 0 and active_p > 0:
                try:
                    res_ts = session.set_trading_stop(
                        category=CATEGORY, symbol=coin,
                        trailingStop=str(trail_r),
                        activePrice=str(active_p),
                        positionIdx=0
                    )
                    if res_ts['retCode'] == 0:
                        active_positions[coin]['trail_set'] = True
                        print(f"📍 {coin}: Trailing stop {trail_r} dipasang "
                              f"(aktif @ {active_p} = entry+1R)")
                    else:
                        print(f"⚠️ {coin}: Gagal set trailing stop: "
                              f"{res_ts.get('retMsg','')} (code:{res_ts['retCode']})")
                except Exception as e:
                    print(f"⚠️ {coin}: set_trading_stop error: {e}")

        if dist > 0 and not p.get('trail_engaged', False):
            if side == "Buy"  and curr_price >= entry + dist:
                active_positions[coin]['trail_engaged'] = True
                print(f"✅ {coin}: Trail engaged @ {curr_price:.6f} (BE+ 1R)")
            elif side == "Sell" and curr_price <= entry - dist:
                active_positions[coin]['trail_engaged'] = True
                print(f"✅ {coin}: Trail engaged @ {curr_price:.6f} (BE+ 1R)")
    except Exception:
        pass


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
# REPLAY H1 — reconstruct state saat startup (fvg_strong)
# ============================================================

def replay_h1(coin, df_h1):
    sh_h1, sl_h1 = find_last_swing_bos(df_h1)
    if not sh_h1 or not sl_h1:
        return None

    closed_h1 = df_h1.iloc[-2]
    is_long = False; is_short = False
    swing_val = None; bos_idx = None

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

    if not (is_long or is_short):
        return None

    stype = "Short" if is_short else "Long"

    if stype == "Long":
        sl_below    = [s for s in sl_h1 if s['val'] < swing_val]
        choch_level = sl_below[-1]['val'] if sl_below else None
    else:
        sh_above    = [s for s in sh_h1 if s['val'] > swing_val]
        choch_level = sh_above[-1]['val'] if sh_above else None

    gaps = _get_strong_fvgs(df_h1, stype, bos_idx, choch_level)
    if not gaps:
        return None

    bos_ts = df_h1['ts'].iloc[bos_idx]
    state  = {
        'type'        : stype,
        'phase'       : 'WAIT_FVG_TOUCH',
        'fvg_list'    : gaps,
        'fvg_idx'     : 0,
        'bos_ts'      : bos_ts,
        'bos_idx'     : bos_idx,
        'swing_val'   : swing_val,
        'choch_level' : choch_level,
    }

    choch_str = f"{choch_level:.6g}" if choch_level else "—"
    print(f"\n📊 {coin}: BOS {stype} | Swing: {swing_val:.6g} | {len(gaps)} FVG kuat")
    print(f"   ⛔ CHOCH batal: {choch_str}")
    for gi, g in enumerate(gaps):
        ocl      = g.get('c3_open', 0)
        sbr_lvl  = g.get('c1_close', 0)
        gap_size = g['top'] - g['bottom']
        ref_p    = ocl if ocl > 0 else (g['bottom'] if stype == 'Short' else g['top'])
        lbl      = ("RBS" if stype == "Long" else "SBR") if SBR_MODE else "OCL"
        entry_v  = sbr_lvl if SBR_MODE and sbr_lvl > 0 else ocl
        mode_lbl = f"{lbl}:{entry_v:.6g}"
        print(f"   FVG {gi+1}: bot:{g['bottom']:.6g} top:{g['top']:.6g} "
              f"{mode_lbl} gap:{abs(gap_size)/ref_p*100:.3f}%" if ref_p > 0 else
              f"   FVG {gi+1}: bot:{g['bottom']:.6g} top:{g['top']:.6g} {mode_lbl}")
    return state


def reconstruct_state():
    for coin in SYMBOLS:
        try:
            time.sleep(1)
            df_h1 = get_data(coin, "60", limit=100)
            if df_h1 is None:
                continue
            state = replay_h1(coin, df_h1)
            if state:
                pending[coin] = state
        except Exception as e:
            print(f"⚠️ Replay {coin}: {e}")
    print(f"🔍 Selesai. {len(pending)} coin dimonitor.\n")


# ============================================================
# CORE LOOP — fvg_strong strategy
# BOS H1 → FVG kuat (C3 vol > avg20H) → OCL touch M5
# → Touch vol filter → Entry market + trailing stop
# ============================================================

def run_bot():
    print("SMC FVG STRONG BOT — BOS H1 → Strong FVG → OCL M5 Entry")
    if not test_connection():
        print("⛔ Tidak bisa konek ke Bybit.")
        return
    if ENTRY_MODE != 'fvg_limit':
        reconstruct_state()

    while True:
        now      = time.time()
        sec      = now % 300
        wait_sec = 300 - sec + 2
        if wait_sec > 300:
            wait_sec = 2
        print(f"⏱️  Tunggu candle M5 close: {wait_sec:.0f} detik...")
        time.sleep(wait_sec)

        # Cek trailing SL semua posisi aktif
        for coin in list(active_positions.keys()):
            try:
                check_trailing_sl(coin)
            except Exception as e:
                print(f"⚠️ Trailing SL {coin}: {e}")

        for coin in SYMBOLS:
            try:
                time.sleep(3)

                # Jika posisi aktif sedang jalan, tidak buka setup baru
                if coin in active_positions:
                    continue

                df_h1_live = get_data(coin, "60", limit=100)
                if df_h1_live is None:
                    continue

                sh_h1, sl_h1 = find_last_swing_bos(df_h1_live)
                if not sh_h1 or not sl_h1:
                    continue

                closed_h1 = df_h1_live.iloc[-2]
                curr_h1   = df_h1_live.iloc[-1]

                # ── PROSES SETUP PENDING ─────────────────────────────
                if coin in pending:
                    setup    = pending[coin]
                    stype    = setup['type']
                    bos_idx  = setup.get('bos_idx', 0)
                    swing_val = setup.get('swing_val')

                    # CHOCH check — struktur batal
                    choch_level = setup.get('choch_level')
                    if choch_level:
                        if stype == "Long"  and curr_h1['close'] < choch_level:
                            if setup.get('order_id'):
                                cancel_order(coin, setup['order_id'])
                            done_setups.pop(coin, None)   # struktur reset → boleh re-entry nanti
                            print(f"🔄 {coin}: CHOCH — swing low {choch_level:.6f} ditembus. Setup batal.")
                            del pending[coin]; continue
                        if stype == "Short" and curr_h1['close'] > choch_level:
                            if setup.get('order_id'):
                                cancel_order(coin, setup['order_id'])
                            done_setups.pop(coin, None)
                            print(f"🔄 {coin}: CHOCH — swing high {choch_level:.6f} ditembus. Setup batal.")
                            del pending[coin]; continue

                    # Refresh FVG list dengan data H1 terbaru
                    # Recompute bos_idx dari bos_ts agar tidak drift setiap fetch baru
                    bos_ts_val = setup.get('bos_ts', 0)
                    bos_rows   = df_h1_live.index[df_h1_live['ts'] == bos_ts_val]
                    if len(bos_rows) > 0:
                        bos_idx = int(bos_rows[0])
                        pending[coin]['bos_idx'] = bos_idx
                    if bos_idx < len(df_h1_live):
                        fresh_gaps = _get_strong_fvgs(df_h1_live, stype, bos_idx, choch_level)
                        if fresh_gaps:
                            pending[coin]['fvg_list'] = fresh_gaps
                    else:
                        print(f"⚠️ {coin}: bos_idx {bos_idx} out of range H1 len={len(df_h1_live)}")

                    fvg_list = pending[coin]['fvg_list']
                    if not fvg_list:
                        if setup.get('order_id'):
                            cancel_order(coin, setup['order_id'])
                        print(f"🗑️ {coin}: Tidak ada FVG kuat tersisa.")
                        del pending[coin]; continue

                    # ── WAIT_FILL: limit order placed, nunggu fill ──────
                    if setup['phase'] == 'WAIT_FILL':
                        pos = get_open_position(coin)
                        if pos:
                            entry_p    = setup['entry']
                            sl_p       = setup['sl']
                            dist       = setup['dist']
                            side_order = "Buy" if stype == "Long" else "Sell"
                            trail_d    = TRAIL_STOP * dist
                            info       = get_instrument_info(coin)
                            tick       = info.get('tick_size', 0.0001)
                            trail_r    = round_price(trail_d, tick)
                            active_p   = round_price(
                                entry_p + dist if side_order == "Buy"
                                else entry_p - dist, tick)
                            if trail_r > 0 and active_p > 0:
                                try:
                                    session.set_trading_stop(
                                        category=CATEGORY, symbol=coin,
                                        trailingStop=str(trail_r),
                                        activePrice=str(active_p),
                                        positionIdx=0
                                    )
                                except Exception:
                                    pass
                            actual_entry = float(pos.get('avgPrice', entry_p))
                            active_positions[coin] = {
                                'side'          : side_order,
                                'entry'         : actual_entry,
                                'sl'            : sl_p,
                                'dist'          : dist,
                                'trail_dist'    : trail_d,
                                'trail_engaged' : False,
                                'trail_set'     : True,
                                'last_price'    : actual_entry,
                                'rev_count'     : 0,
                                'entry_time'    : time.time(),
                                'swing_val'     : setup.get('swing_val'),
                                'bos_type'      : stype,
                            }
                            done_setups[coin] = (setup.get('swing_val'), stype)
                            del pending[coin]
                            print(f"✅ {coin}: Limit filled! Entry:{actual_entry:.6f} "
                                  f"SL:{sl_p:.6f} Trail aktif setelah +1R")
                        else:
                            # Posisi belum terbuka — cek apakah order masih ada di Bybit
                            oid = setup.get('order_id')
                            if oid and not _order_exists(coin, oid):
                                # Order sudah hilang (filled+closed dlm 1 candle, atau dibatalkan)
                                print(f"⚠️ {coin}: Limit order hilang (filled+closed 1 candle "
                                      f"atau dibatalkan). Setup selesai.")
                                done_setups[coin] = (setup.get('swing_val'), stype)
                                del pending[coin]
                            else:
                                print(f"⏳ {coin}: Nunggu fill limit @ {setup['entry']:.6f} | "
                                      f"SL:{setup['sl']:.6f} | {stype} | H1:{curr_h1['close']:.6g}")
                        continue

                    # ── WAIT_FVG_TOUCH: scan M5 untuk OCL touch ──────
                    if setup['phase'] == 'WAIT_FVG_TOUCH':
                        # Ambil M5 terbaru — hanya butuh beberapa candle terakhir
                        df_m5 = get_data(coin, "5", limit=30)
                        if df_m5 is None:
                            continue

                        # Candle-candle yang valid: exclude candle live terakhir
                        df_m5_closed = df_m5.iloc[:-1]

                        found = False
                        for fvg in fvg_list:
                            gap_size = float(fvg['top']) - float(fvg['bottom'])
                            if gap_size <= 0:
                                continue

                            # ── SBR MODE: trigger & entry di C1.close (demand/supply zone) ──
                            # ── LEGACY MODE: trigger & entry di OCL = C3.open ────────────
                            if SBR_MODE:
                                c1_close = float(fvg.get('c1_close', 0))
                                c1_low   = float(fvg.get('c1_low',   0))
                                c1_high  = float(fvg.get('c1_high',  0))
                                if c1_close <= 0:
                                    continue
                                trigger_lvl = c1_close   # entry juga di sini (market order)
                                if stype == "Long":
                                    sl_nat = c1_low - gap_size * 0.1
                                else:
                                    sl_nat = c1_high + gap_size * 0.1
                            else:
                                ocl = float(fvg.get('c3_open',
                                            fvg['bottom'] if stype == 'Short' else fvg['top']))
                                if ocl <= 0:
                                    continue
                                trigger_lvl = ocl
                                sl_nat = (trigger_lvl - SL_MULT * gap_size if stype == "Long"
                                          else trigger_lvl + SL_MULT * gap_size)

                            # Scan hanya 3 candle terakhir (15 menit) — entry di harga market
                            scan_start = max(len(df_m5_closed) - 3, 0)
                            for ki in range(len(df_m5_closed) - 1, scan_start - 1, -1):
                                ck = df_m5_closed.iloc[ki]

                                touched = False
                                if stype == "Long"  and float(ck['low'])  <= trigger_lvl:
                                    touched = True
                                if stype == "Short" and float(ck['high']) >= trigger_lvl:
                                    touched = True
                                if not touched:
                                    continue

                                # FVG belum broken (close masih valid)
                                if stype == "Long"  and float(ck['close']) < float(fvg['bottom']):
                                    continue
                                if stype == "Short" and float(ck['close']) > float(fvg['top']):
                                    continue

                                # Touch volume filter
                                avg_start = max(0, ki - 20)
                                avg_tvol  = float(df_m5_closed.iloc[avg_start:ki]['vol'].mean()) \
                                            if ki > 0 else 0.0
                                t_vol     = float(ck['vol'])
                                tvol_ratio = t_vol / avg_tvol if avg_tvol > 0 else 0.0
                                if TOUCH_VOL_MIN > 0 and 0 < tvol_ratio < TOUCH_VOL_MIN:
                                    print(f"⚠️ {coin}: Touch vol rendah "
                                          f"({tvol_ratio:.2f}× < {TOUCH_VOL_MIN}×), skip.")
                                    continue

                                # Entry params
                                entry_p = trigger_lvl
                                dist    = abs(entry_p - sl_nat)
                                if dist < entry_p * 0.002:   # min 0.2% SL distance
                                    continue
                                sl_p    = sl_nat
                                trail_d = TRAIL_STOP * dist

                                side_order = "Buy" if stype == "Long" else "Sell"
                                mode_tag = ("RBS" if stype == "Long" else "SBR") if SBR_MODE else "OCL"
                                print(f"\n🎯 {coin}: {mode_tag} Touch! {stype} @ {entry_p:.6f} "
                                      f"| SL:{sl_p:.6f} dist:{dist/entry_p*100:.3f}% "
                                      f"| Trail:{trail_d:.6f} "
                                      f"| GapPct:{gap_size/entry_p*100:.3f}% "
                                      f"| VolRatio:{tvol_ratio:.2f}×")

                                order_id = place_market_order(coin, side_order,
                                                              entry_p, sl_p, trail_d)
                                if order_id:
                                    active_positions[coin] = {
                                        'side'          : side_order,
                                        'entry'         : entry_p,
                                        'sl'            : sl_p,
                                        'dist'          : dist,
                                        'trail_dist'    : trail_d,
                                        'trail_engaged' : False,
                                        'last_price'    : entry_p,
                                        'rev_count'     : 0,
                                        'entry_time'    : time.time(),
                                    }
                                    del pending[coin]
                                    found = True
                                    break
                                else:
                                    del pending[coin]
                                    found = True
                                    break

                            if found:
                                break

                        if not found:
                            if SBR_MODE:
                                lvl_list = [f"{float(g.get('c1_close', 0)):.6g}"
                                            for g in fvg_list if float(g.get('c1_close', 0)) > 0]
                            else:
                                lvl_list = [f"{float(g.get('c3_open', 0)):.6g}"
                                            for g in fvg_list if float(g.get('c3_open', 0)) > 0]
                            lvl_str = " / ".join(lvl_list) if lvl_list else "—"
                            mode_tag = ("RBS" if stype == "Long" else "SBR") if SBR_MODE else "OCL"
                            print(f"⏳ {coin}: Nunggu {mode_tag} touch @ {lvl_str} | "
                                  f"{len(fvg_list)} FVG | {stype} | "
                                  f"Harga H1: {curr_h1['close']:.6g}")
                    continue

                # ── SCAN BOS H1 BARU ──────────────────────────────────
                is_long = False; is_short = False
                swing_val = None; bos_idx = None

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

                if not (is_long or is_short):
                    continue
                if swing_val is None or bos_idx is None:
                    continue
                stype = "Short" if is_short else "Long"

                # CHOCH level
                if stype == "Long":
                    sl_below    = [s for s in sl_h1 if s['val'] < swing_val]
                    choch_level = sl_below[-1]['val'] if sl_below else None
                else:
                    sh_above    = [s for s in sh_h1 if s['val'] > swing_val]
                    choch_level = sh_above[-1]['val'] if sh_above else None

                # FVG kuat
                df_h1_snap = df_h1_live.copy()
                gaps = _get_strong_fvgs(df_h1_snap, stype, bos_idx, choch_level)
                if not gaps:
                    continue

                # Deduplikasi: jangan overwrite setup yang sama
                existing = pending.get(coin)
                if existing and existing.get('swing_val') == swing_val and existing.get('type') == stype:
                    continue

                # Skip BOS yang sudah pernah ditradingkan — tunggu swing baru
                done = done_setups.get(coin)
                if done and done == (swing_val, stype):
                    continue

                # Overwrite BOS berbeda: batalkan limit order lama jika ada
                if existing and existing.get('order_id'):
                    cancel_order(coin, existing['order_id'])

                bos_ts    = df_h1_snap['ts'].iloc[bos_idx]
                choch_str = f"{choch_level:.6g}" if choch_level else "—"

                if ENTRY_MODE == 'fvg_limit':
                    # Ambil FVG pertama yang valid — langsung place limit order
                    chosen_fvg = None
                    for g in gaps:
                        c1_c = float(g.get('c1_close', 0))
                        c1_l = float(g.get('c1_low',   0))
                        c1_h = float(g.get('c1_high',  0))
                        if c1_c <= 0 or c1_h <= c1_l:
                            continue
                        c1_mid = (c1_h + c1_l) / 2.0
                        if stype == "Long"  and c1_c <= c1_mid: continue
                        if stype == "Short" and c1_c >= c1_mid: continue
                        chosen_fvg = g; break

                    if not chosen_fvg:
                        continue

                    c1_c   = float(chosen_fvg['c1_close'])
                    c1_l   = float(chosen_fvg['c1_low'])
                    c1_h   = float(chosen_fvg['c1_high'])
                    c1_mid = (c1_h + c1_l) / 2.0
                    gap_s  = float(chosen_fvg['top']) - float(chosen_fvg['bottom'])
                    dist   = abs(c1_c - c1_mid)

                    if dist < c1_c * 0.002:
                        continue  # SL terlalu dekat entry

                    side_order = "Buy" if stype == "Long" else "Sell"
                    print(f"\n📊 {coin} | BOS {stype} | FVG Limit @ {c1_c:.6f} | "
                          f"SL(mid):{c1_mid:.6f} dist:{dist/c1_c*100:.3f}% | "
                          f"GapPct:{gap_s/c1_c*100:.3f}% | CHOCH:{choch_str}")

                    order_id = place_limit_order(coin, side_order, c1_c, c1_mid)
                    if order_id:
                        pending[coin] = {
                            'type'        : stype,
                            'phase'       : 'WAIT_FILL',
                            'order_id'    : order_id,
                            'entry'       : c1_c,
                            'sl'          : c1_mid,
                            'dist'        : dist,
                            'fvg_list'    : gaps,
                            'bos_ts'      : bos_ts,
                            'bos_idx'     : bos_idx,
                            'swing_val'   : swing_val,
                            'choch_level' : choch_level,
                        }
                else:
                    pending[coin] = {
                        'type'        : stype,
                        'phase'       : 'WAIT_FVG_TOUCH',
                        'fvg_list'    : gaps,
                        'fvg_idx'     : 0,
                        'bos_ts'      : bos_ts,
                        'bos_idx'     : bos_idx,
                        'swing_val'   : swing_val,
                        'choch_level' : choch_level,
                    }
                    print(f"\n📊 {coin} | BOS {stype} | Swing: {swing_val:.6g} | C: {curr_h1['close']:.6g}")
                    print(f"   ⛔ CHOCH batal: {choch_str}")
                    print(f"   {len(gaps)} FVG kuat tersedia:")
                    for i, g in enumerate(gaps):
                        ocl      = g.get('c3_open', 0)
                        sbr_lvl  = g.get('c1_close', 0)
                        gap_size = g['top'] - g['bottom']
                        ref_p    = ocl if ocl > 0 else (g['bottom'] if stype == 'Short' else g['top'])
                        lbl      = ("RBS" if stype == "Long" else "SBR") if SBR_MODE else "OCL"
                        entry_v  = sbr_lvl if SBR_MODE and sbr_lvl > 0 else ocl
                        mode_lbl = f"{lbl}:{entry_v:.6g}"
                        print(f"   FVG {i+1}: bot:{g['bottom']:.6g} top:{g['top']:.6g} "
                              f"{mode_lbl} gap:{abs(gap_size)/ref_p*100:.3f}%" if ref_p > 0 else
                              f"   FVG {i+1}: bot:{g['bottom']:.6g} top:{g['top']:.6g} {mode_lbl}")

            except Exception as e:
                print(f"⚠️ Error {coin}: {e}"); continue


if __name__ == "__main__":
    run_bot()
