"""
Definitions / glossary tab. Pure reference content -- explains every
indicator, composite metric, and chart label used across both tabs, in
terms of how it actually influences the bullish/bearish call in THIS app
(not just a generic textbook definition).
"""
from __future__ import annotations
from PySide6 import QtCore, QtWidgets

from ui.signal_panel import BG, TEXT, SUBTEXT, BULLISH_COLOR, BEARISH_COLOR

ACCENT = "#58a6ff"

# (section title, [(term, weight_or_None, html_explanation), ...])
SECTIONS = [
    ("Trend & Momentum Indicators", [
        (
            "EMA 9 / EMA 21 &mdash; Short-term trend",
            "20%",
            "Exponential moving averages of the closing price over the last 9 and 21 bars. "
            "EMAs react faster to recent price than a simple average. When EMA9 sits "
            f"<b style='color:{BULLISH_COLOR}'>above</b> EMA21, short-term momentum is outrunning the "
            f"longer trend &mdash; bullish. When it's <b style='color:{BEARISH_COLOR}'>below</b>, bearish. "
            "This is the single most heavily-weighted signal in the composite score.",
        ),
        (
            "MACD &mdash; Moving Average Convergence Divergence",
            "18%",
            "The gap between a 12-bar and 26-bar EMA (the \"MACD line\"), compared against its own "
            "9-bar EMA (the \"signal line\"). MACD line "
            f"<b style='color:{BULLISH_COLOR}'>above</b> the signal line = momentum shifting bullish; "
            f"<b style='color:{BEARISH_COLOR}'>below</b> = shifting bearish. The size of the gap (the "
            "\"histogram\") shows how strong that shift is, not just its direction.",
        ),
        (
            "RSI &mdash; Relative Strength Index",
            "14%",
            "A 0&ndash;100 gauge of how fast and how far price has moved recently. "
            f"Above 70 = <b style='color:{BEARISH_COLOR}'>overbought</b> (often due for a pullback). "
            f"Below 30 = <b style='color:{BULLISH_COLOR}'>oversold</b> (often due for a bounce). "
            "30&ndash;70 is the neutral zone. Note RSI can stay \"overbought\" through a strong "
            "uptrend &mdash; that's a real mean-reversion warning, not a bug.",
        ),
        (
            "Stochastic Oscillator",
            "10%",
            "Similar idea to RSI: compares the current close to its recent high&ndash;low range, "
            f"scaled 0&ndash;100. Above 80 = <b style='color:{BEARISH_COLOR}'>overbought</b>, "
            f"below 20 = <b style='color:{BULLISH_COLOR}'>oversold</b>. In between, it leans bullish "
            "if the fast line (%K) is above the slow line (%D), bearish if below.",
        ),
    ]),
    ("Optional ML Signal", [
        (
            "ML model prediction &mdash; only appears once trained",
            "~33%*",
            "A calibrated machine-learning model (gradient-boosted trees), trained on historical price "
            "data using the same underlying indicators as everything above, but combined by a model that "
            "learned the weighting from data rather than hand-tuned rules. <b>Retrains itself automatically "
            "roughly once an hour</b> while the app is open, but only replaces the active model if the new "
            "version actually beats it on a freshly-built test set &mdash; most hourly runs won't change "
            "anything, since an extra hour of data rarely shifts a model much. See the <b>Model History</b> "
            "tab to review every trained version's stats, its real-world (\u201clive\u201d) tracked accuracy, "
            "and to manually roll back to an older version if you think it worked better. *~33% reflects its "
            "share of the vote once trained (weight 0.5 alongside the rule-based weights, which sum to 1.0). "
            "This is a genuine experiment, not a guaranteed improvement &mdash; the training results "
            "(accuracy, a naive-baseline comparison, a calibration table) are always visible on the Model "
            "History tab, so you can judge for yourself whether it's actually adding value.",
        ),
    ]),
    ("Volatility & Volume", [
        (
            "VWAP &mdash; Volume-Weighted Average Price",
            "14%",
            "The average price paid per unit over the visible window, weighted by how much volume "
            f"traded at each price level. Price <b style='color:{BULLISH_COLOR}'>above</b> VWAP means "
            f"buyers are in control; <b style='color:{BEARISH_COLOR}'>below</b> means sellers are. "
            "Institutional traders watch this closely as a fair-value reference.",
        ),
        (
            "Bollinger Bands",
            "10%",
            "A band drawn 2 standard deviations above and below a 20-bar moving average. Price pushed "
            f"up against the upper band = stretched/<b style='color:{BEARISH_COLOR}'>overbought</b> "
            f"(mean-reversion risk). Against the lower band = stretched/"
            f"<b style='color:{BULLISH_COLOR}'>oversold</b>. When the bands squeeze unusually tight, "
            "it often precedes a sharp move &mdash; that squeeze also feeds the Breakout/Breakdown "
            "odds below.",
        ),
        (
            "Volume spike",
            "14%",
            "Flags when trading volume is unusually high &mdash; more than 1.5 standard deviations "
            "above its recent average &mdash; versus a normal bar. A spike on a green (up) candle "
            f"reinforces a <b style='color:{BULLISH_COLOR}'>bullish</b> move; on a red (down) candle it "
            f"reinforces a <b style='color:{BEARISH_COLOR}'>bearish</b> one. Big moves on light volume "
            "are treated as less trustworthy.",
        ),
        (
            "ATR &mdash; Average True Range",
            None,
            "Not a directional signal &mdash; a measure of how much an asset has actually been moving "
            "recently. Used behind the scenes to size the Target, Take-Profit, and Stop-Loss distances: "
            "a more volatile asset gets wider levels, a calmer one gets tighter levels.",
        ),
    ]),
    ("Composite Signals", [
        (
            "Bullish % / Bearish %",
            None,
            "Every indicator above casts a weighted \"vote\" bullish or bearish (weights shown next to "
            "each one). All the votes are combined into one 0&ndash;100% bullish score; Bearish % is "
            "just 100 minus that. This is the number behind the green/red split bar.",
        ),
        (
            "Confidence %",
            None,
            "How one-sided the current vote is. A near coin-flip (51/49) shows confidence near 0%; a "
            "lopsided vote (98/2) approaches 100%. Shown on the full 0&ndash;100% scale for maximum "
            "resolution &mdash; it's still not a statistically validated probability of being right, "
            "just a measure of how strongly the signals agree with each other right now.",
        ),
        (
            "Breakout odds / Breakdown odds",
            None,
            "A separate estimate &mdash; based on Bollinger Band squeeze + volume + current trend "
            "lean &mdash; of how likely a sharp move up (breakout) or down (breakdown) is brewing. "
            "This is independent of the main direction call: a squeeze can show elevated odds on "
            "<i>both</i> sides at once, since a squeeze means \"something's coming,\" not which way.",
        ),
    ]),
    ("Options-Only Signals (Stock Options tab)", [
        (
            "IV skew &mdash; Implied Volatility skew",
            None,
            "Compares how expensive put options are versus call options on the same underlying. When "
            f"puts are pricier than calls, the options market is paying up for downside protection "
            f"&mdash; a <b style='color:{BEARISH_COLOR}'>bearish</b> lean. Cheaper puts than calls lean "
            f"<b style='color:{BULLISH_COLOR}'>bullish</b>.",
        ),
        (
            "Put/Call ratio",
            None,
            "The ratio of put option trading volume to call option trading volume. A high ratio "
            f"(&gt;1.15) leans <b style='color:{BEARISH_COLOR}'>bearish</b> (more downside "
            f"positioning); a low ratio (&lt;0.85) leans <b style='color:{BULLISH_COLOR}'>bullish</b>.",
        ),
    ]),
    ("Price Levels Shown on the Chart", [
        (
            "Entry",
            None,
            "The price the trade idea assumes you'd get in at &mdash; the live price at the moment "
            "the plan was formed.",
        ),
        (
            "Target",
            None,
            "<b>Crypto Futures tab:</b> replicates CF Benchmarks' Real-Time Index (RTI) settlement "
            "methodology &mdash; the same mechanism Robinhood's 15-minute crypto contracts settle to. "
            "One price sample is collected every second during the final 60 seconds before each "
            "window boundary (:00/:15/:30/:45); the average of those samples, rounded to 4 decimals, "
            "becomes the fixed Target for the window that just started. (CF Benchmarks' own feed "
            "requires a paid institutional license and isn't publicly queryable, so this app runs the "
            "identical averaging technique against the free Kraken feed instead &mdash; the smoothing "
            "mechanism is the same, the exact number won't be penny-for-penny identical to Robinhood's.) "
            "Not a prediction &mdash; a checkpoint, so you can see how far live price has drifted since "
            "the window began.<br><br>"
            "<b>Stock Options tab:</b> the algorithm's projected price by the end of your selected "
            "timeframe, based on recent volatility (ATR) and the current bullish/bearish lean.",
        ),
        (
            "Take-Profit (TP)",
            None,
            f"Suggested price to exit and lock in gains if the trade goes your way. Sized at least "
            f"1.5&times; the current ATR away from entry.",
        ),
        (
            "Stop-Loss (Stop)",
            None,
            "Suggested price to exit and cap losses if the trade goes against you. Sized at 1.2&times; "
            "the current ATR away from entry.",
        ),
        (
            "My Target",
            None,
            "Your own manually-entered reference price (see the \"Manual target\" field in the side "
            "panel) &mdash; unrelated to the algorithm, useful as a personal sanity check or a level "
            "you're specifically watching.",
        ),
    ]),
]


class DefinitionsTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {BG}; color: {TEXT};")
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(2)

        title = QtWidgets.QLabel("Signal &amp; Price-Level Definitions")
        title.setTextFormat(QtCore.Qt.RichText)
        title.setStyleSheet("font-size: 21px; font-weight: 800;")
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel(
            "What each signal, metric, and chart label means, and how it pulls the bullish/bearish "
            "call in this app. Percentages next to a term are its weight in the composite score."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {SUBTEXT}; font-size: 12.5px; margin-top: 4px; margin-bottom: 6px;")
        layout.addWidget(subtitle)

        for section_title, entries in SECTIONS:
            sec_label = QtWidgets.QLabel(section_title)
            sec_label.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {ACCENT}; margin-top: 20px;")
            layout.addWidget(sec_label)

            rule = QtWidgets.QFrame()
            rule.setFrameShape(QtWidgets.QFrame.HLine)
            rule.setStyleSheet("background: #30363d; max-height: 1px; border: none; margin-bottom: 6px;")
            layout.addWidget(rule)

            for term, weight, body in entries:
                term_html = f"<span style='font-size:13.5px; font-weight:700;'>{term}</span>"
                if weight:
                    term_html += f"  <span style='color:{SUBTEXT}; font-weight:400; font-size:11px;'>(weight: {weight})</span>"
                term_label = QtWidgets.QLabel(term_html)
                term_label.setTextFormat(QtCore.Qt.RichText)
                term_label.setStyleSheet("margin-top: 12px;")
                layout.addWidget(term_label)

                body_label = QtWidgets.QLabel(body)
                body_label.setTextFormat(QtCore.Qt.RichText)
                body_label.setWordWrap(True)
                body_label.setStyleSheet(f"font-size: 12.5px; color: {TEXT}; margin-top: 2px;")
                layout.addWidget(body_label)

        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)
