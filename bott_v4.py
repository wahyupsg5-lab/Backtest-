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
SL_MULT       = 6.2     # SL = SL_MULT × gap_size dari entry
TRAIL_STOP    = 2.0     # trailing distance = TRAIL_STOP × dist
TOUCH_VOL_MIN = 0.8     # touch candle volume min (× avg 20 M5 candle)
MAX_GAP_PCT   = 0.006   # max gap_size / entry_price (FVG ≤ 0.60%)

SYMBOLS = [
    # Core
    'XVGUSDT', 'BELUSDT', '1000BONKUSDT', 'BERAUSDT', 'USUALUSDT',
    '1000PEPEUSDT', 'WIFUSDT', 'PNUTUSDT',
    'ONDOUSDT', 'EIGENUSDT', 'LINKUSDT', 'VIRTUALUSDT', 'ORCAUSDT',
    # Rehabilitasi
    'DOGEUSDT', 'ARBUSDT', 'STORJUSDT', 'ENAUSDT',
    # Baru
    'SHIB1000USDT',
]

ATR_THRESHOLD = {
    'XVGUSDT'       : 0.0030,
    '1000PEPEUSDT'  : 0.0031,
    '1000BONKUSDT'  : 0.0035,
    'BELUSDT'       : 0.0024,
    'USUALUSDT'     : 0.0034,
    'BERAUSDT'      : 0.0032,
    'WIFUSDT'       : 0.0038,
    'PENGUUSDT'     : 0.0040,
    'PNUTUSDT'      : 0.0036,
    'AVAXUSDT'      : 0.0025,
    'ONDOUSDT'      : 0.0027,
    'EIGENUSDT'     : 0.0037,
    'LINKUSDT'      : 0.0025,
    'VIRTUALUSDT'   : 0.0040,
    'ORCAUSDT'      : 0.0024,
    'DOGEUSDT'      : 0.0024,
    'ARBUSDT'       : 0.0028,
    'NEARUSDT'      : 0.0029,
    'STORJUSDT'     : 0.0017,
    'ENAUSDT'       : 0.0039,
    'ADAUSDT'       : 0.0025,
    'SHIB1000USDT'  : 0.0020,
}

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
    for i in range(1, len(df) - 1):
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        if df['high'].iloc[i-1] < h and df['high'].iloc[i+1] < h:
            highs.append({'val': h, 'idx': i, 'ts': df['ts'].iloc[i]})
        if df['low'].iloc[i-1] > l and df['low'].iloc[i+1] > l:
            lows.append({'val': l, 'idx': i, 'ts': df['ts'].iloc[i]})
    return highs, lows


# ============================================================
# FVG — dengan volume fields untuk fvg_strong
# ============================================================

def _gap_vol_fields(df, c3_idx):
    """Extract volume + OCL fields untuk candle ke-3 FVG (df dalam H1)."""
    c2_idx   = c3_idx - 1
    c2_close = float(df['close'].iloc[c2_idx]) if c2_idx >= 0 else 0.0
    c3_open  = float(df['open'].iloc[c3_idx])  if c3_idx < len(df) else 0.0
    if 'vol' not in df.columns:
        return {'c3_vol': 0.0, 'vol_avg20h': 0.0, 'c2_close': c2_close, 'c3_open': c3_open}
    c3_vol    = float(df['vol'].iloc[c3_idx])
    avg_start = max(0, c3_idx - 20)
    vol_avg   = float(df['vol'].iloc[avg_start:c3_idx].mean()) if c3_idx > 0 else 0.0
    return {'c3_vol': c3_vol, 'vol_avg20h': vol_avg, 'c2_close': c2_close, 'c3_open': c3_open}


