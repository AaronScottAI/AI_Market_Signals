"""
Live stock quotes + historical bars via yfinance (free, no API key/login).

yfinance pulls from Yahoo Finance. It's an unofficial/community-maintained
wrapper -- reliable enough for a personal analysis tool, but if you later
want lower-latency real-time quotes, a free Finnhub API key is a drop-in
upgrade (see README.md).
"""
from __future__ import annotations
import pandas as pd


def resolve_chart_params(horizon_minutes: int) -> tuple[str, str]:
    """Pick a sensible (interval, period) pair for yfinance based on the
    prediction horizon, respecting Yahoo's intraday history limits."""
    if horizon_minutes <= 180:          # up to 3 hours out -> fine-grained bars
        return "5m", "5d"
    elif horizon_minutes <= 60 * 24 * 3:  # up to 3 days out
        return "15m", "1mo"
    else:                                  # a week+ out
        return "1h", "3mo"


def fetch_spot_price(symbol: str) -> dict:
    import yfinance as yf
    tkr = yf.Ticker(symbol)
    fast = tkr.fast_info
    price = fast.get("lastPrice") or fast.get("last_price")
    prev_close = fast.get("previousClose") or fast.get("previous_close")
    pct_change = None
    if price is not None and prev_close:
        pct_change = (price - prev_close) / prev_close * 100
    return {
        "price": price,
        "prev_close": prev_close,
        "pct_change": pct_change,
        "timestamp": pd.Timestamp.utcnow(),
        "day_high": fast.get("dayHigh"),
        "day_low": fast.get("dayLow"),
    }


def fetch_ohlcv(symbol: str, horizon_minutes: int) -> pd.DataFrame:
    import yfinance as yf
    interval, period = resolve_chart_params(horizon_minutes)
    tkr = yf.Ticker(symbol)
    hist = tkr.history(period=period, interval=interval, auto_adjust=False)
    hist = hist.reset_index()
    time_col = "Datetime" if "Datetime" in hist.columns else "Date"
    hist = hist.rename(columns={
        time_col: "timestamp", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    return hist[["timestamp", "open", "high", "low", "close", "volume"]]
