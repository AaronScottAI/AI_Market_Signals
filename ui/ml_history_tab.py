"""
Model History tab: review every trained version of each ML model (crypto +
stock), see backtested metrics for each, and roll back to an older version
if you think it performed better than whatever's currently active. Also
shows live-tracked accuracy (from real predictions made during normal use,
resolved once their horizon passed) for the currently active version.
"""
from __future__ import annotations
from PySide6 import QtGui, QtWidgets

import config
from analysis import ml_versions, ml_prediction_tracker

BG = "#0d1117"
CARD_BG = "#161b22"
TEXT = "#e6edf3"
SUBTEXT = "#8b949e"
BULLISH_COLOR = "#26a69a"
BEARISH_COLOR = "#ef5350"
ACCENT = "#42a5f5"


class ModelHistorySection(QtWidgets.QWidget):
    def __init__(self, title: str, model_name: str, parent=None):
        super().__init__(parent)
        self.model_name = model_name

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet(f"color: {TEXT}; font-size: 18px; font-weight: 800;")
        layout.addWidget(title_label)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        layout.addWidget(self.status_label)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Version", "Trained", "Backtest Acc.", "vs. Baseline", "Live Acc.", "Status", "",
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setStyleSheet(f"""
            QTableWidget {{ background: {CARD_BG}; color: {TEXT}; border: 1px solid #30363d;
                              gridline-color: #30363d; font-size: 12px; }}
            QHeaderView::section {{ background: #21262d; color: {SUBTEXT}; padding: 5px;
                                      border: none; font-size: 11px; }}
        """)
        self.table.setMinimumHeight(220)
        layout.addWidget(self.table)

        self.refresh()

    def refresh(self):
        versions = ml_versions.list_versions(self.model_name)  # newest-trained first
        active = ml_versions.get_active_version(self.model_name)
        active_id = active["version"] if active else None

        if not versions:
            self.status_label.setText(
                "No trained versions yet -- run train_crypto_model.py / train_stock_model.py "
                "yourself, or wait for the next automatic hourly retrain."
            )
            self.table.setRowCount(0)
            return

        live_stats = ml_prediction_tracker.get_live_accuracy(self.model_name, version=active_id)
        if live_stats["n"] > 0:
            self.status_label.setText(
                f"Active version: {active_id}  \u2014  live-tracked accuracy so far: "
                f"{live_stats['accuracy']:.1%} across {live_stats['n']} resolved real-world predictions "
                f"(overlapping prediction windows, so treat as a rough ongoing signal, not a rigorous stat)"
            )
        else:
            self.status_label.setText(
                f"Active version: {active_id}  \u2014  no resolved live predictions yet "
                f"(these accumulate as the app runs and predictions' horizons elapse)"
            )

        self.table.setRowCount(len(versions))
        for i, v in enumerate(versions):
            metrics = v.get("metrics", {}) or {}
            acc = metrics.get("accuracy")
            baseline = metrics.get("baseline_majority_class_accuracy")
            version_id = v["version"]
            is_active = version_id == active_id

            version_item = QtWidgets.QTableWidgetItem(version_id + ("  (active)" if is_active else ""))
            version_item.setForeground(QtGui.QColor(ACCENT if is_active else TEXT))
            if is_active:
                bold_font = version_item.font()
                bold_font.setBold(True)
                version_item.setFont(bold_font)

            trained_at = str(v.get("trained_at", ""))[:16].replace("T", " ")
            trained_item = QtWidgets.QTableWidgetItem(trained_at or "\u2014")
            trained_item.setForeground(QtGui.QColor(TEXT))

            acc_item = QtWidgets.QTableWidgetItem(f"{acc:.1%}" if acc is not None else "\u2014")
            acc_item.setForeground(QtGui.QColor(TEXT))

            if acc is not None and baseline is not None:
                diff = acc - baseline
                vs_baseline_item = QtWidgets.QTableWidgetItem(f"{diff:+.1%}")
                vs_baseline_item.setForeground(QtGui.QColor(BULLISH_COLOR if diff > 0 else BEARISH_COLOR))
            else:
                vs_baseline_item = QtWidgets.QTableWidgetItem("\u2014")
                vs_baseline_item.setForeground(QtGui.QColor(TEXT))

            live_for_version = ml_prediction_tracker.get_live_accuracy(self.model_name, version=version_id)
            live_text = (
                f"{live_for_version['accuracy']:.1%} ({live_for_version['n']})"
                if live_for_version["n"] > 0 else "\u2014"
            )
            live_item = QtWidgets.QTableWidgetItem(live_text)
            live_item.setForeground(QtGui.QColor(TEXT))

            if is_active:
                status_text = "Active"
            elif v.get("promoted"):
                status_text = "Promoted at training"
            else:
                status_text = "Not promoted"
            status_item = QtWidgets.QTableWidgetItem(status_text)
            status_item.setForeground(QtGui.QColor(TEXT))

            self.table.setItem(i, 0, version_item)
            self.table.setItem(i, 1, trained_item)
            self.table.setItem(i, 2, acc_item)
            self.table.setItem(i, 3, vs_baseline_item)
            self.table.setItem(i, 4, live_item)
            self.table.setItem(i, 5, status_item)

            if is_active:
                self.table.setItem(i, 6, QtWidgets.QTableWidgetItem(""))
            else:
                btn = QtWidgets.QPushButton("Activate this version")
                btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
                btn.clicked.connect(lambda checked=False, vid=version_id: self._activate(vid))
                self.table.setCellWidget(i, 6, btn)

        self.table.resizeColumnsToContents()

    def _activate(self, version_id: str):
        choice = QtWidgets.QMessageBox.question(
            self, "Roll Back / Switch Version",
            f"Make version {version_id} the active model? It will be used for every "
            f"prediction from now on, until you activate a different version.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            ml_versions.activate_version(self.model_name, version_id)
            self.refresh()


class MLHistoryTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {BG};")

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        content = QtWidgets.QWidget()
        content.setStyleSheet(f"background: {BG};")
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(20)

        header_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Model History")
        title.setStyleSheet(f"color: {TEXT}; font-size: 22px; font-weight: 800;")
        header_row.addWidget(title)
        header_row.addStretch()
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)

        note = QtWidgets.QLabel(
            "Every trained version of the ML model, newest first. \u201cBacktest Acc.\u201d is measured "
            "on held-out historical data at training time; \u201cLive Acc.\u201d is tracked from real "
            "predictions made while the app runs, resolved once their horizon has passed \u2014 the more "
            "honest number, though it takes time to accumulate. A new version only auto-replaces the "
            f"active one if it clears two bars: it must be within {config.ML_MAX_BASELINE_UNDERPERFORMANCE:.1%} "
            "of (or above) the naive majority-guess baseline, AND beat the active version by at least "
            f"{config.ML_PROMOTION_MARGIN:.1%} on a freshly-built test set \u2014 beating the prior version "
            "alone isn't enough if it's still meaningfully worse than trivially guessing the trend "
            "continues. A version that doesn't clear both is kept here for you to review, or manually "
            "activate anyway if you disagree with that call. Retrains automatically roughly every "
            f"{config.ML_AUTO_RETRAIN_INTERVAL_HOURS:g} hour(s) while the app is open."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        layout.addWidget(note)

        self.crypto_section = ModelHistorySection("Crypto Futures Model", config.ML_CRYPTO_MODEL_NAME)
        layout.addWidget(self.crypto_section)

        self.stock_section = ModelHistorySection("Stock Options Model", config.ML_STOCK_MODEL_NAME)
        layout.addWidget(self.stock_section)

        layout.addStretch()
        scroll.setWidget(content)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def refresh(self):
        self.crypto_section.refresh()
        self.stock_section.refresh()
