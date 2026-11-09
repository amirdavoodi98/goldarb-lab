"""Public signal dictionaries retain their shape across typed internal selection."""

import json

import pytest

from goldarb.signals.bubble_rank import compute_rankings, empty_bubble_rank
from goldarb.signals.pair_spread import compute_pair_spread_stats


def test_ranking_ties_and_missing_scores_preserve_order_and_payload():
    result = compute_rankings(
        {"B": [0.0, 0.0], "missing": [], "A": [0.0, 0.0]}, min_samples=2
    )
    assert [row["symbol"] for row in result["rankings"]] == ["A", "B", "missing"]
    assert result["best_pair"] == {
        "active": False,
        "long": "B",
        "short": "A",
        "long_score": 0.0,
        "short_score": 0.0,
        "gap": 0.0,
        "label_fa": "بدون سیگنال جفتی",
    }
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("history", [{}, {"A": []}, {"A": [1.0, 0.0], "B": []}])
def test_ranking_requires_two_numeric_candidates(history):
    result = compute_rankings(history, min_samples=2)
    assert result["best_pair"] is None
    if not history:
        assert result == empty_bubble_rank()


@pytest.mark.parametrize(
    ("series", "threshold", "status", "active"),
    [([], 2.0, "insufficient_samples", False),
     ([0.0, 0.0, 0.0], 2.0, "zero_variance", False),
     ([0.0, 1.0, 5.0], 10.0, "ok", False),
     ([0.0, 1.0, 5.0], 0.5, "ok", True)],
)
def test_pair_signal_optional_keys_and_json_contract(series, threshold, status, active):
    result = compute_pair_spread_stats(
        fund_a="A", fund_b="B", series=series,
        premium_a=5.0, premium_b=0.0, price_a=None, price_b=None,
        min_samples=3, z_threshold=threshold,
    )
    assert result["status"] == status
    signal = result["pair_signal"]
    assert signal["active"] is active
    assert ("premium_long" in signal) is active
    assert ("premium_short" in signal) is active
    assert result["spread_pct"] is None
    assert json.loads(json.dumps(result)) == result
