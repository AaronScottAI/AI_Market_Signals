"""
P&L History tab: the complete logged trade history from both trackers
(Crypto Futures and Stock Options), with date/time stamps, per-day
subtotals, and grand totals. Read-only -- entries are added via each tab's
own "+ Log Trade" button; this page is purely for reviewing everything
logged so far.
"""
from __future__ import annotations
import os
from datetime import datetime

from PySide6 import QtGui, QtWidgets

import config
from ui.pnl_tracker import load_history

BG = "#0d1117"
CARD_BG = "#161b22"
TEXT = "#e6edf3"
SUBTEXT = "#8b949e"
BULLISH_COLOR = "#26a69a"
BEARISH_COLOR = "#ef5350"


def _pnl_color(value: float) -> str:
    if value > 0:
        return BULLISH_COLOR
    if value < 0:
        return BEARISH_COLOR
    return SUBTEXT


class PnLHistorySection(QtWidgets.QWidget):
    """One tracker's full history: grand-total header + a table grouped by
    date, with a bold subtotal row inserted after each day's entries."""

    def __init__(self, title: str, storage_path: str, parent=None):
        super().__init__(parent)
        self.storage_path = storage_path

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet(f"color: {TEXT}; font-size: 18px; font-weight: 800;")
        layout.addWidget(title_label)

        self.grand_total_label = QtWidgets.QLabel()
        self.grand_total_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(self.grand_total_label)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Date", "Time", "Cost", "Ending Value  (P&L)"])
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
        self.table.setMinimumHeight(240)
        layout.addWidget(self.table)

        self.refresh()

    def refresh(self):
        entries = load_history(self.storage_path)  # already sorted newest-first
        grand_total = sum(e["ending_value"] - e["cost"] for e in entries)
        n = len(entries)
        color = _pnl_color(grand_total)
        sign = "+" if grand_total > 0 else ("-" if grand_total < 0 else "")
        self.grand_total_label.setText(
            f"Grand Total: {sign}${abs(grand_total):,.2f}  ({n} trade{'s' if n != 1 else ''} logged)"
        )
        self.grand_total_label.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {color};")

        # group by calendar date, preserving newest-first order
        groups: dict[str, list] = {}
        order: list[str] = []
        for e in entries:
            try:
                dt = datetime.fromisoformat(e["timestamp"])
            except (KeyError, ValueError, TypeError):
                continue
            date_key = dt.strftime("%Y-%m-%d")
            if date_key not in groups:
                groups[date_key] = []
                order.append(date_key)
            groups[date_key].append((dt, e))

        rows = []  # ("subtotal", label, total, count) or ("entry", dt, e)
        for date_key in order:
            day_entries = groups[date_key]
            day_total = sum(e["ending_value"] - e["cost"] for _, e in day_entries)
            date_label = day_entries[0][0].strftime("%A, %B %d, %Y")
            rows.append(("subtotal", date_label, day_total, len(day_entries)))
            rows.extend(("entry", dt, e) for dt, e in day_entries)

        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            if row[0] == "subtotal":
                _, date_label, day_total, count = row
                sign = "+" if day_total > 0 else ("-" if day_total < 0 else "")
                row_color = _pnl_color(day_total)
                text = (
                    f"{date_label}   \u2014   Subtotal: {sign}${abs(day_total):,.2f} "
                    f"({count} trade{'s' if count != 1 else ''})"
                )
                item = QtWidgets.QTableWidgetItem(text)
                item.setForeground(QtGui.QColor(row_color))
                bold_font = item.font()
                bold_font.setBold(True)
                item.setFont(bold_font)
                item.setBackground(QtGui.QColor("#1c2128"))
                self.table.setSpan(i, 0, 1, 4)
                self.table.setItem(i, 0, item)
                self.table.setRowHeight(i, 30)
            else:
                _, dt, e = row
                pnl = e["ending_value"] - e["cost"]
                sign = "+" if pnl >= 0 else ""
                row_color = _pnl_color(pnl)

                date_item = QtWidgets.QTableWidgetItem(dt.strftime("%b %d, %Y"))
                time_item = QtWidgets.QTableWidgetItem(dt.strftime("%I:%M %p").lstrip("0"))
                cost_item = QtWidgets.QTableWidgetItem(f"{e['cost']:,.2f}")
                pnl_item = QtWidgets.QTableWidgetItem(
                    f"{e['ending_value']:,.2f}    ({sign}{pnl:,.2f})"
                )
                for item in (date_item, time_item, cost_item):
                    item.setForeground(QtGui.QColor(SUBTEXT))
                pnl_item.setForeground(QtGui.QColor(row_color))
                self.table.setItem(i, 0, date_item)
                self.table.setItem(i, 1, time_item)
                self.table.setItem(i, 2, cost_item)
                self.table.setItem(i, 3, pnl_item)

        self.table.resizeColumnsToContents()


class PnLHistoryTab(QtWidgets.QWidget):
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
        title = QtWidgets.QLabel("P&L History")
        title.setStyleSheet(f"color: {TEXT}; font-size: 22px; font-weight: 800;")
        header_row.addWidget(title)
        header_row.addStretch()
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)

        note = QtWidgets.QLabel(
            "Everything logged via \u201c+ Log Trade\u201d on both tabs, grouped by day with a "
            "subtotal for each and a grand total overall. This is a manual log you maintain "
            "yourself -- it isn't tied to live prices or the analysis engine. Refreshes "
            "automatically when you open this tab."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        layout.addWidget(note)

        self.futures_section = PnLHistorySection(
            "Crypto Futures", os.path.join(config.PNL_DATA_DIR, "futures_pnl.json")
        )
        layout.addWidget(self.futures_section)

        self.options_section = PnLHistorySection(
            "Stock Options", os.path.join(config.PNL_DATA_DIR, "options_pnl.json")
        )
        layout.addWidget(self.options_section)

        layout.addStretch()
        scroll.setWidget(content)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def refresh(self):
        self.futures_section.refresh()
        self.options_section.refresh()
