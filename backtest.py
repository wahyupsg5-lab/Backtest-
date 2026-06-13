"""
smc_logic_v5.py — LOGIKA DETEKSI v9.7 (MURNI, tanpa API/order/log-server).
Diekstrak verbatim dari bott_v5_smc.py supaya live & backtest pakai SATU sumber logika.
build_setup_from_bos(...) -> (setup_dict, logline). Pada skip gate IDM, logline berformat
"IDM_SKIP::<stype|break|choch>::<pesan break/choch/puncak>" (dipakai backtest utk log+dedup).
"""
import datetime as _dt
import numpy as np
import pandas as pd

def get_data(*a, **k):
    return None


# ===== CONFIG (snapshot v9.7) =====
SWING_BARS = 5
SUBLEG_BARS = 3
RETRACE_LOCK = 0.5
REBREAK_INVALID = True
ZONE_FROM_RETRACE = True
ENTRY_ZONE_LO = 0.618
ENTRY_ZONE_HI = 1.0
ENTRY_C2_WICK = True
REQUIRE_FRESH_C1 = True
MAX_GAP_PCT = 0.0
SL_FRAC = 1.0
SL_CAP_RANGE = 0.1
SL_FIXED_RANGE = True
MIN_DIST_FLOOR = True
INDUCEMENT_ENTRY = True
INDUCEMENT_ZONE_LO = 0.35
INDUCEMENT_ZONE_HI = 0.55
INDUCEMENT_TF = '60'
INDUCEMENT_SWING = 1
INDUCEMENT_SWING_MAX = 5
REQUIRE_IDM_FOR_FVG = True
SESSION_FILTER = {'1000BONKUSDT': None, 'AAVEUSDT': None, 'BERAUSDT': None, 'GMXUSDT': None, 'ICPUSDT': None, 'JUPUSDT': None, 'LTCUSDT': None, 'ORCAUSDT': None, 'SHIB1000USDT': None, 'SOLUSDT': None, 'TAOUSDT': None, 'VIRTUALUSDT': None, 'XRPUSDT': None}

def find_last_swing_bos(df, n=SWING_BARS):
    highs, lows = [], []
    hi = df['high'].values; lo = df['low'].values; ts = df['ts'].values
    for i in range(n, len(df) - n):
        h = hi[i]; l = lo[i]
        if all(hi[i-k] < h for k in range(1, n+1)) and all(hi[i+k] < h for k in range(1, n+1)):
            highs.append({'val': h, 'idx': i, 'ts': ts[i]})
        if all(lo[i-k] > l for k in range(1, n+1)) and all(lo[i+k] > l for k in range(1, n+1)):
            lows.append({'val': l, 'idx': i, 'ts': ts[i]})
    return highs, lows


def impulse_anchors(stype, swing_val, brk_idx, sh_h1, sl_h1, df=None):
    """CHOCH = protective low/high = EKSTREM (low terendah / high tertinggi) ANTARA
    swing-1 (yang di-break) dan puncak/lembah swing-2 — yaitu launch impulse, bukan
    swing lama di belakang swing-1. Return (bos_idx, choch_level, peak_val).
    peak_val = swing 5-5 terkonfirmasi yang jadi puncak/lembah (None bila belum terbentuk)."""
    if swing_val is None or brk_idx is None or not sh_h1 or not sl_h1:
        return None, None, None
    if stype == "Long":
        peaks = [x for x in sh_h1 if x['idx'] > brk_idx and x['val'] > swing_val]
        peak_val = max(peaks, key=lambda x: x['val'])['val'] if peaks else None
        # puncak (batas atas pencarian choch) = high tertinggi mentah setelah break
        if df is not None and len(df) > brk_idx + 1:
            peak_idx = int(df['high'].iloc[brk_idx:].idxmax())
        else:
            peak_idx = (max(peaks, key=lambda x: x['val'])['idx'] if peaks else sh_h1[-1]['idx'])
        # CHOCH = swing low 5-5 TERDALAM antara break & puncak (HARUS swing 5-5; kalau tak ada -> skip)
        cands = [x for x in sl_h1 if brk_idx <= x['idx'] < peak_idx]
        if not cands:
            return None, None, peak_val
        ch = min(cands, key=lambda x: x['val'])
        return ch['idx'], ch['val'], peak_val
    else:
        troughs = [x for x in sl_h1 if x['idx'] > brk_idx and x['val'] < swing_val]
        peak_val = min(troughs, key=lambda x: x['val'])['val'] if troughs else None
        if df is not None and len(df) > brk_idx + 1:
            trough_idx = int(df['low'].iloc[brk_idx:].idxmin())
        else:
            trough_idx = (min(troughs, key=lambda x: x['val'])['idx'] if troughs else sl_h1[-1]['idx'])
        cands = [x for x in sh_h1 if brk_idx <= x['idx'] < trough_idx]
        if not cands:
            return None, None, peak_val
        ch = max(cands, key=lambda x: x['val'])
        return ch['idx'], ch['val'], peak_val


