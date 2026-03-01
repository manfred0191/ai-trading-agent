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
        """Verwendet die originale hyperliquid_api.py aus dem Repo"""
        from src.trading.hyperliquid_api import HyperliquidAPI   # Original-Import

        if os.getenv("DRY_RUN", "false").lower() == "true":
            logging.warning("🔒 DRY-RUN Modus aktiv – keine echten Orders!")
            return
        
        decisions = decision.get("trade_decisions", [])
        if not decisions:
            logging.info("🟡 Keine Trades vorgeschlagen → HOLD")
            return

        logging.info(f"🚀 Führe {len(decisions)} Trade(s) aus...")

        try:
            hl = HyperliquidAPI()   # liest automatisch aus CONFIG / env
            hl.execute(decision)    # Original-Methode des Repos
            logging.info("✅ Trades erfolgreich an Hyperliquid gesendet")
        except Exception as e:
            logging.error(f"❌ Ausführungsfehler: {e}")

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
            
