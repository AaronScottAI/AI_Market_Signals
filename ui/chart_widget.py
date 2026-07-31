"""
Reusable candlestick chart widget (pyqtgraph has no built-in candlestick
item, so this implements one) with:
  - EMA / Bollinger / VWAP overlays (toggleable via IndicatorToggleBar)
  - a volume subplot
  - horizontal reference lines for entry / target / stop-loss
    (toggleable via ReferenceLineToggleBar)
  - a time axis that renders real dates/times
  - a mouse-hover readout (horizontal price line + OHLCV text) with no
    vertical line, so nothing cuts across the candles
  - by default, auto-fits to show all data (and follows a shifting
    settlement boundary) on every update_data() call; the moment you
    manually zoom or pan, that stops -- your view holds steady across
    future data refreshes until you click "Reset View" (see
    ChartModeToggle) or switch symbols/timeframe
"""
from __future__ import annotations
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg


class CandlestickItem(pg.GraphicsObject):
    def __init__(self, df: pd.DataFrame):
        super().__init__()
        self.df = df
        self.picture = QtGui.QPicture()
        self._generate_picture()

    def _generate_picture(self):
        self.picture = QtGui.QPicture()
        painter = QtGui.QPainter(self.picture)
        if len(self.df) == 0:
            painter.end()
            return

        xs = self.df["x"].to_numpy()
        if len(xs) > 1:
            width = float(np.median(np.diff(xs))) * 0.6
        else:
            width = 0.6

        bull_pen = pg.mkPen("#26a69a", width=1)
        bull_brush = pg.mkBrush("#26a69a")
        bear_pen = pg.mkPen("#ef5350", width=1)
        bear_brush = pg.mkBrush("#ef5350")

        for row in self.df.itertuples():
            is_bull = row.close >= row.open
            painter.setPen(bull_pen if is_bull else bear_pen)
            painter.setBrush(bull_brush if is_bull else bear_brush)
            # wick
            painter.drawLine(QtCore.QPointF(row.x, row.low), QtCore.QPointF(row.x, row.high))
            # body
            top, bottom = max(row.open, row.close), min(row.open, row.close)
            painter.drawRect(QtCore.QRectF(row.x - width / 2, bottom, width, max(top - bottom, 1e-9)))
        painter.end()

    def set_data(self, df: pd.DataFrame):
        self.df = df
        self._generate_picture()
        self.prepareGeometryChange()
        self.informViewBoundsChanged()
        self.update()

    def paint(self, painter, *args):
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        if len(self.df) == 0:
            return QtCore.QRectF()
        x0, x1 = self.df["x"].min(), self.df["x"].max()
        y0, y1 = self.df["low"].min(), self.df["high"].max()
        return QtCore.QRectF(x0 - 1, y0, (x1 - x0) + 2, (y1 - y0) or 1)


