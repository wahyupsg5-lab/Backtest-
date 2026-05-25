"""
backtest_web.py — Backtest SEMUA coin bot live via Bybit API
23 Coins | Jan 2025 – Apr 2026 | Modal $10 | Risk 1% compound | fvg_sbr

Deploy ke Railway:
  Start command → python backtest_web.py
  Buka domain Railway → lihat progress & hasil di browser
  /readme → markdown siap copy ke README.md
"""

import os, threading, time
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

import numpy as np
import pandas as pd

import backtest as bt   # engine backtest dari backtest.py

# ── Config ──────────────────────────────────────────────────────────────
PORT             = int(os.environ.get('PORT', 8080))
INITIAL_BALANCE  = 10.0   # modal awal $10

# Entry mode — env var override atau default hardcode di sini
_ENTRY_MODE    = os.environ.get('ENTRY_MODE',    'fvg_limit')
_SL_MULT       = float(os.environ.get('SL_MULT',       '6.2'))
_TP_MULT       = float(os.environ.get('TP_MULT',       '18.6'))
_ENTRY_R       = float(os.environ.get('ENTRY_R',       '9.5'))
_TOUCH_VOL_MIN = float(os.environ.get('TOUCH_VOL_MIN', '0.8'))    # min vol ratio at SBR/OCL touch
_MAX_GAP_PCT   = float(os.environ.get('MAX_GAP_PCT',   '0.006'))  # max gap_size/price — FVG ≤0.60% dari harga
_TRAIL_STOP    = float(os.environ.get('TRAIL_STOP',    '0.15'))   # trail 0.15×dist (tight), reverse 2×
_MIN_DIST_PCT  = float(os.environ.get('MIN_DIST_PCT',  '0.002'))  # min SL distance = 0.2% dari price
bt.ENTRY_MODE    = _ENTRY_MODE
bt.SL_MULT       = _SL_MULT
bt.TP_MULT       = _TP_MULT
bt.ENTRY_R       = _ENTRY_R
bt.TOUCH_VOL_MIN = _TOUCH_VOL_MIN
bt.MAX_GAP_PCT   = _MAX_GAP_PCT
bt.TRAIL_STOP    = _TRAIL_STOP
bt.MIN_DIST_PCT  = _MIN_DIST_PCT

# ── Coin yang sudah lolos backtest fvg_sbr (disimpan, nanti digabung) ─────
COINS_SAVED = [
    'BELUSDT', '1000BONKUSDT', 'ONDOUSDT', 'VIRTUALUSDT',
    'ALGOUSDT', 'ORCAUSDT', 'XAUTUSDT', 'FARTCOINUSDT', 'TIAUSDT', 'SANDUSDT',
    'XVGUSDT', 'BERAUSDT', 'EIGENUSDT', 'SHIB1000USDT',
    'JUPUSDT', 'OPUSDT', 'STXUSDT', 'APEUSDT',
    'SOLUSDT', 'SUIUSDT', 'AAVEUSDT', 'GALAUSDT',
    'IMXUSDT', 'GMXUSDT', 'HBARUSDT', 'AXSUSDT',
    'LTCUSDT', 'DYDXUSDT', 'FLOWUSDT', 'ICPUSDT',
]

# 27 coin: hapus SOLUSDT, SEIUSDT, TIAUSDT, HBARUSDT (WR rendah / PnL negatif)
COINS = [
    # Batch 1
    'XVGUSDT', 'BELUSDT', '1000BONKUSDT', 'BERAUSDT', '1000PEPEUSDT',
    'ONDOUSDT', 'VIRTUALUSDT', 'ENAUSDT', 'SHIB1000USDT',
    'JUPUSDT', 'OPUSDT',
    'ALGOUSDT', 'ORCAUSDT', 'XRPUSDT', 'XAUTUSDT', 'FARTCOINUSDT', 'TAOUSDT',
    # Batch 2
    'SUIUSDT', 'AAVEUSDT', 'GALAUSDT',
    'IMXUSDT', 'GMXUSDT', 'SANDUSDT', 'AXSUSDT',
    'LTCUSDT', 'DYDXUSDT', 'ICPUSDT',
]

# 2025-01-01 00:00:00 UTC  →  2026-04-30 23:59:59 UTC  (dalam ms)
_START_MS = 1735689600000
_END_MS   = 1777593599000

# Batas kuartal (inklusif)
_QUARTERS = [
    ('Q1 2025', pd.Timestamp('2025-01-01'), pd.Timestamp('2025-03-31 23:59:59')),
    ('Q2 2025', pd.Timestamp('2025-04-01'), pd.Timestamp('2025-06-30 23:59:59')),
    ('Q3 2025', pd.Timestamp('2025-07-01'), pd.Timestamp('2025-09-30 23:59:59')),
    ('Q4 2025', pd.Timestamp('2025-10-01'), pd.Timestamp('2025-12-31 23:59:59')),
    ('Q1 2026', pd.Timestamp('2026-01-01'), pd.Timestamp('2026-03-31 23:59:59')),
    ('Q2 2026', pd.Timestamp('2026-04-01'), pd.Timestamp('2026-04-30 23:59:59')),
]

# ── Global state ──────────────────────────────────────────────────────────
_lock               = threading.Lock()
_log                = []
_phase              = 'running'   # 'running' | 'done' | 'error'
_results            = []          # per-coin
_quarter_stats      = {}          # Q1..Q4 compound
_all_trades         = []          # semua trade (compound replayed)
_compound_final_bal = INITIAL_BALANCE
_overall_avg_rr     = 0.0         # avg R:R keseluruhan semua coin
_overall_pf         = 0.0         # profit factor keseluruhan dari semua trade
_portfolio_max_dd   = 0.0         # max drawdown portfolio compound


def _ts():
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime('%H:%M:%S')

def _log_msg(msg: str):
    line = f"[{_ts()}] {msg}"
    print(line, flush=True)
    with _lock:
        _log.append(line)


# ── Bybit M5 fetch ────────────────────────────────────────────────────────
def fetch_bybit_m5(symbol: str) -> pd.DataFrame:
    from pybit.unified_trading import HTTP
    session = HTTP(testnet=False)

    rows, cur_end, n_call = [], _END_MS, 0

    while True:
        for attempt in range(4):
            try:
                res  = session.get_kline(symbol=symbol, category='linear',
                                         interval=5, limit=1000,
                                         start=_START_MS, end=cur_end)
                data = res['result']['list']
                break
            except Exception as e:
                wait = 2 ** attempt
                _log_msg(f"   ⚠ API error (attempt {attempt+1}): {e} — retry in {wait}s")
                time.sleep(wait)
        else:
            _log_msg("   ❌ Gagal fetch setelah 4 percobaan.")
            break

        if not data:
            break

        for kl in data:
            rows.append({
                'ts'   : pd.Timestamp(int(kl[0]), unit='ms'),
                'open' : float(kl[1]),
                'high' : float(kl[2]),
                'low'  : float(kl[3]),
                'close': float(kl[4]),
                'vol'  : float(kl[5]),
            })

        n_call   += 1
        oldest_ts = int(data[-1][0])
        if oldest_ts <= _START_MS:
            break
        cur_end = oldest_ts - 1
        time.sleep(0.2)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset='ts').sort_values('ts').reset_index(drop=True)
    df['ts_ms'] = df['ts'].astype('datetime64[s]').astype(np.int64)
    _log_msg(f"   {len(df):,} candle dari {n_call} API call")
    return df


# ── ATR P25 ───────────────────────────────────────────────────────────────
def calc_p25_atr(df: pd.DataFrame) -> float:
    c = df['close'].to_numpy(float)
    h = df['high'].to_numpy(float)
    l = df['low'].to_numpy(float)
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr14   = pd.Series(tr).rolling(14).mean().to_numpy()
    atr_pct = np.where(c > 0, atr14 / c, 0)[14:]
    valid   = atr_pct[atr_pct > 0]
    return float(np.percentile(valid, 25)) if len(valid) else 0.0035


