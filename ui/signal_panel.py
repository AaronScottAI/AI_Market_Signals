"""
Reusable panel that renders a SignalResult: direction call, confidence,
bullish/bearish split, breakout/breakdown probability, the list of
individual signals (firing or not), suggested price levels, and a rolling
history sparkline of bullish % over time (the "at each minute interval"
view the futures/options tabs both want).
"""
from __future__ import annotations
from collections import deque

from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from analysis.signal_engine import SignalResult, SignalFlag

BULLISH_COLOR = "#26a69a"
BEARISH_COLOR = "#ef5350"
NEUTRAL_COLOR = "#78909c"
BG = "#0d1117"
PANEL_BG = "#161b22"
TEXT = "#e6edf3"
SUBTEXT = "#8b949e"


class PercentSplitBar(QtWidgets.QWidget):
    """Horizontal stacked bar: bullish % (green) vs bearish % (red)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(28)
        self.bullish_pct = 50.0
        self.bearish_pct = 50.0

    def set_values(self, bullish_pct: float, bearish_pct: float):
        self.bullish_pct = bullish_pct
        self.bearish_pct = bearish_pct
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()
        radius = 6
        bull_width = int(rect.width() * self.bullish_pct / 100.0)

        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(rect), radius, radius)
        painter.setClipPath(path)

        painter.fillRect(0, 0, bull_width, rect.height(), QtGui.QColor(BULLISH_COLOR))
        painter.fillRect(bull_width, 0, rect.width() - bull_width, rect.height(), QtGui.QColor(BEARISH_COLOR))

        painter.setPen(QtGui.QColor("#ffffff"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(QtCore.QRect(0, 0, rect.width(), rect.height()),
                          QtCore.Qt.AlignCenter,
                          f"Bullish {self.bullish_pct:.0f}%   |   Bearish {self.bearish_pct:.0f}%")


class SignalListWidget(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QListWidget {{ background: {PANEL_BG}; border: none; color: {TEXT}; }}
            QListWidget::item {{ padding: 4px 2px; }}
        """)

    def set_flags(self, flags: list[SignalFlag]):
        self.clear()
        # active signals first, then neutral/inactive
        for flag in sorted(flags, key=lambda f: not f.active):
            color = {"bullish": BULLISH_COLOR, "bearish": BEARISH_COLOR}.get(flag.direction, NEUTRAL_COLOR)
            dot = "●" if flag.active else "○"
            item = QtWidgets.QListWidgetItem(f"{dot}  {flag.label} — {flag.detail}")
            item.setForeground(QtGui.QColor(color if flag.active else SUBTEXT))
            if flag.active:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.addItem(item)


class HistorySparkline(pg.PlotWidget):
    """Rolling line chart of bullish % over the last N signal refreshes."""

    def __init__(self, maxlen=60, parent=None):
        super().__init__(parent)
        self.setBackground(PANEL_BG)
        self.showGrid(x=False, y=True, alpha=0.15)
        self.setMaximumHeight(90)
        self.getPlotItem().hideAxis("bottom")
        self.getAxis("left").setTicks([[(0, "0%"), (50, "50%"), (100, "100%")]])
        self.setYRange(0, 100, padding=0.05)
        self._history = deque(maxlen=maxlen)
        self._curve = self.plot(pen=pg.mkPen(BULLISH_COLOR, width=2))
        self._mid_line = pg.InfiniteLine(pos=50, angle=0, pen=pg.mkPen(NEUTRAL_COLOR, width=1, style=QtCore.Qt.DotLine))
        self.addItem(self._mid_line)

    def push(self, bullish_pct: float):
        self._history.append(bullish_pct)
        xs = list(range(len(self._history)))
        ys = list(self._history)
        self._curve.setData(xs, ys)

    def values(self):
        return list(self._history)


