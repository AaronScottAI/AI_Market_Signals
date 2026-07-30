"""
Feature engineering for the optional ML direction model.

Reuses the same underlying calculations as the rule-based scorers in
signal_engine.py for the first 10 features, packaged as raw scale-invariant
numeric values instead of individually-thresholded scores. Adds two more
feature families on top:
  - Raw N-bar momentum (return_5bar, return_20bar) -- distinct from the
    oscillator-style RSI/stochastic above; a well-documented factor in its
    own right, especially relevant for stocks where short/medium-term
    momentum has real academic support.
  - Cyclical time-of-day / day-of-week encoding -- now that both models
    train on intraday (crypto: 1m, stocks: 1h) bars, there's genuine
    session/day structure to potentially learn from (e.g. market open vs.
    close volatility, weekday vs weekend crypto behavior).
Deliberately still scale-invariant (percentages, ratios, sin/cos -- never a
raw price) so one pooled model generalizes to symbols it never specifically
trained on.

Shared by both the crypto and stock training pipelines -- not stock-only,
since momentum and session structure are plausible factors for crypto too,
and maintaining one feature set is far simpler than forking two. If it
turns out these don't help a particular model, gradient-boosted trees are
reasonably good at just not leaning on a feature that isn't informative.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "ema_spread_pct",
    "rsi14",
    "macd_hist_norm",
    "bb_position",
    "bb_width_pct",
    "atr_pct",
    "vwap_dist_pct",
    "stoch_k",
    "stoch_d",
    "vol_z",
    "return_5bar",
    "return_20bar",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
]


def compute_features(df_with_indicators: pd.DataFrame) -> pd.DataFrame:
    """df_with_indicators: output of analysis.indicators.compute_all().
    Returns a DataFrame with exactly FEATURE_COLUMNS, same index as input."""
    df = df_with_indicators
    out = pd.DataFrame(index=df.index)

    out["ema_spread_pct"] = (df["ema_fast"] - df["ema_slow"]) / df["ema_slow"].replace(0, np.nan) * 100

    out["rsi14"] = df["rsi14"]

    price_scale = df["close"].abs().replace(0, np.nan)
    out["macd_hist_norm"] = (df["macd_hist"] / price_scale * 100).clip(-50, 50)

    bb_half_range = (df["bb_upper"] - df["bb_lower"]) / 2
    out["bb_position"] = ((df["close"] - df["bb_mid"]) / bb_half_range.replace(0, np.nan)).clip(-3, 3)

    out["bb_width_pct"] = (df["bb_width"] * 100).clip(0, 100)

    out["atr_pct"] = (df["atr14"] / price_scale * 100).clip(0, 50)

    out["vwap_dist_pct"] = ((df["close"] - df["vwap"]) / df["vwap"].replace(0, np.nan) * 100).clip(-50, 50)

    out["stoch_k"] = df["stoch_k"]
    out["stoch_d"] = df["stoch_d"]
    out["vol_z"] = df["vol_z"].clip(-6, 6)

    out["return_5bar"] = ((df["close"] / df["close"].shift(5) - 1) * 100).clip(-50, 50)
    out["return_20bar"] = ((df["close"] / df["close"].shift(20) - 1) * 100).clip(-50, 50)

    ts = pd.to_datetime(df["timestamp"])
    hour_of_day = ts.dt.hour + ts.dt.minute / 60.0
    out["hour_sin"] = np.sin(2 * np.pi * hour_of_day / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour_of_day / 24)
    day_of_week = ts.dt.dayofweek  # 0 = Monday
    out["dow_sin"] = np.sin(2 * np.pi * day_of_week / 7)
    out["dow_cos"] = np.cos(2 * np.pi * day_of_week / 7)

    return out[FEATURE_COLUMNS]


def make_labels(df_with_indicators: pd.DataFrame, horizon_bars: int) -> pd.Series:
    """1 if close price `horizon_bars` bars ahead is higher than the current
    close, else 0. The last `horizon_bars` rows will be NaN (no future data
    yet) -- drop those before training."""
    future_close = df_with_indicators["close"].shift(-horizon_bars)
    label = (future_close > df_with_indicators["close"]).astype("float")
    label[future_close.isna()] = np.nan
    return label


def build_training_frame(df_with_indicators: pd.DataFrame, horizon_bars: int, symbol: str) -> pd.DataFrame:
    """Combines features + label + a symbol tag into one frame, with rows
    that have any NaN (indicator warm-up period or missing future label)
    dropped. `symbol` is kept as a plain column (not a feature) so the
    training script can do a per-symbol time-based train/test split before
    pooling."""
    features = compute_features(df_with_indicators)
    label = make_labels(df_with_indicators, horizon_bars)
    frame = features.copy()
    frame["label"] = label
    frame["symbol"] = symbol
    frame["timestamp"] = df_with_indicators["timestamp"].values
    return frame.dropna(subset=FEATURE_COLUMNS + ["label"]).reset_index(drop=True)
