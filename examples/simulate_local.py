"""Run a strategy-independent paper order with no network access."""

from datetime import UTC, datetime
from decimal import Decimal

from goldarb.simulation import LocalSimulator, MarketSnapshot, Quote, get_broker

broker = get_broker("agah")

with LocalSimulator("paper.sqlite3", broker=broker) as simulator:
    account = simulator.create_account(
        initial_cash="1000000000",
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
    order = broker.submit_buy(
        account,
        symbol="طلا",
        quantity="100",
        client_order_id="example-buy-1",
    )
    print(order)
    resting = broker.submit_sell(
        account,
        symbol="طلا",
        quantity="10",
        order_type="LIMIT",
        limit_price="300000",
        client_order_id="example-sell-1",
    )
    print(broker.cancel_order(resting))
    print(broker.list_orders(account))
    print(broker.list_holdings(account))
    print(broker.get_cash(account))
    print(simulator.portfolio(account.id))
