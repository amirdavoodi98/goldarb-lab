"""Run the MA-band strategy on LocalSimulator with no network access."""

from __future__ import annotations

from ma_band import run_ma_band, snapshots_from_closes

from goldarb.simulation import LocalSimulator

PRICES = ("100", "100", "100", "97", "97", "103", "103", "96", "96", "104")


def main() -> None:
    snapshots = snapshots_from_closes(PRICES)
    with LocalSimulator(":memory:") as simulator:
        account = simulator.create_account(
            initial_cash="10000",
            fee_rate="0.001",
            allow_short=False,
            label="ma-band-v1",
        )
        result = run_ma_band(snapshots, simulator=simulator, account_id=account.id)
        print(
            f"signals={len(result.signals)} "
            f"orders={len(result.orders)} fills={len(result.fills)}"
        )
        for signal in result.signals:
            print(
                f"  {signal.side.value:4} close={signal.close} sma={signal.sma} "
                f"event={signal.event_id}"
            )
        portfolio = result.portfolio
        print(
            f"cash={portfolio.cash} equity={portfolio.equity} "
            f"realized={portfolio.realized_pnl} fees={portfolio.fees_paid}"
        )


if __name__ == "__main__":
    main()
