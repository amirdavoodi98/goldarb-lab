"""Immutable domain results and named ledger records preserve SDK behavior."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from goldarb.gateway import RecordingOrderGateway
from goldarb.signals import evaluate_pair_spread, evaluate_rankings
from goldarb.simulation.models import MarketSnapshot, Quote


def test_ranking_domain_is_immutable_and_serialization_is_detached():
    result = evaluate_rankings({"A": [0.0, -2.0], "B": [0.0, 2.0]}, min_samples=2)
    assert result.best_pair is not None
    assert result.best_pair.long_symbol == "A"
    assert result.best_pair.short_symbol == "B"
    with pytest.raises(FrozenInstanceError):
        result.best_pair.gap = 99
    payload = result.to_dict()
    payload["rankings"][0]["symbol"] = "changed"
    payload["rankings"].clear()
    assert result.rankings[0].symbol == "A"
    assert len(result.to_dict()["rankings"]) == 2


@pytest.mark.parametrize("series", [[], [0.0, 0.0, 0.0], [0.0, 1.0, 5.0]])
def test_spread_domain_keeps_optional_signal_serialization(series):
    result = evaluate_pair_spread(
        fund_a="A",
        fund_b="B",
        series=series,
        premium_a=5.0,
        premium_b=0.0,
        price_a=None,
        price_b=None,
        min_samples=3,
        z_threshold=0.5,
    )
    signal = result.pair_signal
    assert ("premium_long" in signal.to_dict()) is signal.active
    if signal.active:
        assert signal.long_symbol == "B"
        assert signal.short_symbol == "A"
    with pytest.raises(FrozenInstanceError):
        result.status = "ok"


@pytest.mark.parametrize(
    ("first_side", "second_side", "second_qty", "second_price", "quantity", "cost", "realized"),
    [
        ("BUY", "SELL", "1", "120", "1", "100", "20"),
        ("BUY", "SELL", "3", "120", "-1", "120", "40"),
        ("SELL", "BUY", "1", "80", "-1", "100", "20"),
        ("SELL", "BUY", "3", "80", "1", "80", "40"),
        ("BUY", "SELL", "2", "120", "0", "0", "40"),
    ],
)
def test_recording_ledger_partial_close_and_direction_changes(
    first_side, second_side, second_qty, second_price, quantity, cost, realized
):
    gateway = RecordingOrderGateway()
    account = gateway.ledger.create_account(initial_cash="10000", allow_short=True)
    for index, (side, qty, price) in enumerate(
        [(first_side, "2", "100"), (second_side, second_qty, second_price)]
    ):
        gateway.note_market(
            MarketSnapshot(
                event_id=str(index),
                timestamp=datetime(2026, 8, 29, 12, index, tzinfo=UTC),
                quotes=(Quote(symbol="A", last=Decimal(price)),),
            )
        )
        gateway.submit(symbol="A", side=side, quantity=qty)
        gateway.release_fills()
    portfolio = gateway.ledger.portfolio(account.id)
    assert portfolio.realized_pnl == Decimal(realized)
    assert portfolio.equity == Decimal("10040")
    if quantity == "0":
        assert portfolio.positions == ()
    else:
        (position,) = portfolio.positions
        assert position.quantity == Decimal(quantity)
        assert position.average_cost == Decimal(cost)


def test_engine_accepts_structural_observer_without_other_optional_hooks():
    from goldarb.engine import SimulationLoop
    from goldarb.execution import NoLatency, NoSlippage
    from goldarb.simulation import LocalSimulator
    from goldarb.strategy import Strategy

    seen = []

    class ObserverGateway:
        # This custom gateway deliberately implements no bind/release capability.
        def note_market(self, snapshot):
            seen.append(snapshot.event_id)

        def submit(self, **kwargs):
            raise AssertionError("no orders expected")

        def cancel(self, order_id):
            raise AssertionError("no cancels expected")

        def positions(self):
            return ()

        def cash(self):
            return Decimal("10000")

    class NoTrades(Strategy):
        def on_market_data(self, ctx):
            pass

    with LocalSimulator(":memory:") as broker:
        account = broker.create_account(initial_cash="10000")
        loop = SimulationLoop(
            broker=broker,
            account_id=account.id,
            strategy=NoTrades(),
            slippage=NoSlippage(),
            latency=NoLatency(),
            gateway=ObserverGateway(),
        )
        loop.process(
            MarketSnapshot(
                event_id="observed",
                timestamp=datetime(2026, 8, 29, 12, tzinfo=UTC),
                quotes=(),
            )
        )
        loop.finish()
    assert seen == ["observed"]
