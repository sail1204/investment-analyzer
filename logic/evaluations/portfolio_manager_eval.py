from __future__ import annotations

from logic.evaluations.common import EvaluationResult, is_nonempty_string


def evaluate_portfolio_manager_output(output: dict) -> EvaluationResult:
    issues: list[str] = []

    sells = output.get("sells")
    buys = output.get("buys")
    commentary = output.get("portfolio_commentary", "")

    if not isinstance(sells, list):
        issues.append("invalid_sells")
        sells = []
    if not isinstance(buys, list):
        issues.append("invalid_buys")
        buys = []

    normalized_sells = []
    for sell in sells:
        if not isinstance(sell, dict):
            issues.append("non_dict_sell")
            continue
        ticker = str(sell.get("ticker", "")).strip().upper()
        reasoning = str(sell.get("reasoning", "")).strip()
        if not ticker:
            issues.append("sell_missing_ticker")
            continue
        if not reasoning:
            issues.append("sell_missing_reasoning")
        normalized_sells.append({"ticker": ticker, "reasoning": reasoning})

    normalized_buys = []
    for buy in buys:
        if not isinstance(buy, dict):
            issues.append("non_dict_buy")
            continue
        ticker = str(buy.get("ticker", "")).strip().upper()
        reasoning = str(buy.get("reasoning", "")).strip()
        try:
            points = float(buy.get("points", 0))
        except (TypeError, ValueError):
            points = 0.0
            issues.append("buy_invalid_points")
        if not ticker:
            issues.append("buy_missing_ticker")
            continue
        if not reasoning:
            issues.append("buy_missing_reasoning")
        if points <= 0:
            issues.append("buy_non_positive_points")
            continue
        normalized_buys.append({"ticker": ticker, "points": round(points, 2), "reasoning": reasoning})

    if not is_nonempty_string(commentary, min_len=5):
        issues.append("missing_portfolio_commentary")
        commentary = "No portfolio commentary provided."

    should_retry = any(
        issue in issues
        for issue in (
            "invalid_sells",
            "invalid_buys",
            "buy_invalid_points",
            "buy_missing_ticker",
            "sell_missing_ticker",
        )
    )

    return EvaluationResult(
        should_retry=should_retry,
        issues=issues,
        normalized_output={
            "sells": normalized_sells,
            "buys": normalized_buys,
            "portfolio_commentary": commentary,
        },
    )
