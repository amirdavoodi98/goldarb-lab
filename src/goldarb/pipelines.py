"""End-to-end 1s backtest (past month) and Iran-session live simulation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .archive import dataset_store
from .data import HistoricalDataProvider, LabLiveFeed, LiveDataProvider
from .engine import BacktestEngine, LiveSimulationEngine, RunConfig, RunResult
from .execution import FeeModel, PercentFee
from .session import TEHRAN, grain_step, session_bounds
from .simulation.local import LocalSimulator
from .sources import ArchiveDatasetSource
from .strategy import Strategy
from .universe import GOLD_FUND_SYMBOLS

BAR_GRAIN_1S = "1s"


def month_backtest(
    strategy: Strategy,
    client: Any,
    *,
    days: int = 30,
    grain: str = BAR_GRAIN_1S,
    symbols: Sequence[str] | None = None,
    fill_session: bool = True,
    initial_cash: str = "1000000000",
    allow_short: bool = True,
    fee: FeeModel | None = None,
    simulator: LocalSimulator | None = None,
    end: date | None = None,
) -> RunResult:
    """Replay the last ``days`` of ``grain=1s`` Iran-session bars.

    ``fill_session=True`` emits every second from 12:00–17:00 on each day
    that has data so the strategy truly runs at 1s.
    """
    universe = tuple(symbols) if symbols is not None else GOLD_FUND_SYMBOLS
    last = end or datetime.now(TEHRAN).date()
    first = last - timedelta(days=max(1, int(days)))
    fund = getattr(client, "fund", client)
    raw = fund.candles_many(universe, start=first, end=last, grain=grain)
    if not isinstance(raw, dict):
        raw = {}
    provider = HistoricalDataProvider.from_symbol_bars(
        raw,
        ffill=True,
        step=grain_step(grain),
        session_hours=True,
        fill_session=fill_session,
        event_prefix=f"{grain}-month",
        lazy=True,
    )
    return BacktestEngine().run(
        strategy,
        provider,
        RunConfig(
            strategy_name=strategy.name,
            strategy_version=getattr(strategy, "version", "0"),
            initial_cash=initial_cash,
            allow_short=allow_short,
            label=f"{strategy.name}-{grain}-{days}d",
        ),
        simulator=simulator,
        fee=fee or PercentFee("0.0005"),
    )


def iran_session_live(
    strategy: Strategy,
    client: Any,
    *,
    poll_seconds: float = 1.0,
    lookback_days: int = 20,
    include_session_bars: bool = True,
    symbols: Sequence[str] | None = None,
    grain: str = BAR_GRAIN_1S,
    initial_cash: str = "1000000000",
    allow_short: bool = True,
    fee: FeeModel | None = None,
    simulator: LocalSimulator | None = None,
    stop_at: datetime | None = None,
    sleep: Any = None,
    now: Any = None,
) -> RunResult:
    """Paper-trade through today's 12:00–17:00 Tehran session at 1s polls.

    ``lookback_days`` replays recent 1s session bars first so pair windows
    are warm before live ticks. After ``month_backtest`` on the same strategy
    instance, pass ``lookback_days=0`` and ``include_session_bars=False`` so
    history is not replayed (``on_start`` does not clear it).
    """
    universe = tuple(symbols) if symbols is not None else GOLD_FUND_SYMBOLS
    _open, close = session_bounds()
    provider = LiveDataProvider(
        LabLiveFeed(client),
        symbols=universe,
        poll_seconds=poll_seconds,
        bar_grain=grain,
        include_session_bars=include_session_bars,
        lookback_days=lookback_days,
        stop_at=stop_at or close,
        sleep=sleep,
        now=now,
    )
    return LiveSimulationEngine().run(
        strategy,
        provider,
        RunConfig(
            strategy_name=strategy.name,
            strategy_version=getattr(strategy, "version", "0"),
            initial_cash=initial_cash,
            allow_short=allow_short,
            label=f"{strategy.name}-iran-live-{grain}",
        ),
        simulator=simulator,
        fee=fee or PercentFee("0.0005"),
    )


def offline_backtest(
    strategy: Strategy,
    archive: str | Path,
    *,
    grain: str = BAR_GRAIN_1S,
    fill_session: bool = True,
    initial_cash: str = "1000000000",
    allow_short: bool = False,
    fee: FeeModel | None = None,
    simulator: LocalSimulator | None = None,
) -> RunResult:
    """Replay a previously downloaded 1s archive with no HTTP."""
    source = ArchiveDatasetSource(dataset_store(archive))
    manifest = source.store.read_manifest()
    grain_key = str(manifest.get("grain") or grain)
    symbols = tuple(str(item) for item in manifest.get("symbols", ()))
    provider = source.provider(
        symbols,
        grain=grain_key,
        fill_session=fill_session,
        session_hours=True,
    )
    return BacktestEngine().run(
        strategy,
        provider,
        RunConfig(
            strategy_name=strategy.name,
            strategy_version=getattr(strategy, "version", "0"),
            initial_cash=initial_cash,
            allow_short=allow_short,
            label=f"{strategy.name}-{grain_key}-offline",
        ),
        simulator=simulator,
        fee=fee or PercentFee("0.0005"),
    )
