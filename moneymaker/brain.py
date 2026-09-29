"""Claude as the quant decision-maker, via forced tool use for structured output."""
import json

import anthropic

from .risk import Decision

SYSTEM = """You are a disciplined quantitative crypto perpetuals trader on Hyperliquid.
You receive a market snapshot (48 hourly OHLCV candles, funding, open interest, your positions).
Rules:
- Capital preservation first. Default to "hold" unless there is a clear, statistically
  reasonable edge (trend + momentum agreement, funding extremes, volatility regime, etc.).
- Every open_long/open_short MUST include stop_loss_pct and take_profit_pct (fractions, 0.02 = 2%),
  with take_profit at least 1.5x the stop distance.
- Use "close" to exit a position whose thesis is invalidated.
- Give calibrated confidence in [0,1]. Position sizing is handled by a separate risk engine;
  your proposals may be rejected or scaled down. Never try to argue around the limits.
- Decide ONE action per call: the single best opportunity, or hold."""

TOOL = {
    "name": "submit_decision",
    "description": "Submit the trading decision for this cycle.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["open_long", "open_short", "close", "hold"]},
            "coin": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "stop_loss_pct": {"type": "number"},
            "take_profit_pct": {"type": "number"},
            "rationale": {"type": "string", "description": "Brief reasoning, max ~80 words"},
        },
        "required": ["action", "coin", "confidence", "rationale"],
    },
}


class Brain:
    def __init__(self, model: str):
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.model = model

    def decide(self, snap: dict) -> Decision:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM,
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "submit_decision"},
            messages=[{"role": "user", "content": "Snapshot:\n" + json.dumps(snap)}],
        )
        block = next(b for b in resp.content if b.type == "tool_use")
        i = block.input
        return Decision(
            action=i["action"], coin=i["coin"], confidence=float(i["confidence"]),
            stop_loss_pct=float(i.get("stop_loss_pct", 0)),
            take_profit_pct=float(i.get("take_profit_pct", 0)),
            rationale=i.get("rationale", ""),
        )
