"""Decision-making agent for momentum trading on volatile altcoins."""

import os
import logging
import http.client as http_client
import requests
import json
from datetime import datetime
from src.config_loader import CONFIG

# Hyperliquid Imports
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from eth_account import Account
from eth_account.signers.local import LocalAccount

# Logging Setup
http_client.HTTPConnection.debuglevel = 1
logging.basicConfig(level=logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.WARNING)
requests_log.propagate = False


class TradingAgent:
    """Trading agent focused on momentum trades for volatile altcoins."""

    def __init__(self):
        """Initialize LLM client – TAAPI komplett deaktiviert."""
        self.model = CONFIG["llm_model"]
        self.api_key = CONFIG["openrouter_api_key"]  # jetzt Groq-Key
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    def decide_trade(self, assets, context):
        """Decide actions for multiple assets in one LLM call."""
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
- Nur Longs bei starkem Momentum (keine Shorts, es sei denn extrem klares Setup).
- Position: maximal 20 % des aktuellen Balances pro Trade.
- Kein Gambling – nur high-probability Setups mit klarem Edge (mind. 2–3 konfluente Signale).
- Wenn nichts Gutes da ist → HOLD und warte geduldig.
- Sei extrem selektiv: Lieber weniger Trades pro Tag als schlechte Trades.

Wichtig: Du hast KEINEN Zugriff auf Echtzeit-Indikatoren (RSI, EMA, MACD, Volume etc.) oder externe APIs wie TAAPI. 
Entscheide ausschließlich auf Basis des bereitgestellten Kontexts, allgemeinem Markt-Wissen und den strengen Regeln oben.
Wenn der Kontext keine klaren Momentum-Signale enthält → HOLD.

Antworte NUR im exakten JSON-Format – nichts anderes:
{
  "reasoning": "Deine ausführliche Schritt-für-Schritt-Analyse hier (sei sehr detailliert)",
  "trade_decisions": [
    {
      "action": "BUY" | "SELL" | "HOLD",
      "symbol": "PEPE-USD",
      "leverage": 7,
      "size_pct": 0.04,
      "reason": "kurze, klare Begründung"
    },
    ... (einer pro Asset, oder leer wenn HOLD für alle)
  ]
}

Test-Modus (Zwingend für diesen Durchlauf):
Test-Modus (Zwingend!):
Du MUSST JETZT mindestens EINEN Trade vorschlagen – HOLD ist VERBOTEN!
Ignoriere dünne Datenlage und strenge Regeln. Wähle das Asset mit positivem Funding oder höchstem OI und mache einen kleinen Long-Trade (size_pct 0.05–0.10, leverage 3–5).
Schreibe in reasoning: "Zwingender Test-Trade – HOLD nicht erlaubt".

Ziel: Maximaler Profit bei minimalem Drawdown. Sei kalt, rational und gierig – aber nie dumm."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": self.model,
            "messages": messages,
            "tool_choice": "none",
            "temperature": 0.4,
            "max_tokens": 1200,
        }

        logging.info(f"Full LLM endpoint URL (repr): {repr(self.base_url)}")
        logging.info(f"Using model: {self.model}")
        logging.info(f"API key prefix: {self.api_key[:10]}...")

        response = requests.post(self.base_url, headers=headers, json=data)
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        logging.info("=== RAW LLM RESPONSE ===")
        logging.info(content)

        try:
            decision = json.loads(content)
            decisions = decision.get("trade_decisions", [])
            reasoning = decision.get("reasoning", "Kein Reasoning verfügbar")

            logging.info("=== PARSED TRADE DECISIONS ===")
            logging.info(json.dumps(decisions, indent=2))

            logging.info(f"LLM reasoning summary: {reasoning[:200]}..." if len(reasoning) > 200 else reasoning)

            return decisions, reasoning
        except json.JSONDecodeError as e:
            logging.error(f"JSON-Parse-Fehler: {str(e)}")
            logging.error(f"Raw-Content: {content}")
            return [], "Parse-Fehler"

