"""
Manual daily P&L tracker: log a trade's cost and ending value, and it keeps
a running total for the day. Purely a manual log -- doesn't touch any live
market data, price feeds, or the analysis engine.

Persists to a small local JSON file (see config.PNL_DATA_DIR) so entries
survive closing and reopening the app during the same day, and
automatically starts fresh each new calendar day (entries from prior days
are pruned out of what's *displayed*, though kept on disk briefly in case
you want to dig up an old file).
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timedelta

from PySide6 import QtCore, QtGui, QtWidgets

BULLISH_COLOR = "#26a69a"
BEARISH_COLOR = "#ef5350"
SUBTEXT = "#8b949e"
TEXT = "#e6edf3"
PANEL_BG = "#161b22"

KEEP_DAYS = 14  # prune anything older than this from the file on every save


def _load_all_entries(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        return entries if isinstance(entries, list) else []
    except (json.JSONDecodeError, OSError, ValueError, AttributeError):
        return []  # a corrupt/unreadable file just starts fresh, never crashes the app


def _save_all_entries(path: str, entries: list):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"entries": entries}, f, indent=2)


def _is_today(iso_timestamp: str) -> bool:
    try:
        return datetime.fromisoformat(iso_timestamp).date() == datetime.now().date()
    except (ValueError, TypeError):
        return False


def _prune(entries: list, keep_days: int = KEEP_DAYS) -> list:
    cutoff = datetime.now() - timedelta(days=keep_days)
    kept = []
    for e in entries:
        try:
            if datetime.fromisoformat(e["timestamp"]) >= cutoff:
                kept.append(e)
        except (KeyError, ValueError, TypeError):
            continue
    return kept


class PnLTracker(QtWidgets.QWidget):
    def __init__(self, storage_path: str, label: str = "Today's P&L", parent=None):
        super().__init__(parent)
        self.storage_path = storage_path
        self.label_text = label

        all_entries = _prune(_load_all_entries(storage_path))
        _save_all_entries(storage_path, all_entries)
        self.entries = [e for e in all_entries if _is_today(e.get("timestamp", ""))]

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.summary_label = QtWidgets.QLabel()
        self.summary_label.setCursor(QtCore.Qt.PointingHandCursor)
        self.summary_label.mousePressEvent = lambda event: self._open_dialog()
        layout.addWidget(self.summary_label)

        self.log_btn = QtWidgets.QPushButton("+ Log Trade")
        self.log_btn.setStyleSheet("padding: 3px 10px; font-size: 11px;")
        self.log_btn.clicked.connect(self._open_dialog)
        layout.addWidget(self.log_btn)

        self._refresh_summary()

    def _refresh_summary(self):
        total = sum(e["ending_value"] - e["cost"] for e in self.entries)
        n = len(self.entries)
        if n == 0 or total == 0:
            color, sign = SUBTEXT, ""
        elif total > 0:
            color, sign = BULLISH_COLOR, "+"
        else:
            color, sign = BEARISH_COLOR, "-"
        self.summary_label.setText(
            f"{self.label_text}: {sign}${abs(total):,.2f} ({n} trade{'s' if n != 1 else ''})"
        )
        self.summary_label.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 13px;")

    def _persist(self):
        # merge today's (possibly just-edited) entries back with whatever
        # older entries are on disk, so this save doesn't clobber other days
        all_entries = _load_all_entries(self.storage_path)
        other_days = [e for e in all_entries if not _is_today(e.get("timestamp", ""))]
        _save_all_entries(self.storage_path, _prune(other_days + self.entries))

    def _open_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.label_text)
        dialog.setStyleSheet(f"background: {PANEL_BG}; color: {TEXT};")
        dialog.setMinimumWidth(420)
        layout = QtWidgets.QVBoxLayout(dialog)

        form = QtWidgets.QHBoxLayout()
        cost_edit = QtWidgets.QLineEdit()
        cost_edit.setPlaceholderText("e.g. 100.00")
        ending_edit = QtWidgets.QLineEdit()
        ending_edit.setPlaceholderText("e.g. 115.50")
        add_btn = QtWidgets.QPushButton("Add")
        form.addWidget(QtWidgets.QLabel("Cost:"))
        form.addWidget(cost_edit)
        form.addWidget(QtWidgets.QLabel("Ending value:"))
        form.addWidget(ending_edit)
        form.addWidget(add_btn)
        layout.addLayout(form)

        error_label = QtWidgets.QLabel("")
        error_label.setStyleSheet(f"color: {BEARISH_COLOR}; font-size: 11px;")
        layout.addWidget(error_label)

        entry_list = QtWidgets.QListWidget()
        entry_list.setStyleSheet(f"background: {PANEL_BG}; color: {TEXT}; border: 1px solid #30363d;")
        layout.addWidget(entry_list)

        total_label = QtWidgets.QLabel()
        total_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        layout.addWidget(total_label)

        button_row = QtWidgets.QHBoxLayout()
        remove_btn = QtWidgets.QPushButton("Remove Selected")
        clear_btn = QtWidgets.QPushButton("Clear All Today")
        close_btn = QtWidgets.QPushButton("Close")
        button_row.addWidget(remove_btn)
        button_row.addWidget(clear_btn)
        button_row.addStretch()
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        def refresh_list():
            entry_list.clear()
            for e in self.entries:
                pnl = e["ending_value"] - e["cost"]
                sign = "+" if pnl >= 0 else ""
                item = QtWidgets.QListWidgetItem(
                    f"Cost {e['cost']:,.2f}  ->  {e['ending_value']:,.2f}    ({sign}{pnl:,.2f})"
                )
                item.setForeground(QtGui.QColor(BULLISH_COLOR if pnl >= 0 else BEARISH_COLOR))
                entry_list.addItem(item)
            total = sum(e["ending_value"] - e["cost"] for e in self.entries)
            sign = "+" if total >= 0 else ""
            total_label.setText(f"Total: {sign}${total:,.2f}")
            total_label.setStyleSheet(
                f"font-size: 14px; font-weight: 700; "
                f"color: {BULLISH_COLOR if total >= 0 else BEARISH_COLOR};"
            )

        def add_entry():
            error_label.setText("")
            try:
                cost = float(cost_edit.text().strip())
                ending = float(ending_edit.text().strip())
            except ValueError:
                error_label.setText("Enter valid numbers for both fields.")
                return
            self.entries.append({
                "cost": cost, "ending_value": ending, "timestamp": datetime.now().isoformat(),
            })
            self._persist()
            cost_edit.clear()
            ending_edit.clear()
            cost_edit.setFocus()
            refresh_list()
            self._refresh_summary()

        def remove_selected():
            row = entry_list.currentRow()
            if row >= 0:
                del self.entries[row]
                self._persist()
                refresh_list()
                self._refresh_summary()

        def clear_all():
            choice = QtWidgets.QMessageBox.question(
                dialog, "Clear Today's Entries",
                "Remove all of today's logged trades? This can't be undone.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if choice == QtWidgets.QMessageBox.Yes:
                self.entries = []
                self._persist()
                refresh_list()
                self._refresh_summary()

        add_btn.clicked.connect(add_entry)
        cost_edit.returnPressed.connect(add_entry)
        ending_edit.returnPressed.connect(add_entry)
        remove_btn.clicked.connect(remove_selected)
        clear_btn.clicked.connect(clear_all)
        close_btn.clicked.connect(dialog.accept)

        refresh_list()
        dialog.exec()
