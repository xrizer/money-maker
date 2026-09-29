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
