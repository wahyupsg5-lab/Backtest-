# SMC Trading Bot..

Automated trading bot using **Smart Money Concepts (SMC)** on Bybit USDT Perpetual Futures.

---

## Strategy — fvg_strong

Entry is triggered when price touches the OCL (Optimal Close Level) of a high-volume Fair Value Gap, confirmed by a Break of Structure on the H1 timeframe.

```
H1 BOS  →  FVG (C3 vol > 20-bar avg)  →  M5 OCL touch  →  Market entry
```

| Parameter | Value |
|-----------|-------|
| Stop Loss | 6.2 × FVG gap size |
| Trailing Stop | 2.0 × dist, active from entry |
| Break Even | Triggered at entry + 2 × dist |
| Min Touch Volume | ≥ 0.8× 20-bar M5 average |
| Max FVG Size | ≤ 0.60% of price |
| Risk per trade | 1% of balance (compounding) |
| Max leverage | 10× |

---

## Backtest Results — Full Year 2025

> 23 coins · $10 starting capital · 1% risk compounding · Jan 1 – Dec 31 2025

### Summary

| Metric | Value |
|--------|-------|
| Total Trades | 1,999 |
| Win Rate | 36.9% |
| Starting Balance | $10.00 |
| Final Balance | **$1,248.51** |
| Net Profit | +$1,238.51 |
| ROI | **+12,385%** |

### Quarterly Breakdown

| Quarter | Trades | WR | P&L | Balance |
|---------|-------:|---:|----:|--------:|
| Q1 2025 | 468 | 36% | +$12.66 | $10.00 → $22.66 |
| Q2 2025 | 557 | 37% | +$132.08 | $22.66 → $154.73 |
| Q3 2025 | 542 | 37% | +$209.31 | $154.73 → $364.05 |
| Q4 2025 | 432 | 38% | +$884.47 | $364.05 → $1,248.51 |

---

## Active Coins (23)

Sorted by compound contribution. All coins shown passed the positive-compound filter across the full year.

| # | Coin | Trades | WR | Compound P&L | MaxDD | PF | Avg R:R | ATR P25 |
|---|------|-------:|---:|-------------:|------:|---:|--------:|--------:|
| 1 | BELUSDT | 105 | 40.0% | +$166.81 | 13.9% | 1.28 | 1.83 | 0.0024 |
| 2 | JUPUSDT | 86 | 38.4% | +$160.52 | 11.1% | 1.56 | 2.33 | 0.0030 |
| 3 | DOTUSDT | 87 | 41.4% | +$126.16 | 12.8% | 1.60 | 2.12 | 0.0023 |
| 4 | SEIUSDT | 69 | 34.8% | +$88.08 | 6.7% | 1.62 | 2.91 | 0.0028 |
| 5 | ENAUSDT | 99 | 40.4% | +$87.21 | 7.6% | 1.50 | 2.00 | 0.0039 |
| 6 | SHIB1000USDT | 86 | 32.6% | +$71.99 | 16.5% | 1.02 | 2.02 | 0.0020 |
| 7 | 1000PEPEUSDT | 71 | 45.1% | +$64.95 | 4.7% | 2.06 | 2.50 | 0.0031 |
| 8 | ARBUSDT | 85 | 32.9% | +$64.06 | 7.3% | 1.32 | 2.59 | 0.0028 |
| 9 | OPUSDT | 105 | 39.0% | +$59.04 | 11.1% | 1.21 | 1.92 | 0.0029 |
| 10 | 1000BONKUSDT | 100 | 40.0% | +$54.35 | 8.7% | 1.59 | 2.29 | 0.0035 |
| 11 | RUNEUSDT | 93 | 38.7% | +$45.83 | 12.6% | 1.18 | 1.75 | 0.0022 |
| 12 | STXUSDT | 64 | 34.4% | +$42.03 | 10.1% | 1.20 | 2.26 | 0.0025 |
| 13 | ATOMUSDT | 94 | 36.2% | +$37.30 | 15.7% | 1.05 | 1.89 | 0.0021 |
| 14 | 1000FLOKIUSDT | 94 | 35.1% | +$34.33 | 13.0% | 1.02 | 1.88 | 0.0030 |
| 15 | ONDOUSDT | 116 | 32.8% | +$29.68 | 16.2% | 1.05 | 2.20 | 0.0027 |
| 16 | XVGUSDT | 78 | 44.9% | +$28.20 | 8.5% | 1.36 | 1.74 | 0.0030 |
| 17 | LDOUSDT | 88 | 36.4% | +$23.84 | 9.4% | 1.17 | 2.08 | 0.0031 |
| 18 | EIGENUSDT | 76 | 36.8% | +$17.93 | 10.7% | 1.21 | 2.12 | 0.0037 |
| 19 | ALGOUSDT | 93 | 35.5% | +$13.61 | 13.3% | 1.12 | 2.11 | 0.0024 |
| 20 | PNUTUSDT | 54 | 29.6% | +$9.19 | 8.0% | 1.28 | 2.71 | 0.0036 |
| 21 | BERAUSDT | 83 | 32.5% | +$8.99 | 14.7% | 1.11 | 2.44 | 0.0032 |
| 22 | VIRTUALUSDT | 78 | 29.5% | +$5.55 | 10.7% | 1.10 | 2.47 | 0.0040 |
| 23 | APEUSDT | 95 | 38.9% | −$1.10 | 13.8% | 1.24 | 2.03 | 0.0024 |

> **Compound P&L** = each coin's contribution to a single shared balance, with 1% risk per trade drawn from the live balance at trade time — identical to how the live bot operates.

---

## Setup & Deployment

### Environment Variables (Railway)

| Variable | Value |
|----------|-------|
| `API_KEY` | Bybit API key |
| `API_SECRET` | Bybit API secret |
| `TESTNET` | `false` |
| `PORT` | `8080` (set automatically by Railway) |

**Start command:** `python bott_v4.py`

### Running Backtest

```bash
python backtest_web.py
# Open the Railway domain to monitor progress in real time
# /readme  → export results as Markdown
# /logs    → view raw logs
```

---

## Repository Structure

| File | Description |
|------|-------------|
| `bott_v4.py` | Live trading bot — deployed on Railway |
| `backtest.py` | Backtest engine — logic mirrors the live bot exactly |
| `backtest_web.py` | Web-served backtest using live Bybit API data |
| `CLAUDE.md` | Development notes for Claude Code |
