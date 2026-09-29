# money-maker

Claude-driven perpetuals trader for Hyperliquid.

Each cycle: market snapshot -> Claude (forced tool call `submit_decision`) -> deterministic risk engine -> order + mandatory stop-loss/take-profit.

**Claude proposes; `risk.py` disposes.** Position size is computed in code from the stop distance (risk-per-trade), capped by per-position and total exposure limits, with a daily-loss kill switch. Claude cannot change sizing or limits.

## Setup
    pip install -r requirements.txt
    cp .env.example .env   # fill in keys
    python -m moneymaker.main

- Use a Hyperliquid **API/agent wallet** key (can trade, cannot withdraw).
- Defaults: `HL_NETWORK=testnet`, `LIVE=false` (dry run: decisions logged, no orders).
- Progression: dry run -> testnet live -> tiny mainnet size. Do not skip steps.
- Tests: `pytest`

## Not financial advice
LLM decisions are not an edge by themselves. Backtest/paper trade before risking capital.

## Backtest
    python -m moneymaker.backtest --days 90 --step-hours 4 --brain rule     # free baseline
    python -m moneymaker.backtest --days 30 --step-hours 4 --brain claude   # costs API calls, cached in data/

Uses real Hyperliquid 1h candles (max ~205 days), the same risk engine, taker fees 0.045% + 0.02% slippage.
No funding/OI history and no funding payments are simulated. Always compare against the buy&hold line.

## Default strategy (`STRATEGY=rule`)
Found by backtest with a train/hold-out split (200 days, BTC/ETH/SOL): trade the coin with the strongest 12h move
when it agrees with its 24h-average trend; long or short; 4% stop, 8% take-profit; check every 4h in backtests.
200-day result: +24.6%, max drawdown 12.8%, profit factor 1.39, 90 trades. Positive in 4 of 5 separate 40-day windows
(worst window -7.9%). This is past data, ~90 trades, one market regime mix: promising, not proof.
Daily profit target is off by default because it hurt results in testing.

## Dry run without funds
    HL_NETWORK=mainnet LIVE=false PAPER_EQUITY=300 python -m moneymaker.main   # add ONCE=true for a single cycle

## Dashboard
While the bot runs, open http://127.0.0.1:8080/dashboard.html (set `UI_PORT=0` to disable).
Shows balance (USD + IDR), today/month PnL against the monthly loss stop, balance history, open positions,
the last decision, risk limits and an activity log. The bot writes `ui/status.json` every cycle; the page polls it.
The server binds to 127.0.0.1 only. To view it from your phone, use an SSH tunnel; do not expose it to the internet.

## Learning from past trades (review loop)
The bot never retrains itself. Instead it keeps a journal and you review it weekly:

1. Live trades are recorded to `data/journal.jsonl` (real fills, fees, market features at entry, stop/take-profit/other exit).
2. `python -m moneymaker.review` (needs 20+ closed trades and `ANTHROPIC_API_KEY`) computes stats, asks Claude for a skeptical
   analysis and up to 3 proposed rule changes (only whitelisted strategy parameters, never risk limits), then backtests each
   proposal on the candles BEFORE the journal period. Proposals that don't beat the baseline out-of-sample are marked REJECT.
3. Reports go to `data/reviews/`. Nothing is applied automatically; you edit the defaults yourself, backtest, then testnet.

Offline test: `python -m moneymaker.backtest --days 200 --last-days 60 --journal-out data/demo_journal.jsonl`, then
`python -m moneymaker.review --journal data/demo_journal.jsonl --proposals my_proposals.json` (skips the Claude call).

## Quick start (Mac / Linux, Python 3.9+)
    git pull && pip3 install -r requirements.txt
    python3 -m moneymaker.backtest --days 200 --brain rule                 # no keys needed
    PAPER_EQUITY=300 HL_NETWORK=mainnet python3 -m moneymaker.main         # dry run, no keys needed (Ctrl+C to stop)
Secrets go ONLY in `.env` (git-ignored), never in `.env.example` (tracked by git).

## Start / stop from the dashboard
The dashboard has **Pause new trades / Resume trading** and **Stop & close all positions** buttons.
- Pause: no new trades; existing positions keep their exchange stop-loss/take-profit. Resume: the bot checks the market immediately.
- Stop & close all: cancels all resting orders, closes every position at market, and leaves trading paused.
- The paused state is saved (`data/control.json`) and survives restarts. `START_PAUSED=true` starts paused on first run.
- The bot process must be running; the page cannot launch it. Ctrl+C in the terminal stops the process itself.
- The API only accepts requests from this computer, with a per-run secret token, a local Host header and same-origin requests.

## Surviving volatility (tested, 200 days)
Adopted: **drawdown de-risking** (`DD_DERISK_PCT=0.08`). Position size shrinks as equity falls below its peak
(half size at -4%, 25% floor), and grows back as it recovers.
| | return | max drawdown | worst 40-day window | profit factor |
|---|---|---|---|---|
| before | +24.6% | 12.8% | -7.9% | 1.39 |
| with de-risking | +22.4% | 7.5% | -1.6% | 1.55 |
Stress test (instant ±15%/±30% gap on all coins at 18 dates): worst drawdown 31.7% -> 21.5%, worst end result -11.5% -> -5.8%.

Tested and rejected (made things worse out of sample): volatility-scaled stops, skipping high-volatility periods,
pausing after 3 losses in a row, capping to 1-2 positions.
