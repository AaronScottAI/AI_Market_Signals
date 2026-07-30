"""
Self-contained technical indicator library (no `ta`/`pandas_ta` dependency
so there's nothing extra to install or break).

Every function takes/returns pandas Series or a DataFrame with at least
columns: open, high, low, close, volume.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger_bands(series: pd.Series, length: int = 20, num_std: float = 2.0):
    mid = sma(series, length)
    std = series.rolling(length, min_periods=length).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid.replace(0, np.nan)
    return upper, mid, lower, width


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session-style VWAP computed over the whole supplied window."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum().replace(0, np.nan)
    cum_pv = (typical_price * df["volume"]).cumsum()
    return (cum_pv / cum_vol).bfill()


def stochastic(df: pd.DataFrame, k_length: int = 14, d_length: int = 3):
    low_min = df["low"].rolling(k_length, min_periods=k_length).min()
    high_max = df["high"].rolling(k_length, min_periods=k_length).max()
    rng = (high_max - low_min).replace(0, np.nan)
    k = 100 * (df["close"] - low_min) / rng
    k = k.fillna(50.0)
    d = k.rolling(d_length, min_periods=d_length).mean().fillna(50.0)
    return k, d


def volume_zscore(volume: pd.Series, length: int = 20) -> pd.Series:
    mean = volume.rolling(length, min_periods=length).mean()
    std = volume.rolling(length, min_periods=length).std().replace(0, np.nan)
    return ((volume - mean) / std).fillna(0.0)


def bollinger_width_percentile(width: pd.Series, length: int = 100) -> pd.Series:
    """Where current BB width sits vs its own recent history (0-1).
    Low percentile => a 'squeeze' => higher odds of an imminent breakout.
    """
    def _pct_rank(window):
        if np.isnan(window[-1]):
            return np.nan
        return (window < window[-1]).sum() / max(len(window) - 1, 1)

    return width.rolling(length, min_periods=min(30, length)).apply(_pct_rank, raw=True)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Attach every indicator as columns to a copy of df and return it."""
    out = df.copy()
    out["ema_fast"] = ema(out["close"], 9)
    out["ema_slow"] = ema(out["close"], 21)
    out["rsi14"] = rsi(out["close"], 14)
    macd_line, signal_line, hist = macd(out["close"])
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    upper, mid, lower, width = bollinger_bands(out["close"])
    out["bb_upper"] = upper
    out["bb_mid"] = mid
    out["bb_lower"] = lower
    out["bb_width"] = width
    out["bb_width_pct"] = bollinger_width_percentile(width)
    out["atr14"] = atr(out, 14)
    out["vwap"] = vwap(out)
    k, d = stochastic(out)
    out["stoch_k"] = k
    out["stoch_d"] = d
    out["vol_z"] = volume_zscore(out["volume"])
    return out
