from __future__ import annotations
from PySide6 import QtWidgets, QtGui, QtCore

import config
import updater
from ui.futures_tab import FuturesTab
from ui.options_tab import OptionsTab
from ui.definitions_tab import DefinitionsTab
from ui.signal_panel import BG, TEXT, SUBTEXT
from ui.workers import FetchWorker


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, app_dir: str | None = None):
        super().__init__()
        self.app_dir = app_dir
        self._update_workers = []
        self.setWindowTitle(config.APP_NAME)
        self.resize(1440, 900)
        self.setStyleSheet(f"""
            QMainWindow {{ background: {BG}; }}
            QWidget {{ color: {TEXT}; font-family: 'Segoe UI', Arial, sans-serif; }}
            QComboBox, QLineEdit, QPushButton {{
                background: #21262d; border: 1px solid #30363d; border-radius: 4px;
                padding: 4px 8px; color: {TEXT};
            }}
            QPushButton {{ padding: 5px 14px; }}
            QPushButton:hover {{ background: #30363d; }}
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                background: #161b22; color: {SUBTEXT}; padding: 8px 18px; margin-right: 2px;
            }}
            QTabBar::tab:selected {{ background: {BG}; color: {TEXT}; font-weight: 600; }}
        """)

        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        disclaimer = QtWidgets.QLabel(config.DISCLAIMER)
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            f"background: #2d1b00; color: #f0b429; padding: 6px 14px; font-size: 11px;"
        )
        layout.addWidget(disclaimer)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(FuturesTab(), "Crypto Futures")
        tabs.addTab(OptionsTab(), "Stock Options")
        tabs.addTab(DefinitionsTab(), "Definitions")
        layout.addWidget(tabs, stretch=1)

        self.setCentralWidget(central)

        help_menu = self.menuBar().addMenu("Help")
        check_updates_action = QtGui.QAction("Check for Updates...", self)
        check_updates_action.triggered.connect(lambda: self._check_for_updates(silent=False))
        help_menu.addAction(check_updates_action)

        # Silent background check shortly after launch -- doesn't block
        # startup, and does nothing at all if updates aren't configured
        # (see config.py: UPDATE_REPO_OWNER) or if there's no internet.
        QtCore.QTimer.singleShot(2000, lambda: self._check_for_updates(silent=True))

    def _check_for_updates(self, silent: bool):
        worker = FetchWorker(updater.check_for_update)
        worker.result.connect(lambda payload: self._on_update_check_result(payload, silent))
        worker.error.connect(lambda msg: self._on_update_check_result((False, None, msg), silent))
        self._update_workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_update_worker(worker))
        worker.start()

    def _cleanup_update_worker(self, worker):
        if worker in self._update_workers:
            self._update_workers.remove(worker)

    def _on_update_check_result(self, payload, silent: bool):
        available, latest, err = payload
        if available:
            self._prompt_and_apply_update(latest)
            return
        if silent:
            return  # unconfigured, offline, or already up to date -- say nothing
        if err == "not_configured":
            QtWidgets.QMessageBox.information(
                self, "Auto-Update Not Set Up",
                "Auto-update isn't configured yet.\n\n"
                "See the setup instructions at the top of updater.py to connect "
                "this app to a GitHub repo you control.",
            )
        elif err:
            QtWidgets.QMessageBox.warning(self, "Update Check Failed", err)
        else:
            QtWidgets.QMessageBox.information(
                self, "Up to Date", f"You're on the latest version ({config.APP_VERSION})."
            )

    def _prompt_and_apply_update(self, latest_version: str):
        choice = QtWidgets.QMessageBox.question(
            self, "Update Available",
            f"Version {latest_version} is available (you have {config.APP_VERSION}).\n\n"
            "Download and install it now? The app will close and reopen automatically.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if choice != QtWidgets.QMessageBox.Yes:
            return
        if not self.app_dir:
            QtWidgets.QMessageBox.warning(self, "Can't Update", "Couldn't determine the app's install location.")
            return
        try:
            updater.apply_update_and_relaunch(self.app_dir)
        except Exception as exc:  # noqa: BLE001 -- surface any failure instead of silently hanging
            QtWidgets.QMessageBox.warning(self, "Update Failed", f"{type(exc).__name__}: {exc}")
            return
        QtWidgets.QApplication.instance().quit()
