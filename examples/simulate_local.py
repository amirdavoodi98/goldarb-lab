"""Run a strategy-independent paper order with no network access."""

from datetime import UTC, datetime
from decimal import Decimal

from goldarb.simulation import LocalSimulator, MarketSnapshot, Quote

with LocalSimulator("paper.sqlite3") as simulator:
    account = simulator.create_account(
        initial_cash="1000000000",
        fee_rate="0.0005",
        allow_short=True,
        label="offline strategy",
    )
    simulator.feed(
        MarketSnapshot(
            event_id="example-1",
            timestamp=datetime.now(UTC),
            quotes=(
                Quote(
                    symbol="طلا",
                    bid=Decimal(249900),
                    ask=Decimal(250000),
                    bid_size=Decimal(500),
                    ask_size=Decimal(600),
                ),
            ),
        )
    )
    print(
        simulator.submit_order(
            account.id,
            symbol="طلا",
            side="BUY",
            quantity="100",
            client_order_id="example-buy-1",
        )
    )
    print(simulator.portfolio(account.id))