def rebreak_invalid(df, start_idx, swing2, choch_level, stype, lock_retr=0.50):
    """True bila SETELAH harga retrace >= lock_retr (dari swing2 ke arah choch),
    ada candle yang CLOSE melewati swing2 (= rebreak, struktur baru).
    swing2 = puncak/lembah swing 5-5 (TETAP). Dihitung historis -> konsisten lintas-redeploy."""
    n = len(df)
    if swing2 is None or start_idx is None or start_idx >= n - 1 or choch_level is None:
        return False
    hi = df['high'].values; lo = df['low'].values; cl = df['close'].values
    if stype == "Long":
        rng = swing2 - choch_level
        if rng <= 0:
            return False
        half = swing2 - lock_retr * rng
        retraced = False
        for k in range(int(start_idx) + 1, n):
            if lo[k] <= half:
                retraced = True
            if retraced and cl[k] > swing2:
                return True
        return False
    else:
        rng = choch_level - swing2
        if rng <= 0:
            return False
        half = swing2 + lock_retr * rng
        retraced = False
        for k in range(int(start_idx) + 1, n):
            if hi[k] >= half:
                retraced = True
            if retraced and cl[k] < swing2:
                return True
        return False


def choch_is_broken(df, bos_idx, choch_level, stype):
    """CHoCH ditembus = SETELAH puncak, ada candle yang CLOSE menembus choch (Long: < choch / Short: > choch).
    Historis -> tetap mati walau harga sudah balik. bos_idx = indeks choch (launch)."""
    n = len(df)
    if bos_idx is None or bos_idx >= n or choch_level is None:
        return False
    if stype == "Long":
        peak_idx = int(df['high'].iloc[bos_idx:].idxmax())
        return bool((df['close'].iloc[peak_idx:] < choch_level).any())
    else:
        peak_idx = int(df['low'].iloc[bos_idx:].idxmin())
        return bool((df['close'].iloc[peak_idx:] > choch_level).any())


def deepest_retrace_lo(df, bos_idx, choch_level, stype):
    """Batas bawah zona entry dinamis = max(ENTRY_ZONE_LO, retrace TERDALAM setelah puncak).
    Area 0..retrace_terdalam sudah dilewati candle retrace -> tak boleh dipakai entry (sudah terisi)."""
    n = len(df)
    if not ZONE_FROM_RETRACE or bos_idx is None or bos_idx >= n or choch_level is None:
        return ENTRY_ZONE_LO
    if stype == "Long":
        sub = df['high'].iloc[bos_idx:]
        B = float(sub.max()); pk = int(sub.idxmax()); rng = B - choch_level
        if rng <= 0: return ENTRY_ZONE_LO
        low_after = float(df['low'].iloc[pk:].min())
        frac = (B - low_after) / rng
    else:
        sub = df['low'].iloc[bos_idx:]
        B = float(sub.min()); pk = int(sub.idxmin()); rng = choch_level - B
        if rng <= 0: return ENTRY_ZONE_LO
        high_after = float(df['high'].iloc[pk:].max())
        frac = (high_after - B) / rng
    return max(ENTRY_ZONE_LO, min(frac, ENTRY_ZONE_HI))


def _gap_vol_fields(df, c3_idx):
    """Extract volume + OCL + C1 fields untuk FVG (df dalam H1). C1=c3_idx-2."""
    c2_idx   = c3_idx - 1
    c1_idx   = c3_idx - 2
    c2_close = float(df['close'].iloc[c2_idx]) if c2_idx >= 0 else 0.0
    c2_low   = float(df['low'].iloc[c2_idx])   if c2_idx >= 0 else 0.0
    c2_high  = float(df['high'].iloc[c2_idx])  if c2_idx >= 0 else 0.0
    c3_open  = float(df['open'].iloc[c3_idx])  if c3_idx < len(df) else 0.0
    c1_open  = float(df['open'].iloc[c1_idx])  if c1_idx >= 0 else 0.0
    c1_close = float(df['close'].iloc[c1_idx]) if c1_idx >= 0 else 0.0
    c1_low   = float(df['low'].iloc[c1_idx])   if c1_idx >= 0 else 0.0
    c1_high  = float(df['high'].iloc[c1_idx])  if c1_idx >= 0 else 0.0
    base = {'c2_close': c2_close, 'c2_low': c2_low, 'c2_high': c2_high, 'c3_open': c3_open,
            'c1_open': c1_open, 'c1_close': c1_close,
            'c1_low': c1_low,   'c1_high': c1_high, 'c3_idx': c3_idx}
    if 'vol' not in df.columns:
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

    # Post-BOS FVG  (C1=i-1, C2=i, C3=i+1)
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


