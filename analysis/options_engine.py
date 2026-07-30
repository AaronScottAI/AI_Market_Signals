"""
Options-tab analysis. Reuses the core technical signal engine on the
underlying stock, then layers on options-chain context (IV skew, put/call
volume ratio) when that data is available from the options data source.
"""
from __future__ import annotations
from dataclasses import dataclass

import pandas as pd

from analysis.signal_engine import analyze, SignalFlag, SignalResult, _clip


@dataclass
class OptionsAnalysis:
    core: SignalResult
    iv_skew_signal: SignalFlag | None
    put_call_signal: SignalFlag | None
    suggested_contract_type: str    # "CALL" or "PUT"
    suggested_moneyness: str        # e.g. "slightly OTM"
    notes: list


def _iv_skew_flag(chain_summary: dict | None) -> SignalFlag | None:
    if not chain_summary or "call_iv_avg" not in chain_summary or "put_iv_avg" not in chain_summary:
        return None
    call_iv = chain_summary["call_iv_avg"]
    put_iv = chain_summary["put_iv_avg"]
    if not call_iv or not put_iv:
        return None
    skew = (put_iv - call_iv) / ((put_iv + call_iv) / 2) * 100
    # Rich put IV relative to call IV = market paying up for downside protection (bearish lean)
    direction = "bearish" if skew > 3 else ("bullish" if skew < -3 else "neutral")
    active = abs(skew) > 3
    detail = f"Put IV {'>' if skew>0 else '<'} Call IV by {abs(skew):.1f}%"
    return SignalFlag("iv_skew", "Options IV skew", active, direction, detail)


def _put_call_flag(chain_summary: dict | None) -> SignalFlag | None:
    if not chain_summary or "call_volume" not in chain_summary or "put_volume" not in chain_summary:
        return None
    call_vol = chain_summary["call_volume"] or 0
    put_vol = chain_summary["put_volume"] or 0
    if call_vol + put_vol == 0:
        return None
    ratio = put_vol / call_vol if call_vol else float("inf")
    # High put/call ratio => more bearish positioning (or hedging)
    direction = "bearish" if ratio > 1.15 else ("bullish" if ratio < 0.85 else "neutral")
    active = ratio > 1.15 or ratio < 0.85
    detail = f"Put/Call volume ratio {ratio:.2f}"
    return SignalFlag("put_call_ratio", "Put/Call volume ratio", active, direction, detail)


def analyze_options(
    df_with_indicators: pd.DataFrame,
    horizon_minutes: int,
    chain_summary: dict | None = None,
    ml_model_name: str | None = None,
    symbol: str | None = None,
) -> OptionsAnalysis:
    core = analyze(df_with_indicators, horizon_minutes, ml_model_name=ml_model_name, symbol=symbol)

    iv_flag = _iv_skew_flag(chain_summary)
    pc_flag = _put_call_flag(chain_summary)

    # Nudge confidence slightly if options-chain signals agree/disagree with
    # the technical direction. Small effect on purpose -- chain data is
    # supplementary context, not the primary driver.
    nudge = 0.0
    for flag in (iv_flag, pc_flag):
        if flag and flag.active:
            if flag.direction == core.direction.lower().replace("up", "bullish").replace("down", "bearish"):
                nudge += 1.5
            elif flag.direction != "neutral":
                nudge -= 1.5

    adj_confidence = _clip(core.confidence_pct + nudge, 0.0, 100.0)
    core.confidence_pct = round(adj_confidence, 1)

    suggested_contract_type = "CALL" if core.direction == "UP" else "PUT"

    # Rough moneyness suggestion driven purely by confidence level -- higher
    # conviction => can afford to go closer to the money / slightly ITM;
    # lower conviction => cheaper OTM lottery-ticket-style risk is more
    # appropriate. This is a general framing, not a specific strike price.
    # Thresholds are scaled for the full 0-100 confidence range.
    if core.confidence_pct >= 55:
        moneyness = "at-the-money or slightly in-the-money"
    elif core.confidence_pct >= 25:
        moneyness = "slightly out-of-the-money"
    else:
        moneyness = "consider skipping or sizing very small -- conviction is low"

    notes = [
        "Contract type/strike guidance is general, not a specific recommendation.",
        "Check the actual bid/ask spread and open interest before entering -- "
        "wide spreads on illiquid strikes can erase the theoretical edge.",
        "Time decay (theta) works against long option holders every day the "
        "position is open, independent of these directional signals.",
    ]

    return OptionsAnalysis(
        core=core,
        iv_skew_signal=iv_flag,
        put_call_signal=pc_flag,
        suggested_contract_type=suggested_contract_type,
        suggested_moneyness=moneyness,
        notes=notes,
    )
