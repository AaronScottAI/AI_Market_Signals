"""
Options tab:
  - stock symbol input + spot-price update interval selector
  - selectable prediction timeframe (1h/2h/3h/1d/2d/3d/1wk)
  - live spot price + chart
  - AI direction call with confidence % for the selected timeframe
  - buy / sell / stop-loss levels marked on the chart
  - options-chain context (IV skew, put/call ratio) folded into the call
"""
from __future__ import annotations
import os
from PySide6 import QtCore, QtWidgets

import config
from data import stock_source, options_source
from analysis.indicators import compute_all
from analysis.options_engine import analyze_options
from ui.chart_widget import ChartWidget, IndicatorToggleBar, ReferenceLineToggleBar, ChartModeToggle
from ui.signal_panel import SignalPanel, BULLISH_COLOR, BEARISH_COLOR, SUBTEXT, TEXT, BG
from ui.workers import FetchWorker
from ui.pnl_tracker import PnLTracker


class OptionsTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {BG}; color: {TEXT};")
        self._workers = []

        root = QtWidgets.QVBoxLayout(self)

        # --- controls row ---------------------------------------------------
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel("Stock symbol:"))
        self.symbol_edit = QtWidgets.QLineEdit(config.DEFAULT_STOCK_SYMBOL)
        self.symbol_edit.setMaximumWidth(90)
        self.symbol_edit.setPlaceholderText("e.g. AAPL")
        controls.addWidget(self.symbol_edit)
        self.load_btn = QtWidgets.QPushButton("Watch")
        controls.addWidget(self.load_btn)

        controls.addSpacing(16)
        controls.addWidget(QtWidgets.QLabel("Timeframe:"))
        self.timeframe_combo = QtWidgets.QComboBox()
        for label, minutes in config.OPTIONS_TIMEFRAMES:
            self.timeframe_combo.addItem(label, minutes)
        controls.addWidget(self.timeframe_combo)

        controls.addSpacing(16)
        controls.addWidget(QtWidgets.QLabel("Spot update interval:"))
        self.interval_combo = QtWidgets.QComboBox()
        for sec in config.STOCK_SPOT_UPDATE_INTERVALS_SEC:
            self.interval_combo.addItem(f"{sec}s", sec)
        default_idx = config.STOCK_SPOT_UPDATE_INTERVALS_SEC.index(config.DEFAULT_STOCK_UPDATE_INTERVAL_SEC)
        self.interval_combo.setCurrentIndex(default_idx)
        controls.addWidget(self.interval_combo)

        controls.addSpacing(16)
        self.hover_label = QtWidgets.QLabel("Hover the chart for candle details")
        self.hover_label.setStyleSheet(
            f"background: #161b22; color: {TEXT}; padding: 6px 12px;"
            "border: 1px solid #30363d; border-radius: 6px;"
            "font-family: Consolas, 'Courier New', monospace; font-size: 13px;"
        )
        self.hover_label.setFixedSize(380, 92)
        self.hover_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.hover_label.setWordWrap(False)
        controls.addWidget(self.hover_label)

        controls.addStretch()
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        controls.addWidget(self.status_label)
        controls.addSpacing(16)
        self.pnl_tracker = PnLTracker(
            os.path.join(config.PNL_DATA_DIR, "options_pnl.json"), label="Today's P&L"
        )
        controls.addWidget(self.pnl_tracker)
        root.addLayout(controls)

        # --- spot price header -----------------------------------------------
        price_row = QtWidgets.QHBoxLayout()
        self.price_label = QtWidgets.QLabel("—")
        self.price_label.setStyleSheet("font-size: 32px; font-weight: 800;")
        self.change_label = QtWidgets.QLabel("")
        self.change_label.setStyleSheet("font-size: 14px;")
        self.range_label = QtWidgets.QLabel("")
        self.range_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        price_col = QtWidgets.QVBoxLayout()
        price_col.addWidget(self.price_label)
        price_col.addWidget(self.range_label)
        price_row.addLayout(price_col)
        price_row.addWidget(self.change_label)
        price_row.addStretch()
        root.addLayout(price_row)

        # --- main split: chart | signal panel ---------------------------------
        split = QtWidgets.QSplitter()
        self.chart = ChartWidget()
        chart_container = QtWidgets.QWidget()
        chart_layout = QtWidgets.QVBoxLayout(chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(2)
        self.indicator_toggles = IndicatorToggleBar(self.chart)
        self.chart_mode_toggle = ChartModeToggle(self.chart)
        top_toggle_row = QtWidgets.QHBoxLayout()
        top_toggle_row.addWidget(self.indicator_toggles)
        top_toggle_row.addStretch()
        top_toggle_row.addWidget(self.chart_mode_toggle)
        chart_layout.addLayout(top_toggle_row)
        self.reference_toggles = ReferenceLineToggleBar(self.chart)
        chart_layout.addWidget(self.reference_toggles)
        chart_layout.addWidget(self.chart, stretch=1)
        split.addWidget(chart_container)
        self.chart.hover_info.connect(self.hover_label.setText)
        self.chart.hover_cleared.connect(
            lambda: self.hover_label.setText("Hover the chart for candle details")
        )
        self.signal_panel = SignalPanel(title_left="Target", chart=self.chart)
        panel_container = QtWidgets.QWidget()
        panel_container.setMinimumWidth(360)
        pc_layout = QtWidgets.QVBoxLayout(panel_container)
        pc_layout.setContentsMargins(0, 0, 0, 0)
        pc_layout.addWidget(self.signal_panel)
        split.addWidget(panel_container)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, stretch=1)

        # --- contract suggestion strip -----------------------------------
        self.contract_label = QtWidgets.QLabel("")
        self.contract_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px; padding: 4px 0;")
        root.addWidget(self.contract_label)

        # --- timers -------------------------------------------------------
        self.spot_timer = QtCore.QTimer(self)
        self.spot_timer.timeout.connect(self._poll_spot)

        self.signal_timer = QtCore.QTimer(self)
        self.signal_timer.timeout.connect(self._refresh_chart_and_signal)
        self.signal_timer.setInterval(config.STOCK_SIGNAL_REFRESH_SEC * 1000)

        self.load_btn.clicked.connect(self._on_symbol_changed)
        self.symbol_edit.returnPressed.connect(self._on_symbol_changed)
        self.timeframe_combo.currentIndexChanged.connect(self._refresh_chart_and_signal)
        self.interval_combo.currentIndexChanged.connect(self._on_interval_changed)

        self._on_interval_changed()
        self._poll_spot()
        self._refresh_chart_and_signal()
        self.signal_timer.start()

    # -- symbol / interval changes -----------------------------------------
    def _on_symbol_changed(self):
        self.symbol_edit.setText(self.symbol_edit.text().strip().upper())
        self.signal_panel.clear_manual_target()
        self._poll_spot()
        self._refresh_chart_and_signal()

    def _on_interval_changed(self):
        sec = self.interval_combo.currentData()
        self.spot_timer.setInterval(sec * 1000)
        if not self.spot_timer.isActive():
            self.spot_timer.start()

    # -- spot price polling -------------------------------------------------
    def _poll_spot(self):
        symbol = self.symbol_edit.text().strip().upper()
        if not symbol:
            return
        worker = FetchWorker(stock_source.fetch_spot_price, symbol)
        worker.result.connect(lambda data, sym=symbol: self._on_spot_result(sym, data))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _on_spot_result(self, symbol, data):
        if symbol != self.symbol_edit.text().strip().upper():
            return
        price = data.get("price")
        if price is None:
            self._on_error(f"No live price returned for {symbol}. Check the ticker symbol.")
            return
        self.price_label.setText(f"{price:,.2f}")
        self.signal_panel.set_current_price(price)
        pct = data.get("pct_change")
        if pct is not None:
            color = BULLISH_COLOR if pct >= 0 else BEARISH_COLOR
            self.change_label.setText(f"{pct:+.2f}%")
            self.change_label.setStyleSheet(f"font-size: 14px; color: {color}; font-weight: 600;")
        dh, dl = data.get("day_high"), data.get("day_low")
        if dh and dl:
            self.range_label.setText(f"Day range {dl:,.2f} – {dh:,.2f}")
        ts = data.get("timestamp")
        self.status_label.setText(f"Last spot update: {ts:%H:%M:%S}" if ts is not None else "")

    # -- chart + signal engine refresh --------------------------------------
    def _refresh_chart_and_signal(self):
        symbol = self.symbol_edit.text().strip().upper()
        if not symbol:
            return
        horizon_minutes = self.timeframe_combo.currentData()
        worker = FetchWorker(self._fetch_and_analyze, symbol, horizon_minutes)
        worker.result.connect(lambda payload, sym=symbol: self._on_chart_result(sym, payload))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    @staticmethod
    def _fetch_and_analyze(symbol: str, horizon_minutes: int):
        df = stock_source.fetch_ohlcv(symbol, horizon_minutes)
        df_ind = compute_all(df)

        chain_summary = None
        try:
            exp = options_source.pick_expiration_for_horizon(symbol, horizon_minutes)
            chain = options_source.fetch_chain(symbol, exp)
            chain_summary = options_source.summarize_chain(chain)
        except Exception:
            chain_summary = None  # options chain is best-effort context, not required

        result = analyze_options(df_ind, horizon_minutes, chain_summary, ml_model_name=config.ML_STOCK_MODEL_NAME, symbol=symbol)
        return df_ind, result

    def _on_chart_result(self, symbol, payload):
        if symbol != self.symbol_edit.text().strip().upper():
            return
        df_ind, options_result = payload
        core = options_result.core
        self.chart.update_data(df_ind)
        self.chart.set_reference_lines({
            "entry": (core.suggested_entry, "#ffca28", "Entry"),
            "take_profit": (core.suggested_take_profit, BULLISH_COLOR, "TP"),
            "stop": (core.suggested_stop, BEARISH_COLOR, "Stop"),
            "target": (core.target_price, "#42a5f5", "Target"),
        })

        extra_lines = []
        if options_result.iv_skew_signal and options_result.iv_skew_signal.active:
            extra_lines.append(options_result.iv_skew_signal.detail)
        if options_result.put_call_signal and options_result.put_call_signal.active:
            extra_lines.append(options_result.put_call_signal.detail)
        notes = "  ·  ".join(options_result.notes)
        self.signal_panel.update_result(core, extra_notes=notes)

        self.contract_label.setText(
            f"Bias: {options_result.suggested_contract_type} contracts, "
            f"{options_result.suggested_moneyness}"
            + (f"   ({'  ·  '.join(extra_lines)})" if extra_lines else "")
        )

    # -- shared error handling / cleanup ------------------------------------
    def _on_error(self, message: str):
        self.status_label.setText(f"⚠ {message}")
        self.status_label.setStyleSheet(f"color: {BEARISH_COLOR}; font-size: 11px;")

    def _cleanup_worker(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
