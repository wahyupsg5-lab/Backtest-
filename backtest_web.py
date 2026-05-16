"""
backtest_web.py — Backtest SEMUA coin bot live via Bybit API
22 Coins | Full Year 2025 | Modal $10 | Risk 1% compound | TP 3R

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

COINS = [
    'XVGUSDT', 'BELUSDT', 'TAOUSDT', '1000BONKUSDT', 'BERAUSDT',
    'DOGEUSDT', 'USUALUSDT',
    'FARTCOINUSDT', '1000PEPEUSDT', '1000FLOKIUSDT',
    'WIFUSDT', 'PENGUUSDT', 'PNUTUSDT',
    'SUIUSDT', 'AVAXUSDT', 'ONDOUSDT', 'JUPUSDT', 'EIGENUSDT',
    'LINKUSDT',
    'WLDUSDT', 'VIRTUALUSDT', 'ORCAUSDT',
]

# 2025-01-01 00:00:00 UTC  →  2025-12-31 23:59:59 UTC  (dalam ms)
_START_MS = 1735689600000
_END_MS   = 1767225599999

# Batas kuartal (inklusif)
_QUARTERS = [
    ('Q1', pd.Timestamp('2025-01-01'), pd.Timestamp('2025-03-31 23:59:59')),
    ('Q2', pd.Timestamp('2025-04-01'), pd.Timestamp('2025-06-30 23:59:59')),
    ('Q3', pd.Timestamp('2025-07-01'), pd.Timestamp('2025-09-30 23:59:59')),
    ('Q4', pd.Timestamp('2025-10-01'), pd.Timestamp('2025-12-31 23:59:59')),
]

# ── Global state ──────────────────────────────────────────────────────────
_lock          = threading.Lock()
_log           = []
_phase         = 'running'   # 'running' | 'done' | 'error'
_results       = []          # per-coin
_quarter_stats = {}          # Q1..Q4 aggregate
_all_trades    = []          # semua trade (untuk quarter breakdown)


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
    from backtest import (build_h1, find_last_swing_bos, calc_ema,
                          get_internal_gaps, replay_m5, check_bos_or_sweep)
    WARMUP = 2400; H1_WIN = 100; total = len(df)
    scan_end = min(total - 1, WARMUP + 90 * 24 * 12)
    c_bos = c_ema = c_fvg = c_fvg_touch = c_idm = c_bos2 = c_mss = 0
    last_bos_key = None
    i = WARMUP
    while i < scan_end:
        m5_win = df.iloc[max(0, i - H1_WIN * 12): i].reset_index(drop=True)
        df_h1  = build_h1(m5_win)
        if len(df_h1) < 52: i += 12; continue
        sh_h1, sl_h1 = find_last_swing_bos(df_h1)
        if not sh_h1 or not sl_h1: i += 12; continue
        closed_h1 = df_h1.iloc[-2]; curr_h1 = df_h1.iloc[-1]
        is_long  = closed_h1['close'] > sh_h1[-1]['val']
        is_short = closed_h1['close'] < sl_h1[-1]['val']
        if not (is_long or is_short): i += 12; continue
        stype = 'Long' if is_long else 'Short'
        swing_val = sh_h1[-1]['val'] if is_long else sl_h1[-1]['val']
        bos_key = (stype, round(swing_val, 8))
        if bos_key == last_bos_key: i += 12; continue
        last_bos_key = bos_key; c_bos += 1
        ema50 = calc_ema(df_h1['close'], 50).iloc[-1]
        if stype == 'Long'  and curr_h1['close'] < ema50: i += 12; continue
        if stype == 'Short' and curr_h1['close'] > ema50: i += 12; continue
        c_ema += 1
        bos_idx = sl_h1[-1]['idx'] if is_long else sh_h1[-1]['idx']
        gaps = get_internal_gaps(df_h1, stype, bos_idx)
        if not gaps: i += 12; continue
        c_fvg += 1
        scan_fvg_end = min(total - 1, i + 12 * 96)
        seg_h = df.iloc[i:scan_fvg_end]['high'].to_numpy(float)
        seg_l = df.iloc[i:scan_fvg_end]['low'].to_numpy(float)
        seg_c = df.iloc[i:scan_fvg_end]['close'].to_numpy(float)
        seg_len = len(seg_h); found_fvg_idx = -1; used_fvg = None
        for fvg in gaps:
            ft, fb = float(fvg['top']), float(fvg['bottom']); blk = 0
            while blk < seg_len:
                be = min(blk + 12, seg_len); bc = seg_c[be - 1]
                if stype == 'Long'  and bc < fb: break
                if stype == 'Short' and bc > ft: break
                if stype == 'Long'  and seg_l[blk:be].min() <= ft:
                    found_fvg_idx = i + blk; used_fvg = fvg; break
                if stype == 'Short' and seg_h[blk:be].max() >= fb:
                    found_fvg_idx = i + blk; used_fvg = fvg; break
                blk += 12
            if found_fvg_idx >= 0: break
        if found_fvg_idx < 0: i += 12 * 24; continue
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
        mss_c = df_mss.iloc[hits[0]]
        body = abs(float(mss_c['close']) - float(mss_c['open']))
        rng  = abs(float(mss_c['high'])  - float(mss_c['low']))
        if rng > 0 and body / rng < 0.30: i += 12; continue
        c_mss += 1; i += 12

    _log_msg(f"  [DIAG] BOS:{c_bos}→EMA:{c_ema}→FVG:{c_fvg}"
             f"→touch:{c_fvg_touch}→IDM:{c_idm}→BOS2:{c_bos2}→MSS:{c_mss}")


# ── Helper: quarter breakdown ─────────────────────────────────────────────
def _quarter_of(ts) -> str:
    m = ts.month
    if m <= 3:  return 'Q1'
    if m <= 6:  return 'Q2'
    if m <= 9:  return 'Q3'
    return 'Q4'

def _calc_quarters(all_trades: list) -> dict:
    """Hitung statistik per kuartal dari semua trade (sorted by entry_ts)."""
    by_q = {'Q1': [], 'Q2': [], 'Q3': [], 'Q4': []}
    for t in all_trades:
        by_q[_quarter_of(t['entry_ts'])].append(t)

    stats = {}
    running = INITIAL_BALANCE
    for q in ('Q1', 'Q2', 'Q3', 'Q4'):
        trades = by_q[q]
        q_start = running
        q_pnl   = sum(t['pnl_usd'] for t in trades)
        running += q_pnl
        wins = sum(1 for t in trades if t['outcome'] == 'tp')
        n    = len(trades)
        wr   = wins / n * 100 if n else 0.0
        gw = sum(t['pnl_usd'] for t in trades if t['pnl_usd'] > 0)
        gl = abs(sum(t['pnl_usd'] for t in trades if t['pnl_usd'] < 0))
        pf = gw / gl if gl > 0 else (99.0 if gw > 0 else 0.0)
        stats[q] = {
            'trades': n, 'wins': wins, 'wr': wr,
            'pnl': q_pnl, 'pf': pf,
            'start_bal': q_start, 'end_bal': running,
        }
    return stats


# ── Main runner (background thread) ──────────────────────────────────────
def _run():
    global _phase, _results, _quarter_stats, _all_trades

    _log_msg("=" * 62)
    _log_msg(f"BACKTEST SEMUA COIN BOT LIVE | Full Year 2025 | Modal ${INITIAL_BALANCE:.0f} | Risk 1%")
    _log_msg(f"{len(COINS)} Coins: {', '.join(COINS)}")
    _log_msg("=" * 62)

    all_trades_list = []
    results         = []

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
            trades, final_bal = bt.backtest_coin(symbol, df, INITIAL_BALANCE)
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

        wins   = [t for t in trades if t['outcome'] == 'tp']
        losses = [t for t in trades if t['outcome'] == 'sl']
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

        _log_msg(
            f"  ✅ Trade:{n} | W:{len(wins)} L:{len(losses)} | WR:{wr:.1f}% | "
            f"PnL:${pnl:.2f} | ROI:{roi:.1f}% | MaxDD:{max_dd:.1f}% | PF:{pf:.2f}"
        )

        results.append({
            'symbol': symbol, 'status': 'ok',
            'trades': n, 'win': len(wins), 'loss': len(losses),
            'wr': wr, 'pnl': pnl, 'roi': roi,
            'max_dd': max_dd, 'pf': pf, 'final_bal': final_bal,
            'longs': len([t for t in trades if t['type'] == 'Long']),
            'shorts': len([t for t in trades if t['type'] == 'Short']),
            'p25_atr': p25_atr,
        })
        all_trades_list.extend(trades)

        with _lock:
            _results      = list(results)
            _all_trades   = list(all_trades_list)

    # ── Ringkasan kuartal ────────────────────────────────────────────────
    qs = _calc_quarters(all_trades_list)
    total_pnl  = sum(t['pnl_usd'] for t in all_trades_list)
    total_w    = sum(1 for t in all_trades_list if t['outcome'] == 'tp')
    total_n    = len(all_trades_list)
    wr_all     = total_w / total_n * 100 if total_n else 0

    _log_msg(f"\n{'='*62}")
    _log_msg(f"TOTAL: {total_n} trade | WR:{wr_all:.1f}% | PnL:${total_pnl:.2f} "
             f"| ${INITIAL_BALANCE:.2f} → ${INITIAL_BALANCE+total_pnl:.2f}")
    for q, s in qs.items():
        _log_msg(f"  {q}: {s['trades']} trade | WR:{s['wr']:.0f}% | "
                 f"PnL:${s['pnl']:.2f} | ${s['start_bal']:.2f}→${s['end_bal']:.2f}")
    _log_msg("✅ SELESAI — Buka /readme untuk markdown README.md")

    with _lock:
        _phase         = 'done'
        _quarter_stats = qs
        _all_trades    = list(all_trades_list)


# ── README markdown generator ─────────────────────────────────────────────
def _gen_readme() -> str:
    with _lock:
        results  = list(_results)
        qs       = dict(_quarter_stats)
        phase    = _phase

    if phase == 'running':
        return "# Backtest masih berjalan, coba lagi nanti…\n"

    ok = [r for r in results if r.get('status') == 'ok' and r.get('trades', 0) > 0]
    total_n    = sum(r['trades'] for r in ok)
    total_pnl  = sum(r['pnl'] for r in ok)
    total_w    = sum(r['win'] for r in ok)
    wr_all     = total_w / total_n * 100 if total_n else 0
    gw_all     = sum(r['pnl'] for r in ok if r['pnl'] > 0)
    gl_all     = abs(sum(r['pnl'] for r in ok if r['pnl'] < 0))
    pf_all     = gw_all / gl_all if gl_all > 0 else 99.0
    final_bal  = INITIAL_BALANCE + total_pnl
    roi_all    = total_pnl / INITIAL_BALANCE * 100

    # Per-coin table
    coin_rows = ""
    for r in results:
        sym = r['symbol']
        if r.get('status') != 'ok' or r.get('trades', 0) == 0:
            coin_rows += f"| {sym} | 0 | — | — | — | — | — |\n"
            continue
        sign = '+' if r['pnl'] >= 0 else ''
        coin_rows += (
            f"| {sym} | {r['trades']} | {r['wr']:.0f}% | "
            f"{sign}${r['pnl']:.2f} | {r['max_dd']:.1f}% | "
            f"{r['pf']:.2f} | {r['p25_atr']:.4f} |\n"
        )

    total_sign = '+' if total_pnl >= 0 else ''
    coin_rows += (
        f"| **TOTAL** | **{total_n}** | **{wr_all:.0f}%** | "
        f"**{total_sign}${total_pnl:.2f}** | — | **{pf_all:.2f}** | — |\n"
    )

    # Quarter table
    q_rows = ""
    if qs:
        for q, s in qs.items():
            sign = '+' if s['pnl'] >= 0 else ''
            q_rows += (
                f"| {q} | {s['trades']} | {s['wr']:.0f}% | "
                f"{sign}${s['pnl']:.2f} | "
                f"${s['start_bal']:.2f} → ${s['end_bal']:.2f} |\n"
            )
    else:
        q_rows = "| — | — | — | — | — |\n"

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    return f"""# SMC Bot — Backtest Full Year 2025

