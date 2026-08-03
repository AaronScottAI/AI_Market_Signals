"""
Feature engineering for the optional ML direction model.

Reuses the same underlying calculations as the rule-based scorers in
signal_engine.py for the first 10 features, packaged as raw scale-invariant
numeric values instead of individually-thresholded scores. Adds three more
feature families on top:
  - Raw N-bar momentum (return_5bar, return_20bar) -- distinct from the
    oscillator-style RSI/stochastic above; a well-documented factor in its
    own right, especially relevant for stocks where short/medium-term
    momentum has real academic support.
  - Cyclical time-of-day / day-of-week encoding -- now that both models
    train on intraday (crypto: 1m, stocks: 1h) bars, there's genuine
    session/day structure to potentially learn from (e.g. market open vs.
    close volatility, weekday vs weekend crypto behavior).
  - Vectorized chart-pattern PROXY features -- NOT the same detectors as
    analysis/chart_patterns.py (those do iterative peak/trough finding per
    call, fine for one live analysis but far too slow to re-run at every
    row of a 50,000+ row training set). These instead use pure rolling-
    window arithmetic to approximate the same underlying structure: is
    price currently retesting a prior high/low, how deep was the pullback
    since then, is the recent range compressing (narrowing, as in a
    triangle/flag), and what was the move just before the current
    consolidation (a flag's "pole"). Cheaper and less precise than true
    pattern detection, but they scale to full training runs.
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
    "retest_high_proximity",
    "pullback_from_prior_high",
    "retest_low_proximity",
    "bounce_from_prior_low",
    "resistance_slope_pct",
    "support_slope_pct",
    "range_compression_ratio",
    "prior_move_pct",
]

# Bar counts for the pattern-proxy features. Fixed, same convention as
# return_5bar/return_20bar above -- not resolution-aware, just a consistent
# number of bars regardless of whether that's 1-minute or 1-hour data.
_RETEST_LOOKBACK = 40    # how far back to look for a "prior" peak/trough
_RETEST_RECENT_GAP = 10   # exclude this many of the most recent bars when finding that prior peak/trough,
                           # so it's compared against something that happened before right now
_TRIANGLE_WINDOW = 20      # window for slope-fitting and range-compression
_FLAG_BARS = 8              # recent consolidation window
_POLE_BARS = 15               # window just before the flag, checked for a sharp prior move


def _rolling_slope_pct(series: pd.Series, window: int) -> pd.Series:
    """Rolling linear-fit slope, expressed as % change implied over the
    window's span (scale-independent). Uses the closed-form identity
    slope = cov(x,y) / var(x) with pandas' native (C-implemented) rolling
    cov/var, rather than calling np.polyfit per window -- numerically
    identical to a real per-window least-squares fit, but the difference
    matters a lot at training scale: the naive per-window-callback version
    took ~5.4 seconds per column on a 50,000-row series; this takes well
    under a second for both columns combined."""
    x = pd.Series(np.arange(len(series)), index=series.index, dtype=float)
    cov_xy = x.rolling(window).cov(series)
    var_x = x.rolling(window).var()
    slope = cov_xy / var_x.replace(0, np.nan)
    mean = series.rolling(window).mean().replace(0, np.nan)
    return (slope * (window - 1)) / mean * 100


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

    # --- vectorized chart-pattern proxy features ---------------------------
    gap, span = _RETEST_RECENT_GAP, _RETEST_LOOKBACK - _RETEST_RECENT_GAP

    # Proxy for double-top / head-and-shoulders: is price now near a peak
    # from earlier in the window (excluding the last `gap` bars), and how
    # deep was the pullback since then?
    prior_peak = df["high"].shift(gap).rolling(span).max()
    recent_min = df["low"].rolling(gap).min()
    out["retest_high_proximity"] = ((df["close"] - prior_peak) / prior_peak.replace(0, np.nan) * 100).clip(-50, 50)
    out["pullback_from_prior_high"] = ((prior_peak - recent_min) / prior_peak.replace(0, np.nan) * 100).clip(0, 50)

    # Mirror, for double-bottom / inverse head-and-shoulders.
    prior_trough = df["low"].shift(gap).rolling(span).min()
    recent_max = df["high"].rolling(gap).max()
    out["retest_low_proximity"] = ((df["close"] - prior_trough) / prior_trough.replace(0, np.nan) * 100).clip(-50, 50)
    out["bounce_from_prior_low"] = ((recent_max - prior_trough) / prior_trough.replace(0, np.nan) * 100).clip(0, 50)

    # Proxy for triangles: trend slope of recent highs (resistance) and
    # lows (support) -- an ascending triangle shows resistance_slope near 0
    # (flat) with support_slope clearly positive (rising); descending is
    # the mirror.
    out["resistance_slope_pct"] = _rolling_slope_pct(df["high"], _TRIANGLE_WINDOW).clip(-50, 50)
    out["support_slope_pct"] = _rolling_slope_pct(df["low"], _TRIANGLE_WINDOW).clip(-50, 50)

    # Proxy for triangles/flags generally: is the trading range compressing
    # (narrowing) compared to a bit earlier -- classic consolidation signal
    # regardless of which specific named pattern it turns into.
    recent_range = (
        df["high"].rolling(_TRIANGLE_WINDOW).max() - df["low"].rolling(_TRIANGLE_WINDOW).min()
    ) / price_scale
    earlier_range = (
        df["high"].shift(_TRIANGLE_WINDOW).rolling(_TRIANGLE_WINDOW).max()
        - df["low"].shift(_TRIANGLE_WINDOW).rolling(_TRIANGLE_WINDOW).min()
    ) / price_scale.shift(_TRIANGLE_WINDOW)
    out["range_compression_ratio"] = (recent_range / earlier_range.replace(0, np.nan)).clip(0, 5)

    # Proxy for flags: magnitude/direction of the move just before the
    # current consolidation window -- the "pole" a flag would be attached to.
    pole_start = df["close"].shift(_FLAG_BARS + _POLE_BARS)
    pole_end = df["close"].shift(_FLAG_BARS)
    out["prior_move_pct"] = ((pole_end - pole_start) / pole_start.replace(0, np.nan) * 100).clip(-50, 50)

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
