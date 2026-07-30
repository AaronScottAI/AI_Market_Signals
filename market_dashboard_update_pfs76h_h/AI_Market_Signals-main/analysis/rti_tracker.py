"""
Replicates CF Benchmarks' Real-Time Index (RTI) settlement methodology,
which is what Robinhood's 15-minute crypto contracts settle to: one price
sample per second, and at expiration the last 60 one-second samples are
averaged and rounded to 4 decimal places to produce the official value.

CF Benchmarks' actual RTI feed requires a paid institutional license and
isn't publicly queryable (see https://docs.cfbenchmarks.com/api/ -- "This
API requires users to specify an API key ... obtained by contacting CF
Benchmarks for a license"). This module runs the identical averaging
technique against whatever spot-price source it's given (this app uses the
free Kraken feed via data/crypto_source.py). That won't reproduce the exact
official number, since CF Benchmarks aggregates across many exchanges with
its own error-filtering, but it replicates the real mechanism -- smoothing
the settlement price over the last minute instead of relying on one
instantaneous tick -- using data that's actually accessible here.

Pure Python / no Qt dependency, so the state machine can be driven and
tested independently of the UI layer.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

COLLECTION_WINDOW_SECONDS = 60


@dataclass
class _Window:
    boundary: datetime
    samples: list = field(default_factory=list)

    def add_sample(self, price: float):
        self.samples.append(price)

    def average(self) -> float | None:
        if not self.samples:
            return None
        return round(sum(self.samples) / len(self.samples), 4)


class RTITracker:
    """
    Usage (call roughly once per second, e.g. from a 1s QTimer):

        avg, boundary = tracker.tick(now)
        if avg is not None:
            ...a window just closed; avg is its final settlement value...
        if tracker.should_sample(now):
            price = fetch_current_price()   # however the caller gets one
            tracker.record_sample(price, for_boundary=tracker.collecting_boundary)
    """

    def __init__(self, next_boundary_fn):
        """next_boundary_fn(now) -> datetime of the next clock boundary
        strictly after `now` (e.g. analysis.signal_engine.next_clock_boundary)."""
        self._next_boundary_fn = next_boundary_fn
        self._current: _Window | None = None

    @property
    def samples_collected(self) -> int:
        return len(self._current.samples) if self._current else 0

    @property
    def collecting_boundary(self):
        return self._current.boundary if self._current else None

    def should_sample(self, now: datetime) -> bool:
        if self._current is None:
            return False
        return (self._current.boundary - now).total_seconds() <= COLLECTION_WINDOW_SECONDS

    def record_sample(self, price: float, for_boundary=None):
        """for_boundary: pass the boundary that was active when the (possibly
        async) price fetch was *initiated*, so a slow response that arrives
        just after a window closes doesn't get misattributed to the next
        window. Safe to omit if the caller fetches synchronously."""
        if self._current is None:
            return
        if for_boundary is not None and for_boundary != self._current.boundary:
            return  # stale sample from a window that already closed
        self._current.add_sample(price)

    def tick(self, now: datetime):
        """Advance the state machine. Returns (average, boundary) if a
        window just closed this tick (average may be None if zero samples
        were collected, e.g. every fetch failed), else (None, None)."""
        boundary = self._next_boundary_fn(now)

        if self._current is None:
            self._current = _Window(boundary)
            return None, None

        if boundary == self._current.boundary:
            return None, None

        # crossed into a new window -- finalize the one that just closed
        closed = self._current
        self._current = _Window(boundary)
        return closed.average(), closed.boundary
