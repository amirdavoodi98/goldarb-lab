"""Submit a paper order to the main server from user-owned strategy code."""

from goldarb import LabClient

with LabClient.from_env() as client:
    account = client.simulation.create_account(
        initial_cash="1000000000",
        fee_rate="0.0005",
        allow_short=True,
        label="remote strategy",
    )
    order = client.simulation.submit_order(
        account.id,
        symbol="طلا",
        side="BUY",
        quantity="100",
        order_type="LIMIT",
        limit_price="250000",
        client_order_id="example-buy-1",
    )
    print(order)
    print(client.simulation.portfolio(account.id))
