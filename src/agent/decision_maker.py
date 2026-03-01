"""Decision-making agent for momentum trading on volatile altcoins."""
import os
import logging
import http.client as http_client
import requests
import json
from datetime import datetime
from src.config_loader import CONFIG
from urllib.parse import urljoin

# Hyperliquid Imports
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from eth_account import Account
from eth_account.signers.local import LocalAccount

# Logging Setup
http_client.HTTPConnection.debuglevel = 1
logging.basicConfig(level=logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)  # Weniger urllib3-Noise
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
        """Entscheidet + führt sofort aus."""
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
        dry_run = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
        if dry_run:
            logging.warning("DRY_RUN ist aktiv → KEINE echten Orders werden gesendet")
            for trade in decisions:
                logging.info(f"[DRY-RUN] Würde ausführen: {trade}")
            return

        # Alte Zeile:
        # hl_env = os.getenv("HYPERLIQUID_ENVIRONMENT", "testnet")
        
        # Neue, strengere Version:
        hl_env = os.getenv("HYPERLIQUID_ENVIRONMENT")
        if hl_env is None:
            logging.error("HYPERLIQUID_ENVIRONMENT ist nicht gesetzt! Abbruch.")
            return
        if hl_env not in ("mainnet", "testnet"):
            logging.error(f"Ungültiger Wert für HYPERLIQUID_ENVIRONMENT: '{hl_env}' → nur 'mainnet' oder 'testnet' erlaubt")
            return
        base_url = constants.TESTNET_API_URL if hl_env == "testnet" else constants.MAINNET_API_URL

        private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
        account_address = os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS")

        if not private_key:
            logging.error("HYPERLIQUID_PRIVATE_KEY fehlt in Umgebungsvariablen")
            return

        if not private_key.startswith("0x"):
            private_key = "0x" + private_key

        try:
            wallet: LocalAccount = Account.from_key(private_key)
        except ValueError as e:
            logging.error(f"Ungültiger HYPERLIQUID_PRIVATE_KEY: {e}")
            return

        if not account_address:
            account_address = wallet.address

        logging.info(f"Wallet-Adresse: {wallet.address}")
        logging.info(f"Verwendete Account-Adresse: {account_address}")

        try:
            exchange = Exchange(
                wallet,
                base_url=base_url,
                account_address=account_address
            )
            logging.info(f"Hyperliquid Exchange initialisiert ({hl_env})")
        except Exception as e:
            logging.error(f"Fehler beim Initialisieren von Exchange: {e}")
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
                # Leverage setzen
                exchange.update_leverage(leverage, symbol)

                # Preis + Balance holen
                info = Info(base_url, skip_ws=True)
                mids = info.all_mids()
                price = float(mids.get(symbol, "0"))
                if price <= 0:
                    logging.error(f"Kein Preis verfügbar für {symbol}")
                    continue

                user_state = info.user_state(account_address)
                logging.info("=== DEBUG: Vollständiger user_state vom Hyperliquid ===")
                logging.info(json.dumps(user_state, indent=2))
                logging.info("=== ENDE DEBUG ===")
                usdc = float(user_state.get("marginSummary", {}).get("accountValue", "0"))
                if usdc <= 0:
                    logging.error("Kein USDC-Balance verfügbar")
                    continue

                usdc_to_use = usdc * size_pct
                sz = usdc_to_use / price
                # Sicherheits-Cap für ersten Live-Trade
                max_usdc_risk = 10.0  # ← z. B. max 10 USDC pro Trade beim Start
                usdc_to_use = min(usdc_to_use, max_usdc_risk)
                sz = usdc_to_use / price

                if sz < 0.001:  # Mindestgröße – anpassen je nach Asset
                    logging.warning(f"Zu kleine Größe für {symbol} → überspringe")
                    continue                

                logging.info(f"Trade-Plan: {action} {symbol} | sz ≈ {sz:.6f} | price ≈ {price} | lev {leverage}")

                # Market Order senden
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

Test-Modus (nur für diesen einen Durchlauf gültig):
Für diesen Prompt gilt eine Ausnahme: Auch wenn die Datenlage dünn ist und normalerweise HOLD die richtige Entscheidung wäre,
darfst du JETZT aus Testzwecken mindestens einen Trade vorschlagen.
Wähle dafür das Asset, das am ehesten Momentum-potenzial hat (z. B. höchster Funding-Rate positiv, höchste OI-Veränderung, höchster Preis in den letzten Bewegungen, …)
und mache einen kleinen Long-Trade (max 5–10 % Größe, max 3–5× Leverage).
Schreibe in reasoning explizit dazu, dass dies ein Test-Trade ist.
Nach diesem Test kehren die normalen strengen Regeln sofort wieder.

Ziel: Maximaler Profit bei minimalem Drawdown. Sei kalt, rational und gierig – aber nie dumm.""".format(
            current_time=datetime.utcnow().isoformat()
        )

        user_prompt = context

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
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
            resp_json = resp.json()
            message = resp_json["choices"][0]["message"]

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