def _get_fvgs(df_h1, stype, bos_idx, choch_level=None, zone_lo=None):
    """FVG biasa (TANPA syarat volume): C1/C3 valid, CHOCH filter, zona entry, MAX_GAP, fresh-C1.
    zone_lo = batas bawah zona (default ENTRY_ZONE_LO). Dipakai utk zona dinamis (>= retrace terdalam)."""
    gaps = get_internal_gaps(df_h1, stype, bos_idx)
    z_lo = ENTRY_ZONE_LO if zone_lo is None else zone_lo
    # FVG biasa: cukup field C1 (entry) & C3 (OCL) valid — tanpa syarat volume "kuat"
    gaps = [g for g in gaps
            if g.get('c3_open', 0) > 0
            and g.get('c1_close', 0) > 0]
    # Filter FVG yang straddle CHOCH
    if choch_level:
        if stype == "Long":
            gaps = [g for g in gaps if g['bottom'] >= choch_level]
        else:
            gaps = [g for g in gaps if g['top'] <= choch_level]
    # Filter ZONA ENTRY: C1.close harus di retrace z_lo..HI dari range BOS
    # 0% = ekstrem impulse (swing terbaru), 100% = CHOCH. Long: zona di bawah; Short: di atas.
    if choch_level and len(df_h1) > bos_idx:
        if stype == "Long":
            B = float(df_h1['high'].iloc[bos_idx:].max())   # impulse high (0%)
            L = float(choch_level)                          # invalidasi (100%)
            rng = B - L
            if rng > 0:
                lo = B - ENTRY_ZONE_HI * rng                # batas terdalam (100%)
                hi = B - z_lo * rng                         # batas terdangkal (z_lo)
                gaps = [g for g in gaps if lo <= g.get('c1_close', 0) <= hi]
        else:
            B = float(df_h1['low'].iloc[bos_idx:].min())    # impulse low (0%)
            L = float(choch_level)                          # invalidasi (100%)
            rng = L - B
            if rng > 0:
                lo = B + z_lo * rng                         # batas terdangkal (z_lo)
                hi = B + ENTRY_ZONE_HI * rng                # batas terdalam (100%)
                gaps = [g for g in gaps if lo <= g.get('c1_close', 0) <= hi]
    # MAX_GAP_PCT: gap tidak boleh terlalu besar
    result = []
    for g in gaps:
        gap_size = g['top'] - g['bottom']
        ocl      = float(g.get('c3_open', g['bottom'] if stype == 'Short' else g['top']))
        if ocl > 0 and MAX_GAP_PCT > 0 and gap_size / ocl > MAX_GAP_PCT:
            continue
        # Fresh-C1: tolak kalau C1.close sudah disentuh candle SETELAH C3
        if REQUIRE_FRESH_C1 and not c1_is_fresh(df_h1, g, stype):
            continue
        result.append(g)
    return result


def c1_is_fresh(df, gap, stype):
    """C1 fresh = belum ada candle SETELAH C3 (termasuk candle TERBARU walau belum close)
    yang menyentuh C1.close. Long: low <= c1_close. Short: high >= c1_close."""
    c3i = gap.get('c3_idx')
    c1c = float(gap.get('c1_close', 0))
    if c3i is None or c1c <= 0:
        return True
    n = len(df)
    for k in range(int(c3i) + 1, n):   # candle setelah C3 s/d candle TERBARU (ikut yg belum close)
        if stype == "Long" and float(df['low'].iloc[k]) <= c1c:
            return False
        if stype == "Short" and float(df['high'].iloc[k]) >= c1c:
            return False
    return True


def pick_bos_swing(df, sh_h1, sl_h1, stype):
    """Pilih swing-1 BOS: swing 5-5 terbaru yang di-break & menghasilkan struktur LENGKAP (choch 5-5 sah).
    Return (swing_val, brk_idx) atau (None, None)."""
    idx_arr = df.index; closes = df['close']
    up = (stype == "Long")
    swings = sh_h1 if up else sl_h1
    def _broken(s):
        later = closes[idx_arr > s['idx']]
        if len(later) == 0: return False
        return bool((later > s['val']).any()) if up else bool((later < s['val']).any())
    cands = sorted([s for s in swings[-8:] if _broken(s)], key=lambda x: x['idx'], reverse=True)
    for s in cands:
        bi, ch, pk = impulse_anchors(stype, s['val'], s['idx'], sh_h1, sl_h1, df)
        if bi is not None and ch is not None:
            return s['val'], s['idx']
    if cands:
        return cands[0]['val'], cands[0]['idx']
    return None, None


