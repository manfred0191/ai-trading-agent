"""Decision-making agent for momentum trading on volatile altcoins."""
import os
import logging
import http.client as http_client
http_client.HTTPConnection.debuglevel = 1
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True
import requests
import json
from datetime import datetime
from src.config_loader import CONFIG
from urllib.parse import urljoin
from eth_account import Account
from eth_account.signers.local import LocalAccount


class TradingAgent:
    """Trading agent focused on momentum trades for volatile altcoins."""

    def __init__(self):
        """Initialize LLM client – TAAPI komplett deaktiviert."""
        self.model = CONFIG["llm_model"]
        self.api_key = CONFIG["openrouter_api_key"]  # jetzt Groq-Key
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    def decide_trade(self, assets, context):
        """Entscheidet + führt sofort aus (Original-Repo Flow)"""
        decision = self._decide(context, assets=assets)   # dein bestehender LLM-Code
        
        # ← NEU: echte Ausführung
        if decision.get("trade_decisions"):
            self._execute_trades(decision)
        
        return decision

    def _execute_trades(self, decision: dict):
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants
        import os

        decisions = decision.get("trade_decisions", [])
        if not decisions:
            logging.info("Keine Trades → nichts zu tun")
            return

        # Sicherheitsbremse während Test
        if os.getenv("DRY_RUN", "true").lower() in ("true", "1"):
            logging.warning("DRY_RUN aktiv → KEINE echten Orders! (setze DRY_RUN=false für live)")
            for trade in decisions:
                logging.info(f"[DRY] Würde ausführen: {trade}")
            return

        hl_env = os.getenv("HYPERLIQUID_ENVIRONMENT", "testnet")
        base_url = constants.TESTNET_API_URL if hl_env == "testnet" else constants.MAINNET_API_URL

private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY")
account_address = os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS")

if not private_key:
    logging.error("HYPERLIQUID_PRIVATE_KEY fehlt")
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

exchange = Exchange(
    wallet,                         # ← Korrekt: das signierfähige Objekt
    base_url=base_url,
    account_address=account_address
)

        logging.info(f"Hyperliquid Exchange initialisiert ({hl_env})")

        for trade in decisions:
            action = trade.get("action", "HOLD").upper()
            if action not in ("BUY", "SELL"):
                continue

            symbol = trade["symbol"].replace("-USD", "").replace("-USDT", "").upper()  # "ETH"
            is_buy = action == "BUY"
            size_pct = float(trade.get("size_pct", 0.05))   # 0.05 = 5%
            leverage = int(trade.get("leverage", 5))

            try:
                # Leverage zuerst setzen (einmal pro Coin)
                exchange.update_leverage(leverage, symbol)   # ← symbol = "ETH"

                # Aktuellen Mid-Preis holen
                info = Info(base_url, skip_ws=True)
                mids = info.all_mids()
                price = float(mids.get(symbol, "0"))
                if price <= 0:
                    logging.error(f"Kein Preis verfügbar für {symbol}")
                    continue

                # Balance holen → echte Größe berechnen
                user_state = info.user_state(account_address)
                usdc = float(user_state.get("marginSummary", {}).get("accountValue", "0"))
                if usdc <= 0:
                    logging.error("Kein USDC-Balance auf Testnet")
                    continue

                usdc_to_use = usdc * size_pct
                sz = usdc_to_use / price   # Coin-Menge (z.B. 0.012 ETH bei 2000$ und 25$ Einsatz)

                logging.info(f"Trade-Plan: {action} {symbol} | sz ≈ {sz:.6f} | price ≈ {price} | lev {leverage}")

                # Market Open Order
                order_result = exchange.market_open(
                    name=symbol,           # ← der Fix!
                    is_buy=is_buy,
                    sz=sz,
                    slippage=0.015         # 1.5% Toleranz
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

Ziel: Maximaler Profit bei minimalem Drawdown. Sei kalt, rational und gierig – aber nie dumm.""".format(current_time=datetime.utcnow().isoformat())

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
            logging.info(f"Full LLM endpoint URL (len): {len(self.base_url)} chars")
            logging.info(f"Full LLM endpoint URL (hex dump first 100): {self.base_url[:100].encode('utf-8').hex()}")
            logging.info(f"Using model: {self.model}")
            logging.info(f"API key prefix: {self.api_key[:10]}...")

            print(repr(self.base_url))          # in Logs
            print(self.base_url.encode('utf-8').hex())

            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            resp_json = resp.json()
            message = resp_json["choices"][0]["message"]

            # Keine Tool-Calls mehr → direkt den Content parsen
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
            