class SignalPanel(QtWidgets.QWidget):
    """Full recommendation panel: ML prediction (if trained), direction/
    confidence header, split bar, breakout gauges, price levels, signal
    list, and history sparkline."""

    def __init__(self, title_left="Target", chart=None, decimal_threshold: float = 5, parent=None):
        super().__init__(parent)
        self.chart = chart
        self.decimal_threshold = decimal_threshold
        self.setStyleSheet(f"background: {BG}; color: {TEXT};")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        # --- ML model prediction (prominent, above everything else) --------
        # Hidden entirely unless a trained model produced a live prediction.
        self.ml_caption_label = QtWidgets.QLabel("ML Model Prediction")
        self.ml_caption_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        self.ml_caption_label.setVisible(False)
        layout.addWidget(self.ml_caption_label)

        self.ml_prediction_label = QtWidgets.QLabel("")
        self.ml_prediction_label.setStyleSheet("font-size: 19px; font-weight: 800;")
        self.ml_prediction_label.setVisible(False)
        layout.addWidget(self.ml_prediction_label)

        # --- direction header ---
        header = QtWidgets.QHBoxLayout()
        self.direction_label = QtWidgets.QLabel("—")
        self.direction_label.setStyleSheet("font-size: 26px; font-weight: 800;")
        self.confidence_label = QtWidgets.QLabel("")
        self.confidence_label.setStyleSheet(f"font-size: 14px; color: {SUBTEXT};")
        header.addWidget(self.direction_label)
        header.addStretch()
        header.addWidget(self.confidence_label)
        layout.addLayout(header)

        # --- bullish/bearish split ---
        self.split_bar = PercentSplitBar()
        layout.addWidget(self.split_bar)

        # --- history sparkline ---
        spark_label = QtWidgets.QLabel("Bullish % history (per refresh interval)")
        spark_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        layout.addWidget(spark_label)
        self.sparkline = HistorySparkline()
        layout.addWidget(self.sparkline)

        # --- breakout / breakdown ---
        bo_row = QtWidgets.QHBoxLayout()
        self.breakout_label = QtWidgets.QLabel("Breakout: —")
        self.breakout_label.setStyleSheet(f"color: {BULLISH_COLOR}; font-weight: 600;")
        self.breakdown_label = QtWidgets.QLabel("Breakdown: —")
        self.breakdown_label.setStyleSheet(f"color: {BEARISH_COLOR}; font-weight: 600;")
        bo_row.addWidget(self.breakout_label)
        bo_row.addStretch()
        bo_row.addWidget(self.breakdown_label)
        layout.addLayout(bo_row)

        # --- price levels grid ---
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(18)
        self._level_labels = {}
        self._caption_labels = {}
        for i, key in enumerate(["last_price", "target_price", "suggested_entry",
                                    "suggested_take_profit", "suggested_stop"]):
            caption = {
                "last_price": "Current",
                "target_price": title_left,
                "suggested_entry": "Suggested Entry",
                "suggested_take_profit": "Take-Profit",
                "suggested_stop": "Stop-Loss",
            }[key]
            cap_lbl = QtWidgets.QLabel(caption)
            cap_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
            val_lbl = QtWidgets.QLabel("—")
            val_lbl.setStyleSheet("font-size: 15px; font-weight: 700;")
            grid.addWidget(cap_lbl, 0, i)
            grid.addWidget(val_lbl, 1, i)
            self._level_labels[key] = val_lbl
            self._caption_labels[key] = cap_lbl
        layout.addLayout(grid)

        # --- manual target override (sanity check / error-prevention) -------
        if self.chart is not None:
            manual_row = QtWidgets.QHBoxLayout()
            manual_label = QtWidgets.QLabel("Manual target:")
            manual_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
            self.manual_target_edit = QtWidgets.QLineEdit()
            self.manual_target_edit.setPlaceholderText("type a price")
            self.manual_target_edit.setMaximumWidth(90)
            manual_set_btn = QtWidgets.QPushButton("Set")
            manual_clear_btn = QtWidgets.QPushButton("Clear")
            manual_row.addWidget(manual_label)
            manual_row.addWidget(self.manual_target_edit)
            manual_row.addWidget(manual_set_btn)
            manual_row.addWidget(manual_clear_btn)
            manual_row.addStretch()
            layout.addLayout(manual_row)

            manual_set_btn.clicked.connect(self._apply_manual_target)
            self.manual_target_edit.returnPressed.connect(self._apply_manual_target)
            manual_clear_btn.clicked.connect(self.clear_manual_target)

        # --- signals list ---
        sig_label = QtWidgets.QLabel("Signals forming")
        sig_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px; margin-top: 4px;")
        layout.addWidget(sig_label)
        self.signal_list = SignalListWidget()
        layout.addWidget(self.signal_list, stretch=1)

        # --- extra notes area (used by options tab for contract guidance) ---
        self.notes_label = QtWidgets.QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        layout.addWidget(self.notes_label)

    def set_current_price(self, price: float):
        """Updates just the 'Current' price cell, independent of
        update_result(). Wire this to the live spot-price feed so it keeps
        ticking even on tabs where the rest of the panel freezes per window."""
        self._level_labels["last_price"].setText(
            f"{price:,.4f}" if price < self.decimal_threshold else f"{price:,.2f}"
        )

    def update_result(self, result: SignalResult, extra_notes: str = ""):
        if result.ml_signal is not None and result.ml_probability_up is not None:
            ml_direction = "UP" if result.ml_probability_up >= 0.5 else "DOWN"
            ml_arrow = "▲" if ml_direction == "UP" else "▼"
            ml_color = BULLISH_COLOR if ml_direction == "UP" else BEARISH_COLOR
            self.ml_prediction_label.setText(
                f"{ml_arrow} ML Model: {ml_direction}   ({result.ml_probability_up * 100:.0f}% probability)"
            )
            self.ml_prediction_label.setStyleSheet(f"font-size: 19px; font-weight: 800; color: {ml_color};")
            self.ml_caption_label.setVisible(True)
            self.ml_prediction_label.setVisible(True)
        else:
            self.ml_caption_label.setVisible(False)
            self.ml_prediction_label.setVisible(False)

        color = BULLISH_COLOR if result.direction == "UP" else BEARISH_COLOR
        arrow = "▲" if result.direction == "UP" else "▼"
        self.direction_label.setText(f"{arrow} {result.direction}")
        self.direction_label.setStyleSheet(f"font-size: 26px; font-weight: 800; color: {color};")

        if result.target_time is not None:
            local_target = result.target_time.astimezone()
            mins_left = max(result.horizon_minutes, 0)
            self.confidence_label.setText(
                f"Confidence: {result.confidence_pct:.0f}%   ·   "
                f"Target: {local_target:%H:%M:%S}  (~{mins_left:.0f} min)"
            )
            self._caption_labels["target_price"].setText(f"Target ({local_target:%H:%M})")
        else:
            self.confidence_label.setText(
                f"Confidence: {result.confidence_pct:.0f}%   ·   Horizon: {result.horizon_minutes:.0f} min"
            )

        self.split_bar.set_values(result.bullish_pct, result.bearish_pct)
        self.sparkline.push(result.bullish_pct)

        self.breakout_label.setText(f"Breakout odds: {result.breakout_pct:.0f}%")
        self.breakdown_label.setText(f"Breakdown odds: {result.breakdown_pct:.0f}%")

        # NOTE: "Current" is intentionally NOT set from result.last_price here.
        # On tabs where the rest of the panel freezes per window (Crypto
        # Futures), last_price would freeze along with everything else,
        # defeating the point of "Current" -- it needs to keep updating
        # live so you can see it drift away from the frozen Target. See
        # set_current_price(), which is wired to the live spot-price feed.
        self._level_labels["target_price"].setText(f"{result.target_price:,.4f}" if result.target_price < self.decimal_threshold else f"{result.target_price:,.2f}")
        self._level_labels["suggested_entry"].setText(
            f"{result.suggested_entry:,.4f}" if result.suggested_entry < self.decimal_threshold else f"{result.suggested_entry:,.2f}"
        )
        tp_color = BULLISH_COLOR
        sl_color = BEARISH_COLOR
        self._level_labels["suggested_take_profit"].setText(
            f"{result.suggested_take_profit:,.4f}" if result.suggested_take_profit < self.decimal_threshold else f"{result.suggested_take_profit:,.2f}"
        )
        self._level_labels["suggested_take_profit"].setStyleSheet(f"font-size: 15px; font-weight: 700; color: {tp_color};")
        self._level_labels["suggested_stop"].setText(
            f"{result.suggested_stop:,.4f}" if result.suggested_stop < self.decimal_threshold else f"{result.suggested_stop:,.2f}"
        )
        self._level_labels["suggested_stop"].setStyleSheet(f"font-size: 15px; font-weight: 700; color: {sl_color};")

        self.signal_list.set_flags(result.signals)
        if extra_notes:
            self.notes_label.setText(extra_notes)

    def _apply_manual_target(self):
        text = self.manual_target_edit.text().strip()
        if not text:
            return
        try:
            price = float(text)
        except ValueError:
            self.manual_target_edit.setStyleSheet(f"border: 1px solid {BEARISH_COLOR};")
            return
        self.manual_target_edit.setStyleSheet("")
        if self.chart is not None:
            self.chart.set_reference_lines({
                "manual_target": (price, "#ffffff", "My Target", 0.55),
            })

    def clear_manual_target(self):
        if hasattr(self, "manual_target_edit"):
            self.manual_target_edit.clear()
            self.manual_target_edit.setStyleSheet("")
        if self.chart is not None:
            self.chart.remove_reference_line("manual_target")
