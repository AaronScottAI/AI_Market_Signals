"""
Generic background worker so price/chart fetches (network calls) never
freeze the UI thread. Usage:

    worker = FetchWorker(some_function, arg1, arg2, kwarg=val)
    worker.result.connect(on_result)
    worker.error.connect(on_error)
    worker.start()

Keep a reference to `worker` on `self` (e.g. self._workers.append(worker))
until it finishes -- otherwise Python may garbage-collect it mid-flight.
"""
from __future__ import annotations
from PySide6 import QtCore


class FetchWorker(QtCore.QThread):
    result = QtCore.Signal(object)
    error = QtCore.Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            value = self.fn(*self.args, **self.kwargs)
            self.result.emit(value)
        except Exception as exc:  # noqa: BLE001 - surface any error to the UI
            self.error.emit(f"{type(exc).__name__}: {exc}")
