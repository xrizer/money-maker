# Runbook: when something goes wrong

Read this BEFORE going live. Print it or keep it open in a tab.

## Panic order (stop at the first step that solves it)
1. **Pause**: dashboard "Pause new trades" (or Ctrl+C in the terminal). Open positions keep their exchange stop-loss/take-profit.
2. **Exit**: dashboard "Stop & close all positions".
3. **Dashboard/bot unreachable**: Hyperliquid website -> Portfolio -> close every position, then cancel all open orders.
4. **Anything suspicious or a key leaked**: Hyperliquid -> More -> API -> remove the API wallet. The bot loses access at once.
5. **Then** investigate. Do not restart until you know the cause. Keep `journalctl -u moneymaker` / terminal output.

## Loss limits (pilot of 100 USDC)
| Scenario | Worst realistic loss | Why |
|---|---|---|
| Losing trade | ~1% of balance | stop sized to 1% risk |
| Gap through stop | ~2-3% | position ~25% of balance |
| Stop-loss rejected by exchange | ~0 | bot closes the position immediately |
| Losing month | ~8% | monthly kill switch (checked hourly) |
| Position liquidated | its margin (~8%) | isolated margin |
| Bot/PC/VPS offline | nothing extra | stops/take-profits live on the exchange |
| Exchange or internet down | cannot be limited | you cannot trade until it is back |
| API key leaked | up to whole balance | key cannot withdraw but can place trades: revoke it |
| Platform hacked/insolvent | everything deposited | only deposit what you can lose |

## Known unverified areas (until proven on testnet)
Entry, stop-loss/take-profit order formats, cancel-all and close-all have been tested with simulated replies only, never
on a real exchange. On the first live trade, confirm on the Hyperliquid site: position exists, stop-loss AND take-profit
orders are listed, "Stop & close all" really closes and cancels.

## After an incident
- Write down what happened and the times. Send the logs to whoever maintains the bot.
- Rotate the API wallet (remove, generate a new one, authorize, update `.env`) if there is any doubt about the key.
- Return to testnet or a tiny size before scaling up again.