# ── Diagnostic scan ───────────────────────────────────────────────────────
def _diagnose(symbol: str, df: pd.DataFrame, atr_thresh: float):
    from backtest import (build_h1, find_last_swing_bos,
                          get_internal_gaps, replay_m5, check_bos_or_sweep)
    WARMUP = 2400; H1_WIN = 100; total = len(df)
    c_bos = c_fvg = c_fvg_touch = c_idm = c_bos2 = c_mss = 0
    # Rolling BOS state — cermin backtest_coin
    active_bos_key = None; active_gaps = []; active_choch = None; active_stype = None
    i = WARMUP
    while i < total - 50:
        m5_win = df.iloc[max(0, i - H1_WIN * 12): i].reset_index(drop=True)
        df_h1  = build_h1(m5_win)
        if len(df_h1) < 52: i += 12; continue
        sh_h1, sl_h1 = find_last_swing_bos(df_h1)
        if not sh_h1 or not sl_h1: i += 12; continue
        closed_h1 = df_h1.iloc[-2]
        is_long = False; is_short = False; swing_val = None; bos_idx = None
        for sh in sh_h1[-3:]:
            if closed_h1['close'] > sh['val']:
                is_long = True; swing_val = sh['val']
                bos_idx = sl_h1[-1]['idx'] if sl_h1 else sh['idx']
        for sl in sl_h1[-3:]:
            if closed_h1['close'] < sl['val']:
                is_short = True; swing_val = sl['val']
                bos_idx = sh_h1[-1]['idx'] if sh_h1 else sl['idx']
        if (is_long or is_short) and swing_val is not None:
            stype_new = 'Short' if is_short else 'Long'
            bos_key   = (stype_new, round(swing_val, 8))
            if bos_key != active_bos_key:
                if stype_new == 'Long':
                    sl_below  = [s for s in sl_h1 if s['val'] < swing_val]
                    choch_new = sl_below[-1]['val'] if sl_below else None
                else:
                    sh_above  = [s for s in sh_h1 if s['val'] > swing_val]
                    choch_new = sh_above[-1]['val'] if sh_above else None
                gaps_new = get_internal_gaps(df_h1, stype_new, len(df_h1) - 1)
                if choch_new:
                    if stype_new == 'Long':
                        gaps_new = [g for g in gaps_new if g['bottom'] >= choch_new]
                    else:
                        gaps_new = [g for g in gaps_new if g['top'] <= choch_new]
                if gaps_new: c_bos += 1
                active_bos_key = bos_key; active_gaps = gaps_new
                active_choch   = choch_new; active_stype = stype_new
        if not active_gaps: i += 12; continue
        blk_end_m5      = min(i + 12, total)
        blk_close_slice = df['close'].iloc[i:blk_end_m5]
        if len(blk_close_slice) > 0:
            bc = float(blk_close_slice.iloc[-1])
            if active_choch is not None:
                if active_stype == 'Long'  and bc < active_choch:
                    active_bos_key = None; active_gaps = []; active_choch = None; active_stype = None
                    i += 12; continue
                if active_stype == 'Short' and bc > active_choch:
                    active_bos_key = None; active_gaps = []; active_choch = None; active_stype = None
                    i += 12; continue
        last_c = float(df['close'].iloc[blk_end_m5 - 1]) if blk_end_m5 > i else 0.0
        active_gaps = [
            g for g in active_gaps
            if not (active_stype == 'Long'  and last_c < float(g['bottom']))
            and not (active_stype == 'Short' and last_c > float(g['top']))
        ]
        if not active_gaps: i += 12; continue
        c_fvg = c_bos  # FVG count = BOS count (every BOS with gaps qualifies)
        found_fvg_idx = -1
        for fvg in active_gaps:
            ft, fb = float(fvg['top']), float(fvg['bottom'])
            for k in range(i, blk_end_m5):
                ck = df.iloc[k]
                if active_stype == 'Long'  and float(ck['low'])  <= ft:
                    found_fvg_idx = k; break
                if active_stype == 'Short' and float(ck['high']) >= fb:
                    found_fvg_idx = k; break
            if found_fvg_idx >= 0: break
        if found_fvg_idx < 0: i += 12; continue
        stype = active_stype; choch_level = active_choch
        active_bos_key = None; active_gaps = []; active_choch = None; active_stype = None
        c_fvg_touch += 1
        idm_end = min(total - 1, found_fvg_idx + 12 * 48)
        df_m5_idm = df.iloc[found_fvg_idx:idm_end].reset_index(drop=True)
        if len(df_m5_idm) < 5: i += 12; continue
        m5_state = replay_m5(df_m5_idm, stype)
        if m5_state['phase'] != 'IDM_TOUCHED': i += 12 * 24; continue
        c_idm += 1
        fts = m5_state['freeze_ts']
        freeze_mask = df['ts_ms'] == fts
        if not freeze_mask.any(): i += 12; continue
        freeze_m5_idx = df[freeze_mask].index[0]
        bos2_end = min(total - 1, freeze_m5_idx + 12 * 12)
        df_bos2 = df.iloc[freeze_m5_idx:bos2_end].reset_index(drop=True)
        result = check_bos_or_sweep(df_bos2, m5_state['freeze_high'],
                                    m5_state['freeze_low'], fts, stype)
        if result['trigger'] is None: i += 12 * 12; continue
        c_bos2 += 1
        trig_mask = df['ts_ms'] == result['ts']
        if not trig_mask.any(): i += 12; continue
        trigger_m5_idx = df[trig_mask].index[0]
        mss_end = min(total - 1, trigger_m5_idx + 12 * 24)
        df_mss = df.iloc[trigger_m5_idx:mss_end].reset_index(drop=True)
        mss_closes = df_mss['close'].to_numpy(float)
        hits = (np.where(mss_closes > result['nfh'])[0] if stype == 'Long'
                else np.where(mss_closes < result['nfl'])[0])
        if len(hits) == 0: i += 12 * 6; continue
        c_mss += 1; i += 12

    _log_msg(f"  [DIAG] BOS:{c_bos}→FVG_touch:{c_fvg_touch}→IDM:{c_idm}→BOS2:{c_bos2}→MSS:{c_mss}")


# ── Helper: quarter + compound ────────────────────────────────────────────
def _quarter_of(ts) -> str:
    q = (ts.month - 1) // 3 + 1
    return f'Q{q} {ts.year}'


def _compound_replay(all_trades: list, max_concurrent: int = bt.MAX_CONCURRENT) -> tuple:
    """
    Replay semua trade dalam urutan waktu dengan SATU balance bersama.
    Risk per trade = 1% dari balance saat itu (compound nyata).

    max_concurrent: maks posisi/limit aktif bersamaan lintas semua coin (slot margin).
    Trade yang masuk saat slot penuh di-skip (compound_pnl=0, slot_skip=True).

    Return: (replayed_trades, final_balance, portfolio_max_dd_pct)
    """
    sorted_trades = sorted(all_trades, key=lambda t: t['entry_ts'])
    bal    = INITIAL_BALANCE
    peak   = INITIAL_BALANCE
    max_dd = 0.0
    replayed = []

    # Slot tracker: list (exit_ts, symbol) trade yang sedang aktif
    active_exits = []

    for t in sorted_trades:
        entry_ts = t['entry_ts']
        exit_ts  = t.get('exit_ts')

        # Bebaskan slot yang sudah exit sebelum/saat entry ini
        active_exits = [(e, s) for (e, s) in active_exits
                        if e is None or e > entry_ts]

        # Slot penuh → skip trade ini
        if len(active_exits) >= max_concurrent:
            replayed.append({**t, 'compound_pnl': 0.0, 'compound_bal': bal,
                             'slot_skip': True})
            continue

        # Ambil slot
        active_exits.append((exit_ts, t['symbol']))

        if bal <= 0:
            replayed.append({**t, 'compound_pnl': 0.0, 'compound_bal': bal,
                             'slot_skip': False})
            continue
        risk    = bal * 0.01
        sl_dist = abs(t['entry'] - t['sl'])
        if sl_dist == 0 or t['entry'] == 0:
            replayed.append({**t, 'compound_pnl': 0.0, 'compound_bal': bal,
                             'slot_skip': False})
            continue
        if t['type'] == 'Long':
            r_mult = (t['exit_price'] - t['entry']) / sl_dist
        else:
            r_mult = (t['entry'] - t['exit_price']) / sl_dist
        pnl  = r_mult * risk
        bal += pnl
        if bal < 0:
            bal = 0.0
        if bal > peak:
            peak = bal
        dd = (peak - bal) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        replayed.append({**t, 'compound_pnl': pnl, 'compound_bal': bal,
                         'slot_skip': False})
    return replayed, bal, max_dd


