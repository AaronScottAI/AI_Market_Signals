"""
Background hourly auto-retrainer: on a QTimer, trains a fresh candidate
model for both crypto and stocks, compares each against its currently
active version on a freshly-held-out test set, and only promotes a
candidate if it's actually more accurate (see config.ML_PROMOTION_MARGIN).
Runs entirely in a background thread so it never freezes the UI.

Off switch: config.ML_AUTO_RETRAIN_ENABLED = False. Only retrains while
the app is open -- there's no separate background service, so nothing
happens while the app is closed.
"""
from __future__ import annotations
from PySide6 import QtCore

import config
from analysis import ml_training, ml_versions
from ui.workers import FetchWorker


class MLAutoTrainController(QtCore.QObject):
    status_changed = QtCore.Signal(str)
    retrain_finished = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.run_now)
        if config.ML_AUTO_RETRAIN_ENABLED:
            interval_ms = int(config.ML_AUTO_RETRAIN_INTERVAL_HOURS * 60 * 60 * 1000)
            self.timer.setInterval(max(interval_ms, 60_000))
            self.timer.start()
            # also kick off a first run shortly after launch, rather than
            # waiting a full interval for the very first retrain
            QtCore.QTimer.singleShot(20_000, self.run_now)

    def run_now(self):
        if any(w.isRunning() for w in self._workers):
            return  # a retrain is already in progress -- don't overlap
        worker = FetchWorker(_retrain_both_models)
        worker.result.connect(self._on_result)
        worker.error.connect(lambda msg: self.status_changed.emit(f"Auto-retrain error: {msg}"))
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup(worker))
        self.status_changed.emit("Auto-retrain running in the background...")
        worker.start()

    def _cleanup(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)

    def _on_result(self, summary: dict):
        parts = []
        for name, info in summary.items():
            status = info.get("status")
            if status == "promoted":
                parts.append(f"{name}: new version promoted ({info.get('new_version')})")
            elif status == "kept_previous":
                parts.append(f"{name}: candidate trained but not promoted")
            else:
                parts.append(f"{name}: {status}")
        self.status_changed.emit("Auto-retrain complete -- " + "; ".join(parts))
        self.retrain_finished.emit()


def _retrain_both_models() -> dict:
    results = {}
    results[config.ML_CRYPTO_MODEL_NAME] = _retrain_one(
        config.ML_CRYPTO_MODEL_NAME,
        symbols=config.CRYPTO_SYMBOLS,
        fetch_fn=lambda sym: ml_training.fetch_crypto_symbol_history(sym, config.CRYPTO_CHART_TIMEFRAME, 8000),
        horizon_bars=config.ML_CRYPTO_HORIZON_BARS,
    )
    results[config.ML_STOCK_MODEL_NAME] = _retrain_one(
        config.ML_STOCK_MODEL_NAME,
        symbols=config.ML_STOCK_TRAINING_TICKERS,
        fetch_fn=ml_training.fetch_stock_ticker_history,
        horizon_bars=config.ML_STOCK_HORIZON_BARS,
    )
    return results


def _retrain_one(name: str, symbols, fetch_fn, horizon_bars: int) -> dict:
    pooled = ml_training.build_pooled_frame(symbols, fetch_fn, horizon_bars, log=lambda *a: None)
    if pooled is None:
        return {"status": "no_data"}

    candidate, metrics, train_df, test_df = ml_training.train_candidate(pooled)
    if candidate is None:
        return {"status": "not_enough_data"}

    active_metrics = ml_training.evaluate_active_model(name, test_df)
    promote = ml_training.decide_promotion(metrics, active_metrics)

    metrics["compared_active_accuracy"] = active_metrics["accuracy"] if active_metrics else None
    metrics["promoted"] = promote
    new_version = ml_versions.register_version(name, candidate, metrics, activate=promote)

    return {
        "status": "promoted" if promote else "kept_previous",
        "new_version": new_version,
        "metrics": metrics,
    }
