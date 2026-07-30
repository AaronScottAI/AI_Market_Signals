"""
Central configuration for the dashboard.

No Robinhood login and no paid API keys are required to run this app.
Everything here can be safely tweaked without touching other files.
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Where the manual P&L tracker (see ui/pnl_tracker.py) stores its local log
# files. This directory holds personal trade figures, not app code -- make
# sure it's listed in .gitignore so it's never pushed to a public repo.
PNL_DATA_DIR = os.path.join(PROJECT_ROOT, "pnl_data")

# ---------------------------------------------------------------------------
# Crypto / "futures" tab
# ---------------------------------------------------------------------------
# Data comes from a public crypto exchange (via ccxt) rather than Robinhood
# itself, since Robinhood has no public market-data API. Kraken's public
# endpoints require no API key/login and are a very close proxy for spot
# crypto prices (crypto is fungible/arbitraged across venues, so BTC-USD on
# Kraken tracks BTC-USD on Robinhood to within a few basis points).
CRYPTO_EXCHANGE = "kraken"

CRYPTO_SYMBOLS = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "DOGE/USD",
    "XRP/USD",
    "LTC/USD",
    "HYPE/USD",
    "BNB/USD",
]

# Prices below this show 4 decimal places instead of 2 (crypto tokens can
# trade at low unit prices where 2 decimals hides real price movement).
CRYPTO_DECIMAL_THRESHOLD = 100

# Robinhood settles perpetual-futures P&L every 15 minutes, so that is the
# default prediction horizon on the futures tab.
FUTURES_HORIZON_MINUTES = 15

# Spot price polling interval choices shown in the UI dropdown (seconds)
SPOT_UPDATE_INTERVALS_SEC = [1, 2, 5, 10, 15, 30, 60]
DEFAULT_SPOT_UPDATE_INTERVAL_SEC = 5

# Candle timeframe used to build the price chart / indicators
CRYPTO_CHART_TIMEFRAME = "1m"
CRYPTO_CHART_LOOKBACK_BARS = 180  # 3 hours of 1-minute candles

# How often the AI signal engine recomputes bullish/bearish % (seconds)
CRYPTO_SIGNAL_REFRESH_SEC = 60

# ---------------------------------------------------------------------------
# Options / stock tab
# ---------------------------------------------------------------------------
DEFAULT_STOCK_SYMBOL = "AAPL"

# Selectable prediction horizons for the options tab, (label, minutes)
OPTIONS_TIMEFRAMES = [
    ("1 Hour", 60),
    ("2 Hours", 120),
    ("3 Hours", 180),
    ("1 Day", 60 * 24),
    ("2 Days", 60 * 24 * 2),
    ("3 Days", 60 * 24 * 3),
    ("1 Week", 60 * 24 * 5),
]

STOCK_SPOT_UPDATE_INTERVALS_SEC = [5, 10, 15, 30, 60, 120]
DEFAULT_STOCK_UPDATE_INTERVAL_SEC = 15

# Candle timeframe/lookback used for the underlying's chart + indicators.
# yfinance restricts how far back intraday intervals go, so we pick a
# resolution appropriate to the chosen horizon at runtime (see
# data/stock_source.py: resolve_chart_params).
STOCK_SIGNAL_REFRESH_SEC = 60

# ---------------------------------------------------------------------------
# Signal engine weights (0-1, should roughly sum to 1 across the group used)
# ---------------------------------------------------------------------------
INDICATOR_WEIGHTS = {
    "trend_ema": 0.20,      # fast EMA vs slow EMA
    "macd": 0.18,           # MACD histogram / cross
    "rsi": 0.14,             # RSI momentum
    "stochastic": 0.10,      # stochastic oscillator
    "vwap": 0.14,             # price vs VWAP
    "bollinger": 0.10,        # position within Bollinger Bands
    "volume": 0.14,           # volume trend / spikes
}

# Confidence is the raw distance from a 50/50 coin-flip, shown on the full
# 0-100 scale (no artificial compression) so the numbers carry real
# resolution for decision-making. Nothing here is a statistically validated
# probability of being correct -- it's a measure of how one-sided the
# current indicator mix is, not a guarantee.
CONFIDENCE_FLOOR = 0.0
CONFIDENCE_CEIL = 100.0

# ---------------------------------------------------------------------------
# Optional ML-based direction signal (see analysis/ml_model.py)
# ---------------------------------------------------------------------------
# Purely additive: if no trained model exists yet, the app runs exactly as
# it always has (the 7 rule-based indicators only). Run train_crypto_model.py
# / train_stock_model.py to train one; re-run periodically to retrain on
# fresher data, since market patterns drift over time.
ML_MODEL_DIR = os.path.join(PROJECT_ROOT, "ml_models")
ML_CRYPTO_MODEL_NAME = "crypto_direction"
ML_STOCK_MODEL_NAME = "stock_direction"

# Relative weight of the ML signal in the blended vote, alongside
# INDICATOR_WEIGHTS (which sum to 1.0). Set independently per model since
# they've shown very different real edges in practice: crypto has
# consistently beaten its naive baseline by a small but real margin, while
# stock hasn't shown a meaningful edge yet -- so stock's influence is
# turned down accordingly. Revisit these once you've watched more retrains
# accumulate (see the Model History tab). 0.5 means that signal carries
# roughly 1/3 of the total vote (0.5 / (1.0 + 0.5)) once trained; 0.15
# means roughly 1/8 (0.15 / (1.0 + 0.15)).
ML_SIGNAL_WEIGHT_CRYPTO = 0.5
ML_SIGNAL_WEIGHT_STOCK = 0.15

# Crypto model: predict direction this many 1-minute bars ahead (matches
# the 15-min futures settlement window).
ML_CRYPTO_HORIZON_BARS = 15

# Stock model: trained on hourly bars (not daily -- daily bars barely
# change hour-to-hour, which wasted most of the hourly auto-retrains,
# since they'd just be re-training on nearly identical data each time).
# Horizon of 1 bar = predicting ~1 hour ahead, matching the shortest
# selectable timeframe on the Stock Options tab; treat it as most relevant
# to the 1h/2h/3h selections, less so for the multi-day ones.
ML_STOCK_BAR_INTERVAL = "1h"     # yfinance interval string
ML_STOCK_BAR_MINUTES = 60         # minutes per bar -- used to convert horizon_bars to minutes for live tracking
ML_STOCK_HISTORY_PERIOD = "730d"   # yfinance's actual max lookback at 1h resolution (Yahoo's own limit, not a choice)
ML_STOCK_HORIZON_BARS = 1
# Mixed large-cap + small-cap basket, on purpose: the large-cap-only version
# showed essentially zero edge over the naive baseline (large-caps are
# heavily arbitraged/efficiently priced), so this adds 10 genuinely smaller,
# less-followed names across different sectors to see whether there's more
# learnable signal there. More total tickers also means more pooled
# training data, at the cost of longer training runs.
ML_STOCK_TRAINING_TICKERS = [
    # Large-cap (original 10)
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "XOM", "JNJ",
    # Small-cap additions -- spread across defense, healthcare, clean
    # energy, materials, biotech, industrials, semis, and telecom
    "KTOS", "GH", "BE", "HL", "BBIO", "GRC", "SMTC", "IONQ", "SATS", "FN",
]

# --- Automatic hourly retraining -----------------------------------------
# Runs entirely in the background while the app is open; there's no
# separate background service, so nothing retrains while the app is closed.
ML_AUTO_RETRAIN_ENABLED = True
ML_AUTO_RETRAIN_INTERVAL_HOURS = 1
# A freshly-trained candidate must beat the currently active version by at
# least this many percentage points (evaluated on the SAME held-out test
# set, for a fair comparison) to get auto-promoted. Guards against
# replacing a good model due to random noise from one training run to the
# next -- most hourly runs will NOT result in a change, since an hour of
# extra data rarely shifts a model meaningfully.
ML_PROMOTION_MARGIN = 0.005
# How many trained versions to keep on disk per model (the active version
# is always kept regardless of this limit).
ML_VERSION_RETENTION = 30

# --- Live prediction accuracy tracking ------------------------------------
# Every live prediction the active model makes gets logged here, then
# resolved once its horizon has passed -- a real-world accuracy record,
# separate from (and a check against) the backtested training metrics.
ML_PREDICTIONS_DATA_DIR = os.path.join(PROJECT_ROOT, "ml_predictions")

APP_NAME = "Market Signal Dashboard"
APP_VERSION = "1.7.1"

# Auto-update checker settings. Leave UPDATE_REPO_OWNER blank to disable the
# checker entirely (it silently does nothing if unconfigured). See
# updater.py for full one-time setup instructions.
UPDATE_REPO_OWNER = "AaronScottAI"
UPDATE_REPO_NAME = "AI_Market_Signals"
UPDATE_BRANCH = "main"

DISCLAIMER = (
    "Educational / informational tool only. Not financial advice, not a "
    "Robinhood product, and not affiliated with Robinhood. Technical "
    "indicators describe historical price action and do not guarantee "
    "future results. Futures and options are leveraged, high-risk "
    "instruments -- you can lose money quickly. Trade at your own risk."
)
