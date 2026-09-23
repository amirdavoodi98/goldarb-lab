"""Unit tests for replaceable fee, slippage, and latency models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldarb.execution import (
    FixedLatency,
    FixedSlippage,
    LocalFeedExecution,
    LocalMarketIngress,
    NoLatency,
    NoOpMarketIngress,
    NoSlippage,
    PercentFee,
    PercentSlippage,
    ServerSideExecution,
)
from goldarb.simulation.engine import fee_for
from goldarb.simulation.models import MarketSnapshot, Quote


def _snapshot(*, last="100", bid=None, ask=None) -> MarketSnapshot:
    return MarketSnapshot(
        event_id="e1",
        timestamp=datetime(2026, 8, 29, 9, 0, tzinfo=UTC),
        quotes=(
            Quote(
                symbol="طلا",
                last=Decimal(last),
                bid=None if bid is None else Decimal(bid),
                ask=None if ask is None else Decimal(ask),
            ),
        ),
    )


def test_percent_fee_matches_simulator_formula():
    fee = PercentFee("0.001")
    assert fee.rate() == Decimal("0.001")
    assert fee.fee_for(quantity=Decimal(10), price=Decimal(97)) == fee_for(
        Decimal(10), Decimal(97), Decimal("0.001")
    )
    assert fee.config() == {"fee_rate": "0.001"}


def test_no_slippage_keeps_quotes():
    snapshot = _snapshot(bid="99", ask="101")
    assert NoSlippage().apply_snapshot(snapshot) is snapshot


def test_fixed_slippage_widens_book():
    slipped = FixedSlippage("2").apply_snapshot(_snapshot(bid="100", ask="102"))
    quote = slipped.quotes[0]
    assert quote.bid == Decimal("98")
    assert quote.ask == Decimal("104")
    assert slipped.event_id == "e1"


def test_percent_slippage_synthesizes_bid_ask_from_last():
    slipped = PercentSlippage("0.01").apply_snapshot(_snapshot(last="100"))
    quote = slipped.quotes[0]
    assert quote.bid == Decimal("99")
    assert quote.ask == Decimal("101")
    assert quote.last == Decimal("100")


def test_noop_market_ingress_alias():
    assert NoOpMarketIngress is ServerSideExecution
    assert LocalMarketIngress().name == "LocalMarketIngress"
    assert NoLatency().submit_delay().total_seconds() == 0


def test_fixed_latency_shifts_timestamp_only():
    snapshot = _snapshot()
    delayed = FixedLatency(100).apply_snapshot(snapshot)
    assert delayed.timestamp - snapshot.timestamp == timedelta(milliseconds=100)
    assert delayed.event_id == snapshot.event_id
    assert delayed.quotes == snapshot.quotes
    assert NoLatency().apply_snapshot(snapshot) is snapshot