def _calc_quarters_compound(replayed: list) -> dict:
    """Statistik per kuartal dari compound replay (sudah sorted by entry_ts)."""
    labels = [label for label, _, _ in _QUARTERS]
    by_q   = {label: [] for label in labels}
    for t in replayed:
        q = _quarter_of(t['entry_ts'])
        if q in by_q:
            by_q[q].append(t)

    stats = {}
    running = INITIAL_BALANCE
    for label in labels:
        trades  = by_q[label]
        q_start = running
        q_pnl   = sum(t['compound_pnl'] for t in trades)
        running += q_pnl
        wins    = sum(1 for t in trades if t['outcome'] == 'tp')
        n       = len(trades)
        wr      = wins / n * 100 if n else 0.0
        gw = sum(t['compound_pnl'] for t in trades if t['compound_pnl'] > 0)
        gl = abs(sum(t['compound_pnl'] for t in trades if t['compound_pnl'] < 0))
        pf = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
        stats[label] = {
            'trades': n, 'wins': wins, 'wr': wr,
            'pnl': q_pnl, 'pf': pf,
            'start_bal': q_start, 'end_bal': running,
        }
    return stats


# ── Win/Loss analysis ────────────────────────────────────────────────────
def _win_loss_analysis(trades: list) -> dict:
    """Compute per-group stats for win and loss trades (fvg_strong strategy)."""
    import pandas as _pd
    wins   = [t for t in trades if t['outcome'] == 'tp']
    losses = [t for t in trades if t['outcome'] == 'sl']

    def _hour(t):
        ts = t.get('entry_ts')
        if ts is None: return None
        try:
            return _pd.Timestamp(ts).hour
        except Exception:
            return None

    def grp(g):
        if not g: return None
        n = len(g)
        long_n   = sum(1 for t in g if t['type'] == 'Long')
        # C3 volume strength at FVG formation (c3_vol / avg 20H)
        vol_vals = [t.get('vol_ratio', 0.0) for t in g if t.get('vol_ratio', 0.0) > 0]
        avg_vol  = sum(vol_vals) / len(vol_vals) if vol_vals else 0.0
        # Touch candle volume (M5 candle that first hits OCL)
        tv_vals  = [t.get('touch_vol_ratio', 0.0) for t in g if t.get('touch_vol_ratio', 0.0) > 0]
        avg_tvol = sum(tv_vals) / len(tv_vals) if tv_vals else 0.0
        # FVG gap size as % of entry price
        gap_vals = [t.get('atr_ratio', 0.0) for t in g if t.get('atr_ratio', 0.0) > 0]
        avg_gap  = sum(gap_vals) / len(gap_vals) * 100 if gap_vals else 0.0
        # Entry hour (UTC)
        hours    = [h for h in (_hour(t) for t in g) if h is not None]
        avg_hour = sum(hours) / len(hours) if hours else 0.0
        # Session breakdown: Asia 0-7, London 8-15, NY 16-23
        asia   = sum(1 for h in hours if 0  <= h < 8)
        london = sum(1 for h in hours if 8  <= h < 16)
        ny     = sum(1 for h in hours if 16 <= h < 24)
        dom_session = max([('Asia', asia), ('London', london), ('NY', ny)],
                          key=lambda x: x[1])[0] if hours else '—'
        # SL breakdown (relevant for loss group)
        stp_n  = sum(1 for t in g if t.get('sl_then_tp'))
        sch_n  = sum(1 for t in g if t.get('sl_choch'))
        return {
            'n'           : n,
            'long_pct'    : long_n / n * 100,
            'avg_vol'     : avg_vol,
            'avg_tvol'    : avg_tvol,
            'avg_gap'     : avg_gap,
            'avg_hour'    : avg_hour,
            'dom_session' : dom_session,
            'stp_pct'     : stp_n / n * 100,
            'sch_pct'     : sch_n / n * 100,
        }

    return {'win': grp(wins), 'loss': grp(losses)}


def _insight(ws, ls) -> str:
    """One-line human-readable insight from win vs loss stats (fvg_strong)."""
    if ws is None or ls is None:
        return '—'
    clues = []
    # Direction
    dd = ws['long_pct'] - ls['long_pct']
    if   dd >  20: clues.append(f'Long lebih baik ({ws["long_pct"]:.0f}% vs {ls["long_pct"]:.0f}%)')
    elif dd < -20: clues.append(f'Short lebih baik ({100-ws["long_pct"]:.0f}% vs {100-ls["long_pct"]:.0f}%)')
    # C3 volume strength (FVG formation candle)
    vd = ws['avg_vol'] - ls['avg_vol']
    if   vd >  0.3: clues.append(f'Vol C3 lebih kuat saat win ({ws["avg_vol"]:.1f}× vs {ls["avg_vol"]:.1f}×)')
    elif vd < -0.3: clues.append(f'Vol C3 justru lebih lemah saat win ({ws["avg_vol"]:.1f}× vs {ls["avg_vol"]:.1f}×)')
    # Touch candle volume (M5 saat harga menyentuh SBR/OCL)
    tvd = ws['avg_tvol'] - ls['avg_tvol']
    if   tvd >  0.3: clues.append(f'Vol sentuh SBR lebih besar saat win ({ws["avg_tvol"]:.1f}× vs {ls["avg_tvol"]:.1f}×)')
    elif tvd < -0.3: clues.append(f'Vol sentuh SBR lebih kecil saat win ({ws["avg_tvol"]:.1f}× vs {ls["avg_tvol"]:.1f}×)')
    # FVG gap size
    gd = ws['avg_gap'] - ls['avg_gap']
    if   gd >  0.05: clues.append(f'FVG lebih besar saat win ({ws["avg_gap"]:.2f}% vs {ls["avg_gap"]:.2f}%)')
    elif gd < -0.05: clues.append(f'FVG lebih kecil saat win ({ws["avg_gap"]:.2f}% vs {ls["avg_gap"]:.2f}%)')
    # Session dominance
    if ws['dom_session'] != ls['dom_session']:
        clues.append(f'Win dominan sesi {ws["dom_session"]} (loss: {ls["dom_session"]})')
    # Loss breakdown
    if ls['stp_pct'] > 35:
        clues.append(f'{ls["stp_pct"]:.0f}% loss = stop hunt (SL→TP)')
    if ls['sch_pct'] > 25:
        clues.append(f'{ls["sch_pct"]:.0f}% loss = CHOCH nyata')
    drift = 100 - ls['stp_pct'] - ls['sch_pct']
    if drift > 50:
        clues.append(f'{drift:.0f}% loss = drift (konsolidasi/ambiguous)')
    return ' · '.join(clues) if clues else 'Tidak ada pola dominan'


def _fmt_grp(s) -> str:
    """Compact one-line summary for a win/loss group (fvg_strong)."""
    if s is None: return '—'
    dir_lbl  = f'Long {s["long_pct"]:.0f}%' if s['long_pct'] >= 50 else f'Short {100-s["long_pct"]:.0f}%'
    vol_lbl  = f'C3 {s["avg_vol"]:.1f}×'   if s['avg_vol']  > 0 else 'C3 —'
    tvol_lbl = f'Tch {s["avg_tvol"]:.1f}×' if s['avg_tvol'] > 0 else 'Tch —'
    gap_lbl  = f'Gap {s["avg_gap"]:.2f}%'  if s['avg_gap']  > 0 else 'Gap —'
    sess_lbl = s['dom_session']
    return f'{dir_lbl} · {vol_lbl} · {tvol_lbl} · {gap_lbl} · {sess_lbl}'


