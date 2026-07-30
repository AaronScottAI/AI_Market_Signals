"""
Central configuration for the dashboard.

No Robinhood login and no paid API keys are required to run this app.
Everything here can be safely tweaked without touching other files.
"""

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

APP_NAME = "Market Signal Dashboard"
APP_VERSION = "1.0.0"

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
