"""
Live crypto market data via a public exchange API (through ccxt).

No Robinhood login, no API key, no account needed -- these are public
market-data endpoints. Crypto prices are arbitraged tightly across venues,
so this is a reliable proxy for what you'd see on Robinhood's crypto/
perpetual-futures screens (small basis-point differences are normal and
expected between any two venues).
"""
from __future__ import annotations
import time
import pandas as pd

import config

_exchanges: dict[str, object] = {}


def get_exchange(context: str = "default"):
    """Lazily construct a ccxt exchange client (avoids network calls at
    import time). `context` gets its own isolated instance with its own
    independent rate-limiter state -- e.g. background ML model training
    (analysis/ml_training.py) uses context="ml_training" specifically so
    its burst of historical-data requests can never queue up behind (and
    delay) the live UI's price polling, which shares one rate-limited
    connection on a single exchange object like this one enforces a
    minimum gap between EVERY request on that object, regardless of which
    part of the app is asking."""
    if context not in _exchanges:
        import ccxt  # imported lazily so the rest of the app works even before `pip install ccxt`
        exchange_cls = getattr(ccxt, config.CRYPTO_EXCHANGE)
        _exchanges[context] = exchange_cls({"enableRateLimit": True})
    return _exchanges[context]


def fetch_spot_price(symbol: str, context: str = "default") -> dict:
    """Returns {'price': float, 'bid': float, 'ask': float, 'timestamp': datetime, 'pct_change_24h': float}"""
    ex = get_exchange(context)
    ticker = ex.fetch_ticker(symbol)
    return {
        "price": ticker.get("last") or ticker.get("close"),
        "bid": ticker.get("bid"),
        "ask": ticker.get("ask"),
        "timestamp": pd.Timestamp.utcnow(),
        "pct_change_24h": ticker.get("percentage"),
        "base_volume_24h": ticker.get("baseVolume"),
    }


def fetch_ohlcv(symbol: str, timeframe: str = "1m", limit: int = 180, context: str = "default") -> pd.DataFrame:
    """Returns a DataFrame with columns: timestamp, open, high, low, close, volume"""
    ex = get_exchange(context)
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def list_available_symbols(context: str = "default") -> list[str]:
    """Filter config.CRYPTO_SYMBOLS down to ones the exchange actually lists."""
    ex = get_exchange(context)
    try:
        markets = ex.load_markets()
        return [s for s in config.CRYPTO_SYMBOLS if s in markets]
    except Exception:
        # If markets can't be loaded (e.g. no network yet), just return the
        # configured list and let individual fetches fail/retry later.
        return list(config.CRYPTO_SYMBOLS)