class ChartWidget(pg.GraphicsLayoutWidget):
    """Price chart (candles + overlays + reference lines) with a linked
    volume subplot beneath it."""

    hover_info = QtCore.Signal(str)   # emits a formatted time/OHLC/cursor readout
    hover_cleared = QtCore.Signal()    # emitted when the mouse leaves the chart

    OVERLAY_COLORS = {
        "ema_fast": "#42a5f5",
        "ema_slow": "#ab47bc",
        "bb_upper": "#78909c",
        "bb_lower": "#78909c",
        "vwap": "#ffca28",
    }

    def __init__(self, parent=None, decimal_threshold: float = 5):
        super().__init__(parent)
        self.decimal_threshold = decimal_threshold
        self.setBackground("#0d1117")

        axis = pg.DateAxisItem(orientation="bottom")
        self.price_plot = self.addPlot(row=0, col=0, axisItems={"bottom": axis})
        self.price_plot.showGrid(x=False, y=True, alpha=0.15)
        self.price_plot.setLabel("left", "Price")
        self.nextRow()
        vaxis = pg.DateAxisItem(orientation="bottom")
        self.volume_plot = self.addPlot(row=1, col=0, axisItems={"bottom": vaxis})
        self.volume_plot.showGrid(x=False, y=True, alpha=0.1)
        self.volume_plot.setMaximumHeight(120)
        self.volume_plot.setLabel("left", "Vol")
        self.volume_plot.setXLink(self.price_plot)

        self.candle_item = CandlestickItem(pd.DataFrame(columns=["x", "open", "high", "low", "close"]))
        self.price_plot.addItem(self.candle_item)

        self.line_item = self.price_plot.plot(pen=pg.mkPen("#58a6ff", width=1.8))
        self.line_item.setVisible(False)
        self.chart_mode = "candles"

        self.volume_bars = pg.BarGraphItem(x=[], height=[], width=0.6, brush="#37474f")
        self.volume_plot.addItem(self.volume_bars)

        self._overlay_curves: dict[str, pg.PlotDataItem] = {}
        self._overlay_enabled: dict[str, bool] = {}
        self._ref_lines: dict[str, pg.InfiniteLine] = {}
        self._ref_line_enabled: dict[str, bool] = {}
        self._current_plot_df: pd.DataFrame | None = None

        # Once the user manually zooms or pans (mouse wheel / drag), stop
        # auto-fitting the view on every update_data() call so their chosen
        # view survives data refreshes. sigRangeChangedManually only fires
        # for genuine mouse interaction, never for our own programmatic
        # setXRange()/autoRange() calls below -- that distinction is exactly
        # what lets "follow new data by default" and "stay put once you've
        # zoomed" coexist.
        self._user_has_zoomed = False
        self.price_plot.getViewBox().sigRangeChangedManually.connect(self._on_user_zoomed)

        # --- hover readout: horizontal price line only (no vertical line) ---
        crosshair_pen = pg.mkPen("#8b949e", width=1, style=QtCore.Qt.DashLine)
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=crosshair_pen)
        self.price_plot.addItem(self._hline, ignoreBounds=True)
        self._hline.hide()

        self.scene().sigMouseMoved.connect(self._on_mouse_moved)

    def update_data(self, df: pd.DataFrame, overlays: dict[str, str] | None = None, right_edge_x: float | None = None):
        """df must have: timestamp, open, high, low, close, volume, plus any
        overlay columns named in `overlays` (defaults to OVERLAY_COLORS keys
        present in df). `right_edge_x` (seconds-since-epoch, optional) lets
        the caller reserve visible space out to a future point in time --
        e.g. the futures tab passes the next 15-min settlement boundary so
        the chart's right edge doesn't stop right at the last candle."""
        if df.empty:
            return
        plot_df = df.copy()
        # Robust across pandas versions/resolutions (ns/us/ms/s datetime64) --
        # do NOT use .astype("int64") here, its meaning depends on the
        # Series' internal time unit and differs across pandas versions.
        plot_df["x"] = (plot_df["timestamp"] - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(seconds=1)
        self.candle_item.set_data(plot_df[["x", "open", "high", "low", "close"]])
        self.line_item.setData(plot_df["x"].to_numpy(), plot_df["close"].to_numpy())

        is_up = (plot_df["close"] >= plot_df["open"]).to_numpy()
        colors = np.where(is_up, "#26a69a", "#ef5350")
        brushes = [pg.mkBrush(c) for c in colors]
        median_gap = plot_df["x"].diff().median()
        bar_width = 0.6 * median_gap if pd.notna(median_gap) and median_gap > 0 else 0.6
        self.volume_bars.setOpts(x=plot_df["x"].to_numpy(), height=plot_df["volume"].to_numpy(),
                                   width=bar_width, brushes=brushes)

        overlay_map = overlays or self.OVERLAY_COLORS
        for name, color in overlay_map.items():
            if name not in self._overlay_curves:
                pen_style = QtCore.Qt.DashLine if name in ("bb_upper", "bb_lower") else QtCore.Qt.SolidLine
                curve = self.price_plot.plot(pen=pg.mkPen(color, width=1.3, style=pen_style))
                curve.setVisible(self._overlay_enabled.get(name, True))
                self._overlay_curves[name] = curve
            if name not in plot_df.columns:
                continue
            series = plot_df[["x", name]].dropna()
            if series.empty:
                continue
            self._overlay_curves[name].setData(series["x"].to_numpy(), series[name].to_numpy())

        x_min = plot_df["x"].min()
        x_max = plot_df["x"].max()
        if right_edge_x is not None:
            x_max = max(x_max, right_edge_x)

        if not self._user_has_zoomed:
            self.price_plot.enableAutoRange(axis="y")
            self.price_plot.setXRange(x_min, x_max, padding=0.02)
        # else: leave the current view range exactly as the user left it --
        # don't yank them back to "fit everything" just because new data
        # (or a shifted settlement boundary) arrived.

        self._current_plot_df = plot_df[["x", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

    def _on_user_zoomed(self, *_args):
        self._user_has_zoomed = True
        self.price_plot.enableAutoRange(x=False, y=False)

    def reset_view(self):
        """Goes back to auto-fitting the full visible data range on every
        update, exactly like before any manual zoom/pan -- lets you return
        to the default live-following view without needing to switch
        symbols or restart the app."""
        self._user_has_zoomed = False
        if self._current_plot_df is not None and not self._current_plot_df.empty:
            self.price_plot.enableAutoRange(axis="y")
            x_min = self._current_plot_df["x"].min()
            x_max = self._current_plot_df["x"].max()
            self.price_plot.setXRange(x_min, x_max, padding=0.02)

    def set_chart_mode(self, mode: str):
        """mode: 'candles' or 'line'. Both representations are kept up to
        date on every update_data() call, so switching is instant."""
        self.chart_mode = mode
        self.candle_item.setVisible(mode == "candles")
        self.line_item.setVisible(mode == "line")

    def set_overlay_visible(self, key: str, visible: bool):
        """Show/hide a single overlay curve by its data-column key (e.g.
        'ema_fast', 'bb_upper', 'vwap'). Safe to call before any data has
        been loaded -- the preference is remembered and applied once the
        curve is created."""
        self._overlay_enabled[key] = visible
        curve = self._overlay_curves.get(key)
        if curve is not None:
            curve.setVisible(visible)

    def set_reference_lines(self, levels: dict[str, tuple]):
        """levels: {key: (price, color, label)} or {key: (price, color, label, position)}
        `position` (0-1, default 0.97) is how far across the plot width the
        label sits -- pass a smaller value for longer label text so it has
        room to render without being clipped by the plot's right edge."""
        for key, spec in levels.items():
            price, color, label = spec[0], spec[1], spec[2]
            position = spec[3] if len(spec) > 3 else 0.97
            if price is None:
                continue
            if key in self._ref_lines:
                self._ref_lines[key].setPos(price)
                self._ref_lines[key].setPen(pg.mkPen(color, width=1.2, style=QtCore.Qt.DashLine))
            else:
                line = pg.InfiniteLine(
                    pos=price, angle=0, movable=False,
                    pen=pg.mkPen(color, width=1.2, style=QtCore.Qt.DashLine),
                    label=label, labelOpts={"color": color, "position": position},
                )
                line.setVisible(self._ref_line_enabled.get(key, True))
                self.price_plot.addItem(line)
                self._ref_lines[key] = line

    def set_reference_line_visible(self, key: str, visible: bool):
        """Show/hide a single reference line (e.g. 'stop', 'take_profit',
        'target', 'manual_target'). Safe to call before the line exists --
        the preference is remembered and applied once it's created."""
        self._ref_line_enabled[key] = visible
        line = self._ref_lines.get(key)
        if line is not None:
            line.setVisible(visible)

    def clear_reference_lines(self):
        for line in self._ref_lines.values():
            self.price_plot.removeItem(line)
        self._ref_lines.clear()

    def remove_reference_line(self, key: str):
        line = self._ref_lines.pop(key, None)
        if line is not None:
            self.price_plot.removeItem(line)

    # -- hover readout ---------------------------------------------------
    def _on_mouse_moved(self, scene_pos):
        price_rect = self.price_plot.sceneBoundingRect()
        volume_rect = self.volume_plot.sceneBoundingRect()
        if not (price_rect.contains(scene_pos) or volume_rect.contains(scene_pos)):
            self._hide_crosshair()
            return

        view_pos = self.price_plot.vb.mapSceneToView(scene_pos)
        x = view_pos.x()

        if price_rect.contains(scene_pos):
            self._hline.setPos(view_pos.y())
            self._hline.show()
        else:
            self._hline.hide()

        if self._current_plot_df is None or self._current_plot_df.empty:
            self.hover_cleared.emit()
            return

        xs = self._current_plot_df["x"].to_numpy()
        idx = int(np.argmin(np.abs(xs - x)))
        row = self._current_plot_df.iloc[idx]

        try:
            dt = datetime.fromtimestamp(float(row["x"]), tz=timezone.utc).astimezone()
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError):
            time_str = "--"

        decimals = 4 if row["close"] < self.decimal_threshold else 2
        text = (
            f"{time_str}\n"
            f"O {row['open']:,.{decimals}f}   H {row['high']:,.{decimals}f}\n"
            f"L {row['low']:,.{decimals}f}   C {row['close']:,.{decimals}f}\n"
            f"Vol {row['volume']:,.0f}   Cursor: {view_pos.y():,.{decimals}f}"
        )
        self.hover_info.emit(text)

    def _hide_crosshair(self):
        self._hline.hide()
        self.hover_cleared.emit()

    def leaveEvent(self, event):
        self._hide_crosshair()
        super().leaveEvent(event)


# Shared by IndicatorToggleBar and ReferenceLineToggleBar -- a bit larger
# than the Qt default in both the clickable box and the label text.
_CHECKBOX_STYLE = """
    QCheckBox { color: #e6edf3; font-size: 13px; spacing: 7px; }
    QCheckBox::indicator { width: 18px; height: 18px; }
"""


class IndicatorToggleBar(QtWidgets.QWidget):
    """A row of checkboxes that show/hide chart overlay indicators.
    One checkbox can control more than one underlying curve (e.g. a single
    'Bollinger Bands' checkbox toggles both the upper and lower band)."""

    # (checkbox label, ChartWidget overlay keys it controls, default checked)
    TOGGLES = [
        ("EMA 9", ["ema_fast"], True),
        ("EMA 21", ["ema_slow"], True),
        ("Bollinger Bands", ["bb_upper", "bb_lower"], True),
        ("VWAP", ["vwap"], True),
    ]

    def __init__(self, chart: ChartWidget, parent=None):
        super().__init__(parent)
        self.chart = chart
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(14)

        caption = QtWidgets.QLabel("Indicators:")
        caption.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(caption)

        for text, keys, default_checked in self.TOGGLES:
            checkbox = QtWidgets.QCheckBox(text)
            checkbox.setChecked(default_checked)
            checkbox.setStyleSheet(_CHECKBOX_STYLE)
            checkbox.toggled.connect(lambda checked, ks=keys: self._on_toggle(ks, checked))
            layout.addWidget(checkbox)
            # apply the initial (default_checked) state immediately so the
            # chart's internal visibility map matches what's shown on screen
            self._on_toggle(keys, default_checked)

        layout.addStretch()

    def _on_toggle(self, keys: list[str], checked: bool):
        for key in keys:
            self.chart.set_overlay_visible(key, checked)


class ReferenceLineToggleBar(QtWidgets.QWidget):
    """Checkboxes to show/hide the chart's horizontal reference lines:
    take-profit, stop-loss, the algorithm's target, and any manually-set
    target. Entry is left always-on since it just marks the current price."""

    # (checkbox label, ChartWidget reference-line key, default checked)
    TOGGLES = [
        ("TP", "take_profit", True),
        ("Stop", "stop", True),
        ("Target", "target", True),
        ("My Target", "manual_target", True),
    ]

    def __init__(self, chart: ChartWidget, parent=None):
        super().__init__(parent)
        self.chart = chart
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(14)

        caption = QtWidgets.QLabel("Lines:")
        caption.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(caption)

        for text, key, default_checked in self.TOGGLES:
            checkbox = QtWidgets.QCheckBox(text)
            checkbox.setChecked(default_checked)
            checkbox.setStyleSheet(_CHECKBOX_STYLE)
            checkbox.toggled.connect(lambda checked, k=key: self.chart.set_reference_line_visible(k, checked))
            layout.addWidget(checkbox)
            # apply the initial state immediately so it matches the checkbox
            self.chart.set_reference_line_visible(key, default_checked)

        layout.addStretch()


class ChartModeToggle(QtWidgets.QWidget):
    """Segmented-style toggle between candlestick and line chart rendering."""

    _BUTTON_STYLE = """
        QPushButton {
            background: #161b22; color: #8b949e; border: 1px solid #30363d;
            border-radius: 4px; padding: 4px 14px; font-size: 12px;
        }
        QPushButton:checked {
            background: #21262d; color: #e6edf3; border: 1px solid #58a6ff; font-weight: 600;
        }
        QPushButton:hover { background: #21262d; }
    """

    def __init__(self, chart: ChartWidget, parent=None):
        super().__init__(parent)
        self.chart = chart
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)

        caption = QtWidgets.QLabel("Chart type:")
        caption.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(caption)

        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)

        self.candles_btn = QtWidgets.QPushButton("Candles")
        self.candles_btn.setCheckable(True)
        self.candles_btn.setChecked(True)
        self.candles_btn.setStyleSheet(self._BUTTON_STYLE)

        self.line_btn = QtWidgets.QPushButton("Line")
        self.line_btn.setCheckable(True)
        self.line_btn.setStyleSheet(self._BUTTON_STYLE)

        self._group.addButton(self.candles_btn)
        self._group.addButton(self.line_btn)
        layout.addWidget(self.candles_btn)
        layout.addWidget(self.line_btn)

        self.reset_view_btn = QtWidgets.QPushButton("Reset View")
        self.reset_view_btn.setStyleSheet(
            "QPushButton { background: #161b22; color: #8b949e; border: 1px solid #30363d; "
            "border-radius: 4px; padding: 4px 14px; font-size: 12px; } "
            "QPushButton:hover { background: #21262d; color: #e6edf3; }"
        )
        self.reset_view_btn.setToolTip(
            "Zooming or panning the chart freezes your view so live updates don't reset it. "
            "Click here to go back to auto-fitting the full chart."
        )
        self.reset_view_btn.clicked.connect(self.chart.reset_view)
        layout.addWidget(self.reset_view_btn)

        self.candles_btn.toggled.connect(self._on_toggle)
        self.chart.set_chart_mode("candles")

    def _on_toggle(self, candles_checked: bool):
        self.chart.set_chart_mode("candles" if candles_checked else "line")
