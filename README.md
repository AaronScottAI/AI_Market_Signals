# Market Signal Dashboard

A Python desktop app (PySide6) with two tabs:

- **Crypto Futures** — live spot price (selectable update interval), a
  candlestick chart, and an AI-style direction call for Robinhood's
  15‑minute perpetual-futures settlement window, with confidence %,
  bullish/bearish split (updated every minute, with a rolling history
  chart), breakout/breakdown odds, and a list of which technical signals
  are currently firing.
- **Stock Options** — watch any stock, pick a horizon (1h/2h/3h/1d/2d/3d/
  1wk), and get a direction call with confidence %, a live chart with
  entry/take-profit/stop-loss levels marked on it, and options-chain
  context (IV skew, put/call ratio) folded into the call.

## Important things to know before you run this

1. **Not connected to your Robinhood account, on purpose.** Robinhood has
   no public API for market data or automated trading. The only way to
   pull data programmatically "from Robinhood" is an unofficial,
   reverse-engineered library that logs in with your real credentials —
   doing that violates Robinhood's Terms of Service and can get accounts
   flagged. This app instead uses legitimate, free, public market-data
   APIs (a crypto exchange for crypto prices, Yahoo Finance for stocks/
   options). Crypto prices are consistent across venues to within a few
   basis points, so this is a very close proxy for what you'd see in the
   Robinhood app. **You still place any actual trades yourself, in the
   Robinhood app.**
2. **The "AI" is a transparent, rules-based scoring model** — RSI, MACD,
   EMA trend, Bollinger Bands, VWAP, stochastic oscillator, and volume,
   combined into a weighted vote (see `analysis/signal_engine.py`). It is
   **not** a trained model with a demonstrated forecasting track record,
   and short-horizon price direction (especially 15-minute crypto) is
   genuinely hard to predict. Treat every output as decision support, not
   a guarantee. Confidence percentages describe how one-sided the current
   indicator mix is, not a statistically validated probability of being
   right.
3. **Futures and options are leveraged, high-risk instruments.** It's
   possible to lose your entire position (and more, with margin) quickly.
   Nothing in this app is financial advice.

## Optional ML-based direction signal (auto-retrains hourly)

Off until a model exists. To bootstrap the very first version yourself:

```bash
python train_crypto_model.py    # needs internet access; takes a few minutes
python train_stock_model.py     # same
```

After that, **it retrains itself automatically roughly once an hour** while
the app is open (see `config.ML_AUTO_RETRAIN_ENABLED` / `ui/ml_autotrain.py`)
-- no need to run the scripts by hand again unless you want to trigger a
retrain immediately or read the detailed printed output. There's no
separate background service, so nothing retrains while the app is closed.

**A new version only replaces the active one if it's actually more
accurate** -- each retrain trains a candidate, evaluates it on a freshly
held-out test set, evaluates the *currently active* model on that same
test set for a fair comparison, and only promotes the candidate if it
beats the active model by at least `config.ML_PROMOTION_MARGIN` (0.5
percentage points by default). Most hourly runs won't change anything,
since an extra hour of data rarely shifts a model meaningfully -- that's
expected, not a bug.

**Every trained version is kept**, whether promoted or not, and reviewable
on the **Model History** tab: training date, backtested accuracy, how it
compared to a naive baseline, and (once enough time has passed) real
"live" tracked accuracy from actual predictions made during normal use. If
you think an older version actually performed better, click **"Activate
this version"** to roll back to it manually -- it stays active until either
you switch again or a future auto-retrain beats it.

Once trained, the active model's prediction folds into the same
weighted-vote system as the 7 rule-based indicators (visible in the
Signals list as "ML model prediction"), influencing both the direction
call and confidence %. It does **not** touch the Crypto Futures tab's
Target price, which stays exactly what you asked for earlier -- the real
observed price at window start, no prediction math.

Both models are trained on a *pooled* basket of several symbols (all 8
configured crypto pairs; a diversified 10-stock basket for stocks) using 16
scale-invariant features (percentages/ratios/cyclical encodings, never a
raw price) -- the original 10 technical indicators, plus short/medium-term
momentum (5-bar and 20-bar returns) and cyclical time-of-day / day-of-week
encoding, added to give the model a shot at learning session and weekly
structure now that both models train on intraday bars. One pooled model
generalizes reasonably to a ticker it never specifically trained on.