**Modal Awal: ${INITIAL_BALANCE:.0f} | Risk: 1%/trade compound | TP: 3R | {len(COINS)} Coin**
**Strategi: BOS H1 → EMA50 → FVG → IDM M5 → BOS/Sweep M5 → MSS → Entry**
**Data: Bybit Perpetual USDT | M5 → H1 | 2025-01-01 ~ 2025-12-31**
_(Generated: {today})_

---

## Hasil Per Coin

| Coin | Trade | WR% | PnL USD | MaxDD | PF | ATR P25 |
|------|------:|----:|--------:|------:|---:|--------:|
{coin_rows}
**${INITIAL_BALANCE:.2f} → ${final_bal:.2f} dalam setahun (+{roi_all:.0f}% ROI)**

---

## Per Kuartal

| Kuartal | Trade | WR% | PnL | Bal Awal → Akhir |
|---------|------:|----:|----:|:----------------:|
{q_rows}
---

## Konfigurasi Backtest

| Parameter | Nilai |
|-----------|-------|
| Modal Awal | ${INITIAL_BALANCE:.0f} |
| Risk per Trade | 1% (compound) |
| TP | 3R |
| Leverage | 10× |
| Fee | 0.055% per sisi (Bybit taker) |
| Timeframe | M5 + H1 |
| ATR Filter | P25 per coin (75% waktu lolos) |
| Min RR | 2.8 |
| Min SL distance | 0.5% |

