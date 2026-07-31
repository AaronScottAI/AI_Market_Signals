"""
Trains a new candidate crypto direction model and, if it's actually more
accurate than whatever's currently active, promotes it. Run this yourself
-- it needs internet access to pull historical prices from Kraken, which
this sandboxed build environment doesn't have, so this has been tested
with synthetic data but you'll see the first *real* results when you run
it.

    python train_crypto_model.py

This is also exactly what runs automatically once an hour while the app is
open (see config.ML_AUTO_RETRAIN_ENABLED / ui/ml_autotrain.py) -- running
this script by hand is only useful for triggering a retrain immediately,
or for reading the detailed printed output.

Read the results honestly: "accuracy" alone doesn't tell you much if the
market mostly moved one direction during the training window -- that's why
this also prints a naive-baseline comparison (always guessing the majority
class), a comparison against whatever model is currently active, and a
calibration table (do 70%-confidence predictions actually come true ~70%
of the time?). Every trained version -- promoted or not -- is kept and
viewable on the "Model History" tab in the app, where you can also roll
back to an older version manually if you think it worked better.
"""
from __future__ import annotations
import sys

import config
from analysis import ml_training, ml_versions

BARS_PER_SYMBOL = 8000  # ~5.5 days of 1-minute bars per symbol


def main():
    print(f"Training crypto direction model across {len(config.CRYPTO_SYMBOLS)} symbols...")
    print(f"Target horizon: {config.ML_CRYPTO_HORIZON_BARS} one-minute bars ahead\n")

    pooled = ml_training.build_pooled_frame(
        config.CRYPTO_SYMBOLS,
        fetch_fn=lambda sym: ml_training.fetch_crypto_symbol_history(
            sym, config.CRYPTO_CHART_TIMEFRAME, BARS_PER_SYMBOL,
        ),
        horizon_bars=config.ML_CRYPTO_HORIZON_BARS,
    )
    if pooled is None:
        print("\nNo usable data was fetched from any symbol -- check your internet connection and try again.")
        sys.exit(1)

    print(f"\nPooled training set: {len(pooled)} rows across {pooled['symbol'].nunique()} symbols")

    candidate, metrics, train_df, test_df = ml_training.train_candidate(pooled)
    if candidate is None:
        print("\nNot enough data to train reliably yet. Try increasing BARS_PER_SYMBOL at the "
              "top of this script, or just run it again later once more history has accumulated.")
        sys.exit(1)

    print(f"Time-based split: {len(train_df)} train rows, {len(test_df)} test rows "
          f"(test rows are always chronologically after their symbol's training rows -- no lookahead)")
    print("\nEvaluating candidate on held-out (unseen) data...\n")
    _print_results(metrics)

    active_metrics = ml_training.evaluate_active_model(config.ML_CRYPTO_MODEL_NAME, test_df)
    promote = _decide_promotion(metrics, active_metrics)
    metrics["compared_active_accuracy"] = active_metrics["accuracy"] if active_metrics else None
    metrics["promoted"] = promote

    version_id = ml_versions.register_version(config.ML_CRYPTO_MODEL_NAME, candidate, metrics, activate=promote)
    print(f"\nSaved as version {version_id}.")
    if promote:
        print("PROMOTED -- this is now the active model the Crypto Futures tab uses.")
    else:
        print("NOT promoted -- kept alongside previous versions for review, but the "
              "previously active model is still in use. See the Model History tab "
              "to compare or manually activate this version anyway if you disagree.")


def _decide_promotion(candidate_metrics: dict, active_metrics: dict | None) -> bool:
    baseline = candidate_metrics.get("baseline_majority_class_accuracy")
    accuracy = candidate_metrics.get("accuracy")
    if baseline is not None and accuracy is not None:
        gap = accuracy - baseline
        passes = ml_training.passes_baseline_check(candidate_metrics)
        print(f"Baseline check: candidate is {gap:+.1%} vs. the naive baseline "
              f"(must be within {config.ML_MAX_BASELINE_UNDERPERFORMANCE:.1%} of it, or above) -- "
              f"{'PASSES' if passes else 'FAILS'}")
        if not passes:
            print("Candidate meaningfully underperforms trivially guessing the trend continues -- "
                  "will NOT be promoted, regardless of how it compares to the active model.")

    if active_metrics is not None:
        diff = candidate_metrics["accuracy"] - active_metrics["accuracy"]
        print(f"Currently active model's accuracy on this SAME fresh test set: {active_metrics['accuracy']:.1%}")
        print(f"New candidate's accuracy:                                     {candidate_metrics['accuracy']:.1%}")
        print(f"Difference: {diff:+.1%}  (promotion also requires beating the active model by at "
              f"least {config.ML_PROMOTION_MARGIN:.1%})")
    else:
        print("No currently active model to compare against -- clearing the baseline bar is "
              "the only requirement in that case.")

    return ml_training.decide_promotion(candidate_metrics, active_metrics)


def _print_results(results: dict):
    if "error" in results:
        print(f"  {results['error']}")
        return
    print(f"  Test set size:              {results['n_test']} rows")
    print(f"  Candidate accuracy:         {results['accuracy']:.1%}")
    print(f"  Naive baseline accuracy:    {results['baseline_majority_class_accuracy']:.1%}  "
          f"(always guessing the more common outcome)")
    diff = results['accuracy'] - results['baseline_majority_class_accuracy']
    verdict = "beats" if diff > 0.01 else ("roughly matches" if diff > -0.01 else "UNDERPERFORMS")
    print(f"  -> Candidate {verdict} the naive baseline by {diff:+.1%}")
    print(f"  Precision (of 'UP' calls, how many were right):  {results['precision']:.1%}")
    print(f"  Recall (of actual 'UP' moves, how many caught):  {results['recall']:.1%}")
    print(f"  F1 score:                   {results['f1']:.3f}")
    print()
    print("  Calibration (is a 70% prediction actually right ~70% of the time?):")
    print(f"  {'Confidence bucket':<20}{'# predictions':<16}{'Avg predicted':<16}{'Actual up-rate'}")
    for row in results["calibration"]:
        print(f"  {row['bucket']:<20}{row['n']:<16}{row['avg_predicted_confidence']:<16.1%}{row['actual_up_rate']:.1%}")


if __name__ == "__main__":
    main()
