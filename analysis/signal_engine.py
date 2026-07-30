"""
Turns raw indicator values into:
  - a bullish % / bearish % split
  - a direction call (UP / DOWN) with a confidence %
  - a breakout / breakdown probability
  - a list of individual named signals (firing or not, and which way)
  - a suggested target price for a given time horizon
  - suggested buy / stop-loss levels

Primarily a transparent, rules-based scoring model -- the same family of
technique used by most retail technical-analysis dashboards: turn
indicators into a weighted vote. An optional trained ML signal (see
analysis/ml_model.py) can be folded in as one additional weighted vote
alongside the 7 rule-based ones, but only once you've actually trained a
model (see train_crypto_model.py / train_stock_model.py) -- with no
trained model, this is exactly the rules-only system it always was. Either
way, treat outputs as decision support, not certainty.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math

import numpy as np
import pandas as pd

import config
from config import INDICATOR_WEIGHTS, CONFIDENCE_FLOOR, CONFIDENCE_CEIL


@dataclass
class SignalResult:
    bullish_pct: float
    bearish_pct: float
    direction: str          # "UP" or "DOWN"
    confidence_pct: float
    breakout_pct: float
    breakdown_pct: float
    signals: list           # list[SignalFlag]
    target_price: float
    suggested_entry: float
    suggested_stop: float
    suggested_take_profit: float
    last_price: float
    horizon_minutes: float
    target_time: "datetime | None" = None  # set when the horizon is pinned to
                                             # a clock boundary (e.g. Robinhood's
                                             # 15-min futures settlement times)


@dataclass
class SignalFlag:
    name: str
    label: str               # human readable e.g. "MACD bullish cross"
    active: bool              # is this signal currently "firing"
    direction: str             # "bullish" / "bearish" / "neutral"
    detail: str                 # short explanation for the UI


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def _score_trend_ema(row) -> tuple[float, SignalFlag]:
    fast, slow = row["ema_fast"], row["ema_slow"]
    if pd.isna(fast) or pd.isna(slow):
        return 0.0, SignalFlag("trend_ema", "EMA9/EMA21 trend", False, "neutral", "warming up")
    diff_pct = (fast - slow) / slow * 100 if slow else 0
    score = _clip(diff_pct / 0.5, -1, 1)  # +/-0.5% spread -> full score
    direction = "bullish" if diff_pct > 0 else "bearish"
    active = abs(diff_pct) > 0.03
    detail = f"EMA9 {'above' if diff_pct>0 else 'below'} EMA21 by {abs(diff_pct):.2f}%"
    return score, SignalFlag("trend_ema", "Short-term trend (EMA9 vs EMA21)", active, direction, detail)


def _score_macd(row) -> tuple[float, SignalFlag]:
    hist = row["macd_hist"]
    macd_line, sig_line = row["macd"], row["macd_signal"]
    if pd.isna(hist):
        return 0.0, SignalFlag("macd", "MACD", False, "neutral", "warming up")
    scale = max(abs(row["close"]) * 0.0015, 1e-9)
    score = _clip(hist / scale, -1, 1)
    direction = "bullish" if macd_line > sig_line else "bearish"
    active = abs(hist) > scale * 0.15
    detail = f"MACD {'above' if macd_line>sig_line else 'below'} signal line"
    return score, SignalFlag("macd", "MACD cross", active, direction, detail)


def _score_rsi(row) -> tuple[float, SignalFlag]:
    v = row["rsi14"]
    if pd.isna(v):
        return 0.0, SignalFlag("rsi", "RSI(14)", False, "neutral", "warming up")
    # Oversold (<30) is a bullish-leaning signal, overbought (>70) bearish-leaning
    score = _clip((50 - v) / 25, -1, 1)
    if v >= 70:
        direction, active, detail = "bearish", True, f"RSI {v:.0f} - overbought"
    elif v <= 30:
        direction, active, detail = "bullish", True, f"RSI {v:.0f} - oversold"
    else:
        direction = "bullish" if v > 50 else "bearish"
        active = False
        detail = f"RSI {v:.0f} - neutral zone"
    return score, SignalFlag("rsi", "RSI momentum", active, direction, detail)


def _score_stochastic(row) -> tuple[float, SignalFlag]:
    k, d = row["stoch_k"], row["stoch_d"]
    if pd.isna(k) or pd.isna(d):
        return 0.0, SignalFlag("stochastic", "Stochastic", False, "neutral", "warming up")
    score = _clip((k - 50) / 40, -1, 1)
    if k >= 80:
        direction, active, detail = "bearish", True, f"Stoch %K {k:.0f} - overbought"
    elif k <= 20:
        direction, active, detail = "bullish", True, f"Stoch %K {k:.0f} - oversold"
    else:
        direction = "bullish" if k > d else "bearish"
        active = False
        detail = f"Stoch %K {k:.0f}, %D {d:.0f}"
    return score, SignalFlag("stochastic", "Stochastic oscillator", active, direction, detail)


def _score_vwap(row) -> tuple[float, SignalFlag]:
    price, vw = row["close"], row["vwap"]
    if pd.isna(vw) or vw == 0:
        return 0.0, SignalFlag("vwap", "Price vs VWAP", False, "neutral", "warming up")
    diff_pct = (price - vw) / vw * 100
    score = _clip(diff_pct / 0.4, -1, 1)
    direction = "bullish" if diff_pct > 0 else "bearish"
    active = abs(diff_pct) > 0.05
    detail = f"Price {'above' if diff_pct>0 else 'below'} VWAP by {abs(diff_pct):.2f}%"
    return score, SignalFlag("vwap", "Price vs VWAP", active, direction, detail)


def _score_bollinger(row) -> tuple[float, SignalFlag]:
    price, upper, lower, mid = row["close"], row["bb_upper"], row["bb_lower"], row["bb_mid"]
    if pd.isna(upper) or pd.isna(lower) or upper == lower:
        return 0.0, SignalFlag("bollinger", "Bollinger position", False, "neutral", "warming up")
    pos = (price - mid) / ((upper - lower) / 2)  # -1 (lower band) .. +1 (upper band)
    pos = _clip(pos, -1.5, 1.5)
    score = _clip(pos / 1.2, -1, 1)
    if price >= upper:
        direction, active, detail = "bearish", True, "Price at/above upper band (stretched)"
    elif price <= lower:
        direction, active, detail = "bullish", True, "Price at/below lower band (stretched)"
    else:
        direction = "bullish" if pos > 0 else "bearish"
        active = False
        detail = "Price inside the bands"
    return score, SignalFlag("bollinger", "Bollinger Band position", active, direction, detail)


def _score_volume(row) -> tuple[float, SignalFlag]:
    z = row["vol_z"]
    price_up = row["close"] >= row.get("open", row["close"])
    if pd.isna(z):
        return 0.0, SignalFlag("volume", "Volume", False, "neutral", "warming up")
    spike = z > 1.5
    lean = 1 if price_up else -1
    score = _clip((z / 3) * lean, -1, 1) if spike else 0.0
    direction = "bullish" if lean > 0 else "bearish"
    detail = (f"Volume spike ({z:.1f}sigma) on a {'green' if price_up else 'red'} bar"
              if spike else f"Volume normal ({z:.1f}sigma)")
    return score, SignalFlag("volume", "Volume spike", bool(spike), direction, detail)


def _score_ml(
    df_with_indicators: pd.DataFrame, model_name: str, symbol: str | None = None,
) -> tuple[float, SignalFlag | None]:
    from analysis import ml_model  # lazy import: sklearn/joblib only get imported if a model is actually used

    last_price = float(df_with_indicators.iloc[-1]["close"])

    if symbol is not None:
        try:
            from analysis import ml_prediction_tracker
            ml_prediction_tracker.resolve_pending(model_name, symbol, last_price)
        except Exception:
            pass  # live tracking is best-effort, never blocks the actual signal

    proba_up = ml_model.predict_proba_up(model_name, df_with_indicators)
    if proba_up is None:
        return 0.0, None  # no trained/active model yet, or not enough warmed-up history -- caller skips this signal

    if symbol is not None:
        try:
            from analysis import ml_prediction_tracker, ml_versions
            active_version = ml_versions.get_active_version(model_name)
            version_id = active_version["version"] if active_version else "unknown"
            tracking_horizon_minutes = (
                config.ML_CRYPTO_HORIZON_BARS if model_name == config.ML_CRYPTO_MODEL_NAME
                else config.ML_STOCK_HORIZON_BARS * config.ML_STOCK_BAR_MINUTES
            )
            ml_prediction_tracker.log_prediction(
                model_name, symbol, version_id, proba_up, tracking_horizon_minutes, last_price,
            )
        except Exception:
            pass

    score = _clip((proba_up - 0.5) * 2, -1, 1)
    direction = "bullish" if proba_up > 0.5 else ("bearish" if proba_up < 0.5 else "neutral")
    active = abs(proba_up - 0.5) > 0.05
    detail = f"Trained model estimates {proba_up * 100:.0f}% probability of a higher price"
    return score, SignalFlag("ml_model", "ML model prediction", active, direction, detail)


_SCORERS = {
    "trend_ema": _score_trend_ema,
    "macd": _score_macd,
    "rsi": _score_rsi,
    "stochastic": _score_stochastic,
    "vwap": _score_vwap,
    "bollinger": _score_bollinger,
    "volume": _score_volume,
}


def _breakout_probability(row) -> tuple[float, float]:
    """Bollinger-squeeze + volume + ATR expansion heuristic.
    Returns (breakout_up_pct, breakout_down_pct); these are NOT complementary
    (both can be elevated during a squeeze -- direction is still uncertain).
    """
    width_pct = row.get("bb_width_pct", np.nan)
    vol_z = row.get("vol_z", 0.0)
    trend_score, _ = _score_trend_ema(row)

    if pd.isna(width_pct):
        squeeze_factor = 0.3
    else:
        # low width_pct (band is tighter than its recent history) => squeeze
        squeeze_factor = _clip(1 - width_pct, 0, 1)

    vol_factor = _clip((vol_z + 1) / 3, 0, 1)
    base = 0.35 * squeeze_factor + 0.25 * vol_factor + 0.15
    base = _clip(base, 0.05, 0.85)

    # lean the split by current trend direction
    lean = _clip(trend_score, -1, 1) * 0.5 * base
    breakout_up = _clip(base / 2 + lean, 0.02, 0.95)
    breakout_down = _clip(base / 2 - lean, 0.02, 0.95)
    return breakout_up * 100, breakout_down * 100


def next_clock_boundary(now: datetime, interval_minutes: int = 15) -> datetime:
    """The next clock-aligned boundary strictly after `now` -- e.g. with
    interval_minutes=15: 12:07 -> 12:15, 12:16 -> 12:30, and 12:00:00.000
    exactly -> 12:15 (the *next* one, not the instant itself). This mirrors
    Robinhood's perpetual-futures settlement schedule (:00/:15/:30/:45)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    discard = timedelta(
        minutes=now.minute % interval_minutes,
        seconds=now.second,
        microseconds=now.microsecond,
    )
    floor = now - discard
    return floor + timedelta(minutes=interval_minutes)