def apply_latest_leg(df, sh, sl, stype, swing_val, brk_idx, choch_level, peak_val, B, peak_idx, bos_idx):
    """FORWARD-CHAINING sub-puncak fraktal HALUS (n=SUBLEG_BARS) -> baca leg kiri->kanan tapi
    pakai swing tervalidasi (saring noise bar). choch & swing-1 selalu ikut LEG TERAKHIR;
    ambang retrace 50% diukur PER-LEG. Telusuri tiap sub-puncak halus setelah swing-1:
      - high baru TANPA retrace>=50% leg -> EXTENSION (puncak tumbuh, choch tetap)
      - high baru SETELAH retrace>=50%   -> REBREAK -> leg baru:
            swing-1 = puncak lama, choch = protective low/high HALUS TERBARU di leg baru, swing-2 = high baru
            (tak ada protective halus di leg baru -> None / tak ada BOS)
    Return (swing_val, brk_idx, choch_level, peak_val, bos_idx) atau None."""
    fsh, fsl = find_last_swing_bos(df, n=SUBLEG_BARS)
    if stype == "Long":
        peaks = sorted([x for x in fsh if x['idx'] > brk_idx and x['val'] > swing_val], key=lambda x: x['idx'])
    else:
        peaks = sorted([x for x in fsl if x['idx'] > brk_idx and x['val'] < swing_val], key=lambda x: x['idx'])
    if not peaks:
        return (swing_val, brk_idx, choch_level, peak_val, bos_idx)

    def prot_between(i_lo, i_hi):   # protective swing HALUS TERBARU (idx terbesar) di (i_lo, i_hi)
        if stype == "Long":
            c = [x for x in fsl if i_lo <= x['idx'] < i_hi]
        else:
            c = [x for x in fsh if i_lo <= x['idx'] < i_hi]
        return max(c, key=lambda x: x['idx']) if c else None

    def retr(s2v, chv, i_from, i_to):   # retrace >= RETRACE_LOCK leg [chv..s2v] di [i_from,i_to]?
        if stype == "Long":
            half = s2v - RETRACE_LOCK * (s2v - chv)
            return float(df['low'].iloc[i_from:i_to + 1].min()) <= half
        else:
            half = s2v + RETRACE_LOCK * (chv - s2v)
            return float(df['high'].iloc[i_from:i_to + 1].max()) >= half

    higher = (lambda a, b: a > b) if stype == "Long" else (lambda a, b: a < b)
    # leg 0
    ch0 = prot_between(brk_idx, peaks[0]['idx'])
    cur_s1v, cur_s1i = swing_val, brk_idx
    cur_chv, cur_chi = (ch0['val'], ch0['idx']) if ch0 else (choch_level, bos_idx)
    cur_s2v, cur_s2i = peaks[0]['val'], peaks[0]['idx']
    # chain sisa sub-puncak halus
    for p in peaks[1:]:
        if not higher(p['val'], cur_s2v):
            continue
        if retr(cur_s2v, cur_chv, cur_s2i, p['idx']):     # REBREAK
            nch = prot_between(cur_s2i, p['idx'])
            if nch is None:
                return None
            cur_s1v, cur_s1i = cur_s2v, cur_s2i
            cur_chv, cur_chi = nch['val'], nch['idx']
            cur_s2v, cur_s2i = p['val'], p['idx']
        else:                                             # EXTENSION
            nch = prot_between(cur_s2i, p['idx'])          # choch naik ke higher-low/lower-high HALUS terbaru
            if nch is not None:
                cur_chv, cur_chi = nch['val'], nch['idx']
            cur_s2v, cur_s2i = p['val'], p['idx']
    # puncak MENTAH B di luar sub-puncak halus terakhir
    final_peak_val = cur_s2v
    if higher(B, cur_s2v):
        if retr(cur_s2v, cur_chv, cur_s2i, peak_idx):     # REBREAK ke B
            nch = prot_between(cur_s2i, peak_idx)
            if nch is None:
                return None
            cur_s1v, cur_s1i = cur_s2v, cur_s2i
            cur_chv, cur_chi = nch['val'], nch['idx']
            final_peak_val = None     # puncak = B mentah (belum jadi swing)
        # else: EXTENSION ke B -> final_peak_val tetap cur_s2v
    return (cur_s1v, cur_s1i, cur_chv, final_peak_val, cur_chi)


