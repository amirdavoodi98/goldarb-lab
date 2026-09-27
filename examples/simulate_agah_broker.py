"""Trade through Agah on the local paper simulator with no network access."""

from datetime import UTC, datetime
from decimal import Decimal

from goldarb.simulation import LocalSimulator, MarketSnapshot, Quote, get_broker

broker = get_broker("agah")
print(f"{type(broker).__name__}  code={broker.code}  name={broker.display_name}")

with LocalSimulator(":memory:", broker=broker) as simulator:
    account = simulator.create_account(
        initial_cash="1000000000",
        label="agah offline",
    )
    simulator.feed(
        MarketSnapshot(
            event_id="agah-example-1",
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
    bought = broker.submit_buy(
        account,
        symbol="طلا",
        quantity="100",
        client_order_id="agah-buy-1",
    )
    print(bought)
    sold = broker.submit_sell(
        account,
        symbol="طلا",
        quantity="40",
        client_order_id="agah-sell-1",
    )
    print(sold)
    resting = broker.submit_buy(
        account,
        symbol="طلا",
        quantity="10",
        order_type="LIMIT",
        limit_price="200000",
        client_order_id="agah-rest-1",
    )
    print(broker.cancel_order(resting))
    print(broker.list_orders(account))
    print(broker.list_holdings(account))
    print(broker.get_cash(account))