**Crypto and stock carry different weights in the blended vote**
(`ML_SIGNAL_WEIGHT_CRYPTO` / `ML_SIGNAL_WEIGHT_STOCK` in `config.py`, 0.5
and 0.15 by default) rather than sharing one setting -- crypto has
consistently shown a small real edge over its naive baseline in testing,
while stock hasn't yet, so stock's influence is intentionally turned down
until it demonstrates one. Adjust these yourself once you've watched more
retrains accumulate on the Model History tab.

Note: if you already had a model trained before this 16-feature update, it
won't crash -- it just can't be meaningfully compared against a new
candidate (different number of inputs), so the very next retrain (manual
or the next automatic hourly one) will promote a fresh, schema-matching
model automatically.

Trained models live in `ml_models/*.joblib` plus a small JSON manifest per
model tracking version history; live prediction tracking lives in
`ml_predictions/`. Unlike `pnl_data/`, neither of these folders is
gitignored, since they're not personal trade data -- pushing them to your
repo means other computers get the same trained models and tracked
history automatically via the updater, instead of starting from scratch.

## Manual daily P&L tracker

Top-right corner of both tabs: click **"+ Log Trade"** to enter a trade's
cost and ending value, and it keeps a running total for the day (click the
total itself to reopen the log, review entries, or remove/clear them).
Purely a manual log -- it doesn't touch live prices or the analysis engine.

It's saved locally to `pnl_data/` so it survives closing and reopening the
app, and automatically starts fresh each new day. That folder holds your
personal trade figures, not app code, so it's listed in `.gitignore` and
will never get pushed to GitHub if you're using the auto-updater.

## Keeping every computer updated automatically

If you run this on more than one computer (or share it with someone), you
don't have to manually re-download and unzip every time something changes.
There's a built-in updater: **Help &rarr; Check for Updates...** in the app's
menu bar, and it also checks silently in the background a couple seconds
after launch.

It works by checking a plain-text `VERSION` file in a GitHub repo you
control. One-time setup (full instructions are also in `updater.py`):

1. Create a free GitHub account and a **public** repo, then upload this
   whole project folder to it (drag-and-drop via "Add file → Upload files"
   on the repo page works fine, no command line needed).
2. In `config.py`, set `UPDATE_REPO_OWNER` to your GitHub username (and
   `UPDATE_REPO_NAME`/`UPDATE_BRANCH` if you used different values).
3. Re-run `setup_and_run.bat` once so that configuration takes effect.

From then on, publishing an update to every computer is just: bump the
version number in both `VERSION` and `config.py` (`APP_VERSION`), push the
changed files to the repo, done. Each install will offer to pull it down
with one click next time it's opened.

Nothing sensitive lives in this codebase (no API keys, no credentials), so
a public repo is fine -- but the repo *will* be visible to anyone with the
link, worth knowing if that matters to you.

## Setup

Requires Python 3.10+.

### Easiest way (Windows)
Double-click **`setup_and_run.bat`**. First run installs everything
automatically (takes a minute or two); every run after that just launches
the app in a few seconds. This runs through `cmd.exe`, not PowerShell, so
it isn't affected by PowerShell's script execution policy.

