"""
Shared training pipeline: fetching history, pooling multiple symbols,
splitting, training, and evaluating. Used identically by the manual
train_crypto_model.py / train_stock_model.py scripts and the in-app hourly
auto-retrainer (ui/ml_autotrain.py), so both paths behave the same way.
"""
from __future__ import annotations
import time

import pandas as pd

import config
from analysis.indicators import compute_all
from analysis.ml_features import build_training_frame, FEATURE_COLUMNS
from analysis import ml_model


def fetch_crypto_symbol_history(symbol: str, timeframe: str, total_bars: int) -> pd.DataFrame:
    """Pages forward through Kraken's OHLCV history via ccxt until either
    `total_bars` is collected or the exchange runs out of data to return.
    Uses its own isolated exchange connection (context="ml_training") so
    this background fetching never queues up behind the live UI's price
    polling on a shared rate-limited connection."""
    from data import crypto_source

    exchange = crypto_source.get_exchange(context="ml_training")
    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
    since = exchange.milliseconds() - total_bars * timeframe_ms
    rows = []
    while len(rows) < total_bars:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=720)
        if not batch:
            break
        rows.extend(batch)
        next_since = batch[-1][0] + timeframe_ms
        if next_since <= since or len(batch) < 2:
            break
        since = next_since
        time.sleep(max(exchange.rateLimit, 200) / 1000)

    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="ts_ms").sort_values("ts_ms")
    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def fetch_stock_ticker_history(ticker: str, period: str | None = None, interval: str | None = None) -> pd.DataFrame:
    import yfinance as yf

    period = period or config.ML_STOCK_HISTORY_PERIOD
    interval = interval or config.ML_STOCK_BAR_INTERVAL
    tkr = yf.Ticker(ticker)
    hist = tkr.history(period=period, interval=interval, auto_adjust=False)
    if hist.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    hist = hist.reset_index()
    time_col = "Datetime" if "Datetime" in hist.columns else "Date"
    hist = hist.rename(columns={
        time_col: "timestamp", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    return hist[["timestamp", "open", "high", "low", "close", "volume"]]


def build_pooled_frame(symbols, fetch_fn, horizon_bars: int, min_bars: int = 200, log=print) -> pd.DataFrame | None:
    """fetch_fn: callable(symbol) -> raw OHLCV DataFrame. Returns None if no
    symbol produced usable data."""
    frames = []
    for symbol in symbols:
        log(f"  Fetching {symbol}...")
        try:
            df = fetch_fn(symbol)
        except Exception as exc:
            log(f"    FAILED ({type(exc).__name__}: {exc}) -- skipping")
            continue
        if len(df) < min_bars:
            log(f"    only got {len(df)} bars -- skipping (need at least {min_bars})")
            continue
        df_ind = compute_all(df)
        frame = build_training_frame(df_ind, horizon_bars=horizon_bars, symbol=symbol)
        frames.append(frame)
        log(f"    {len(df)} bars fetched, {len(frame)} usable training rows")
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def train_candidate(pooled_frame: pd.DataFrame, test_fraction: float = 0.2):
    """Returns (model, metrics, train_df, test_df), or (None, None, None,
    None) if there isn't enough data to train reliably."""
    train, test = ml_model.time_based_split(pooled_frame, test_fraction=test_fraction)
    if len(train) < 200 or len(test) < 50:
        return None, None, None, None
    clf = ml_model.build_classifier()
    clf.fit(train[FEATURE_COLUMNS], train["label"].astype(int))
    metrics = ml_model.evaluate(clf, test)
    metrics["n_train"] = len(train)
    return clf, metrics, train, test


def passes_baseline_check(metrics: dict) -> bool:
    """A candidate must not underperform the naive majority-class baseline
    by more than config.ML_MAX_BASELINE_UNDERPERFORMANCE, regardless of how
    it compares to whatever's currently active. Guards against a model
    that's genuinely bad in absolute terms getting promoted just because it
    happens to be less bad than the version before it."""
    accuracy = metrics.get("accuracy")
    baseline = metrics.get("baseline_majority_class_accuracy")
    if accuracy is None or baseline is None:
        return True  # nothing to check against -- don't block on missing data
    return accuracy >= baseline - config.ML_MAX_BASELINE_UNDERPERFORMANCE


def decide_promotion(candidate_metrics: dict, active_metrics: dict | None) -> bool:
    """The single shared promotion rule, used identically by
    train_crypto_model.py, train_stock_model.py, and the in-app hourly
    auto-retrainer (ui/ml_autotrain.py) -- so there's exactly one place
    this logic lives, not three copies that can silently drift apart.

    Two conditions, both required:
      1. Clears the naive-baseline bar (see passes_baseline_check) --
         applies even to a version with nothing else to compare against,
         so being "first" is never a free pass for a genuinely bad model.
      2. Beats the currently active model by at least ML_PROMOTION_MARGIN
         on the same freshly-built test set (skipped if there's no active
         model to compare against, since condition 1 already covers that
         case on its own)."""
    if not passes_baseline_check(candidate_metrics):
        return False
    if active_metrics is None:
        return True
    return (candidate_metrics["accuracy"] - active_metrics["accuracy"]) >= config.ML_PROMOTION_MARGIN


def evaluate_active_model(name: str, test_frame: pd.DataFrame) -> dict | None:
    """Re-evaluates whatever model is CURRENTLY active on a freshly-built
    test set, so a candidate can be compared fairly against it (the active
    model's own recorded metrics were measured on a different, older test
    split). Returns None (treated as "nothing to compare against, promote
    the candidate by default") if the active model can't be evaluated at
    all -- e.g. it predates a feature-set change and expects a different
    number of input columns than the current pipeline produces."""
    model = ml_model.load_model(name)
    if model is None:
        return None
    try:
        return ml_model.evaluate(model, test_frame)
    except Exception:
        return None
