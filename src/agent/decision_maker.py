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
        self.model = CONFIG["llm_model"]
        self.api_key = CONFIG["openrouter_api_key"]
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    def decide_trade(self, assets, context):
        decision = self._decide(context, assets=assets)
        if decision.get("trade_decisions"):
            self._execute_trades(decision)
        return decision

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

                user_state = info.user_state(account_address)
                usdc = float(user_state.get("marginSummary", {}).get("accountValue", "0"))
                if usdc <= 0:
                    logging.error("Kein USDC-Balance verfügbar")
                    continue

                usdc_to_use = usdc * size_pct
                usdc_to_use = min(usdc_to_use, 10.0)          # Sicherheits-Cap

                sz_raw = usdc_to_use / price

                # === SAUBERE RUNDUNG ===
                sz = round(sz_raw, 8)                         # Standard für die meisten Assets

                # Mindestgröße-Check
                min_sz = 0.001 if symbol in ["ETH", "BTC", "SOL"] else 0.01
                if sz < min_sz:
                    logging.warning(f"Größe zu klein ({sz:.8f}) für {symbol} → überspringe")
                    continue

                logging.info(f"Trade-Plan: {action} {symbol} | sz = {sz:.8f} | price ≈ {price:.2f} | usdc ≈ {usdc_to_use:.2f}")

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

    def _decide(self, context, assets):
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

Test-Modus (nur für diesen einen Durchlauf gültig):
Für diesen Prompt gilt eine Ausnahme: Auch wenn die Datenlage dünn ist und normalerweise HOLD die richtige Entscheidung wäre,
darfst du JETZT aus Testzwecken mindestens einen Trade vorschlagen.
Wähle dafür das Asset, das am ehesten Momentum-potenzial hat und mache einen kleinen Long-Trade (max 5–10 % Größe, max 3–5× Leverage).
Schreibe in reasoning explizit dazu, dass dies ein Test-Trade ist.
Nach diesem Test kehren die normalen strengen Regeln sofort wieder.

Ziel: Maximaler Profit bei minimalem Drawdown. Sei kalt, rational und gierig – aber nie dumm.""".format(
            current_time=datetime.utcnow().isoformat()
        )

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
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

            parsed = json.loads(content)
            if "trade_decisions" not in parsed:
                parsed = {"reasoning": "Parse-Fehler", "trade_decisions": []}
            return parsed

        except Exception as e:
            logging.error(f"LLM decision failed: {str(e)}")
            return {"reasoning": f"Error: {str(e)}", "trade_decisions": []}
