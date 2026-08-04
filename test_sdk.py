from goldarb import LabClient

client = LabClient.login(
    base_url="https://goldarb.ir",
    username="shahrzad",
    password="3p41IKv3KwJi",
)

bars = client.fund.candles(
    symbol="طلا",
    start="2026-07-01",
    end="2026-07-03",
    grain="1m",
)

print(bars)