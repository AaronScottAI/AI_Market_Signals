"""
Classic chart pattern detection, operating on plain OHLC price history.

These are heuristic approximations of patterns a human technical analyst
would eyeball -- "double top," "bull flag," etc. are inherently a bit
fuzzy/subjective even in traditional TA, so treat detection as "this
reasonably resembles the pattern," not an exact geometric match. Every
detector returns a PatternResult (or None if nothing was found), including
a 0-1 quality/strength score reflecting how clean the pattern looks, so
downstream code (the rule-based scorer, the ML features) can weight a
textbook-clean pattern more than a rough approximation of one.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PatternResult:
    name: str          # "double_top", "double_bottom", "bull_flag", "bear_flag"
    direction: str      # "bullish" or "bearish" -- which way the pattern implies price goes next
    quality: float        # 0-1, how clean/textbook the pattern looks
    confirmed: bool         # for double top/bottom: has price actually broken the neckline yet?
    detail: str                # human-readable description for the signals list


def find_pivots(high: pd.Series, low: pd.Series, window: int = 5) -> tuple[list[int], list[int]]:
    """Local swing highs/lows: bar i is a peak if its high is the max within
    +/- window bars (and similarly for troughs on the low). Returns
    (peak_positions, trough_positions) as positional (iloc-style) indices."""
    h = high.to_numpy()
    l = low.to_numpy()
    n = len(h)
    peaks, troughs = [], []
    for i in range(window, n - window):
        h_seg = h[i - window : i + window + 1]
        l_seg = l[i - window : i + window + 1]
        if np.isnan(h[i]) or np.isnan(l[i]):
            continue
        if h[i] == np.nanmax(h_seg):
            peaks.append(i)
        if l[i] == np.nanmin(l_seg):
            troughs.append(i)
    return peaks, troughs


def detect_double_top(
    df: pd.DataFrame, peaks: list[int], troughs: list[int],
    lookback_bars: int = 120, recency_bars: int = 20,
    price_tolerance: float = 0.015, min_pullback: float = 0.02,
) -> PatternResult | None:
    """Two recent peaks at a similar price level, with a genuine pullback
    (trough) between them -- a classic bearish reversal setup. `confirmed`
    is True once price has actually broken below the trough (the
    "neckline"); otherwise the pattern is still just forming."""
    n = len(df)
    recent_peaks = [p for p in peaks if p >= n - lookback_bars]
    if len(recent_peaks) < 2:
        return None
    p1, p2 = recent_peaks[-2], recent_peaks[-1]
    if p2 < n - recency_bars:
        return None  # most recent peak is too old to be an actionable, current pattern

    price1, price2 = df["high"].iloc[p1], df["high"].iloc[p2]
    peak_level = max(price1, price2)
    price_diff = abs(price1 - price2) / peak_level
    if price_diff > price_tolerance:
        return None

    between = [t for t in troughs if p1 < t < p2]
    if not between:
        return None
    trough_price = df["low"].iloc[between].min()
    pullback = (peak_level - trough_price) / peak_level
    if pullback < min_pullback:
        return None

    current_price = df["close"].iloc[-1]
    confirmed = current_price < trough_price

    similarity_quality = 1.0 - (price_diff / price_tolerance)  # 1.0 = identical peaks, 0.0 = at the tolerance edge
    pullback_quality = min(pullback / (min_pullback * 2), 1.0)  # deeper pullback = cleaner pattern, caps out at 2x the minimum
    quality = float(np.clip(0.5 * similarity_quality + 0.5 * pullback_quality, 0.0, 1.0))
    if confirmed:
        quality = min(quality + 0.15, 1.0)  # a confirmed break adds a bit more conviction

    detail = (
        f"Two peaks near {peak_level:,.4g} with a {pullback:.1%} pullback between them"
        + (" -- neckline broken" if confirmed else " -- not yet confirmed")
    )
    return PatternResult("double_top", "bearish", quality, confirmed, detail)


def detect_double_bottom(
    df: pd.DataFrame, peaks: list[int], troughs: list[int],
    lookback_bars: int = 120, recency_bars: int = 20,
    price_tolerance: float = 0.015, min_pullback: float = 0.02,
) -> PatternResult | None:
    """Mirror image of detect_double_top: two recent troughs at a similar
    level with a genuine bounce between them -- a bullish reversal setup."""
    n = len(df)
    recent_troughs = [t for t in troughs if t >= n - lookback_bars]
    if len(recent_troughs) < 2:
        return None
    t1, t2 = recent_troughs[-2], recent_troughs[-1]
    if t2 < n - recency_bars:
        return None

    price1, price2 = df["low"].iloc[t1], df["low"].iloc[t2]
    trough_level = min(price1, price2)
    price_diff = abs(price1 - price2) / trough_level
    if price_diff > price_tolerance:
        return None

    between = [p for p in peaks if t1 < p < t2]
    if not between:
        return None
    peak_price = df["high"].iloc[between].max()
    bounce = (peak_price - trough_level) / trough_level
    if bounce < min_pullback:
        return None

    current_price = df["close"].iloc[-1]
    confirmed = current_price > peak_price

    similarity_quality = 1.0 - (price_diff / price_tolerance)
    bounce_quality = min(bounce / (min_pullback * 2), 1.0)
    quality = float(np.clip(0.5 * similarity_quality + 0.5 * bounce_quality, 0.0, 1.0))
    if confirmed:
        quality = min(quality + 0.15, 1.0)

    detail = (
        f"Two troughs near {trough_level:,.4g} with a {bounce:.1%} bounce between them"
        + (" -- neckline broken" if confirmed else " -- not yet confirmed")
    )
    return PatternResult("double_bottom", "bullish", quality, confirmed, detail)


def _detect_flag(
    close: np.ndarray, pole_bars: int, flag_bars: int,
    min_pole_move: float, max_flag_retrace: float, max_flag_range_ratio: float,
    bullish: bool,
) -> PatternResult | None:
    n = len(close)
    if n < pole_bars + flag_bars:
        return None

    flag_start = n - flag_bars
    pole_start = flag_start - pole_bars
    pole_open, pole_close = close[pole_start], close[flag_start - 1]
    pole_move = (pole_close - pole_open) / pole_open if bullish else (pole_open - pole_close) / pole_open
    if pole_move < min_pole_move:
        return None  # not a strong enough directional pole

    flag_segment = close[flag_start:]
    flag_high, flag_low = flag_segment.max(), flag_segment.min()
    flag_range = (flag_high - flag_low) / pole_close
    pole_size = abs(pole_close - pole_open)

    if bullish:
        retrace = (pole_close - flag_low) / pole_size if pole_size > 0 else 1.0
    else:
        retrace = (flag_high - pole_close) / pole_size if pole_size > 0 else 1.0

    if retrace > max_flag_retrace:
        return None  # consolidation gave back too much of the pole -- looks more like a reversal
    if flag_range > pole_move * max_flag_range_ratio:
        return None  # consolidation isn't tight enough to read as a pause, not a big move

    tightness_quality = 1.0 - min(flag_range / (pole_move * max_flag_range_ratio), 1.0)
    retrace_quality = 1.0 - min(retrace / max_flag_retrace, 1.0)
    quality = float(np.clip(0.5 * tightness_quality + 0.5 * retrace_quality, 0.0, 1.0))

    name = "bull_flag" if bullish else "bear_flag"
    direction = "bullish" if bullish else "bearish"
    detail = (
        f"{'Sharp rise' if bullish else 'Sharp drop'} ({pole_move:.1%}) followed by a tight "
        f"{flag_range:.1%}-range consolidation, retracing {retrace:.0%} of the move"
    )
    return PatternResult(name, direction, quality, True, detail)


def detect_bull_flag(
    df: pd.DataFrame, pole_bars: int = 15, flag_bars: int = 8,
    min_pole_move: float = 0.02, max_flag_retrace: float = 0.5, max_flag_range_ratio: float = 0.6,
) -> PatternResult | None:
    """A strong upward move (the pole) followed by a tight, mostly-sideways
    or mildly-pulled-back consolidation (the flag) -- classically a
    continuation setup, implying more upside once the consolidation
    resolves."""
    return _detect_flag(
        df["close"].to_numpy(), pole_bars, flag_bars,
        min_pole_move, max_flag_retrace, max_flag_range_ratio, bullish=True,
    )


def detect_bear_flag(
    df: pd.DataFrame, pole_bars: int = 15, flag_bars: int = 8,
    min_pole_move: float = 0.02, max_flag_retrace: float = 0.5, max_flag_range_ratio: float = 0.6,
) -> PatternResult | None:
    """Mirror image of detect_bull_flag: a strong downward move followed by
    a tight consolidation, implying more downside to come."""
    return _detect_flag(
        df["close"].to_numpy(), pole_bars, flag_bars,
        min_pole_move, max_flag_retrace, max_flag_range_ratio, bullish=False,
    )


def detect_head_and_shoulders(
    df: pd.DataFrame, peaks: list[int], troughs: list[int],
    lookback_bars: int = 150, recency_bars: int = 25,
    shoulder_tolerance: float = 0.03, min_head_prominence: float = 0.015,
) -> PatternResult | None:
    """Three peaks -- a prominent middle one (the head) higher than two
    roughly-similar-height flanking ones (the shoulders) -- a classic
    bearish reversal. The "neckline" connects the two troughs on either
    side of the head; confirmed once price breaks below it."""
    n = len(df)
    recent_peaks = [p for p in peaks if p >= n - lookback_bars]
    if len(recent_peaks) < 3:
        return None
    left_shoulder, head, right_shoulder = recent_peaks[-3], recent_peaks[-2], recent_peaks[-1]
    if right_shoulder < n - recency_bars:
        return None

    ls_price = df["high"].iloc[left_shoulder]
    head_price = df["high"].iloc[head]
    rs_price = df["high"].iloc[right_shoulder]

    prominence_left = (head_price - ls_price) / ls_price
    prominence_right = (head_price - rs_price) / rs_price
    if prominence_left < min_head_prominence or prominence_right < min_head_prominence:
        return None  # head isn't meaningfully higher than both shoulders

    shoulder_diff = abs(ls_price - rs_price) / max(ls_price, rs_price)
    if shoulder_diff > shoulder_tolerance:
        return None

    trough1 = [t for t in troughs if left_shoulder < t < head]
    trough2 = [t for t in troughs if head < t < right_shoulder]
    if not trough1 or not trough2:
        return None
    neckline = (df["low"].iloc[trough1].min() + df["low"].iloc[trough2].min()) / 2

    current_price = df["close"].iloc[-1]
    confirmed = current_price < neckline

    symmetry_quality = 1.0 - (shoulder_diff / shoulder_tolerance)
    prominence_quality = min((prominence_left + prominence_right) / (min_head_prominence * 4), 1.0)
    quality = float(np.clip(0.5 * symmetry_quality + 0.5 * prominence_quality, 0.0, 1.0))
    if confirmed:
        quality = min(quality + 0.15, 1.0)

    detail = (
        f"Three peaks, prominent head near {head_price:,.4g}, shoulders near "
        f"{(ls_price + rs_price) / 2:,.4g}" + (" -- neckline broken" if confirmed else " -- not yet confirmed")
    )
    return PatternResult("head_and_shoulders", "bearish", quality, confirmed, detail)


def detect_inverse_head_and_shoulders(
    df: pd.DataFrame, peaks: list[int], troughs: list[int],
    lookback_bars: int = 150, recency_bars: int = 25,
    shoulder_tolerance: float = 0.03, min_head_prominence: float = 0.015,
) -> PatternResult | None:
    """Mirror image of detect_head_and_shoulders: three troughs, a
    prominent middle one (the head) lower than two roughly-similar-depth
    shoulders -- a classic bullish reversal."""
    n = len(df)
    recent_troughs = [t for t in troughs if t >= n - lookback_bars]
    if len(recent_troughs) < 3:
        return None
    left_shoulder, head, right_shoulder = recent_troughs[-3], recent_troughs[-2], recent_troughs[-1]
    if right_shoulder < n - recency_bars:
        return None

    ls_price = df["low"].iloc[left_shoulder]
    head_price = df["low"].iloc[head]
    rs_price = df["low"].iloc[right_shoulder]

    prominence_left = (ls_price - head_price) / ls_price
    prominence_right = (rs_price - head_price) / rs_price
    if prominence_left < min_head_prominence or prominence_right < min_head_prominence:
        return None

    shoulder_diff = abs(ls_price - rs_price) / max(ls_price, rs_price)
    if shoulder_diff > shoulder_tolerance:
        return None

    peak1 = [p for p in peaks if left_shoulder < p < head]
    peak2 = [p for p in peaks if head < p < right_shoulder]
    if not peak1 or not peak2:
        return None
    neckline = (df["high"].iloc[peak1].max() + df["high"].iloc[peak2].max()) / 2

    current_price = df["close"].iloc[-1]
    confirmed = current_price > neckline

    symmetry_quality = 1.0 - (shoulder_diff / shoulder_tolerance)
    prominence_quality = min((prominence_left + prominence_right) / (min_head_prominence * 4), 1.0)
    quality = float(np.clip(0.5 * symmetry_quality + 0.5 * prominence_quality, 0.0, 1.0))
    if confirmed:
        quality = min(quality + 0.15, 1.0)

    detail = (
        f"Three troughs, prominent head near {head_price:,.4g}, shoulders near "
        f"{(ls_price + rs_price) / 2:,.4g}" + (" -- neckline broken" if confirmed else " -- not yet confirmed")
    )
    return PatternResult("inverse_head_and_shoulders", "bullish", quality, confirmed, detail)


def _fit_trend(indices: list[int], prices: np.ndarray) -> tuple[float, float]:
    """Linear fit of prices against bar position. Returns (pct_change,
    r_squared): pct_change is what the fitted line implies over the full
    span as a fraction of the mean price (scale-independent, works the
    same for a $0.20 token or a $110,000 one); r_squared measures how
    clean/linear the trend is (1.0 = perfect line, low = scattered noise)."""
    if len(indices) < 2:
        return 0.0, 0.0
    x = np.array(indices, dtype=float)
    y = np.array(prices, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    ss_res = np.sum((y - predicted) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0  # a perfectly flat line still "fits" itself
    mean_price = y.mean()
    pct_change = (slope * (x.max() - x.min())) / mean_price if mean_price != 0 else 0.0
    return float(pct_change), float(r_squared)


def _detect_triangle(
    df: pd.DataFrame, peaks: list[int], troughs: list[int],
    lookback_bars: int, recency_bars: int, min_pivots: int,
    flat_tolerance: float, min_slope_pct: float, min_r_squared: float,
    ascending: bool,
) -> PatternResult | None:
    n = len(df)
    recent_peaks = [p for p in peaks if p >= n - lookback_bars][-min_pivots:]
    recent_troughs = [t for t in troughs if t >= n - lookback_bars][-min_pivots:]
    if len(recent_peaks) < min_pivots or len(recent_troughs) < min_pivots:
        return None

    last_pivot = max(recent_peaks[-1], recent_troughs[-1])
    if last_pivot < n - recency_bars:
        return None

    peak_prices = df["high"].iloc[recent_peaks].to_numpy()
    trough_prices = df["low"].iloc[recent_troughs].to_numpy()

    if ascending:
        # flat resistance (peaks) + rising support (troughs)
        flat_change, flat_fit = _fit_trend(recent_peaks, peak_prices)
        slope_change, slope_fit = _fit_trend(recent_troughs, trough_prices)
        if abs(flat_change) > flat_tolerance:
            return None
        if slope_change < min_slope_pct or slope_fit < min_r_squared:
            return None
    else:
        # flat support (troughs) + falling resistance (peaks)
        flat_change, flat_fit = _fit_trend(recent_troughs, trough_prices)
        slope_change, slope_fit = _fit_trend(recent_peaks, peak_prices)
        if abs(flat_change) > flat_tolerance:
            return None
        if slope_change > -min_slope_pct or slope_fit < min_r_squared:
            return None

    flatness_quality = 1.0 - min(abs(flat_change) / flat_tolerance, 1.0)
    trend_quality = min(slope_fit, 1.0)
    quality = float(np.clip(0.5 * flatness_quality + 0.5 * trend_quality, 0.0, 1.0))

    name = "ascending_triangle" if ascending else "descending_triangle"
    direction = "bullish" if ascending else "bearish"
    detail = (
        f"{'Flat resistance with rising support' if ascending else 'Flat support with falling resistance'} "
        f"across {min_pivots} touches each -- a narrowing range typically resolving "
        f"{'upward' if ascending else 'downward'}"
    )
    return PatternResult(name, direction, quality, True, detail)


def detect_ascending_triangle(
    df: pd.DataFrame, peaks: list[int], troughs: list[int],
    lookback_bars: int = 150, recency_bars: int = 25, min_pivots: int = 3,
    flat_tolerance: float = 0.012, min_slope_pct: float = 0.015, min_r_squared: float = 0.5,
) -> PatternResult | None:
    """Roughly flat resistance (peaks at a similar level) with rising
    support (progressively higher troughs) -- a narrowing range that
    classically tends to break out upward."""
    return _detect_triangle(
        df, peaks, troughs, lookback_bars, recency_bars, min_pivots,
        flat_tolerance, min_slope_pct, min_r_squared, ascending=True,
    )


def detect_descending_triangle(
    df: pd.DataFrame, peaks: list[int], troughs: list[int],
    lookback_bars: int = 150, recency_bars: int = 25, min_pivots: int = 3,
    flat_tolerance: float = 0.012, min_slope_pct: float = 0.015, min_r_squared: float = 0.5,
) -> PatternResult | None:
    """Mirror image of detect_ascending_triangle: roughly flat support with
    falling resistance (progressively lower peaks) -- classically tends to
    break out downward."""
    return _detect_triangle(
        df, peaks, troughs, lookback_bars, recency_bars, min_pivots,
        flat_tolerance, min_slope_pct, min_r_squared, ascending=False,
    )


def best_reversal_pattern(df: pd.DataFrame, peaks: list[int], troughs: list[int]) -> PatternResult | None:
    """Checks every reversal-family detector (double top/bottom, head &
    shoulders / inverse) and returns whichever result has the highest
    quality, if any were found. It's possible for more than one to
    genuinely apply to the same price action at once -- this just picks
    the cleanest read rather than trying to combine them."""
    candidates = [
        detect_double_top(df, peaks, troughs),
        detect_double_bottom(df, peaks, troughs),
        detect_head_and_shoulders(df, peaks, troughs),
        detect_inverse_head_and_shoulders(df, peaks, troughs),
    ]
    found = [c for c in candidates if c is not None]
    if not found:
        return None
    return max(found, key=lambda r: r.quality)


def best_continuation_pattern(df: pd.DataFrame, peaks: list[int], troughs: list[int]) -> PatternResult | None:
    """Same idea as best_reversal_pattern, for the continuation family
    (bull/bear flag, ascending/descending triangle)."""
    candidates = [
        detect_bull_flag(df),
        detect_bear_flag(df),
        detect_ascending_triangle(df, peaks, troughs),
        detect_descending_triangle(df, peaks, troughs),
    ]
    found = [c for c in candidates if c is not None]
    if not found:
        return None
    return max(found, key=lambda r: r.quality)


def detect_all(df: pd.DataFrame, pivot_window: int = 5) -> dict[str, PatternResult]:
    """Runs every detector and returns a dict of whichever patterns were
    actually found (name -> PatternResult), skipping ones that weren't."""
    results: dict[str, PatternResult] = {}
    if len(df) < pivot_window * 2 + 10:
        return results  # not enough history yet

    peaks, troughs = find_pivots(df["high"], df["low"], window=pivot_window)

    dt = detect_double_top(df, peaks, troughs)
    if dt is not None:
        results["double_top"] = dt
    else:
        db = detect_double_bottom(df, peaks, troughs)
        if db is not None:
            results["double_bottom"] = db

    hs = detect_head_and_shoulders(df, peaks, troughs)
    if hs is not None:
        results["head_and_shoulders"] = hs
    else:
        ihs = detect_inverse_head_and_shoulders(df, peaks, troughs)
        if ihs is not None:
            results["inverse_head_and_shoulders"] = ihs

    bull = detect_bull_flag(df)
    if bull is not None:
        results["bull_flag"] = bull
    else:
        bear = detect_bear_flag(df)
        if bear is not None:
            results["bear_flag"] = bear

    asc = detect_ascending_triangle(df, peaks, troughs)
    if asc is not None:
        results["ascending_triangle"] = asc
    else:
        desc = detect_descending_triangle(df, peaks, troughs)
        if desc is not None:
            results["descending_triangle"] = desc

    return results
