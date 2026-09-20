"""Configuration-driven Strategy runner and component registries."""

from __future__ import annotations

import os
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .client import LabClient
from .config import AppConfig, ModelConfig
from .data import HistoricalDataProvider, LiveDataProvider
from .engine import BacktestEngine, LiveSimulationEngine, RunConfig, RunResult
from .execution import (
    ExecutionDriver,
    FeeModel,
    FixedLatency,
    FixedSlippage,
    LatencyModel,
    LocalFeedExecution,
    NoFee,
    NoLatency,
    NoSlippage,
    PercentFee,
    PercentSlippage,
    ServerSideExecution,
    SlippageModel,
)
from .session import grain_step
from .sources import ArchiveDatasetSource, historical_source, live_source
from .strategy import Strategy

FeeFactory = Callable[[dict[str, Any]], FeeModel]
SlippageFactory = Callable[[dict[str, Any]], SlippageModel]
LatencyFactory = Callable[[dict[str, Any]], LatencyModel]


def _decimal_param(params: dict[str, Any], *names: str, default: str = "0") -> Decimal:
    for name in names:
        if name in params:
            return Decimal(str(params[name]))
    return Decimal(default)


FEE_MODELS: dict[str, FeeFactory] = {
    "percentfee": lambda p: PercentFee(_decimal_param(p, "fee_rate", "rate", default="0.0005")),
    "nofee": lambda p: NoFee(),
}
SLIPPAGE_MODELS: dict[str, SlippageFactory] = {
    "noslippage": lambda p: NoSlippage(),
    "fixedslippage": lambda p: FixedSlippage(_decimal_param(p, "amount")),
    "percentslippage": lambda p: PercentSlippage(_decimal_param(p, "fraction", "percent")),
}
LATENCY_MODELS: dict[str, LatencyFactory] = {
    "nolatency": lambda p: NoLatency(),
    "fixedlatency": lambda p: FixedLatency(int(p.get("milliseconds", 0))),
}


def _model(config: ModelConfig, registry: dict[str, Callable[[dict[str, Any]], Any]]) -> Any:
    key = config.name.replace("_", "").replace("-", "").lower()
    try:
        factory = registry[key]
    except KeyError as exc:
        raise ValueError(f"unknown model: {config.name}") from exc
    return factory(dict(config.params))


def build_fee(config: ModelConfig) -> FeeModel:
    return _model(config, FEE_MODELS)


def build_slippage(config: ModelConfig) -> SlippageModel:
    return _model(config, SLIPPAGE_MODELS)


def build_latency(config: ModelConfig) -> LatencyModel:
    return _model(config, LATENCY_MODELS)


class StrategyRunner:
    """Build providers, execution models and broker from one validated config."""

    def __init__(self, config: AppConfig, *, client: Any | None = None) -> None:
        config.validate()
        self.config = config
        self.client = client
        self._owns_client = False

    @classmethod
    def from_config(
        cls,
        config: AppConfig | str | Path,
        *,
        client: Any | None = None,
    ) -> StrategyRunner:
        loaded = AppConfig.from_file(config) if isinstance(config, (str, Path)) else config
        return cls(loaded, client=client)

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        source = self.config.data.source.strip()
        token = os.environ.get("GOLDARB_TOKEN", "").strip()
        if source.startswith(("http://", "https://")):
            if not token:
                raise RuntimeError("Set GOLDARB_TOKEN for the configured API source")
            self.client = LabClient(base_url=source, token=token)
        else:
            self.client = LabClient.from_env()
        self._owns_client = True
        return self.client

    def _historical_provider(self) -> HistoricalDataProvider:
        data = self.config.data
        session = self.config.session
        zone = ZoneInfo(session.timezone)
        open_at = time.fromisoformat(session.start)
        close_at = time.fromisoformat(session.end)
        needs_client = data.provider in {"goldarb_api", "api"}
        source = historical_source(
            data.provider,
            data.source,
            client=self._client() if needs_client else None,
        )
        if isinstance(source, ArchiveDatasetSource):
            return source.provider(
                data.symbols,
                start=data.start,
                end=data.end,
                grain=data.grain,
                fill_session=data.fill_session,
                session_hours=data.session_hours,
                session_zone=zone,
                session_open=open_at,
                session_close=close_at,
            )
        rows = source.bars(
            data.symbols,
            start=data.start,
            end=data.end,
            grain=data.grain,
        )
        return HistoricalDataProvider.from_symbol_bars(
            rows,
            step=grain_step(data.grain),
            fill_session=data.fill_session,
            session_hours=data.session_hours,
            event_prefix=f"{data.grain}-{data.provider}",
            lazy=True,
            session_zone=zone,
            session_open=open_at,
            session_close=close_at,
        )

    def _live_provider(self) -> LiveDataProvider:
        data = self.config.data
        session = self.config.session
        feed = live_source(data.provider, client=self._client())
        zone = ZoneInfo(session.timezone)
        today = datetime.now(zone).date()
        stop_parts = time.fromisoformat(session.end)
        open_parts = time.fromisoformat(session.start)
        stop_at = datetime.combine(today, stop_parts, tzinfo=zone)
        return LiveDataProvider(
            feed,
            symbols=data.symbols,
            poll_seconds=session.poll_seconds,
            bar_grain=data.grain,
            include_session_bars=session.include_session_bars,
            lookback_days=session.lookback_days,
            stop_at=stop_at,
            max_polls=session.max_polls,
            session_zone=zone,
            session_open=open_parts,
            session_close=stop_parts,
        )

    def run(self, strategy: Strategy) -> RunResult:
        try:
            return self._run(strategy)
        finally:
            if self._owns_client and self.client is not None:
                self.client.close()
                self.client = None
                self._owns_client = False

    def _run(self, strategy: Strategy) -> RunResult:
        runtime = self.config.runtime
        is_live = runtime.mode.startswith("live_")
        fee = build_fee(self.config.fee)
        slippage = build_slippage(self.config.slippage)
        latency = build_latency(self.config.latency)
        provider = self._live_provider() if is_live else self._historical_provider()
        engine = LiveSimulationEngine() if is_live else BacktestEngine()
        broker = None
        execution: ExecutionDriver = LocalFeedExecution()
        if runtime.mode == "live_paper_remote":
            if not isinstance(slippage, NoSlippage) or not isinstance(latency, NoLatency):
                raise ValueError(
                    "remote paper matching only supports NoSlippage and NoLatency; "
                    "configure execution effects on the server"
                )
            broker = self._client().simulation
            execution = ServerSideExecution()
        run_config = RunConfig(
            strategy_name=self.config.strategy.name or strategy.name,
            strategy_version=self.config.strategy.version or getattr(strategy, "version", "0"),
            initial_cash=runtime.initial_cash,
            allow_short=runtime.allow_short,
            label=runtime.label or strategy.name,
            account_id=runtime.account_id,
            database=runtime.database,
            strategy_config={
                str(key): str(value) for key, value in self.config.strategy.params.items()
            },
        )
        return engine.run(
            strategy,
            provider,
            run_config,
            simulator=broker,
            fee=fee,
            slippage=slippage,
            latency=latency,
            execution=execution,
        )


__all__ = [
    "FEE_MODELS",
    "LATENCY_MODELS",
    "SLIPPAGE_MODELS",
    "StrategyRunner",
    "build_fee",
    "build_latency",
    "build_slippage",
]
