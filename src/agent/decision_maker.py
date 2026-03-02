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
- Nur Longs bei starkem Momentum (keine Shorts, es sei denn extrem klares Setup).
- Position: maximal 20 % des aktuellen Balances pro Trade.
- Kein Gambling – nur high-probability Setups mit klarem Edge (mind. 2–3 konfluente Signale).
- Wenn nichts Gutes da ist → HOLD und warte geduldig.
- Sei extrem selektiv: Lieber weniger Trades pro Tag als schlechte Trades.

Wichtig: Du hast KEINEN Zugriff auf Echtzeit-Indikatoren (RSI, EMA, MACD, Volume etc.) oder externe APIs wie TAAPI. 
Entscheide ausschließlich auf Basis des bereitgestellten Kontexts, allgemeinem Markt-Wissen und den strengen Regeln oben.
Wenn der Kontext keine klaren Momentum-Signale enthält → HOLD.

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

Test-Modus (Zwingend für diesen Durchlauf):
Test-Modus (Zwingend!):
Du MUSST JETZT mindestens EINEN Trade vorschlagen – HOLD ist VERBOTEN!
Ignoriere dünne Datenlage und strenge Regeln. Wähle das Asset mit positivem Funding oder höchstem OI und mache einen kleinen Long-Trade (size_pct 0.05–0.10, leverage 3–5).
Schreibe in reasoning: "Zwingender Test-Trade – HOLD nicht erlaubt".

