from datetime import date, timedelta
from goldarb import LabClient

end = date.today()
start = end - timedelta(days=3)

with LabClient.login(
    base_url="https://goldarb.ir",
    username="amirmd98",
    password="...", # add your password here
    timeout=180.0,
) as c:
    bars = c.fund.candles("طلا", start=start, end=end, grain="1s")

print(len(bars))
print(bars[0] if bars else "empty")
print(bars[-1] if bars else "")