def analyze(
    df_with_indicators: pd.DataFrame,
    horizon_minutes: float,
    weights: dict | None = None,
    target_time: datetime | None = None,
    decimal_threshold: float = 5,
    ml_model_name: str | None = None,
    symbol: str | None = None,
) -> SignalResult:
    """
    df_with_indicators: output of indicators.compute_all(), most recent row last.
    target_time: optional -- if the caller pinned the horizon to a specific
    clock time (e.g. the next 15-minute settlement), pass it through here so
    the UI can display "Target for 12:15:00" instead of a generic countdown.
    decimal_threshold: prices below this are rounded/displayed to 6 decimal
    places instead of 2 (useful for low-unit-price crypto tokens).
    ml_model_name: optional -- name of a trained model (see
    analysis/ml_model.py) to fold in as an additional weighted signal
    alongside the 7 rule-based indicators. If no trained/active model
    exists yet, this is silently skipped and behavior is unchanged.
    symbol: optional -- only used alongside ml_model_name, to log/resolve
    live predictions for the Model History tab's accuracy tracking. Safe to
    omit (the ML signal itself still works; only the tracking is skipped).
    """
    weights = weights or INDICATOR_WEIGHTS
    row = df_with_indicators.iloc[-1]
    last_price = float(row["close"])

    total_score = 0.0
    total_weight = 0.0
    flags: list[SignalFlag] = []
    for key, weight in weights.items():
        scorer = _SCORERS[key]
        score, flag = scorer(row)
        flags.append(flag)
        total_score += score * weight
        total_weight += weight

    if ml_model_name:
        ml_score, ml_flag = _score_ml(df_with_indicators, ml_model_name, symbol)
        if ml_flag is not None:
            flags.append(ml_flag)
            ml_weight = (
                config.ML_SIGNAL_WEIGHT_CRYPTO if ml_model_name == config.ML_CRYPTO_MODEL_NAME
                else config.ML_SIGNAL_WEIGHT_STOCK
            )
            total_score += ml_score * ml_weight
            total_weight += ml_weight

    net_score = total_score / total_weight if total_weight else 0.0  # -1..1
    bullish_pct = _clip(50 + net_score * 50, 2, 98)
    bearish_pct = 100 - bullish_pct

    direction = "UP" if bullish_pct >= 50 else "DOWN"
    raw_confidence = abs(bullish_pct - 50) * 2  # 0..100 distance from a coin flip
    confidence_pct = _clip(
        CONFIDENCE_FLOOR + (raw_confidence / 100) * (CONFIDENCE_CEIL - CONFIDENCE_FLOOR),
        CONFIDENCE_FLOOR, CONFIDENCE_CEIL,
    )

    breakout_up_pct, breakout_down_pct = _breakout_probability(row)

    # --- price target -----------------------------------------------------
    atr_val = row.get("atr14", np.nan)
    if pd.isna(atr_val) or atr_val <= 0:
        atr_val = last_price * 0.004  # fallback ~0.4%

    # Project ATR (a per-bar volatility measure) across the horizon using a
    # sqrt-of-time scaling, then bias by net_score. This is a heuristic, not
    # a statistical guarantee.
    bars_in_horizon = max(horizon_minutes / _infer_bar_minutes(df_with_indicators), 1)
    projected_move = atr_val * math.sqrt(bars_in_horizon) * 0.5
    target_price = last_price + net_score * projected_move
    if direction == "UP":
        target_price = max(target_price, last_price)
    else:
        target_price = min(target_price, last_price)

    # --- entry / stop / take-profit suggestion -----------------------------
    stop_distance = atr_val * 1.2
    tp_distance = max(abs(target_price - last_price), atr_val * 1.5)
    if direction == "UP":
        suggested_entry = last_price
        suggested_stop = last_price - stop_distance
        suggested_take_profit = last_price + tp_distance
    else:
        suggested_entry = last_price
        suggested_stop = last_price + stop_distance
        suggested_take_profit = last_price - tp_distance

    return SignalResult(
        bullish_pct=round(bullish_pct, 1),
        bearish_pct=round(bearish_pct, 1),
        direction=direction,
        confidence_pct=round(confidence_pct, 1),
        breakout_pct=round(breakout_up_pct, 1),
        breakdown_pct=round(breakout_down_pct, 1),
        signals=flags,
        target_price=round(target_price, 6 if last_price < decimal_threshold else 2),
        suggested_entry=round(suggested_entry, 6 if last_price < decimal_threshold else 2),
        suggested_stop=round(suggested_stop, 6 if last_price < decimal_threshold else 2),
        suggested_take_profit=round(suggested_take_profit, 6 if last_price < decimal_threshold else 2),
        last_price=last_price,
        horizon_minutes=horizon_minutes,
        target_time=target_time,
    )


def _infer_bar_minutes(df: pd.DataFrame) -> float:
    if "timestamp" in df.columns and len(df) >= 2:
        diffs = df["timestamp"].diff().dropna()
        if len(diffs):
            median_sec = diffs.dt.total_seconds().median()
            if median_sec and median_sec > 0:
                return median_sec / 60.0
    return 1.0