Ziel: Maximaler Profit bei minimalem Drawdown. Sei kalt, rational und gierig – aber nie dumm.""".format(current_time=datetime.utcnow().isoformat())

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "tool_choice": "none",
            "temperature": 0.4,
            "max_tokens": 1200
        }

        try:
            logging.info(f"Full LLM endpoint URL (repr): {repr(self.base_url)}")
            logging.info(f"Using model: {self.model}")
            logging.info(f"API key prefix: {self.api_key[:10]}...")

            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

            parsed = json.loads(content)
            logging.info("=== RAW LLM RESPONSE ===")
            logging.info(content)
            logging.info("=== PARSED TRADE DECISIONS ===")
            logging.info(json.dumps(parsed.get("trade_decisions", []), indent=2))
            if "trade_decisions" not in parsed:
                parsed = {"reasoning": "Parse-Fehler", "trade_decisions": []}
            return parsed

        except Exception as e:
            logging.error(f"LLM decision failed: {str(e)}")
            return {"reasoning": f"Error: {str(e)}", "trade_decisions": []}

    def _execute_trades(self, decision: dict):
        decisions = decision.get("trade_decisions", [])
        if not decisions:
            logging.info("Keine Trades vorgeschlagen → nichts zu tun")
            return

        # Sicherheitsbremse
        if os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes"):
            logging.warning("DRY_RUN aktiv → KEINE echten Orders!")
            for trade in decisions:
                logging.info(f"[DRY] Würde ausführen: {trade}")
            return

        hl_env = os.getenv("HYPERLIQUID_ENVIRONMENT", "mainnet")
        base_url = constants.TESTNET_API_URL if hl_env == "testnet" else constants.MAINNET_API_URL

        private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
        account_address = os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS")

        if not private_key:
            logging.error("HYPERLIQUID_PRIVATE_KEY fehlt")
            return

        if not private_key.startswith("0x"):
            private_key = "0x" + private_key

        try:
            wallet = Account.from_key(private_key)
        except ValueError as e:
            logging.error(f"Ungültiger Private Key: {e}")
            return

        if not account_address:
            account_address = wallet.address

        logging.info(f"Wallet-Adresse: {wallet.address}")
        logging.info(f"Verwendete Account-Adresse: {account_address}")

        try:
            exchange = Exchange(wallet, base_url=base_url, account_address=account_address)
            logging.info("=== DEBUG: Exchange erfolgreich initialisiert ===")
            logging.info(f"Base-URL: {base_url}")
            logging.info(f"Account-Adresse: {account_address}")
            logging.info(f"Hyperliquid Exchange initialisiert ({hl_env})")
        except Exception as e:
            logging.error(f"Exchange-Initialisierung fehlgeschlagen: {e}")
            return

        for trade in decisions:
            action = trade.get("action", "HOLD").upper()
            if action not in ("BUY", "SELL"):
                continue

            symbol = trade["symbol"].replace("-USD", "").replace("-USDT", "").upper()
            is_buy = action == "BUY"
            size_pct = float(trade.get("size_pct", 0.05))
            leverage = int(trade.get("leverage", 5))

            try:
                exchange.update_leverage(leverage, symbol)

                info = Info(base_url, skip_ws=True)
                mids = info.all_mids()
                price = float(mids.get(symbol, "0"))
                if price <= 0:
                    logging.error(f"Kein Preis für {symbol}")
                    continue

                # Balance aus Spot + Fallback Perps
                spot_state = info.spot_user_state(account_address)
                usdc_spot = 0.0
                for bal in spot_state.get("balances", []):
                    if bal.get("coin") == "USDC":
                        usdc_spot = float(bal.get("total", "0"))
                        break

                user_state = info.user_state(account_address)
                usdc_perps = float(user_state.get("marginSummary", {}).get("accountValue", "0"))

                usdc = max(usdc_spot, usdc_perps)
                usdc_to_use = usdc * size_pct
                usdc_to_use = min(usdc_to_use, 10.0)  # Sicherheits-Cap

                sz_raw = usdc_to_use / price

                # Asset-spezifische Mindestgröße (Hyperliquid lehnt sehr kleine Orders ab)
                min_sz_map = {
                    "ETH": 0.001,
                    "BTC": 0.0001,
                    "SOL": 0.01,
                    "BNB": 0.01,
                    "EIGEN": 1.0,      # ← entscheidend für dein aktuelles Asset!
                }
                min_sz = min_sz_map.get(symbol, 0.01)  # Default 0.01

                # Mindestens min_sz verwenden (zwingend für "invalid size")
                sz = max(sz_raw, min_sz)

                # Präzision anpassen – EIGEN braucht meist 1 oder 0 Dezimalen
                decimals = 1 if symbol == "EIGEN" else 5
                sz = round(sz, decimals)

                if sz < min_sz:
                    logging.warning(f"Größe {sz:.8f} unter Minimum {min_sz} für {symbol} → überspringe")
                    continue

                logging.info(f"Trade-Plan: {action} {symbol} | sz = {sz:.8f} (raw {sz_raw:.8f}, min {min_sz}) | price ≈ {price:.2f} | usdc ≈ {usdc_to_use:.2f}")

                order_result = exchange.market_open(
                    name=symbol,
                    is_buy=is_buy,
                    sz=sz,
                    slippage=0.015
                )                
                
                logging.info(f"Spot raw balances: {json.dumps(spot_state.get('balances', []), indent=2)}")
                logging.info(f"Balance-Check: Spot = {usdc_spot:.2f}, Perps = {usdc_perps:.2f} → verwende {usdc:.2f}")

                if usdc <= 0:
                    logging.error("Kein USDC-Balance verfügbar (weder Spot noch Perps)")
                    continue

                usdc_to_use = usdc * size_pct
                usdc_to_use = min(usdc_to_use, 10.0)  # Sicherheits-Cap

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

                order_result = exchange.market_open(
                    name=symbol,
                    is_buy=is_buy,
                    sz=sz,
                    slippage=0.015
                )

                logging.info(f"Order-Antwort: {json.dumps(order_result, indent=2)}")

                if order_result.get("status") == "ok":
                    logging.info(f"✅ Erfolgreich: {action} {symbol}")
                else:
                    logging.error(f"Order fehlgeschlagen: {order_result}")

            except Exception as e:
                logging.exception(f"Fehler bei {symbol}: {str(e)}")