def get_internal_gaps(df, stype, bos_idx, lookback=60):
    gaps = []
    scan_start = max(2, bos_idx - lookback)

    # Pre-BOS FVG
    for i in range(bos_idx - 1, scan_start, -1):
        gap = None
        if stype == "Long" and df['high'].iloc[i-2] < df['low'].iloc[i]:
            gap = {"top": df['low'].iloc[i], "bottom": df['high'].iloc[i-2], "zone": "pre"}
            gap.update(_gap_vol_fields(df, i))
        elif stype == "Short" and df['low'].iloc[i-2] > df['high'].iloc[i]:
            gap = {"top": df['low'].iloc[i-2], "bottom": df['high'].iloc[i], "zone": "pre"}
            gap.update(_gap_vol_fields(df, i))
        if gap:
            is_fresh = True
            for j in range(i + 1, bos_idx + 1):
                if stype == "Long"  and df['close'].iloc[j] < gap['bottom']: is_fresh = False; break
                if stype == "Short" and df['close'].iloc[j] > gap['top']:    is_fresh = False; break
            if is_fresh:
                gaps.append(gap)

    # Post-BOS FVG
    post_end = len(df) - 2
    for i in range(bos_idx + 1, post_end):
        if i + 1 >= len(df): continue
        gap = None
        if stype == "Long" and df['high'].iloc[i-1] < df['low'].iloc[i+1]:
            gap = {"top": df['low'].iloc[i+1], "bottom": df['high'].iloc[i-1], "zone": "post"}
            gap.update(_gap_vol_fields(df, i + 1))
        elif stype == "Short" and df['low'].iloc[i-1] > df['high'].iloc[i+1]:
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
    """FVG kuat: C3 vol > avg20H, c2_close ada, CHOCH filter, MAX_GAP_PCT filter."""
    gaps = get_internal_gaps(df_h1, stype, bos_idx)
    # Hanya FVG dengan volume kuat (C3 candle volume lebih besar dari rata-rata)
    gaps = [g for g in gaps
            if g.get('c3_vol', 0) > g.get('vol_avg20h', 0) > 0
            and g.get('c2_close', 0) > 0]
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
        ocl      = float(g.get('c2_close', g['bottom'] if stype == 'Short' else g['top']))
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

        min_dist = entry * 0.005
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

        try:
            max_lev = float(info.get('max_leverage', 10))
            lev     = str(int(min(10, max_lev)))
            session.set_leverage(category=CATEGORY, symbol=symbol,
                                 buyLeverage=lev, sellLeverage=lev)
        except Exception:
            pass

        print(f"   Balance:{balance:.2f} Risk:{risk_usd:.2f} Dist:{dist:.6f} "
              f"Trail:{trail_dist:.6f} Qty:{qty} SL:{sl_r}")

        res = session.place_order(
            category=CATEGORY, symbol=symbol, side=side,
            orderType="Market", qty=str(qty),
            stopLoss=str(sl_r),
            timeInForce="IOC"
        )
        if res['retCode'] == 0:
            return res['result']['orderId']
        print(f"⚠️ {symbol}: Order ditolak → {res.get('retMsg','')} (code:{res['retCode']})")
        return None
    except Exception as e:
        print(f"⚠️ {symbol}: place_order error → {e}")
        return None


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
# TRAILING SL + REVERSE POSITION
# ============================================================