def bos_anchors(df, sh_h1, sl_h1, stype):
    """Struktur BOS besar (tanpa perlu FVG) untuk arah `stype`.
    Return dict {swing_val, brk_idx, choch_level, peak_val, B, bos_idx, bos_rng} atau None bila tak ada/invalid."""
    if not sh_h1 or not sl_h1:
        return None
    swing_val, brk_idx = pick_bos_swing(df, sh_h1, sl_h1, stype)
    if swing_val is None:
        return None
    bos_idx, choch_level, peak_val = impulse_anchors(stype, swing_val, brk_idx, sh_h1, sl_h1, df)
    if bos_idx is None or choch_level is None:
        return None
    if stype == "Long":
        sub = df['high'].iloc[bos_idx:]; B = float(sub.max()); peak_idx = int(sub.idxmax())
    else:
        sub = df['low'].iloc[bos_idx:];  B = float(sub.min()); peak_idx = int(sub.idxmin())
    # === ATURAN LEG TERBARU (extension vs rebreak) — bersama jalur FVG ===
    res = apply_latest_leg(df, sh_h1, sl_h1, stype, swing_val, brk_idx, choch_level, peak_val, B, peak_idx, bos_idx)
    if res is None:
        return None
    swing_val, brk_idx, choch_level, peak_val, bos_idx = res
    bos_rng = (B - choch_level) if stype == "Long" else (choch_level - B)
    if bos_rng <= 0:
        return None
    # invalidasi: choch ditembus historis ATAU rebreak swing-2
    if choch_is_broken(df, bos_idx, choch_level, stype):
        return None
    if REBREAK_INVALID and peak_val is not None and \
       rebreak_invalid(df, bos_idx, peak_val, choch_level, stype, RETRACE_LOCK):
        return None
    return {'swing_val': swing_val, 'brk_idx': brk_idx, 'choch_level': choch_level,
            'peak_val': peak_val, 'B': B, 'bos_idx': bos_idx, 'peak_idx': peak_idx, 'bos_rng': bos_rng}


def find_inducement(df_tf, big_stype, band_lo, band_hi, n=1, ts_lo=None, ts_hi=None):
    """Inducement = MINI-BOS searah big_stype (swing 1-1..4-4; 5-5+ dibuang -> itu BOS besar).
    TRIGGER tiap IDM = choch mini-BOS (di antara swing-1 & swing-2). Bisa ADA BANYAK IDM.
    Kumpulkan SEMUA trigger di PITA 35-55% range BOS besar, lalu pilih yang TERDEKAT ke 35%
    (level dekat puncak). Tak pakai rebreak/latest-leg. choch (trigger) kalau disapu M5 -> entry lawan.
    Return {prot(trigger terpilih), prot_idx, micro_val(swing-1), micro_idx, n_trigger, all_triggers} atau None."""
    if df_tf is None or len(df_tf) < (2 * n + 1):
        return None
    sh_tf, sl_tf = find_last_swing_bos(df_tf, n=n)   # swing n-n (minimum)
    if not sh_tf or not sl_tf:
        return None
    # BUANG swing skala BOS besar: kekuatan >= INDUCEMENT_SWING_MAX di KEDUA sisi (mis. 5-5+).
    # IDM hanya boleh dari swing minor (1-1 s/d 4-4, asimetris spt 2-4 boleh; 5-3 boleh, 5-5 tidak).
    hi_a = df_tf['high'].values; lo_a = df_tf['low'].values
    cap = INDUCEMENT_SWING_MAX
    def _too_big(idx, is_high):
        arr = hi_a if is_high else lo_a
        v = arr[idx]; L = 0; R = 0; k = 1
        while idx - k >= 0 and ((arr[idx - k] < v) if is_high else (arr[idx - k] > v)):
            L += 1; k += 1
            if L >= cap: break
        k = 1
        while idx + k < len(arr) and ((arr[idx + k] < v) if is_high else (arr[idx + k] > v)):
            R += 1; k += 1
            if R >= cap: break
        return L >= cap and R >= cap
    sh_tf = [s for s in sh_tf if not _too_big(s['idx'], True)]
    sl_tf = [s for s in sl_tf if not _too_big(s['idx'], False)]
    if not sh_tf or not sl_tf:
        return None
    ts_col = df_tf['ts']
    def _in_win(idx):
        if ts_lo is None:
            return True
        t = float(ts_col.iloc[idx])
        return ts_lo <= t <= ts_hi
    shw = [s for s in sh_tf if _in_win(s['idx'])]
    slw = [s for s in sl_tf if _in_win(s['idx'])]
    if not shw or not slw:
        return None
    # ENUMERASI SEMUA mini-BOS 1-1 searah: tiap swing-1 (1-1..4-4) yg di-break -> choch = TRIGGER.
    # Bisa ada banyak IDM. Kumpulkan SEMUA trigger yang ada di pita 35-55%, lalu pilih yang
    # TERDEKAT ke 35% (level dekat puncak). Tak pakai rebreak/latest-leg (IDM = mini-BOS murni).
    up = (big_stype == "Long")
    swings1 = shw if up else slw
    closes = df_tf['close']; idx_arr = df_tf.index
    triggers = []   # (trigger_val, trigger_idx, swing1_val, swing1_idx)
    for s in swings1:
        later = closes[idx_arr > s['idx']]
        if len(later) == 0:
            continue
        broken = bool((later > s['val']).any()) if up else bool((later < s['val']).any())
        if not broken:
            continue
        mb, mch, _mpk = impulse_anchors(big_stype, s['val'], s['idx'], shw, slw, df_tf)
        if mb is None or mch is None:
            continue
        if band_lo <= mch <= band_hi:                 # trigger di pita 35-55%
            triggers.append((mch, mb, s['val'], s['idx']))
    if not triggers:
        return None
    seen = set(); uniq = []                           # dedup: trigger value sama -> 1 saja
    for t in sorted(triggers, key=lambda x: x[1]):
        k = round(t[0], 10)
        if k in seen:
            continue
        seen.add(k); uniq.append(t)
    triggers = uniq
    lvl35 = band_hi if up else band_lo                # level 35% (dekat puncak)
    best = min(triggers, key=lambda t: abs(t[0] - lvl35))   # trigger TERDEKAT ke 35%
    return {'prot': best[0], 'prot_idx': best[1], 'micro_val': best[2], 'micro_idx': best[3],
            'n_trigger': len(triggers), 'all_triggers': sorted(t[0] for t in triggers)}