---

## Coin yang Tidak Dimasukkan

- **ENAUSDT** — bearish 3 dari 4 kuartal 2025, ATR tinggi tapi choppy
- **INJUSDT** — WR 40.7%, PF 1.62 (batch 4 backtest)
- **ICPUSDT** — hanya 9 trade setahun (terlalu sedikit)
- **ARBUSDT** — WR 40%, PF 1.57
- **TONUSDT** — PF 0.82 (losing)
- **ADAUSDT** — 9 trade
- **STORJUSDT** — 5 trade
- **NEARUSDT** — WR 44%
- **SHIB1000USDT** — symbol tidak tersedia di Bybit (SHIB1000USDT)
"""


# ── HTML rendering ────────────────────────────────────────────────────────
_CSS = """
<style>
*{box-sizing:border-box}
body{font-family:'Courier New',monospace;background:#0d1117;color:#c9d1d9;
     padding:24px 32px;max-width:1200px;margin:0 auto}
h1{color:#58a6ff;font-size:20px;margin:0 0 6px}
h2{color:#79c0ff;font-size:14px;margin:22px 0 8px;text-transform:uppercase;letter-spacing:.5px}
p{margin:4px 0;font-size:13px}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:12px}
th{background:#161b22;color:#58a6ff;padding:8px 12px;text-align:left;
   border-bottom:2px solid #30363d;white-space:nowrap}
td{padding:7px 12px;border-bottom:1px solid #21262d;white-space:nowrap}
tr:hover td{background:#161b22}
.g{color:#3fb950}.r{color:#f85149}.y{color:#e3b341}
.log{background:#161b22;border:1px solid #30363d;border-radius:6px;
     padding:14px 16px;max-height:500px;overflow-y:auto;
     white-space:pre-wrap;font-size:11px;line-height:1.6}
.chip{display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:bold}
.chip-run{background:#1c3c5e;color:#58a6ff}
.chip-done{background:#1a3d28;color:#3fb950}
.note{background:#161b22;border-left:3px solid #58a6ff;padding:10px 14px;
      border-radius:0 6px 6px 0;font-size:12px;margin:10px 0 0;line-height:1.6}
a{color:#58a6ff}
</style>
"""

def _render_html() -> bytes:
    with _lock:
        phase  = _phase
        log_cp = list(_log)
        res_cp = list(_results)
        qs     = dict(_quarter_stats)

    refresh = '<meta http-equiv="refresh" content="8">' if phase == 'running' else ''
    chip    = ('<span class="chip chip-run">⏳ Running…</span>' if phase == 'running'
               else '<span class="chip chip-done">✅ Selesai</span>')

    # ── per-coin table ──
    coin_rows = ''
    total_n = total_win = total_loss = 0
    total_pnl = 0.0
    for r in res_cp:
        sym     = r['symbol']
        atr_str = f"{r['p25_atr']:.4f}" if 'p25_atr' in r else '—'
        if r.get('status') in ('no_data', 'error'):
            label = '⚠ no data' if r['status'] == 'no_data' else '❌ error'
            coin_rows += f'<tr><td><b>{sym}</b></td><td class="r" colspan="7">{label}</td></tr>\n'
        elif r.get('trades', 0) == 0:
            coin_rows += (f'<tr><td><b>{sym}</b></td><td class="y">0</td>'
                          + '<td class="y">—</td>' * 5
                          + f'<td>{atr_str}</td></tr>\n')
        else:
            wr_c  = 'g' if r['wr']     >= 55 else ('y' if r['wr'] >= 45 else 'r')
            pnl_c = 'g' if r['pnl']    >= 0  else 'r'
            dd_c  = 'r' if r['max_dd'] > 20  else ('y' if r['max_dd'] > 10 else 'g')
            pf_c  = 'g' if r['pf']     >= 3  else ('y' if r['pf'] >= 2 else 'r')
            sign  = '+' if r['pnl'] >= 0 else ''
            total_n += r['trades']; total_win += r['win']; total_loss += r['loss']
            total_pnl += r['pnl']
            coin_rows += (
                f'<tr>'
                f'<td><b>{sym}</b></td>'
                f'<td>{r["trades"]}</td>'
                f'<td class="{wr_c}">{r["wr"]:.1f}%</td>'
                f'<td class="{pnl_c}">{sign}${r["pnl"]:.2f}</td>'
                f'<td class="{dd_c}">{r["max_dd"]:.1f}%</td>'
                f'<td class="{pf_c}">{r["pf"]:.2f}</td>'
                f'<td>${r["final_bal"]:.2f}</td>'
                f'<td class="g">{atr_str}</td>'
                f'</tr>\n'
            )

    if total_n:
        wr_tot = total_win / total_n * 100
        sign   = '+' if total_pnl >= 0 else ''
        coin_rows += (
            f'<tr style="border-top:2px solid #30363d;font-weight:bold">'
            f'<td>TOTAL ({len(res_cp)} coin)</td>'
            f'<td>{total_n}</td>'
            f'<td class="{"g" if wr_tot>=55 else "y"}">{wr_tot:.1f}%</td>'
            f'<td class="{"g" if total_pnl>=0 else "r"}">{sign}${total_pnl:.2f}</td>'
            f'<td>—</td><td>—</td>'
            f'<td>${INITIAL_BALANCE+total_pnl:.2f}</td>'
            f'<td>—</td></tr>\n'
        )

    coin_table = f'''
        <table>
          <tr>
            <th>Coin</th><th>Trade</th><th>WR%</th><th>PnL USD</th>
            <th>MaxDD%</th><th>PF</th><th>Final Bal</th><th>ATR P25</th>
          </tr>
          {coin_rows or '<tr><td colspan="8" class="y">Menunggu hasil pertama…</td></tr>'}
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
        done_note = '<p class="g">✅ Backtest selesai! Buka <a href="/readme">/readme</a> untuk export README.md</p>'

    n_done = len(res_cp)
    n_total = len(COINS)

    return f'''<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <title>Backtest All Coins — SMC Bot</title>
  {_CSS}
  {refresh}
</head>
<body>
  <h1>🤖 Backtest SMC Bot — All Coins (Full Year 2025)</h1>
  <p>
    <b>{n_done}/{n_total} coin selesai</b> &nbsp;|&nbsp;
    Modal: <b>${INITIAL_BALANCE:.0f}</b> &nbsp;|&nbsp;
    Period: <b>2025-01-01 → 2025-12-31</b> &nbsp;|&nbsp;
    Status: {chip}
  </p>
  {done_note}

  <h2>Hasil Per Coin</h2>
  {coin_table}

  {'<h2>Per Kuartal (Agregat Semua Coin)</h2>' + q_table if q_table else ''}

  <div class="note">
    💡 <b>ATR P25</b> = threshold filter yang digunakan. &nbsp;
    <b>Final Bal</b> = ${INITIAL_BALANCE:.0f} + PnL coin tersebut (compound per-coin). &nbsp;
    Baris <b>TOTAL</b> = ${INITIAL_BALANCE:.0f} + sum semua PnL.
    <br>Per Kuartal = PnL semua coin yang trade di kuartal tersebut (balance kumulatif).
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
