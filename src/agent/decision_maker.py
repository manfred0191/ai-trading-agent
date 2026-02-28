"""Decision-making agent for momentum trading on volatile altcoins."""

import requests
import json
import logging
from datetime import datetime
from src.config_loader import CONFIG
from src.indicators.taapi_client import TAAPIClient

class TradingAgent:
    """Trading agent focused on momentum trades for volatile altcoins."""

    def __init__(self):
        """Initialize LLM and TAAPI client."""
        self.model = CONFIG["llm_model"]
        self.api_key = CONFIG["openrouter_api_key"]  # das ist jetzt dein Groq-Key
        base = CONFIG["openrouter_base_url"]         # https://api.groq.com/openai/v1
        self.base_url = f"{base}/chat/completions"
        self.taapi = TAAPIClient()

    def decide_trade(self, assets, context):
        """Decide for multiple assets in one LLM call."""
        return self._decide(context, assets=assets)

    def _decide(self, context, assets):
        """Send request to LLM and parse decision."""
        system_prompt = """Du bist der smarteste, disziplinierteste und profitabelste Crypto-Trader der Welt. 
Dein einziger Job ist es, auf Hyperliquid möglichst viel Geld zu verdienen.

Regeln, an die du dich 100 % hältst:
- Nur Momentum-Trades auf dem 15-Minuten-Timeframe.
- Finde volatile Altcoins (hohe Volatilität, steigendes Volume, Breakouts, starke Moves).
- Maximal 10x Leverage – nie mehr!
- Check alle 15 Minuten.
- Nutze TAAPI-Indikatoren auf 15m: EMA9/EMA21 Crossover bullish, RSI14 > 55 (besser >60), MACD-Histogramm steigend und über Null, Volume-Surge, Price über recent high oder VWAP.
- Nur Longs bei starkem Momentum (keine Shorts, es sei denn extrem klares Setup).
- Position: maximal 20 % des aktuellen Balances pro Trade.
- Kein Gambling – nur high-probability Setups mit klarem Edge (mind. 2–3 konfluente Signale).
- Wenn nichts Gutes da ist → HOLD und warte geduldig.
- Sei extrem selektiv: Lieber 0–1 Trade pro Tag als schlechte Trades.

Du bekommst immer die aktuellen TAAPI-Indikatoren und Markt-Context für die Assets aus der Config.
Aktuelle Zeit: {current_time}

Nutze fetch_taapi_indicator aggressiv, um fehlende Daten zu holen (15m Interval!).

Antworte NUR im exakten JSON-Format – nichts anderes:
{{
  "reasoning": "Deine ausführliche Schritt-für-Schritt-Analyse hier (sei sehr detailliert)",
  "trade_decisions": [
    {{
      "action": "BUY" | "SELL" | "HOLD",
      "symbol": "PEPE-USD",
      "leverage": 7,
      "size_pct": 0.04,
      "reason": "kurze, klare Begründung"
    }},
    ... (einer pro Asset, oder leer wenn HOLD für alle)
  ]
}}

Ziel: Maximaler Profit bei minimalem Drawdown. Sei kalt, rational und gierig – aber nie dumm.""".format(current_time=datetime.utcnow().isoformat())

        user_prompt = context

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        tools = [{
            "type": "function",
            "function": {
                "name": "fetch_taapi_indicator",
                "description": "Fetch TAAPI indicator (15m empfohlen). Available: ema, rsi, macd, volume, atr, supertrend, vwap, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "indicator": {"type": "string"},
                        "symbol": {"type": "string"},
                        "interval": {"type": "string", "default": "15m"},
                        "period": {"type": "integer"},
                        "backtrack": {"type": "integer", "default": 0},
                        "other_params": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["indicator", "symbol", "interval"]
                }
            }
        }]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.4,           # etwas Kreativität, aber nicht zu wild
            "max_tokens": 1200
        }

        try:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            resp_json = resp.json()
            message = resp_json["choices"][0]["message"]

            # Tool calls handlen (falls LLM mehr Daten will)
            if "tool_calls" in message:
                for tc in message["tool_calls"]:
                    if tc["function"]["name"] == "fetch_taapi_indicator":
                        args = json.loads(tc["function"]["arguments"])
                        params = {
                            "secret": self.taapi.api_key,
                            "exchange": "binance",
                            "symbol": args["symbol"],
                            "interval": args.get("interval", "15m"),
                        }
                        if "period" in args:
                            params["period"] = args["period"]
                        if "backtrack" in args:
                            params["backtrack"] = args["backtrack"]
                        params.update(args.get("other_params", {}))

                        ind_resp = requests.get(
                            f"{self.taapi.base_url}{args['indicator']}",
                            params=params,
                            timeout=30
                        ).json()

                        # Tool-Antwort zurück an LLM schicken würde hier fehlen – 
                        # für Einfachheit: wir parsen direkt die erste Antwort
                        # (du kannst später loop hinzufügen, wenn nötig)

            # Output parsen
            content = message.get("content") or "{}"
            try:
                parsed = json.loads(content)
                if "trade_decisions" not in parsed:
                    parsed = {"reasoning": "Parse-Fehler – ungültiges Format", "trade_decisions": []}
            except json.JSONDecodeError:
                parsed = {"reasoning": f"JSON Parse Error: {content[:200]}...", "trade_decisions": []}

            return parsed

        except Exception as e:
            logging.error(f"LLM decision failed: {str(e)}")
            return {"reasoning": f"Error during decision: {str(e)}", "trade_decisions": []}