# ── Main runner (background thread) ──────────────────────────────────────
def _run():
    global _phase, _results, _quarter_stats, _all_trades, _compound_final_bal, \
           _overall_avg_rr, _overall_pf, _portfolio_max_dd

    _log_msg("=" * 62)
    _trail_str = f" Trail={_TRAIL_STOP}R+Reverse" if _TRAIL_STOP > 0 else f" TP={_TP_MULT}R"
    _log_msg(f"BACKTEST {len(COINS)} COIN — {_ENTRY_MODE.upper()} SL={_SL_MULT}R{_trail_str} TouchVol≥{_TOUCH_VOL_MIN}× MaxGap≤{_MAX_GAP_PCT*100:.2f}% CoinFilter:ON | Jan 2025–Apr 2026 | Modal ${INITIAL_BALANCE:.0f} | Risk 1%")
    _log_msg(f"{len(COINS)} Coins: {', '.join(COINS)}")
    _log_msg("=" * 62)

    all_trades_list = []
    results         = []

    # ── Concurrent mode (fvg_limit) ──────────────────────────────────────
    if _ENTRY_MODE == 'fvg_limit':
        _log_msg("📡 Fetching data semua coin...")
        coins_data = {}
        for symbol in COINS:
            _log_msg(f"  Fetch {symbol}...")
            try:
                df = fetch_bybit_m5(symbol)
                if len(df) < 3000:
                    _log_msg(f"   ⚠ Data {symbol} terlalu sedikit, skip.")
                    continue
                df = df[(df['ts'] >= pd.Timestamp(_START_MS, unit='ms')) &
                        (df['ts'] <= pd.Timestamp(_END_MS, unit='ms'))].reset_index(drop=True)
                coins_data[symbol] = df
                _log_msg(f"   ✅ {symbol}: {len(df)} candle")
            except Exception as e:
                _log_msg(f"   ❌ {symbol}: {e}")

        bt.REQUIRE_BOS = False  # FVG-only mode: tidak perlu BOS H1
        _log_msg(f"\n🔄 Concurrent backtest (FVG-only): {len(coins_data)} coin, max {bt.MAX_CONCURRENT} slot...")
        concurrent_trades, concurrent_final, monthly_diag_bt = bt.backtest_concurrent(
            coins_data, initial_balance=INITIAL_BALANCE, max_concurrent=bt.MAX_CONCURRENT)

        if not concurrent_trades:
            _log_msg("⚠ Tidak ada trade dari concurrent backtest.")
        else:
            total_n = len(concurrent_trades)
            total_w = sum(1 for t in concurrent_trades if t['outcome'] == 'tp')
            wr = total_w / total_n * 100 if total_n else 0
            cpnl = concurrent_final - INITIAL_BALANCE

            def _rr(t):
                dist_t = t.get('dist', 0)
                if dist_t <= 0: return None
                stype_t = t.get('type', 'Long')
                return (t['exit_price'] - t['entry']) / dist_t if stype_t == 'Long' \
                       else (t['entry'] - t['exit_price']) / dist_t

            win_rr  = [r for t in concurrent_trades if t['outcome'] == 'tp'  and (r := _rr(t)) is not None]
            loss_rr = [r for t in concurrent_trades if t['outcome'] != 'tp'  and (r := _rr(t)) is not None]
            avg_win  = sum(win_rr)  / len(win_rr)  if win_rr  else 0.0
            avg_loss = sum(loss_rr) / len(loss_rr) if loss_rr else 0.0
            total_fees = sum(t.get('fee_usd', 0.0) for t in concurrent_trades)
            gross_pnl  = cpnl + total_fees

            _log_msg(f"TOTAL: {total_n} trade | WR:{wr:.1f}% | "
                     f"AvgWin:{avg_win:.2f}R | AvgLoss:{avg_loss:.2f}R | "
                     f"Compound: ${INITIAL_BALANCE:.2f} → ${concurrent_final:.2f} "
                     f"(+${cpnl:.2f}, +{cpnl/INITIAL_BALANCE*100:.0f}% ROI)")
            _log_msg(f"Fee total: ${total_fees:.4f} | Gross (sebelum fee): ${gross_pnl:.4f} | "
                     f"Fee per trade avg: ${total_fees/total_n:.6f}")

            # Per-coin breakdown
            from collections import defaultdict
            coin_stats = defaultdict(lambda: {'n': 0, 'w': 0, 'pnl': 0, 'win_rr': [], 'loss_rr': []})
            for t in concurrent_trades:
                s = coin_stats[t['symbol']]
                s['n']   += 1
                s['w']   += 1 if t['outcome'] == 'tp' else 0
                s['pnl'] += t['pnl_usd']
                r = _rr(t)
                if r is not None:
                    if t['outcome'] == 'tp':
                        s['win_rr'].append(r)
                    else:
                        s['loss_rr'].append(r)
            _log_msg("\nPer-coin (trade efektif setelah slot filter):")
            for sym in COINS:
                s = coin_stats.get(sym)
                if not s or s['n'] == 0:
                    _log_msg(f"  {sym:<20} — tidak ada trade")
                else:
                    wr_c     = s['w'] / s['n'] * 100
                    aw = sum(s['win_rr'])  / len(s['win_rr'])  if s['win_rr']  else 0.0
                    al = sum(s['loss_rr']) / len(s['loss_rr']) if s['loss_rr'] else 0.0
                    rr_str = f"Win:{aw:.2f}R Loss:{al:.2f}R"
                    _log_msg(f"  {sym:<20} {s['n']:>4} trade | WR:{wr_c:.0f}% | "
                             f"PnL:${s['pnl']:.2f} | {rr_str}")

            # ── Per-bulan breakdown ───────────────────────────────────────
            import calendar
            monthly = {}
            for t in concurrent_trades:
                ts_ms = t.get('entry_ts') or t.get('exit_ts')
                if not ts_ms:
                    continue
                dt  = pd.Timestamp(ts_ms, unit='ms')
                key = (dt.year, dt.month)
                if key not in monthly:
                    monthly[key] = {'n': 0, 'w': 0, 'pnl': 0.0, 'win_rr': []}
                m = monthly[key]
                m['n']   += 1
                m['w']   += 1 if t['outcome'] == 'tp' else 0
                m['pnl'] += t['pnl_usd']
                r = _rr(t)
                if r is not None and t['outcome'] == 'tp':
                    m['win_rr'].append(r)
            _log_msg("\nPer-bulan (trade | WR | PnL | Setup=BOS+FVG | SlotOK | BlokSlot | CHOCH):")
            for (yr, mo) in sorted(monthly.keys()):
                m    = monthly[(yr, mo)]
                wr_m = m['w'] / m['n'] * 100 if m['n'] else 0
                aw_m = sum(m['win_rr']) / len(m['win_rr']) if m['win_rr'] else 0.0
                name = f"{calendar.month_abbr[mo]}-{yr}"
                d    = monthly_diag_bt.get((yr, mo), {})
                setup        = d.get('setup', 0)
                slot_ok      = d.get('slot_ok', 0)
                slot_blocked = d.get('slot_blocked', 0)
                choch        = d.get('choch', 0)
                _log_msg(f"  {name:<12} {m['n']:>4} trade | WR:{wr_m:.0f}% | "
                         f"PnL:${m['pnl']:.2f} | AvgWin:{aw_m:.2f}R | "
                         f"Setup:{setup} SlotOK:{slot_ok} Blok:{slot_blocked} CHOCH:{choch}")

        with _lock:
            _phase = 'done'
            _results = []
            _compound_final_bal = concurrent_final
            _all_trades = concurrent_trades
        return

    for symbol in COINS:
        _log_msg(f"\n{'─'*54}")
        _log_msg(f"▶ {symbol}")
        _log_msg("  Fetching M5 data dari Bybit API...")

        df = fetch_bybit_m5(symbol)
        if df.empty or len(df) < 3000:
            _log_msg(f"  ⚠ Data terlalu sedikit ({len(df)} candle) — skip.")
            results.append({'symbol': symbol, 'status': 'no_data'})
            with _lock: _results = list(results)
            continue

        date_from = df['ts'].iloc[0].strftime('%Y-%m-%d')
        date_to   = df['ts'].iloc[-1].strftime('%Y-%m-%d')
        expected  = 365 * 24 * 12
        missing   = max(0, expected - len(df))
        _log_msg(f"  Data: {len(df):,} candle | {date_from} → {date_to} "
                 f"| Missing: {missing:,} (~{missing/expected*100:.1f}%)")

        # ATR P25
        p25_atr = calc_p25_atr(df)
        bt.ATR_THRESHOLD[symbol] = round(p25_atr, 4)
        _log_msg(f"  ATR P25: {p25_atr*100:.3f}% → threshold = {p25_atr:.4f}")

        # Diagnostic
        try:
            _diagnose(symbol, df, p25_atr)
        except Exception as e:
            _log_msg(f"  [DIAG] Error: {e}")

        # Full backtest
        _log_msg("  Running full backtest (1 tahun)...")
        try:
            trades, final_bal, dbg = bt.backtest_coin(symbol, df, INITIAL_BALANCE)
        except Exception as e:
            import traceback
            _log_msg(f"  ❌ Error: {e}\n{traceback.format_exc()}")
            results.append({'symbol': symbol, 'status': 'error', 'p25_atr': p25_atr})
            with _lock: _results = list(results)
            continue

        n = len(trades)
        if n == 0:
            _log_msg("  Tidak ada trade ditemukan.")
            results.append({
                'symbol': symbol, 'status': 'ok', 'trades': 0,
                'win': 0, 'loss': 0, 'wr': 0.0, 'pnl': 0.0,
                'roi': 0.0, 'max_dd': 0.0, 'pf': 0.0,
                'final_bal': INITIAL_BALANCE, 'longs': 0, 'shorts': 0,
                'p25_atr': p25_atr,
            })
            with _lock: _results = list(results)
            continue

        wins      = [t for t in trades if t['outcome'] == 'tp']
        losses    = [t for t in trades if t['outcome'] == 'sl']
        sl_then_tp = sum(1 for t in trades if t.get('sl_then_tp'))
        sl_choch   = sum(1 for t in trades if t.get('sl_choch'))
        pnl    = sum(t['pnl_usd'] for t in trades)
        wr     = len(wins) / n * 100
        roi    = pnl / INITIAL_BALANCE * 100

        peak = INITIAL_BALANCE; cur_bal = INITIAL_BALANCE; max_dd = 0.0
        for t in trades:
            cur_bal += t['pnl_usd']
            if cur_bal > peak: peak = cur_bal
            dd = (peak - cur_bal) / peak * 100
            if dd > max_dd: max_dd = dd

        gw = sum(t['pnl_usd'] for t in trades if t['pnl_usd'] > 0)
        gl = abs(sum(t['pnl_usd'] for t in trades if t['pnl_usd'] < 0))
        pf = gw / gl if gl > 0 else 99.0

        nl = len(losses)
        sl_drift   = nl - sl_then_tp - sl_choch
        choch_pct  = sl_choch / nl * 100 if nl else 0
        _log_msg(
            f"  ✅ Trade:{n} | W:{len(wins)} L:{nl} | WR:{wr:.1f}% | "
            f"PnL:${pnl:.2f} | ROI:{roi:.1f}% | MaxDD:{max_dd:.1f}% | PF:{pf:.2f} | "
            f"SL→TP:{sl_then_tp} CHOCH:{sl_choch} Drift:{sl_drift} ({choch_pct:.0f}% CHOCH)"
        )
        skip_rsn = dbg.get('simskip_reasons', {})
        rsn_str  = ' '.join(f"{k}:{v}" for k, v in sorted(skip_rsn.items())) if skip_rsn else ''
        _log_msg(
            f"  MSS→Trade: {dbg['mss_found']} ditemukan → {n} traded"
            f" | skip: InTrade:{dbg['intrade']} DirFail:{dbg['dir_fail']} SimSkip:{dbg['sim_skip']}"
            + (f" [{rsn_str}]" if rsn_str else "")
        )
        mae_trades = [t['mae_r'] for t in trades if t.get('sl_then_tp') and t.get('mae_r', 0) > 0]
        if mae_trades:
            buckets = {}
            for r in mae_trades:
                lo = int(r); key = f"{lo}-{lo+1}R"
                buckets[key] = buckets.get(key, 0) + 1
            bkt_str = "  ".join(f"{k}:{v}" for k, v in sorted(buckets.items(), key=lambda x: int(x[0].split('-')[0])))
            _log_msg(f"  MAE (SL→TP={sl_then_tp}): {bkt_str}")
        mfe_trades = [t['mfe_r'] for t in trades
                      if t['outcome'] in ('sl', 'timeout')
                      and not t.get('sl_then_tp')
                      and t.get('mfe_r', -1) >= 0]
        if mfe_trades:
            mbuckets = {}
            for r in mfe_trades:
                lo = int(r); key = f"{lo}-{lo+1}R"
                mbuckets[key] = mbuckets.get(key, 0) + 1
            mkt_str = "  ".join(f"{k}:{v}" for k, v in sorted(mbuckets.items(), key=lambda x: int(x[0].split('-')[0])))
            n_dr = sum(1 for t in trades if t['outcome'] in ('sl', 'timeout') and not t.get('sl_then_tp'))
            _log_msg(f"  MFE Dr (n={len(mfe_trades)}/{n_dr}): {mkt_str}")

        # Avg R:R per coin — dari exit_price aktual (bukan far TP)
        rr_list = []
        for t in trades:
            if t.get('outcome') != 'tp': continue
            ep = t.get('entry', 0); sl = t.get('sl', 0); xp = t.get('exit_price', 0)
            sl_dist = abs(ep - sl)
            if ep and sl_dist > 0 and xp:
                rr_list.append(abs(xp - ep) / sl_dist)
        avg_rr = sum(rr_list) / len(rr_list) if rr_list else 0.0
        _log_msg(f"  Avg R:R = {avg_rr:.2f}:1 (dari {len(rr_list)} win)")

        results.append({
            'symbol': symbol, 'status': 'ok',
            'trades': n, 'win': len(wins), 'loss': nl,
            'wr': wr, 'pnl': pnl, 'roi': roi,
            'max_dd': max_dd, 'pf': pf, 'final_bal': final_bal,
            'longs': len([t for t in trades if t['type'] == 'Long']),
            'shorts': len([t for t in trades if t['type'] == 'Short']),
            'p25_atr': p25_atr,
            'sl_then_tp': sl_then_tp,
            'sl_choch':   sl_choch,
            'avg_rr':     round(avg_rr, 2),
            'win_loss': _win_loss_analysis(trades),
            '_trades':  trades,
        })
        all_trades_list.extend(trades)

        # Progressive compound: update setiap kali 1 coin selesai
        rep_tmp, cpnd_tmp, _ = _compound_replay(all_trades_list)
        cpnl_tmp = {}
        for _t in rep_tmp:
            cpnl_tmp[_t['symbol']] = cpnl_tmp.get(_t['symbol'], 0.0) + _t['compound_pnl']
        qs_tmp = _calc_quarters_compound(rep_tmp)
        for r in results:
            r['compound_pnl'] = cpnl_tmp.get(r['symbol'], 0.0)
        with _lock:
            _results            = list(results)
            _quarter_stats      = qs_tmp
            _compound_final_bal = cpnd_tmp

    # ── Compound replay: 1 pot bersama, risk 1% per trade ───────────────
    _log_msg(f"\n{'='*62}")
    _log_msg("📐 Compound Replay (1 pot bersama, risk 1%/trade dari balance live)...")
    replayed, compound_final, port_max_dd = _compound_replay(all_trades_list)

    # Update per-coin compound PnL
    coin_cpnl = {}
    for t in replayed:
        coin_cpnl.setdefault(t['symbol'], 0.0)
        coin_cpnl[t['symbol']] += t['compound_pnl']
    for r in results:
        r['compound_pnl'] = coin_cpnl.get(r['symbol'], 0.0)

    qs = _calc_quarters_compound(replayed)

    total_n   = len(all_trades_list)
    total_w   = sum(1 for t in all_trades_list if t['outcome'] == 'tp')
    wr_all    = total_w / total_n * 100 if total_n else 0
    cpnl_tot  = compound_final - INITIAL_BALANCE
    # Hitung berapa trade yang di-skip karena slot penuh
    n_skipped = sum(1 for t in replayed if t.get('slot_skip'))
    n_traded  = total_n - n_skipped

    # Overall avg R:R (dari semua win) + overall PF (dari semua trade)
    all_rr = []; gw_r = 0.0; gl_r = 0.0
    for t in all_trades_list:
        ep = t.get('entry', 0); sl_p = t.get('sl', 0); xp = t.get('exit_price', 0)
        sl_dist = abs(ep - sl_p)
        if not (ep and sl_dist > 0 and xp):
            continue
        if t['type'] == 'Long':
            r = (xp - ep) / sl_dist
        else:
            r = (ep - xp) / sl_dist
        if r > 0:
            gw_r += r
            if t.get('outcome') == 'tp':
                all_rr.append(r)
        else:
            gl_r += abs(r)
    overall_rr = round(sum(all_rr) / len(all_rr), 2) if all_rr else 0.0
    overall_pf = round(gw_r / gl_r, 2) if gl_r > 0 else 99.0

    _log_msg(f"TOTAL: {total_n} trade potensial | Slot skip (max {bt.MAX_CONCURRENT}): {n_skipped} "
             f"| Efektif: {n_traded} trade")
    _log_msg(f"WR:{wr_all:.1f}% | Avg R:R:{overall_rr:.2f}:1 | "
             f"PF:{overall_pf:.2f} | MaxDD:{port_max_dd:.1f}% | "
             f"Compound: ${INITIAL_BALANCE:.2f} → ${compound_final:.2f} "
             f"(+${cpnl_tot:.2f}, +{cpnl_tot/INITIAL_BALANCE*100:.0f}% ROI)")
    for q, s in qs.items():
        _log_msg(f"  {q}: {s['trades']} trade | WR:{s['wr']:.0f}% | "
                 f"PnL:${s['pnl']:.2f} | ${s['start_bal']:.2f}→${s['end_bal']:.2f}")
    _log_msg("✅ SELESAI — Buka /readme untuk markdown README.md")

    with _lock:
        _phase               = 'done'
        _quarter_stats       = qs
        _all_trades          = list(replayed)
        _compound_final_bal  = compound_final
        _results             = list(results)
        _overall_avg_rr      = overall_rr
        _overall_pf          = overall_pf
        _portfolio_max_dd    = port_max_dd