def build_setup_from_bos(coin, df_h1_live, sh_h1, sl_h1, closed_h1, verbose=True, force_dir=None):
    """Deteksi BOS H1 terbaru -> FVG -> bangun setup WAIT_APPROACH.
    force_dir='Long'/'Short' => deteksi HANYA arah itu (untuk monitoring dua arah).
    Return (setup_dict, logline) atau (None, None). TIDAK menyentuh pending."""
    if not sh_h1 or not sl_h1:
        return None, None
    is_long = False; is_short = False; swing_val = None; brk_idx = None
    if force_dir in (None, "Long"):
        sv, bi = pick_bos_swing(df_h1_live, sh_h1, sl_h1, "Long")
        if sv is not None: is_long = True; swing_val = sv; brk_idx = bi
    if force_dir in (None, "Short"):
        sv, bi = pick_bos_swing(df_h1_live, sh_h1, sl_h1, "Short")
        if sv is not None: is_short = True; swing_val = sv; brk_idx = bi
    if not (is_long or is_short):
        if verbose: print(f"   {coin}: tidak ada BOS {force_dir or 'H1'}")
        return None, None
    if force_dir == "Long":
        stype = "Long"
    elif force_dir == "Short":
        stype = "Short"
    else:
        stype = "Short" if is_short else "Long"
    bos_idx, choch_level, peak_val = impulse_anchors(stype, swing_val, brk_idx, sh_h1, sl_h1, df_h1_live)
    if swing_val is None or bos_idx is None or choch_level is None:
        if verbose:
            if swing_val is None:
                print(f"   {coin}: tak ada swing 5-5 yang ter-break ({stype})")
            else:
                if stype == "Long":
                    pk_idx = int(df_h1_live['high'].iloc[brk_idx:].idxmax())
                    pk_val = float(df_h1_live['high'].iloc[brk_idx:].max())
                    cand_list = sl_h1; what = "swingLow"
                else:
                    pk_idx = int(df_h1_live['low'].iloc[brk_idx:].idxmin())
                    pk_val = float(df_h1_live['low'].iloc[brk_idx:].min())
                    cand_list = sh_h1; what = "swingHigh"
                tags = []
                for x in cand_list:
                    if x['idx'] < brk_idx:   pos = "✗sblm-break"
                    elif x['idx'] >= pk_idx: pos = "✗stlh-puncak"
                    else:                    pos = "✓DALAM"
                    tags.append(f"{x['val']:.6g}@{x['idx']}[{pos}]")
                body = ', '.join(tags) if tags else '(tak ada swing 5-5 sama sekali)'
                print(f"   {coin}: BOS {stype} tak lengkap — break={swing_val:.6g}@{brk_idx} puncak={pk_val:.6g}@{pk_idx} | {what}5-5 kandidat choch: {body}")
        return None, None
    # Puncak/lembah B + indeksnya (ekstrem langsung, tanpa nunggu)
    if stype == "Long":
        sub = df_h1_live['high'].iloc[bos_idx:]; _B = float(sub.max()); peak_idx = int(sub.idxmax())
    else:
        sub = df_h1_live['low'].iloc[bos_idx:]; _B = float(sub.min()); peak_idx = int(sub.idxmin())
    # === ATURAN LEG TERBARU (extension vs rebreak) — sama dgn jalur inducement ===
    res = apply_latest_leg(df_h1_live, sh_h1, sl_h1, stype, swing_val, brk_idx, choch_level, peak_val, _B, peak_idx, bos_idx)
    if res is None:
        if verbose: print(f"   {coin}: BOS {stype} — swing-2 ditembus & leg baru tanpa choch 5-5 (tunggu BOS baru)")
        return None, None
    swing_val, brk_idx, choch_level, peak_val, bos_idx = res
    bos_rng = (_B - choch_level) if stype == "Long" else (choch_level - _B)
    # CHoCH invalidation HISTORIS: kalau SETELAH puncak ada candle yang CLOSE menembus choch -> BOS mati
    # (walau harga sekarang sudah balik). Sebelumnya cuma cek close terakhir -> bocor.
    seg_cl = df_h1_live['close'].iloc[peak_idx:]
    choch_broken = bool((seg_cl < choch_level).any()) if stype == "Long" else bool((seg_cl > choch_level).any())
    if choch_broken:
        if verbose: print(f"   {coin}: BOS {stype} sudah CHoCH — harga pernah close lewat choch {choch_level:.6g} (mati, tunggu BOS baru)")
        return None, None
    # Invalidasi struktur: swing-2 = puncak swing 5-5; bila harga retrace >= RETRACE_LOCK
    # lalu CLOSE melewati swing-2 -> BOS invalid (struktur baru), tunggu BOS baru.
    if REBREAK_INVALID and peak_val is not None and \
       rebreak_invalid(df_h1_live, bos_idx, peak_val, choch_level, stype, RETRACE_LOCK):
        if verbose: print(f"   {coin}: BOS {stype} INVALID — retrace>={RETRACE_LOCK*100:.0f}% lalu close lewati swing-2 {peak_val:.6g} (tunggu BOS baru)")
        return None, None
    # === GATE: BOS besar WAJIB punya IDM mini-BOS di dalamnya (lebih ketat, simetris dgn jalur IDM) ===
    if REQUIRE_IDM_FOR_FVG:
        if stype == "Long":
            ib_lo, ib_hi = _B - INDUCEMENT_ZONE_HI * bos_rng, _B - INDUCEMENT_ZONE_LO * bos_rng
        else:
            ib_lo, ib_hi = _B + INDUCEMENT_ZONE_LO * bos_rng, _B + INDUCEMENT_ZONE_HI * bos_rng
        its_lo = float(df_h1_live['ts'].iloc[bos_idx])
        its_hi = float(df_h1_live['ts'].iloc[peak_idx])
        df_idm = df_h1_live if INDUCEMENT_TF == "60" else get_data(coin, "5", limit=300)
        idm_chk = None
        if df_idm is not None:
            idm_chk = find_inducement(df_idm, stype, ib_lo, ib_hi, n=INDUCEMENT_SWING, ts_lo=its_lo, ts_hi=its_hi)
        if idm_chk is None:
            msg = (f"BOS {stype} TAK ada IDM mini-BOS {INDUCEMENT_SWING}-{INDUCEMENT_SWING} "
                   f"di pita {INDUCEMENT_ZONE_LO*100:.0f}-{INDUCEMENT_ZONE_HI*100:.0f}% (skip FVG limit) | "
                   f"break:{swing_val:.6g} choch:{choch_level:.6g} puncak:{_B:.6g}")
            if verbose:
                print(f"   {coin}: {msg}")
            _k = f"{stype}|{swing_val:.8g}|{choch_level:.8g}"
            return None, (f"IDM_SKIP::{_k}::" + msg)
    zlo = deepest_retrace_lo(df_h1_live, bos_idx, choch_level, stype)
    gaps = _get_fvgs(df_h1_live, stype, bos_idx, choch_level, zone_lo=zlo)
    if not gaps:
        if verbose:
            raw = get_internal_gaps(df_h1_live, stype, bos_idx)
            Bp = _B; rng = bos_rng
            z618 = (Bp - zlo * rng) if stype == "Long" else (Bp + zlo * rng)
            tags = []
            for g in raw:
                c1c = float(g.get('c1_close', 0))
                r = ((Bp - c1c) if stype == "Long" else (c1c - Bp)) / rng * 100 if rng > 0 else 0
                if stype == "Long" and g['bottom'] < choch_level:
                    why = "choch"
                elif stype == "Short" and g['top'] > choch_level:
                    why = "choch"
                else:
                    if stype == "Long":
                        lo = Bp - ENTRY_ZONE_HI * rng; hi = Bp - zlo * rng
                    else:
                        lo = Bp + zlo * rng; hi = Bp + ENTRY_ZONE_HI * rng
                    if not (lo <= c1c <= hi):
                        why = "dilewati" if r < zlo * 100 else "zona"
                    else:
                        gs = g['top'] - g['bottom']; ocl = float(g.get('c3_open', 0))
                        if ocl > 0 and MAX_GAP_PCT > 0 and gs / ocl > MAX_GAP_PCT:
                            why = f"gap{gs / ocl * 100:.2f}%"
                        elif REQUIRE_FRESH_C1 and not c1_is_fresh(df_h1_live, g, stype):
                            why = "stale"
                        else:
                            why = "OK"
                tags.append(f"{r:.0f}%:{why}")
            print(f"   {coin}: BOS {stype} tdk ada FVG di zona | break={swing_val:.6g} "
                  f"choch={choch_level:.6g} puncak={Bp:.6g} | rawFVG={len(raw)} "
                  f"[{', '.join(tags)}] (zona>={zlo*100:.1f}%@{z618:.6g}, maxgap={MAX_GAP_PCT*100:.2f}%)")
        return None, None
    bos_ts = df_h1_live['ts'].iloc[bos_idx]
    g0 = gaps[0]
    c1_c = float(g0.get('c1_close', 0)); c1_l = float(g0.get('c1_low', 0)); c1_h = float(g0.get('c1_high', 0))
    c2_l = float(g0.get('c2_low', 0));   c2_h = float(g0.get('c2_high', 0))
    if not (c1_c > 0 and c1_h > c1_l):
        return None, None
    gap_s = float(g0['top']) - float(g0['bottom'])
    if stype == 'Long':
        # Entry = ujung wick C2 (low). SL = invalidasi C1.low. Fallback C1.close bila C2 invalid.
        entry_adj = c2_l if (ENTRY_C2_WICK and c2_l > 0) else c1_c
        sl_base   = min(c1_l, entry_adj)            # SL tak boleh di atas entry
        dist = max(entry_adj - sl_base, 0.0) * SL_FRAC; sl_entry = entry_adj - dist
    else:
        entry_adj = c2_h if (ENTRY_C2_WICK and c2_h > 0) else c1_c
        sl_base   = max(c1_h, entry_adj)
        dist = max(sl_base - entry_adj, 0.0) * SL_FRAC; sl_entry = entry_adj + dist
    import datetime as _dt
    _h_s = _dt.datetime.utcfromtimestamp(df_h1_live.iloc[-1]['ts_ms'] / 1000).hour if 'ts_ms' in df_h1_live.columns else -1
    if _h_s >= 0:
        _sesi = 'Asia' if _h_s < 8 else ('London' if _h_s < 13 else 'NY')
        _allowed = SESSION_FILTER.get(coin)
        if _allowed is not None and _sesi not in _allowed:
            return None, None
    # SL: mode FIXED 10% range BOS (di setiap situasi), atau ikut C1 dengan cap 10% range
    if SL_FIXED_RANGE and bos_rng > 0:
        dist = SL_CAP_RANGE * bos_rng
        sl_entry = entry_adj - dist if stype == 'Long' else entry_adj + dist
    elif SL_CAP_RANGE > 0 and bos_rng > 0 and dist > SL_CAP_RANGE * bos_rng:
        dist = SL_CAP_RANGE * bos_rng
        sl_entry = entry_adj - dist if stype == 'Long' else entry_adj + dist
    # Floor Bybit: kalau dist kepecil, perbesar (jaga-jaga range BOS sangat sempit)
    min_d = entry_adj * 0.002
    if dist < min_d:
        if MIN_DIST_FLOOR:
            dist = min_d; sl_entry = entry_adj - dist if stype == 'Long' else entry_adj + dist
        else:
            return None, None
    # (guard done_setups dihapus — anti-retrade kini lewat REQUIRE_FRESH_C1)
    choch_str = f"{choch_level:.6g}" if choch_level else "—"
    _slr = (dist / bos_rng * 100) if bos_rng > 0 else 0
    logline = (f"\n📊 {coin} | BOS {stype} | break:{swing_val:.6g} puncak:{_B:.6g} CHOCH:{choch_str} | "
               f"OCL:{c1_c:.6f} Entry:{entry_adj:.6f} SL:{sl_entry:.6f} "
               f"dist:{dist/c1_c*100:.3f}% (SL {_slr:.1f}% range) Gap:{gap_s/c1_c*100:.3f}%")
    setup = {
        'type': stype, 'phase': 'WAIT_APPROACH', 'entry': entry_adj, 'sl': sl_entry,
        'dist': dist, 'orig_ocl': c1_c, 'fvg_list': gaps, 'bos_ts': bos_ts,
        'bos_idx': bos_idx, 'swing_val': swing_val, 'choch_level': choch_level,
        'peak_val': _B, 'swing2': peak_val, 'brk_idx': brk_idx,
    }
    return setup, logline

