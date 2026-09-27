"""End-to-end 1s backtest (past month) and Iran-session live simulation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .archive import dataset_store
from .config import AppConfig
from .engine import RunResult
from .execution import FeeModel
from .runtime import StrategyRunner
from .session import TEHRAN, session_bounds
from .simulation.local import LocalSimulator
from .sources import ArchiveDatasetSource
from .strategy import Strategy
from .universe import GOLD_FUND_SYMBOLS

BAR_GRAIN_1S = "1s"


def _config(
    *,
    mode: str,
    provider: str,
    symbols: Sequence[str],
    grain: str,
    fill_session: bool,
    initial_cash: str,
    allow_short: bool,
    label: str,
    source: str | None = None,
    start: str | None = None,
    end: str | None = None,
    fee: FeeModel | None = None,
    poll_seconds: float | None = None,
    lookback_days: int | None = None,
    include_session_bars: bool | None = None,
) -> AppConfig:
    builder = (
        AppConfig.builder()
        .set_mode(mode)
        .set_provider(provider)
        .set_symbols(tuple(symbols))
        .set_grain(grain)
        .set_fill_session(fill_session)
        .set_session_hours(True)
        .set_initial_cash(initial_cash)
        .set_allow_short(allow_short)
        .set_label(label)
    )
    if source is not None:
        builder.set_source(source)
    if start is not None or end is not None:
        builder.set_period(start, end)
    if fee is not None:
        builder.set_fee(fee.name, **dict(fee.config()))
    if poll_seconds is not None:
        builder.set_poll_seconds(poll_seconds)
    if lookback_days is not None:
        builder.set_lookback_days(lookback_days)
    if include_session_bars is not None:
        builder.set_include_session_bars(include_session_bars)
    return builder.build()


def _run(
    strategy: Strategy,
    config: AppConfig,
    *,
    client: Any | None = None,
    simulator: LocalSimulator | None = None,
    sleep: Any = None,
    now: Any = None,
    stop_at: datetime | None = None,
) -> RunResult:
    runner = StrategyRunner.from_config(config, client=client).set_strategy(strategy)
    if stop_at is not None or sleep is not None or now is not None:
        runner.set_live_clock(sleep=sleep, now=now, stop_at=stop_at)
    if simulator is not None:
        runner.set_broker(simulator)
    return runner.run()


def month_backtest(
    strategy: Strategy,
    client: Any,
    *,
    days: int = 30,
    grain: str = BAR_GRAIN_1S,
    symbols: Sequence[str] | None = None,
    fill_session: bool = True,
    initial_cash: str = "1000000000",
    allow_short: bool = False,
    fee: FeeModel | None = None,
    simulator: LocalSimulator | None = None,
    end: date | None = None,
) -> RunResult:
    """Replay the last ``days`` of ``grain=1s`` Iran-session bars.

    ``fill_session=True`` emits every second from 12:00–18:00 on each
    Saturday–Wednesday that has data so the strategy truly runs at 1s.

    ``allow_short`` defaults to false, the same as ``AppConfig``. Pair
    strategies that need a short leg must pass ``allow_short=True``.
    """
    universe = tuple(symbols) if symbols is not None else GOLD_FUND_SYMBOLS
    last = end or datetime.now(TEHRAN).date()
    first = last - timedelta(days=max(1, int(days)))
    config = _config(
        mode="backtest",
        provider="goldarb_api",
        symbols=universe,
        grain=grain,
        fill_session=fill_session,
        initial_cash=initial_cash,
        allow_short=allow_short,
        label=f"{strategy.name}-{grain}-{days}d",
        start=first.isoformat(),
        end=last.isoformat(),
        fee=fee,
    )
    return _run(strategy, config, client=client, simulator=simulator)


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
    allow_short: bool = False,
    fee: FeeModel | None = None,
    simulator: LocalSimulator | None = None,
    stop_at: datetime | None = None,
    sleep: Any = None,
    now: Any = None,
) -> RunResult:
    """Paper-trade through today's 12:00–18:00 Tehran session at 1s polls.

    ``lookback_days`` replays recent 1s session bars first so pair windows
    are warm before live ticks. After ``month_backtest`` on the same strategy
    instance, pass ``lookback_days=0`` and ``include_session_bars=False`` so
    history is not replayed (``on_start`` does not clear it).

    ``allow_short`` defaults to false. Pair strategies must pass
    ``allow_short=True``.
    """
    universe = tuple(symbols) if symbols is not None else GOLD_FUND_SYMBOLS
    _open, close = session_bounds()
    config = _config(
        mode="live_paper_local",
        provider="goldarb_api",
        symbols=universe,
        grain=grain,
        fill_session=False,
        initial_cash=initial_cash,
        allow_short=allow_short,
        label=f"{strategy.name}-iran-live-{grain}",
        fee=fee,
        poll_seconds=poll_seconds,
        lookback_days=lookback_days,
        include_session_bars=include_session_bars,
    )
    return _run(
        strategy,
        config,
        client=client,
        simulator=simulator,
        sleep=sleep,
        now=now,
        stop_at=stop_at or close,
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
    config = _config(
        mode="offline_backtest",
        provider="archive",
        symbols=symbols,
        grain=grain_key,
        fill_session=fill_session,
        initial_cash=initial_cash,
        allow_short=allow_short,
        label=f"{strategy.name}-{grain_key}-offline",
        source=str(archive),
        fee=fee,
    )
    return _run(strategy, config, simulator=simulator)