# ── README markdown generator ─────────────────────────────────────────────
def _gen_readme() -> str:
    with _lock:
        results      = list(_results)
        qs           = dict(_quarter_stats)
        phase        = _phase
        final_bal    = _compound_final_bal
        overall_rr   = _overall_avg_rr
        overall_pf   = _overall_pf
        port_max_dd  = _portfolio_max_dd

    if phase == 'running':
        return "# Backtest masih berjalan, coba lagi nanti…\n"

    ok       = [r for r in results if r.get('status') == 'ok' and r.get('trades', 0) > 0]
    total_n  = sum(r['trades'] for r in ok)
    total_w  = sum(r['win'] for r in ok)
    wr_all   = total_w / total_n * 100 if total_n else 0
    cpnl_tot = final_bal - INITIAL_BALANCE
    roi_all  = cpnl_tot / INITIAL_BALANCE * 100

    # Per-coin table (gunakan compound_pnl)
    coin_rows = ""
    for r in sorted(ok, key=lambda x: x.get('compound_pnl', 0), reverse=True):
        sym   = r['symbol']
        cpnl  = r.get('compound_pnl', r['pnl'])
        sign  = '+' if cpnl >= 0 else ''
        roi_c = cpnl / INITIAL_BALANCE * 100
        rr_c = r.get('avg_rr', 0.0)
        rr_s = f"{rr_c:.2f}:1" if rr_c > 0 else "—"
        coin_rows += (
            f"| {sym} | {r['trades']} | {r['wr']:.0f}% | "
            f"{sign}${cpnl:.2f} | {sign}{roi_c:.0f}% | {r['max_dd']:.1f}% | "
            f"{r['pf']:.2f} | {rr_s} | {r['p25_atr']:.4f} |\n"
        )

    total_sign     = '+' if cpnl_tot >= 0 else ''
    roi_total_sign = '+' if roi_all >= 0 else ''
    rr_tot_str  = f"**{overall_rr:.2f}:1**" if overall_rr > 0 else "—"
    pf_tot_str  = f"**{overall_pf:.2f}**"   if overall_pf > 0 else "—"
    dd_tot_str  = f"**{port_max_dd:.1f}%**" if port_max_dd > 0 else "—"
    coin_rows += (
        f"| **TOTAL** | **{total_n}** | **{wr_all:.0f}%** | "
        f"**{total_sign}${cpnl_tot:.2f}** | **{roi_total_sign}{roi_all:.0f}%** | "
        f"{dd_tot_str} | {pf_tot_str} | {rr_tot_str} | — |\n"
    )

    # Win/loss analysis — per coin + total keseluruhan
    all_coin_trades = []
    for r in ok:
        all_coin_trades.extend(r.get('_trades', []))
    wl_total    = _win_loss_analysis(all_coin_trades)
    ins_total   = _insight(wl_total.get('win'), wl_total.get('loss'))
    wl_rows_md  = (
        f"| **TOTAL** | **{_fmt_grp(wl_total.get('win'))}** | "
        f"**{_fmt_grp(wl_total.get('loss'))}** | **{ins_total}** |\n"
    )
    for r in sorted(ok, key=lambda x: x.get('compound_pnl', 0), reverse=True):
        wl  = r.get('win_loss', {})
        ws  = wl.get('win')
        ls  = wl.get('loss')
        ins = _insight(ws, ls)
        wl_rows_md += (
            f"| {r['symbol']} | {_fmt_grp(ws)} | {_fmt_grp(ls)} | {ins} |\n"
        )

    # Quarter table
    q_rows = ""
    if qs:
        for q, s in qs.items():
            sign = '+' if s['pnl'] >= 0 else ''
            roi_q = (s['end_bal'] - s['start_bal']) / s['start_bal'] * 100 if s['start_bal'] else 0
            q_rows += (
                f"| {q} | {s['trades']} | {s['wr']:.0f}% | "
                f"{sign}${s['pnl']:.2f} | +{roi_q:.1f}% | "
                f"${s['start_bal']:.2f} → ${s['end_bal']:.2f} |\n"
            )
    else:
        q_rows = "| — | — | — | — | — | — |\n"

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    return f"""# 🤖 SMC Trading Bot v4

Bot trading otomatis berbasis **Smart Money Concepts (SMC)** untuk Bybit Futures (USDT Perpetual).

---

## 📐 Strategi

```
BOS H1 → FVG Kuat (C3 vol > avg20H) → SBR Touch M5
  → Entry market di C1.close (SBR/RBS demand/supply zone)
  → SL di C1.low/C1.high ± 10% gap buffer
  → Trail stop {_TRAIL_STOP}× dist (aktif setelah +1R) → Reverse max 2×
```

**Risk Management:**
- Risk per trade: **1% dari balance** (compound — tiap trade risk ikut balance live)
- Exit: **trailing stop** {_TRAIL_STOP}× dist, aktif setelah profit +1R
- Reverse: Long→SL→Short (max 2 kali per setup)
- Leverage: otomatis sesuai limit coin, maks 10×

---

## 📊 Hasil Backtest — Jan 2025–Apr 2026

> Modal ${INITIAL_BALANCE:.0f} | Risk 1%/trade compound (1 pot bersama) | Trail {_TRAIL_STOP}R + Reverse | ATR Filter Adaptif
> _{len(COINS)} Coin | Data Bybit Perpetual USDT | M5+H1 | Jan 2025–Apr 2026_
> _(Generated: {today})_

### Per Coin (diurutkan PnL terbesar)

| Coin | Trade | WR% | PnL ($) | ROI% | MaxDD% | PF | Avg R:R | ATR P25 |
|------|------:|----:|--------:|-----:|-------:|---:|--------:|--------:|
{coin_rows}

**${INITIAL_BALANCE:.2f} → ${final_bal:.2f} dalam setahun (+{roi_all:.0f}% ROI)**

### Analisis Win/Loss per Coin

> Format: Direction · Vol C3 (FVG strength) · Gap size · Sesi dominan

| Coin | ✅ Win (pola rata-rata) | ❌ Loss (pola rata-rata) | 💡 Insight |
|------|------------------------|-------------------------|------------|
{wl_rows_md}
### Per Kuartal

| Kuartal | Trade | WR% | PnL | ROI Kuartal | Bal Awal → Akhir |
|---------|------:|----:|----:|:-----------:|:----------------:|
{q_rows}
### Konfigurasi

| Parameter | Nilai |
|-----------|-------|
| Modal Awal | ${INITIAL_BALANCE:.0f} |
| Risk per Trade | 1% balance (compound) |
| Entry Mode | {_ENTRY_MODE} (SBR — C1.close) |
| Exit | Trail stop {_TRAIL_STOP}× dist + Reverse 2× |
| Leverage | maks 10× |
| Fee | 0.055%/sisi (Bybit taker) |
| Touch Vol Min | {_TOUCH_VOL_MIN}× avg20M5 |
| Max Gap | {_MAX_GAP_PCT*100:.2f}% dari harga |
| Min SL distance | {_MIN_DIST_PCT*100:.1f}% |

---

## ⚙️ Daftar Coin ({len(COINS)} coin aktif)

```python
SYMBOLS = {COINS}
```

## Catatan

Strategi: **FVG SBR** (BOS H1 → FVG kuat → OCL touch → entry limit di C1.close dengan trailing stop).
Filter aktif: C3 vol > avg20H, CHOCH invalidasi setup, TOUCH_VOL_MIN di fill candle, MAX_GAP_PCT.

---

## 🚀 Deploy ke Railway

Set environment variables:

| Variable | Keterangan |
|----------|-----------|
| `API_KEY` | Bybit API Key (permission: Trade + Read) |
| `API_SECRET` | Bybit API Secret |
| `TESTNET` | `true` untuk testnet, default `false` |

Log monitoring: `https://<project>.up.railway.app/logs`

---

> ⚠️ Hasil backtest tidak menjamin performa di masa depan. Trading crypto mengandung risiko tinggi.
"""


