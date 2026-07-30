"""
Options chain data via yfinance (free, no API key). Provides IV, volume,
and open interest per contract, which we summarize into the aggregate
metrics the options_engine wants (avg IV per side, put/call volume ratio).

Note: yfinance options data is delayed like most free sources. For
real-time greeks/IV, the Tradier sandbox API is a solid free upgrade path
(see README.md).
"""
from __future__ import annotations
import pandas as pd


def list_expirations(symbol: str) -> list[str]:
    import yfinance as yf
    tkr = yf.Ticker(symbol)
    return list(tkr.options)


def fetch_chain(symbol: str, expiration: str | None = None) -> dict:
    """Returns {'calls': df, 'puts': df, 'expiration': str} for the nearest
    (or specified) expiration."""
    import yfinance as yf
    tkr = yf.Ticker(symbol)
    expirations = tkr.options
    if not expirations:
        return {"calls": pd.DataFrame(), "puts": pd.DataFrame(), "expiration": None}
    exp = expiration or expirations[0]
    chain = tkr.option_chain(exp)
    return {"calls": chain.calls, "puts": chain.puts, "expiration": exp}


def summarize_chain(chain: dict) -> dict:
    """Collapse a chain (calls/puts DataFrames) into the scalar metrics the
    options signal engine consumes."""
    calls, puts = chain.get("calls"), chain.get("puts")
    summary = {
        "expiration": chain.get("expiration"),
        "call_iv_avg": None,
        "put_iv_avg": None,
        "call_volume": None,
        "put_volume": None,
        "call_open_interest": None,
        "put_open_interest": None,
    }
    if calls is not None and not calls.empty:
        summary["call_iv_avg"] = float(calls["impliedVolatility"].mean())
        summary["call_volume"] = float(calls["volume"].fillna(0).sum())
        summary["call_open_interest"] = float(calls["openInterest"].fillna(0).sum())
    if puts is not None and not puts.empty:
        summary["put_iv_avg"] = float(puts["impliedVolatility"].mean())
        summary["put_volume"] = float(puts["volume"].fillna(0).sum())
        summary["put_open_interest"] = float(puts["openInterest"].fillna(0).sum())
    return summary


def pick_expiration_for_horizon(symbol: str, horizon_minutes: int) -> str | None:
    """Choose the nearest expiration that is at or after the prediction
    horizon (falls back to the nearest available expiration otherwise)."""
    import datetime as dt
    expirations = list_expirations(symbol)
    if not expirations:
        return None
    target_date = (dt.datetime.utcnow() + dt.timedelta(minutes=horizon_minutes)).date()
    for exp in expirations:
        exp_date = dt.datetime.strptime(exp, "%Y-%m-%d").date()
        if exp_date >= target_date:
            return exp
    return expirations[-1]
