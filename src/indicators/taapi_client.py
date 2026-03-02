"""Client helper for interacting with the TAAPI technical analysis API.
THIS FILE IS NOW FULLY DISABLED – NO API CALLS ARE MADE ANYMORE!
All methods return None or empty structures immediately.
"""

import logging

logger = logging.getLogger(__name__)


class TAAPIClient:
    """Fetches TA indicators – DISABLED VERSION. Returns always None/empty."""

    def __init__(self):
        logger.warning("TAAPIClient initialisiert – ABER ALLE AUFRUFE SIND DEAKTIVIERT!")
        self.api_key = None
        self.base_url = "https://api.taapi.io/"  # nur noch für Logging

    def _get_with_retry(self, url, params, retries=3, backoff=0.5):
        logger.warning(f"TAAPI-Call deaktiviert – kein Request zu {url}")
        return None

    def get_indicators(self, asset, interval):
        logger.info(f"TAAPI get_indicators deaktiviert für {asset} ({interval}) → return None")
        return {
            "rsi": None,
            "macd": None,
            "sma": None,
            "ema": None,
            "bbands": None
        }

    def get_historical_indicator(self, indicator, symbol, interval, results=10, params=None):
        logger.info(f"TAAPI get_historical_indicator deaktiviert: {indicator} {symbol} {interval}")
        return []

    def fetch_series(self, indicator: str, symbol: str, interval: str, results: int = 10, params: dict | None = None, value_key: str = "value") -> list:
        logger.info(f"TAAPI fetch_series deaktiviert für {indicator} {symbol} {interval}")
        return []

    def fetch_value(self, indicator: str, symbol: str, interval: str, params: dict | None = None, key: str = "value"):
        logger.info(f"TAAPI fetch_value deaktiviert für {indicator} {symbol} {interval}")
        return None