# ── HTML rendering ────────────────────────────────────────────────────────
_CSS = """
<style>
*{box-sizing:border-box}
body{font-family:'Courier New',monospace;background:#0d1117;color:#c9d1d9;
     padding:16px;max-width:100%;margin:0 auto;overflow-x:hidden}
h1{color:#58a6ff;font-size:16px;margin:0 0 6px}
h2{color:#79c0ff;font-size:13px;margin:18px 0 6px;text-transform:uppercase;letter-spacing:.5px}
p{margin:4px 0;font-size:12px}
.tbl-wrap{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:max-content;min-width:100%;border-collapse:collapse;margin:6px 0;font-size:11px}
th{background:#161b22;color:#58a6ff;padding:7px 10px;text-align:left;
   border-bottom:2px solid #30363d;white-space:nowrap}
td{padding:6px 10px;border-bottom:1px solid #21262d;white-space:nowrap}
tr:hover td{background:#161b22}
.g{color:#3fb950}.r{color:#f85149}.y{color:#e3b341}
.log{background:#161b22;border:1px solid #30363d;border-radius:6px;
     padding:12px;max-height:400px;overflow-y:auto;
     white-space:pre-wrap;font-size:10px;line-height:1.6;word-break:break-all}
.chip{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold}
.chip-run{background:#1c3c5e;color:#58a6ff}
.chip-done{background:#1a3d28;color:#3fb950}
.note{background:#161b22;border-left:3px solid #58a6ff;padding:10px 12px;
      border-radius:0 6px 6px 0;font-size:11px;margin:10px 0 0;line-height:1.6}
a{color:#58a6ff}
@media(max-width:600px){h1{font-size:14px}}
</style>
"""

