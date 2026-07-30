"""
Robinhood-style crypto perpetual-futures tab:
  - symbol selector + spot-price update interval selector
  - live spot price (bid/ask, 24h change)
  - target price for the next 15-minute settlement window + AI direction call
    with confidence %
  - price chart with indicator overlays
  - bullish/bearish % (refreshed every minute, with a rolling history view)
  - signals forming / not forming
  - breakout / breakdown probability
"""
from __future__ import annotations
import copy
import os
from datetime import datetime, timezone
from PySide6 import QtCore, QtWidgets

import config
from data import crypto_source
from analysis.indicators import compute_all
from analysis.signal_engine import analyze, next_clock_boundary
from analysis.rti_tracker import RTITracker
from ui.chart_widget import ChartWidget, IndicatorToggleBar, ReferenceLineToggleBar, ChartModeToggle
from ui.signal_panel import SignalPanel, BULLISH_COLOR, BEARISH_COLOR, SUBTEXT, TEXT, BG
from ui.workers import FetchWorker
from ui.pnl_tracker import PnLTracker


class FuturesTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {BG}; color: {TEXT};")
        self._workers = []
        self._latest_ohlcv = None

        # Target price replicates CF Benchmarks' RTI settlement methodology
        # (see analysis/rti_tracker.py): one price sample per second during
        # the final 60 seconds before each :00/:15/:30/:45 boundary, then
        # the average of those samples becomes the frozen target/entry for
        # the window that just started. The ENTIRE signal panel snapshots
        # together at that same moment -- confidence, bullish/bearish %,
        # breakout odds, and the signals list all freeze as one unit rather
        # than drifting independently every 60 seconds, so the whole panel
        # always reflects a single consistent reading taken once per window.
        self.rti_tracker = RTITracker(lambda now: next_clock_boundary(now, config.FUTURES_HORIZON_MINUTES))
        self._latest_result = None
        self._frozen_result = None
        self._frozen_target_time = None
        self._frozen_target_price = None
        self._frozen_entry = None
        self._frozen_stop = None
        self._frozen_tp = None

        root = QtWidgets.QVBoxLayout(self)

        # --- controls row ---------------------------------------------------
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel("Symbol:"))
        self.symbol_combo = QtWidgets.QComboBox()
        self.symbol_combo.addItems(config.CRYPTO_SYMBOLS)
        controls.addWidget(self.symbol_combo)

        controls.addSpacing(20)
        controls.addWidget(QtWidgets.QLabel("Spot update interval:"))
        self.interval_combo = QtWidgets.QComboBox()
        for sec in config.SPOT_UPDATE_INTERVALS_SEC:
            self.interval_combo.addItem(f"{sec}s", sec)
        default_idx = config.SPOT_UPDATE_INTERVALS_SEC.index(config.DEFAULT_SPOT_UPDATE_INTERVAL_SEC)
        self.interval_combo.setCurrentIndex(default_idx)
        controls.addWidget(self.interval_combo)

        controls.addSpacing(20)
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
            os.path.join(config.PNL_DATA_DIR, "futures_pnl.json"), label="Today's P&L"
        )
        controls.addWidget(self.pnl_tracker)
        root.addLayout(controls)

        # --- spot price header -----------------------------------------------
        price_row = QtWidgets.QHBoxLayout()
        self.price_label = QtWidgets.QLabel("—")
        self.price_label.setStyleSheet("font-size: 32px; font-weight: 800;")
        self.change_label = QtWidgets.QLabel("")
        self.change_label.setStyleSheet("font-size: 14px;")
        self.bid_ask_label = QtWidgets.QLabel("")
        self.bid_ask_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        price_col = QtWidgets.QVBoxLayout()
        price_col.addWidget(self.price_label)
        price_col.addWidget(self.bid_ask_label)
        price_row.addLayout(price_col)
        price_row.addWidget(self.change_label)
        price_row.addStretch()
        self.rti_status_label = QtWidgets.QLabel("")
        self.rti_status_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        price_row.addWidget(self.rti_status_label)
        root.addLayout(price_row)

        # --- main split: chart | signal panel ---------------------------------
        split = QtWidgets.QSplitter()
        self.chart = ChartWidget(decimal_threshold=config.CRYPTO_DECIMAL_THRESHOLD)
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
        self.signal_panel = SignalPanel(title_left="Target", chart=self.chart, decimal_threshold=config.CRYPTO_DECIMAL_THRESHOLD)
        panel_container = QtWidgets.QWidget()
        panel_container.setMinimumWidth(360)
        pc_layout = QtWidgets.QVBoxLayout(panel_container)
        pc_layout.setContentsMargins(0, 0, 0, 0)
        pc_layout.addWidget(self.signal_panel)
        split.addWidget(panel_container)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, stretch=1)

        # --- timers -------------------------------------------------------
        self.spot_timer = QtCore.QTimer(self)
        self.spot_timer.timeout.connect(self._poll_spot)

        self.signal_timer = QtCore.QTimer(self)
        self.signal_timer.timeout.connect(self._refresh_chart_and_signal)
        self.signal_timer.setInterval(config.CRYPTO_SIGNAL_REFRESH_SEC * 1000)

        self.rti_timer = QtCore.QTimer(self)
        self.rti_timer.timeout.connect(self._rti_tick)
        self.rti_timer.setInterval(1000)

        self.symbol_combo.currentTextChanged.connect(self._on_symbol_changed)
        self.interval_combo.currentIndexChanged.connect(self._on_interval_changed)

        self._on_interval_changed()
        self._poll_spot()
        self._refresh_chart_and_signal()
        self.signal_timer.start()
        self.rti_timer.start()

    # -- symbol / interval changes -----------------------------------------
    def _on_symbol_changed(self):
        self.signal_panel.clear_manual_target()
        self.rti_tracker = RTITracker(lambda now: next_clock_boundary(now, config.FUTURES_HORIZON_MINUTES))
        self._frozen_result = None
        self._frozen_target_time = None
        self._frozen_target_price = None
        self._frozen_entry = None
        self._frozen_stop = None
        self._frozen_tp = None
        self.rti_status_label.setText("")
        self._poll_spot()
        self._refresh_chart_and_signal()

    def _on_interval_changed(self):
        sec = self.interval_combo.currentData()
        self.spot_timer.setInterval(sec * 1000)
        if not self.spot_timer.isActive():
            self.spot_timer.start()

    # -- RTI settlement-style target sampling --------------------------------
    def _rti_tick(self):
        symbol = self.symbol_combo.currentText()
        now = datetime.now(timezone.utc)

        avg, boundary = self.rti_tracker.tick(now)
        if avg is not None:
            self._finalize_frozen_target(boundary, avg)

        if self.rti_tracker.should_sample(now):
            collecting_boundary = self.rti_tracker.collecting_boundary
            worker = FetchWorker(crypto_source.fetch_spot_price, symbol)
            worker.result.connect(
                lambda data, sym=symbol, b=collecting_boundary: self._on_rti_sample(sym, b, data)
            )
            worker.error.connect(lambda msg: None)  # a missed sample just shrinks this window's average
            self._workers.append(worker)
            worker.finished.connect(lambda: self._cleanup_worker(worker))
            worker.start()
            remaining = int(max((self.rti_tracker.collecting_boundary - now).total_seconds(), 0))
            self.rti_status_label.setText(
                f"Collecting RTI settlement sample: {self.rti_tracker.samples_collected}/60 "
                f"({remaining}s to {collecting_boundary.astimezone():%H:%M:%S})"
            )
        else:
            self.rti_status_label.setText("")

    def _on_rti_sample(self, symbol, for_boundary, data):
        if symbol != self.symbol_combo.currentText():
            return
        price = data.get("price")
        if price is None:
            return
        self.rti_tracker.record_sample(price, for_boundary=for_boundary)

    def _finalize_frozen_target(self, boundary, avg_price):
        if avg_price is None:
            return  # every sample this window failed to fetch -- keep prior frozen values
        if self._latest_result is None:
            return  # no analysis has completed yet -- nothing to snapshot
        # Re-anchor entry/stop/TP to the newly-averaged settlement price,
        # preserving the same ATR-based distances the most recent analysis
        # computed, so the trade plan stays internally consistent.
        stop_distance = abs(self._latest_result.suggested_stop - self._latest_result.last_price)
        tp_distance = abs(self._latest_result.suggested_take_profit - self._latest_result.last_price)
        direction = self._latest_result.direction

        self._frozen_target_time = boundary
        self._frozen_target_price = avg_price
        self._frozen_entry = avg_price
        if direction == "UP":
            self._frozen_stop = round(avg_price - stop_distance, 6)
            self._frozen_tp = round(avg_price + tp_distance, 6)
        else:
            self._frozen_stop = round(avg_price + stop_distance, 6)
            self._frozen_tp = round(avg_price - tp_distance, 6)

        # Freeze the WHOLE panel together: take the most recent analysis
        # (confidence/bullish%/breakout odds/signals list, at most ~60s old)
        # and overwrite just the price levels with this window's RTI
        # average, then display that as a single consistent snapshot that
        # holds until the next boundary.
        frozen = copy.copy(self._latest_result)
        frozen.target_time = self._frozen_target_time
        frozen.target_price = self._frozen_target_price
        frozen.suggested_entry = self._frozen_entry
        frozen.suggested_stop = self._frozen_stop
        frozen.suggested_take_profit = self._frozen_tp
        self._frozen_result = frozen

        # Refresh the chart's right-edge boundary immediately rather than
        # waiting for the next 60s cycle, so the extended range matches the
        # new window right away.
        if self._latest_ohlcv is not None:
            right_edge_x = (boundary - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
            self.chart.update_data(self._latest_ohlcv, right_edge_x=right_edge_x)
        self._display_result(frozen)

    def _display_result(self, result):
        target_label = "Target"
        if result.target_time is not None:
            target_label = f"Target {result.target_time.astimezone():%H:%M}"
        self.chart.set_reference_lines({
            "entry": (result.suggested_entry, "#ffca28", "Entry"),
            "take_profit": (result.suggested_take_profit, BULLISH_COLOR, "TP"),
            "stop": (result.suggested_stop, BEARISH_COLOR, "Stop"),
            "target": (result.target_price, "#42a5f5", target_label, 0.78),
        })
        self.signal_panel.update_result(result)

    # -- spot price polling -------------------------------------------------
    def _poll_spot(self):
        symbol = self.symbol_combo.currentText()
        worker = FetchWorker(crypto_source.fetch_spot_price, symbol)
        worker.result.connect(lambda data, sym=symbol: self._on_spot_result(sym, data))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _on_spot_result(self, symbol, data):
        if symbol != self.symbol_combo.currentText():
            return  # stale response from a symbol the user already changed away from
        price = data.get("price")
        if price is None:
            return
        self.price_label.setText(f"{price:,.4f}" if price < config.CRYPTO_DECIMAL_THRESHOLD else f"{price:,.2f}")
        self.signal_panel.set_current_price(price)
        pct = data.get("pct_change_24h")
        if pct is not None:
            color = BULLISH_COLOR if pct >= 0 else BEARISH_COLOR
            self.change_label.setText(f"{pct:+.2f}% (24h)")
            self.change_label.setStyleSheet(f"font-size: 14px; color: {color}; font-weight: 600;")
        bid, ask = data.get("bid"), data.get("ask")
        if bid and ask:
            if bid < config.CRYPTO_DECIMAL_THRESHOLD:
                self.bid_ask_label.setText(f"Bid {bid:,.4f}   Ask {ask:,.4f}")
            else:
                self.bid_ask_label.setText(f"Bid {bid:,.2f}   Ask {ask:,.2f}")
        ts = data.get("timestamp")
        self.status_label.setText(f"Last spot update: {ts:%H:%M:%S}" if ts is not None else "")

    # -- chart + signal engine refresh --------------------------------------
    def _refresh_chart_and_signal(self):
        symbol = self.symbol_combo.currentText()
        worker = FetchWorker(self._fetch_and_analyze, symbol)
        worker.result.connect(lambda payload, sym=symbol: self._on_chart_result(sym, payload))
        worker.error.connect(self._on_error)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    @staticmethod
    def _fetch_and_analyze(symbol: str):
        df = crypto_source.fetch_ohlcv(
            symbol,
            timeframe=config.CRYPTO_CHART_TIMEFRAME,
            limit=config.CRYPTO_CHART_LOOKBACK_BARS,
        )
        df_ind = compute_all(df)
        now = datetime.now(timezone.utc)
        target_time = next_clock_boundary(now, config.FUTURES_HORIZON_MINUTES)
        horizon_minutes = max((target_time - now).total_seconds() / 60.0, 0.01)
        result = analyze(
            df_ind, horizon_minutes=horizon_minutes, target_time=target_time,
            decimal_threshold=config.CRYPTO_DECIMAL_THRESHOLD, ml_model_name=config.ML_CRYPTO_MODEL_NAME,
            symbol=symbol,
        )
        return df_ind, result

    def _on_chart_result(self, symbol, payload):
        if symbol != self.symbol_combo.currentText():
            return
        df_ind, result = payload
        self._latest_ohlcv = df_ind
        self._latest_result = result  # used by _finalize_frozen_target to build the next frozen snapshot

        # The chart's candles/volume/overlays always stay live -- only the
        # signal panel (confidence, bullish %, signals, breakout odds) and
        # the trade-plan price levels freeze per 15-min window (see
        # _finalize_frozen_target / _display_result).
        right_edge_x = None
        boundary_for_edge = self._frozen_target_time or result.target_time
        if boundary_for_edge is not None:
            right_edge_x = (boundary_for_edge - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
        self.chart.update_data(df_ind, right_edge_x=right_edge_x)

        if self._frozen_result is None:
            # No window has closed yet (e.g. right after launch or a symbol
            # change) -- show this live analysis as a temporary placeholder
            # so the panel isn't empty. target_price still shows the
            # observed price, never the AI-projected value analyze()
            # computes internally, consistent with the frozen behavior.
            result.target_price = result.last_price
            self._display_result(result)

    # -- shared error handling / cleanup ------------------------------------
    def _on_error(self, message: str):
        self.status_label.setText(f"⚠ {message}")
        self.status_label.setStyleSheet(f"color: {BEARISH_COLOR}; font-size: 11px;")

    def _cleanup_worker(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
