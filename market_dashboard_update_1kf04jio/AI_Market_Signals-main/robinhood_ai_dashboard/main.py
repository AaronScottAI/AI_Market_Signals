"""
Entry point.

Run with:
    python main.py
"""
import os
import sys
from PySide6 import QtWidgets
import pyqtgraph as pg

from ui.main_window import MainWindow

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    pg.setConfigOptions(antialias=True)
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Market Signal Dashboard")
    window = MainWindow(app_dir=APP_DIR)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
