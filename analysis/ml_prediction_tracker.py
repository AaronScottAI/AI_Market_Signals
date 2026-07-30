"""
Tracks live predictions made by the active ML model during normal app
usage, and resolves them once enough real time has passed to know the
actual outcome -- a real-world accuracy record for the currently active
version, separate from (and a check against) its backtested training
metrics.

Note: predictions are logged on every analyze() cycle (e.g. every 60
seconds), and each one's horizon is much longer than that cycle, so
consecutive logged predictions have overlapping time windows rather than
being fully independent samples. That's a known simplification -- treat
the live accuracy % as a reasonable ongoing signal, not a rigorous
statistic.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timedelta

import config


def _path(name: str) -> str:
    return os.path.join(config.ML_PREDICTIONS_DATA_DIR, f"{name}_predictions.json")


def _load(name: str) -> list:
    path = _path(name)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        predictions = data.get("predictions", [])
        return predictions if isinstance(predictions, list) else []
    except (json.JSONDecodeError, OSError, ValueError, AttributeError):
        return []


def _save(name: str, predictions: list):
    os.makedirs(config.ML_PREDICTIONS_DATA_DIR, exist_ok=True)
    with open(_path(name), "w") as f:
        json.dump({"predictions": predictions}, f, indent=2)


def log_prediction(
    name: str, symbol: str, version: str, proba_up: float,
    horizon_minutes: float, price_at_prediction: float,
):
    predictions = _load(name)
    predictions.append({
        "symbol": symbol,
        "version": version,
        "proba_up": proba_up,
        "predicted_direction": "UP" if proba_up >= 0.5 else "DOWN",
        "horizon_minutes": horizon_minutes,
        "price_at_prediction": price_at_prediction,
        "predicted_at": datetime.now().isoformat(),
        "resolve_at": (datetime.now() + timedelta(minutes=horizon_minutes)).isoformat(),
        "resolved": False,
        "actual_direction": None,
        "correct": None,
    })
    if len(predictions) > 5000:  # keep the file from growing forever
        predictions = predictions[-5000:]
    _save(name, predictions)


def resolve_pending(name: str, symbol: str, current_price: float):
    """Call this periodically (e.g. each live analyze() cycle) with the
    latest price for `symbol` -- resolves any of that symbol's predictions
    whose horizon has elapsed."""
    predictions = _load(name)
    now = datetime.now()
    changed = False
    for p in predictions:
        if p.get("resolved") or p.get("symbol") != symbol:
            continue
        try:
            resolve_at = datetime.fromisoformat(p["resolve_at"])
        except (KeyError, ValueError, TypeError):
            continue
        if now >= resolve_at:
            actual_direction = "UP" if current_price > p["price_at_prediction"] else "DOWN"
            p["actual_direction"] = actual_direction
            p["correct"] = actual_direction == p["predicted_direction"]
            p["resolved"] = True
            p["resolved_price"] = current_price
            changed = True
    if changed:
        _save(name, predictions)


def get_live_accuracy(name: str, version: str | None = None) -> dict:
    """Returns {'n': resolved_count, 'accuracy': fraction_correct_or_None}.
    If `version` is given, restricts to predictions made by that specific
    model version."""
    predictions = _load(name)
    resolved = [p for p in predictions if p.get("resolved")]
    if version is not None:
        resolved = [p for p in resolved if p.get("version") == version]
    if not resolved:
        return {"n": 0, "accuracy": None}
    correct = sum(1 for p in resolved if p.get("correct"))
    return {"n": len(resolved), "accuracy": correct / len(resolved)}
