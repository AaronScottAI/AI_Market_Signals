# Crypto Futures Tab — What Updates When

Personal reference. Matches the code as of v1.8.0 (Target-only freezing).
If behavior ever looks off, check it against this table first — if it
doesn't match what's listed here, *that's* the bug to report, with a
screenshot + timestamp.

## Live (continuous — nearly everything, as of this version)

| Element | Updates via | Cadence |
|---|---|---|
| **Current price** (big number, top-left) | `spot_timer` | Your "Spot update interval" dropdown (1s–60s, default 5s) |
| **Bid / Ask** | `spot_timer` | Same as Current price |
| **24h % change** | `spot_timer` | Same as Current price |
| **"Current"** field (inside the right panel) | `spot_timer` | Same as Current price — wired to the identical feed |
| **Chart candles / volume / overlays** | `signal_timer` | Every 60s, *plus* an extra immediate refresh right when a 15-min window closes |
| **Direction (UP/DOWN)** | `signal_timer` | Every 60s, live |
| **Confidence %** | `signal_timer` | Every 60s, live |
| **Bullish % / Bearish % bar** | `signal_timer` | Every 60s, live |
| **Bullish % history sparkline** | `signal_timer` | One new point every 60s, live |
| **Breakout odds / Breakdown odds** | `signal_timer` | Every 60s, live |
| **Signals forming** (the list) | `signal_timer` | Every 60s, live |
| **ML Model Prediction** | `signal_timer` | Every 60s, live (re-evaluated each cycle). The underlying *model itself* can separately auto-retrain ~hourly in the background (see Model History tab) — that's independent of this per-cycle re-evaluation |
| **Suggested Entry** | `signal_timer` | Every 60s, live — always the current price at that moment |
| **Take-Profit** | `signal_timer` | Every 60s, live — ATR-distance from current price |
| **Stop-Loss** | `signal_timer` | Every 60s, live — ATR-distance from current price |
| **Hover box** (candle detail readout) | mouse movement | Instant, on hover — not timer-driven |
| **RTI collection status** ("Collecting settlement sample: 34/60...") | `rti_timer` | Every 1s, but only *shows* text during the final 60s before each boundary |

## Frozen — Target price only

This is the one deliberate exception. Everything above is live; **Target**
is a fixed reference point, specifically so you can compare the live price
against a stable anchor rather than a constantly-shifting one.

| Element | Freezes via | Notes |
|---|---|---|
| **Target** (price + its "HH:MM" time label) | `_finalize_frozen_target()` | RTI-averaged observed price at the moment the current 15-min window started (not a prediction). Holds until the next :00/:15/:30/:45 boundary, then jumps to the new window's average. |

**Before the first window has closed** (e.g. right after launch or
switching symbols), Target temporarily shows the live observed price each
cycle instead, until the first RTI averaging window completes and the
first real freeze happens.

## Manual / user-controlled only (never automatic)

| Element | Changes when |
|---|---|
| **My Target** (manual line) | You click "Set" or "Clear" |
| **Today's P&L** | You log, remove, or clear a trade |
| **Indicator checkboxes** (EMA9/EMA21/Bollinger/VWAP) | You click them — pure display toggle, doesn't affect the analysis |
| **Line checkboxes** (TP/Stop/Target/My Target) | You click them — pure display toggle |
| **Chart type** (Candles/Line) | You click it — pure display toggle |
| **Symbol** | You pick one — resets the RTI tracker and frozen Target for the new symbol |
