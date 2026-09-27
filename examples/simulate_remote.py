"""Submit a paper order to the main server from user-owned strategy code."""

from goldarb import LabClient
from goldarb.simulation import get_broker

broker = get_broker("mofid")

with LabClient.from_env() as client:
    client.simulation.bind(broker)
    account = client.simulation.create_account(
        initial_cash="1000000000",
        label="remote strategy",
    )
    order = broker.submit_buy(
        account,
        symbol="طلا",
        quantity="100",
        order_type="LIMIT",
        limit_price="250000",
        client_order_id="example-buy-1",
    )
    print(order)
    print(broker.list_orders(account))
    print(broker.list_holdings(account))
    print(broker.get_cash(account))
    print(client.simulation.portfolio(account.id))
