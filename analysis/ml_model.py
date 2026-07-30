"""
ML-based direction classifier: loading and inference here; the actual
training happens in analysis/ml_training.py (shared) and is invoked by
train_crypto_model.py / train_stock_model.py or the in-app hourly
auto-retrainer (ui/ml_autotrain.py) -- never as part of the app's normal
startup path.

Models are versioned (see analysis/ml_versions.py): every trained version
is kept on disk with its metrics, and one is marked "active" -- that's the
one loaded here. Purely an optional enhancement -- if no trained/active
model exists yet, predict_proba_up() returns None and
analysis/signal_engine.py's analyze() just skips the ML signal, falling
back to the 7 rule-based indicators only. Nothing about running the app
normally requires a trained model.
"""
from __future__ import annotations
import os

import numpy as np
import pandas as pd

import config
from analysis.ml_features import FEATURE_COLUMNS, compute_features

_model_cache: dict[str, object] = {}


def model_path(name: str) -> str:
    """Legacy flat-file path (pre-versioning). Only used now to detect and
    migrate a model saved by an older build of this feature."""
    return os.path.join(config.ML_MODEL_DIR, f"{name}.joblib")


def is_trained(name: str) -> bool:
    from analysis import ml_versions
    return ml_versions.get_active_version(name) is not None or os.path.exists(model_path(name))


def load_model(name: str):
    if name in _model_cache:
        return _model_cache[name]

    from analysis import ml_versions
    path = ml_versions.get_active_model_path(name)

    if path is None:
        # backward-compat: adopt a pre-versioning flat model file as v1 if
        # no versions have been registered yet
        legacy_path = model_path(name)
        if os.path.exists(legacy_path) and not ml_versions.list_versions(name):
            try:
                import joblib
                legacy_model = joblib.load(legacy_path)
            except Exception:
                return None
            ml_versions.register_version(
                name, legacy_model,
                metrics={"note": "imported from a pre-versioning model file"},
                activate=True,
            )
            path = ml_versions.get_active_model_path(name)

    if path is None:
        return None
    try:
        import joblib
        model = joblib.load(path)
    except Exception:
        return None  # a corrupt/incompatible model file just disables the ML signal, never crashes the app
    _model_cache[name] = model
    return model


def predict_proba_up(name: str, df_with_indicators: pd.DataFrame) -> float | None:
    """Calibrated probability (0-1) that price will be higher at the
    model's trained horizon, using the most recent row of indicators.
    Returns None if no trained model exists or there isn't enough warmed-up
    history yet to compute features."""
    model = load_model(name)
    if model is None or df_with_indicators.empty:
        return None
    try:
        features = compute_features(df_with_indicators)
        last_row = features.iloc[[-1]][FEATURE_COLUMNS]
    except (KeyError, IndexError):
        return None
    if last_row.isna().any(axis=None):
        return None
    try:
        proba = model.predict_proba(last_row)[0]
        classes = list(model.classes_)
        idx_up = classes.index(1.0) if 1.0 in classes else classes.index(1)
        return float(proba[idx_up])
    except Exception:
        return None


def build_classifier():
    """The actual sklearn estimator used by both training scripts --
    shared here so crypto/stock training stay consistent. Gradient-boosted
    trees tend to handle this kind of small-feature tabular data better
    than linear models or deep nets, and are cheap enough to retrain
    regularly on a personal computer. Wrapped in calibration so
    predict_proba() reflects genuine confidence rather than a raw,
    overconfident score."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.calibration import CalibratedClassifierCV

    base = HistGradientBoostingClassifier(
        max_depth=4,
        max_iter=200,
        learning_rate=0.06,
        l2_regularization=1.0,
        random_state=42,
    )
    return CalibratedClassifierCV(base, method="isotonic", cv=3)


def time_based_split(frame: pd.DataFrame, test_fraction: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits each symbol's rows by TIME (earliest -> train, most recent ->
    test), then concatenates across symbols. Never a random split -- a
    random split would leak future information into training and make the
    reported accuracy meaningless."""
    train_parts, test_parts = [], []
    for symbol, group in frame.groupby("symbol"):
        group = group.sort_values("timestamp")
        cutoff = int(len(group) * (1 - test_fraction))
        train_parts.append(group.iloc[:cutoff])
        test_parts.append(group.iloc[cutoff:])
    train = pd.concat(train_parts, ignore_index=True) if train_parts else frame.iloc[0:0]
    test = pd.concat(test_parts, ignore_index=True) if test_parts else frame.iloc[0:0]
    return train, test


def evaluate(model, test_frame: pd.DataFrame) -> dict:
    """Returns accuracy/precision/recall/F1, a naive-baseline comparison
    (always predicting the majority class), and a calibration table
    (predicted-confidence bucket -> actual accuracy in that bucket) so you
    can see whether the model's confidence is trustworthy, not just whether
    its predictions are right on average."""
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

    X = test_frame[FEATURE_COLUMNS]
    y = test_frame["label"].astype(int)
    if len(y) == 0:
        return {"error": "No test rows available."}

    pred = model.predict(X).astype(int)
    proba = model.predict_proba(X)
    classes = list(model.classes_)
    idx_up = classes.index(1.0) if 1.0 in classes else classes.index(1)
    proba_up = proba[:, idx_up]

    majority_class = int(y.mean() >= 0.5)
    baseline_acc = float((y == majority_class).mean())

    calibration_rows = []
    bins = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.01]
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (proba_up >= lo) & (proba_up < hi)
        if mask.sum() == 0:
            continue
        calibration_rows.append({
            "bucket": f"{lo:.0%}-{hi:.0%}",
            "n": int(mask.sum()),
            "avg_predicted_confidence": float(proba_up[mask].mean()),
            "actual_up_rate": float(y[mask].mean()),
        })

    return {
        "n_test": int(len(y)),
        "accuracy": float(accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "baseline_majority_class_accuracy": baseline_acc,
        "calibration": calibration_rows,
    }


def save_model(model, name: str, metrics: dict | None = None):
    """Convenience: registers a new version AND makes it active immediately
    (no promotion-gate comparison). The auto-retrain pipeline instead calls
    analysis.ml_versions.register_version() directly so it can apply its
    own compare-against-active-then-decide logic."""
    from analysis import ml_versions
    return ml_versions.register_version(name, model, metrics or {}, activate=True)