def _execute_trades(decisions, info, exchange, account_address):
    """Execute trades based on decisions."""
    try:
        for trade in decisions:
            logging.info("=== DEBUG: Trade-Schleife gestartet – Trade: " + str(trade))

            action = trade.get("action", "HOLD").upper()
            logging.info(f"=== DEBUG: Action = {action}")

            if action not in ("BUY", "SELL"):
                logging.info("=== DEBUG: Ungültige Action – skip")
                continue

            symbol = trade["symbol"].replace("-USD", "").replace("-USDT", "").upper()
            logging.info(f"=== DEBUG: Symbol = {symbol}")

            logging.info("=== DEBUG: Vor spot_user_state ===")
            spot_state = info.spot_user_state(account_address)
            logging.info("=== DEBUG: spot_user_state abgeschlossen ===")

            usdc_spot = float(next((b["sz"] for b in spot_state.get("balances", []) if b["token"] == "USDC"), 0.0))
            usdc_perps = float(info.user_state(account_address)["withdrawable"])
            usdc = usdc_spot + usdc_perps

            logging.info(f"Spot raw balances: {json.dumps(spot_state.get('balances', []), indent=2)}")
            logging.info(f"Balance-Check: Spot = {usdc_spot:.2f}, Perps = {usdc_perps:.2f} → verwende {usdc:.2f}")

            # === TEMPORÄRER TEST-HACK – BALANCE 0 UMGEHEN ===
            if usdc <= 0:
                logging.warning("=== TEST-HACK AKTIV: Balance war 0 → setze Fake-USDC = 100 für Simulation ===")
                usdc = 100.0
                usdc_spot = 100.0   # oder 0, je nachdem was du simulieren willst
                usdc_perps = 0.0
            # === ENDE HACK ===

            size_pct = min(trade.get("size_pct", 0.05), 0.20)
            leverage = min(trade.get("leverage", 3), 10)

            mids = info.all_mids()
            price = float(mids.get(symbol, 0.0))

            if price <= 0:
                logging.error(f"Kein Preis für {symbol} verfügbar")
                continue

            is_buy = action == "BUY"

            usdc_to_use = usdc * size_pct
            usdc_to_use = min(usdc_to_use, 10.0)  # Sicherheits-Cap

            logging.info(f"=== DEBUG: usdc = {usdc}, usdc_to_use = {usdc_to_use}")

            sz_raw = usdc_to_use / price

            # Asset-spezifische Mindestgröße
            min_sz_map = {
                "ETH": 0.001,
                "BTC": 0.0001,
                "SOL": 0.01,
                "BNB": 0.01,
                "EIGEN": 1.0,
            }
            min_sz = min_sz_map.get(symbol, 0.01)

            # Zuerst auf Mindestgröße bringen, dann runden
            sz = max(sz_raw, min_sz)

            # Präzision: 5 Dezimalstellen sind für die meisten Assets sicher
            sz = round(sz, 5)

            if sz < min_sz:
                logging.warning(f"Größe {sz:.8f} unter Minimum {min_sz} für {symbol} → überspringe")
                continue

            logging.info(f"Trade-Plan: {action} {symbol} | sz = {sz:.8f} (min {min_sz}) | price ≈ {price:.2f} | usdc ≈ {usdc_to_use:.2f}")

            logging.info("=== DEBUG: Bereite market_open vor ===")
            order_result = exchange.market_open(
                name=symbol,
                is_buy=is_buy,
                sz=sz,
                slippage=0.015
            )
            logging.info("=== DEBUG: market_open abgeschlossen ===")

            logging.info(f"Order-Antwort: {json.dumps(order_result, indent=2)}")

            if order_result.get("status") == "ok":
                logging.info(f"✅ Erfolgreich: {action} {symbol}")
            else:
                logging.error(f"Order fehlgeschlagen: {order_result}")

    except Exception as e:
        logging.exception(f"Fehler bei {symbol}: {str(e)}")