def check_trailing_sl(coin):
    """
    Dipanggil setiap M5 close.
    - Track trail_engaged: harga sudah lewati BE (TRAIL_STOP × dist dari entry)
    - Jika posisi tutup: cek apakah immediate SL atau trail → buka reverse (max 2×)
    Bybit handle trailing stop natively via trailingStop param saat order.
    Di sini kita tracking state untuk keputusan reverse.
    """
    if coin not in active_positions:
        return

    p   = active_positions[coin]
    pos = get_open_position(coin)

    if pos is None:
        # Posisi sudah tutup — keputusan reverse
        entry      = p['entry']
        side       = p['side']
        dist       = p.get('dist', 0)
        last_price = p.get('last_price', entry)
        rev_count  = p.get('rev_count', 0)

        if TRAIL_STOP > 0 and dist > 0 and rev_count < 2:
            moved = (last_price - entry) if side == "Buy" else (entry - last_price)
            imm_sl     = moved < -0.9 * dist           # exit sebelum sempat bergerak
            trail_hit  = p.get('trail_engaged', False)  # pernah BE atau lebih

            if imm_sl or trail_hit:
                rev_side  = "Sell" if side == "Buy" else "Buy"
                # Immediate SL: gunakan harga SL actual (bukan last_price yang bisa beda)
                rev_entry = p['sl'] if imm_sl else last_price
                rev_sl    = rev_entry - dist if rev_side == "Buy" else rev_entry + dist
                rev_trail = TRAIL_STOP * dist
                reason    = "imm" if imm_sl else "trail"
                print(f"🔄 {coin}: Posisi {side} tutup ({reason}) → "
                      f"Reverse {rev_side} @ {rev_entry:.6f} (rev#{rev_count+1})")

                order_id = place_market_order(coin, rev_side, rev_entry, rev_sl, rev_trail)
                if order_id:
                    active_positions[coin] = {
                        'side'          : rev_side,
                        'entry'         : rev_entry,
                        'sl'            : rev_sl,
                        'dist'          : dist,
                        'trail_dist'    : rev_trail,
                        'trail_engaged' : False,
                        'last_price'    : rev_entry,
                        'rev_count'     : rev_count + 1,
                        'entry_time'    : time.time(),
                    }
                    return

        print(f"📭 {coin}: Posisi tutup.")
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
        if TRAIL_STOP > 0 and dist > 0 and not p.get('trail_set', False):
            trail_dist = p.get('trail_dist', TRAIL_STOP * dist)
            info       = get_instrument_info(coin)
            trail_r    = round_price(trail_dist, info.get('tick_size', 0.0001))
            if trail_r > 0:
                try:
                    res_ts = session.set_trading_stop(
                        category=CATEGORY, symbol=coin,
                        trailingStop=str(trail_r), positionIdx=0
                    )
                    if res_ts['retCode'] == 0:
                        active_positions[coin]['trail_set'] = True
                        print(f"📍 {coin}: Trailing stop {trail_r} dipasang "
                              f"(dist={dist:.6f} × {TRAIL_STOP})")
                    else:
                        print(f"⚠️ {coin}: Gagal set trailing stop: "
                              f"{res_ts.get('retMsg','')} (code:{res_ts['retCode']})")
                except Exception as e:
                    print(f"⚠️ {coin}: set_trading_stop error: {e}")

        if dist > 0 and not p.get('trail_engaged', False):
            if side == "Buy"  and curr_price >= entry + TRAIL_STOP * dist:
                active_positions[coin]['trail_engaged'] = True
                print(f"✅ {coin}: Trail engaged @ {curr_price:.6f} (BE+)")
            elif side == "Sell" and curr_price <= entry - TRAIL_STOP * dist:
                active_positions[coin]['trail_engaged'] = True
                print(f"✅ {coin}: Trail engaged @ {curr_price:.6f} (BE+)")
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
        ocl = g.get('c2_close', 0)
        gap_size = g['top'] - g['bottom']
        print(f"   FVG {gi+1}: bot:{g['bottom']:.6g} top:{g['top']:.6g} "
              f"OCL:{ocl:.6g} gap:{gap_size/ocl*100:.3f}%")
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
                            print(f"🔄 {coin}: CHOCH — swing low {choch_level:.6f} ditembus. Setup batal.")
                            del pending[coin]; continue
                        if stype == "Short" and curr_h1['close'] > choch_level:
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
                        print(f"🗑️ {coin}: Tidak ada FVG kuat tersisa.")
                        del pending[coin]; continue

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
                            ocl      = float(fvg.get('c2_close',
                                       fvg['bottom'] if stype == 'Short' else fvg['top']))
                            if ocl <= 0:
                                continue

                            # Scan hanya 3 candle terakhir (15 menit) — entry di harga market
                            # sekarang, jadi sentuhan lama tidak relevan (harga sudah pindah)
                            scan_start = max(len(df_m5_closed) - 3, 0)
                            for ki in range(len(df_m5_closed) - 1, scan_start - 1, -1):
                                ck = df_m5_closed.iloc[ki]

                                touched = False
                                if stype == "Long"  and float(ck['low'])  <= ocl:
                                    touched = True
                                if stype == "Short" and float(ck['high']) >= ocl:
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
                                entry_p = ocl
                                dist    = SL_MULT * gap_size
                                if stype == "Long":
                                    sl_p = entry_p - dist
                                else:
                                    sl_p = entry_p + dist
                                trail_d = TRAIL_STOP * dist

                                side_order = "Buy" if stype == "Long" else "Sell"
                                print(f"\n🎯 {coin}: OCL Touch! {stype} @ {entry_p:.6f} "
                                      f"| SL:{sl_p:.6f} | Trail:{trail_d:.6f} "
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
                            ocl_list = [f"{float(g.get('c2_close', 0)):.6g}"
                                        for g in fvg_list if float(g.get('c2_close', 0)) > 0]
                            ocl_str  = " / ".join(ocl_list) if ocl_list else "—"
                            print(f"⏳ {coin}: Nunggu OCL touch @ {ocl_str} | "
                                  f"{len(fvg_list)} FVG | "
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

                bos_ts = df_h1_snap['ts'].iloc[bos_idx]
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
                choch_str = f"{choch_level:.6g}" if choch_level else "—"
                print(f"\n📊 {coin} | BOS {stype} | Swing: {swing_val:.6g} | C: {curr_h1['close']:.6g}")
                print(f"   ⛔ CHOCH batal: {choch_str}")
                print(f"   {len(gaps)} FVG kuat tersedia:")
                for i, g in enumerate(gaps):
                    ocl      = g.get('c2_close', 0)
                    gap_size = g['top'] - g['bottom']
                    print(f"   FVG {i+1}: bot:{g['bottom']:.6g} top:{g['top']:.6g} "
                          f"OCL:{ocl:.6g} gap:{gap_size/ocl*100:.3f}%")

            except Exception as e:
                print(f"⚠️ Error {coin}: {e}"); continue


if __name__ == "__main__":
    run_bot()