def _render_html() -> bytes:
    with _lock:
        phase       = _phase
        log_cp      = list(_log)
        res_cp      = list(_results)
        qs          = dict(_quarter_stats)
        cmp_bal     = _compound_final_bal
        overall_rr  = _overall_avg_rr
        port_max_dd = _portfolio_max_dd

    refresh = '<meta http-equiv="refresh" content="8">' if phase == 'running' else ''
    chip    = ('<span class="chip chip-run">⏳ Running…</span>' if phase == 'running'
               else '<span class="chip chip-done">✅ Selesai</span>')

    # ── per-coin table ──
    coin_rows = ''
    total_n = total_win = total_loss = 0
    total_cpnl = 0.0
    for r in res_cp:
        sym     = r['symbol']
        atr_str = f"{r['p25_atr']:.4f}" if 'p25_atr' in r else '—'
        if r.get('status') in ('no_data', 'error'):
            label = '⚠ no data' if r['status'] == 'no_data' else '❌ error'
            coin_rows += f'<tr><td><b>{sym}</b></td><td class="r" colspan="10">{label}</td></tr>\n'
        elif r.get('trades', 0) == 0:
            coin_rows += (f'<tr><td><b>{sym}</b></td><td class="y">0</td>'
                          + '<td class="y">—</td>' * 8
                          + f'<td>{atr_str}</td></tr>\n')
        else:
            cpnl   = r.get('compound_pnl', r['pnl'])
            roi    = cpnl / INITIAL_BALANCE * 100
            wr_c   = 'g' if r['wr']     >= 55 else ('y' if r['wr'] >= 45 else 'r')
            pnl_c  = 'g' if cpnl        >= 0  else 'r'
            roi_c  = 'g' if roi         >= 0  else 'r'
            dd_c   = 'r' if r['max_dd'] > 20  else ('y' if r['max_dd'] > 10 else 'g')
            pf_c   = 'g' if r['pf']     >= 3  else ('y' if r['pf'] >= 2 else 'r')
            sign   = '+' if cpnl >= 0 else ''
            stp    = r.get('sl_then_tp', 0)
            schoch = r.get('sl_choch', 0)
            nl     = r['loss']
            sdrift = nl - stp - schoch
            choch_pct = schoch / nl * 100 if nl else 0
            stp_c  = 'g' if stp / nl * 100 >= 30 else 'y' if stp / nl * 100 >= 15 else 'r' if nl else 'g'
            choch_c = 'g' if choch_pct >= 50 else ('y' if choch_pct >= 30 else 'r')
            total_n += r['trades']; total_win += r['win']; total_loss += r['loss']
            total_cpnl += cpnl
            avg_rr  = r.get('avg_rr', 0.0)
            rr_c    = 'g' if avg_rr >= 2.0 else ('y' if avg_rr >= 1.5 else 'r')
            coin_rows += (
                f'<tr>'
                f'<td><b>{sym}</b></td>'
                f'<td>{r["trades"]}</td>'
                f'<td class="{wr_c}">{r["wr"]:.1f}%</td>'
                f'<td class="{pnl_c}">{sign}${cpnl:.2f}</td>'
                f'<td class="{roi_c}">{sign}{roi:.0f}%</td>'
                f'<td class="{dd_c}">{r["max_dd"]:.1f}%</td>'
                f'<td class="{pf_c}">{r["pf"]:.2f}</td>'
                f'<td class="{rr_c}">{avg_rr:.2f}:1</td>'
                f'<td class="{stp_c}" title="SL→TP: {stp} | CHOCH: {schoch} | Drift: {sdrift}">'
                f'<small>TP:{stp} CH:{schoch} Dr:{sdrift}</small></td>'
                f'<td class="{choch_c}" title="{choch_pct:.0f}% dari {nl} loss kena CHOCH">'
                f'{choch_pct:.0f}%</td>'
                f'<td class="g">{atr_str}</td>'
                f'</tr>\n'
            )

    if total_n:
        wr_tot    = total_win / total_n * 100
        roi_tot   = total_cpnl / INITIAL_BALANCE * 100
        sign      = '+' if total_cpnl >= 0 else ''
        ok_res    = [r for r in res_cp if r.get('status') == 'ok']
        stp_tot   = sum(r.get('sl_then_tp', 0) for r in ok_res)
        schoch_tot = sum(r.get('sl_choch', 0) for r in ok_res)
        nl_tot    = total_loss
        sdrift_tot = nl_tot - stp_tot - schoch_tot
        choch_tot_pct = schoch_tot / nl_tot * 100 if nl_tot else 0
        rr_tot_c  = 'g' if overall_rr >= 2.0 else ('y' if overall_rr >= 1.5 else 'r')
        rr_tot_s  = f'{overall_rr:.2f}:1' if overall_rr > 0 else '—'
        dd_tot_c  = 'r' if port_max_dd > 20 else ('y' if port_max_dd > 10 else 'g')
        dd_tot_s  = f'{port_max_dd:.1f}%' if port_max_dd > 0 else '—'
        coin_rows += (
            f'<tr style="border-top:2px solid #30363d;font-weight:bold">'
            f'<td>TOTAL ({len(res_cp)} coin)</td>'
            f'<td>{total_n}</td>'
            f'<td class="{"g" if wr_tot>=55 else "y"}">{wr_tot:.1f}%</td>'
            f'<td class="{"g" if total_cpnl>=0 else "r"}">{sign}${total_cpnl:.2f}</td>'
            f'<td class="{"g" if total_cpnl>=0 else "r"}">{sign}{roi_tot:.0f}%</td>'
            f'<td class="{dd_tot_c}">{dd_tot_s}</td><td>—</td>'
            f'<td class="{rr_tot_c}">{rr_tot_s}</td>'
            f'<td><small>TP:{stp_tot} CH:{schoch_tot} Dr:{sdrift_tot}</small></td>'
            f'<td>{choch_tot_pct:.0f}%</td>'
            f'<td>—</td></tr>\n'
        )

    coin_table = f'''
        <table>
          <tr>
            <th>Coin</th><th>Trade</th><th>WR%</th>
            <th>PnL Compound</th><th>ROI%</th><th>MaxDD%</th><th>PF</th>
            <th title="Rata-rata R:R per trade (reward/risk)">Avg R:R</th>
            <th title="SL→TP: balik ke TP setelah SL | CHOCH: struktur berbalik | Drift: ambiguous">SL Breakdown</th>
            <th title="Persen loss yang kena CHOCH (struktur beneran balik)">CHOCH%</th>
            <th>ATR P25</th>
          </tr>
          {coin_rows or '<tr><td colspan="11" class="y">Menunggu hasil pertama…</td></tr>'}
        </table>
    '''

    # ── win/loss analysis table ──
    all_wl_trades = []
    for r in res_cp:
        if r.get('status') == 'ok':
            all_wl_trades.extend(r.get('_trades', []))
    wl_tot    = _win_loss_analysis(all_wl_trades)
    ins_tot   = _insight(wl_tot.get('win'), wl_tot.get('loss'))
    wl_rows   = (
        f'<tr style="background:#1a2a1a;font-weight:bold">'
        f'<td>TOTAL</td>'
        f'<td class="g">{_fmt_grp(wl_tot.get("win"))}</td>'
        f'<td class="r">{_fmt_grp(wl_tot.get("loss"))}</td>'
        f'<td class="y">{ins_tot}</td>'
        f'</tr>\n'
    )
    for r in res_cp:
        if r.get('status') != 'ok' or r.get('trades', 0) == 0:
            continue
        wl  = r.get('win_loss', {})
        ws  = wl.get('win')
        ls  = wl.get('loss')
        ins = _insight(ws, ls)
        wl_rows += (
            f'<tr>'
            f'<td><b>{r["symbol"]}</b></td>'
            f'<td class="g">{_fmt_grp(ws)}</td>'
            f'<td class="r">{_fmt_grp(ls)}</td>'
            f'<td class="y">{ins}</td>'
            f'</tr>\n'
        )

    wl_table = f'''
        <table>
          <tr>
            <th>Coin</th>
            <th title="Direction · Vol C3 · FVG Gap% · Sesi dominan">✅ Win ({total_win if total_n else 0}) — Direction · Vol · Gap · Sesi</th>
            <th title="Direction · Vol C3 · FVG Gap% · Sesi dominan">❌ Loss ({total_loss if total_n else 0}) — Direction · Vol · Gap · Sesi</th>
            <th>💡 Insight</th>
          </tr>
          {wl_rows or '<tr><td colspan="4" class="y">Menunggu hasil…</td></tr>'}
        </table>
    '''

    # ── quarter table ──
    q_rows = ''
    for q, s in qs.items():
        sign  = '+' if s['pnl'] >= 0 else ''
        wr_c  = 'g' if s['wr'] >= 55 else ('y' if s['wr'] >= 45 else 'r')
        pnl_c = 'g' if s['pnl'] >= 0 else 'r'
        q_rows += (
            f'<tr>'
            f'<td><b>{q}</b></td>'
            f'<td>{s["trades"]}</td>'
            f'<td class="{wr_c}">{s["wr"]:.1f}%</td>'
            f'<td class="{pnl_c}">{sign}${s["pnl"]:.2f}</td>'
            f'<td>${s["start_bal"]:.2f} → ${s["end_bal"]:.2f}</td>'
            f'</tr>\n'
        )

    q_table = (f'''
        <table>
          <tr><th>Kuartal</th><th>Trade</th><th>WR%</th><th>PnL</th>
              <th>Bal Awal → Akhir</th></tr>
          {q_rows or '<tr><td colspan="5" class="y">Menunggu selesai…</td></tr>'}
        </table>
    ''' if qs or phase == 'done' else '')

    log_html = '\n'.join(log_cp[-400:])

    done_note = ''
    if phase == 'done':
        cpnl = cmp_bal - INITIAL_BALANCE
        roi  = cpnl / INITIAL_BALANCE * 100
        done_note = (
            f'<p class="g">✅ Selesai! '
            f'Compound: <b>${INITIAL_BALANCE:.2f} → ${cmp_bal:.2f}</b> '
            f'(+${cpnl:.2f}, +{roi:.0f}% ROI) &nbsp;|&nbsp; '
            f'<a href="/readme">/readme</a> untuk export README.md</p>'
        )

    n_done  = len(res_cp)
    n_total = len(COINS)

    return f'''<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <title>Backtest {len(COINS)} Coins — SMC Bot {_ENTRY_MODE}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {_CSS}
  {refresh}
</head>
<body>
  <h1>🤖 Backtest SMC Bot — {len(COINS)} Coins ({_ENTRY_MODE})</h1>
  <p>
    <b>{n_done}/{n_total} coin selesai</b> &nbsp;|&nbsp;
    Modal: <b>${INITIAL_BALANCE:.0f}</b> &nbsp;|&nbsp;
    Period: <b>Jan 2025 → Apr 2026</b> &nbsp;|&nbsp;
    Status: {chip}
  </p>
  {done_note}

  <h2>Hasil Per Coin</h2>
  <div class="tbl-wrap">{coin_table}</div>

  <h2>Analisis Win/Loss per Coin</h2>
  <p style="font-size:11px;color:#8b949e">
    Format: Direction · Vol C3 (FVG strength) · Vol sentuh SBR · Gap size · Sesi dominan
  </p>
  <div class="tbl-wrap">{wl_table}</div>

  {'<h2>Per Kuartal (Agregat Semua Coin)</h2><div class="tbl-wrap">' + q_table + '</div>' if q_table else ''}

  <div class="note">
    💡 <b>PnL Compound</b> = kontribusi tiap coin ke 1 pot bersama (risk 1% dari balance live per trade).
    <br><b>Per Kuartal</b> = semua coin diurutkan waktu, balance bergerak bersama.
    <br>Ini sama persis dengan cara bot live bekerja: tiap trade, risk ikut balance Bybit saat itu.
  </div>

  <h2>Log Progress</h2>
  <div class="log" id="log">{log_html}</div>
  <script>var e=document.getElementById('log');if(e)e.scrollTop=e.scrollHeight;</script>
</body>
</html>'''.encode('utf-8')


# ── HTTP handler ──────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/readme'):
            body  = _gen_readme().encode('utf-8')
            ctype = 'text/plain; charset=utf-8'
        elif self.path.startswith('/logs'):
            with _lock:
                body = '\n'.join(_log).encode('utf-8')
            ctype = 'text/plain; charset=utf-8'
        else:
            body  = _render_html()
            ctype = 'text/html; charset=utf-8'

        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


# ── Entry point ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    threading.Thread(target=_run, daemon=True).start()
    server = HTTPServer(('0.0.0.0', PORT), _Handler)
    print(f"🌐 Server running on port {PORT}", flush=True)
    server.serve_forever()
