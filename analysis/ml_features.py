"""
Feature engineering for the optional ML direction model.

Deliberately reuses the exact same underlying calculations as the
rule-based scorers in signal_engine.py, just packaged as raw scale-invariant
numeric features instead of individually-thresholded scores. Scale-invariant
(percentages, ratios, z-scores -- never a raw price) so one model trained on
a pool of several symbols generalizes reasonably to symbols it never saw in
training, rather than needing a dedicated model per ticker.
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