### Manual way (Windows/Mac/Linux)
```bash
cd robinhood_ai_dashboard
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

No API keys, no login, no signup required to get it running. Both tabs
work with free/public data out of the box.

## How the data sources map to what you'd see on Robinhood

| Tab | Source | Notes |
|---|---|---|
| Crypto Futures | Kraken public REST API (via `ccxt`) | No key needed. Change `CRYPTO_EXCHANGE` in `config.py` to `"coinbase"`, `"binanceus"`, etc. if you prefer another venue. |
| Stock Options — quotes/chart | Yahoo Finance (via `yfinance`) | No key needed. Unofficial but reliable for personal use; refreshes on the interval you pick. |
| Stock Options — chain (IV, put/call ratio) | Yahoo Finance (via `yfinance`) | Delayed like most free sources; used as *supplementary* context, not the primary signal. |

### Optional upgrades (still free or low-cost)
- **Faster/more reliable stock quotes:** get a free [Finnhub](https://finnhub.io) API key
  (60 req/min free tier) and swap it into `data/stock_source.py`.
- **Real options greeks & tighter data:** [Tradier](https://tradier.com)'s developer
  sandbox is free and gives you real options chains with greeks/IV/open
  interest through an actual registered broker's API — a more "real"
  options data source than scraping. Swap it into `data/options_source.py`
  following the same function signatures (`fetch_chain`, `summarize_chain`).

## Customizing

Everything tunable lives in `config.py`:
- Which crypto pairs appear in the dropdown
- The list of spot-price update intervals offered in each tab
- The options prediction-timeframe choices
- How much weight each indicator gets in the scoring model
  (`INDICATOR_WEIGHTS`) — turn one down/off or add your own scorer in
  `analysis/signal_engine.py` (`_SCORERS` dict) if you want to fold in
  something else, like news sentiment or order-book depth.

## Project layout

```
robinhood_ai_dashboard/
├── main.py                 # entry point
├── config.py                # all tunables in one place
├── updater.py                 # auto-update checker (see "Keeping every computer updated")
├── VERSION                     # plain-text version number the updater checks against
├── setup_and_run.bat             # one-click Windows setup + launch
├── train_crypto_model.py           # optional: train the crypto ML signal
├── train_stock_model.py             # optional: train the stock ML signal
├── data/
│   ├── crypto_source.py      # Kraken/ccxt spot price + candles
│   ├── stock_source.py        # yfinance spot price + candles
│   └── options_source.py       # yfinance options chain
├── analysis/
│   ├── indicators.py           # RSI, MACD, EMA, Bollinger, ATR, VWAP, stochastic
│   ├── signal_engine.py         # weighted scoring -> direction/confidence/target/stop
│   ├── options_engine.py         # wraps signal_engine + adds IV/put-call context
│   ├── rti_tracker.py             # CF Benchmarks-style settlement price averaging
│   ├── ml_features.py              # scale-invariant feature engineering for the ML signal
│   ├── ml_model.py                  # optional ML model: load/predict helpers
│   ├── ml_versions.py                # versioned model registry (train/promote/rollback)
│   ├── ml_training.py                 # shared fetch/pool/train/evaluate pipeline
│   └── ml_prediction_tracker.py        # live prediction logging + real-world accuracy
└── ui/
    ├── chart_widget.py           # candlestick chart + overlays + ref lines
    ├── signal_panel.py            # direction/confidence/signals display
    ├── futures_tab.py              # Crypto Futures tab
    ├── options_tab.py               # Stock Options tab
    ├── definitions_tab.py            # signal glossary tab
    ├── pnl_tracker.py                  # manual daily P&L log (top-right of both tabs)
    ├── pnl_history_tab.py               # full P&L history page (date/time stamps + totals)
    ├── ml_history_tab.py                  # model version history + rollback page
    ├── ml_autotrain.py                     # hourly background auto-retrain controller
    ├── workers.py                     # background thread helper for network calls
    └── main_window.py                  # window shell + tabs
```

## Troubleshooting

- **"No matching distribution" / install errors** — make sure you're on a
  recent `pip` (`pip install --upgrade pip`) and Python 3.10+.
- **Enum-related `AttributeError` from PySide6 (e.g. around `Qt.DashLine`
  or `Qt.AlignCenter`)** — very rare, but if your specific PySide6 version
  requires fully-scoped enums, change occurrences like `QtCore.Qt.DashLine`
  to `QtCore.Qt.PenStyle.DashLine` and `QtCore.Qt.AlignCenter` to
  `QtCore.Qt.AlignmentFlag.AlignCenter` in `ui/chart_widget.py` and
  `ui/signal_panel.py`.
- **yfinance returning empty data / rate limited** — Yahoo occasionally
  throttles; wait a bit or lower the refresh frequency in `config.py`
  (`STOCK_SIGNAL_REFRESH_SEC`).
- **A crypto symbol isn't found** — not every pair in `config.CRYPTO_SYMBOLS`
  is guaranteed to be listed on every exchange; trim the list or switch
  `CRYPTO_EXCHANGE` in `config.py`.

---
*Educational/informational tool only. Not affiliated with, endorsed by, or
connected to Robinhood Markets, Inc. Not financial advice.*
