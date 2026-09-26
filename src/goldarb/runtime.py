"""Configuration-driven Strategy runner and component registries."""

from __future__ import annotations

import os
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Self
from zoneinfo import ZoneInfo

from .client import LabClient
from .config import AppConfig, AppConfigBuilder, ModelConfig, StrategyConfig
from .data import HistoricalDataProvider, LiveDataProvider
from .engine import BacktestEngine, LiveSimulationEngine, RunConfig, RunResult
from .execution import (
    Broker,
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
from .simulation import RemoteSimulator
from .sources import ArchiveDatasetSource, historical_source, live_source
from .strategies import (
    BubbleRankStrategy,
    BubbleSignStrategy,
    MaBandStrategy,
    PairZScoreStrategy,
    PriceMomentumStrategy,
)
from .strategy import Strategy

FeeFactory = Callable[[dict[str, Any]], FeeModel]
SlippageFactory = Callable[[dict[str, Any]], SlippageModel]
LatencyFactory = Callable[[dict[str, Any]], LatencyModel]
StrategyFactory = Callable[[dict[str, Any]], Strategy]


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

STRATEGY_REGISTRY: dict[str, StrategyFactory] = {
    "price_momentum": lambda p: PriceMomentumStrategy(**p),
    "pricemomentum": lambda p: PriceMomentumStrategy(**p),
    "bubble_sign": lambda p: BubbleSignStrategy(**p),
    "bubblesign": lambda p: BubbleSignStrategy(**p),
    "bubble_rank": lambda p: BubbleRankStrategy(**p),
    "bubblerank": lambda p: BubbleRankStrategy(**p),
    "pair_zscore": lambda p: PairZScoreStrategy(**p),
    "pairzscore": lambda p: PairZScoreStrategy(**p),
    "ma_band": lambda p: MaBandStrategy(**p),
    "maband": lambda p: MaBandStrategy(**p),
}


def _normalize_key(name: str) -> str:
    return name.replace("-", "_").strip().lower()


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


def build_strategy(
    config: StrategyConfig | Mapping[str, Any] | None = None,
    **params: Any,
) -> Strategy:
    """Construct a Strategy from ``strategy.name`` + ``strategy.params``."""
    if isinstance(config, StrategyConfig):
        name = config.name
        merged = dict(config.params)
        merged.update(params)
    elif config is None:
        name = str(params.pop("name", "") or "")
        merged = dict(params)
    else:
        item = dict(config)
        name = str(item.get("name") or params.pop("name", "") or "")
        merged = dict(item.get("params") or {})
        merged.update({k: v for k, v in item.items() if k not in {"name", "params", "version"}})
        merged.update(params)
    key = _normalize_key(name)
    compact = key.replace("_", "")
    factory = STRATEGY_REGISTRY.get(key) or STRATEGY_REGISTRY.get(compact)
    if factory is None:
        known = ", ".join(
            sorted({k for k in STRATEGY_REGISTRY if "_" in k})
        )
        raise ValueError(f"unknown strategy.name {name!r}; known: {known}")
    return factory(merged)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def _client_from_env(*, timeout: float = 120.0) -> LabClient:
    """Token first; fall back to username/password login."""
    _load_dotenv()
    try:
        return LabClient.from_env(timeout=timeout)
    except RuntimeError:
        username = os.environ.get("GOLDARB_USERNAME", "").strip()
        password = os.environ.get("GOLDARB_PASSWORD", "").strip()
        base = os.environ.get("GOLDARB_BASE_URL", "https://goldarb.ir").strip()
        if username and password and base:
            return LabClient.login(
                base_url=base,
                username=username,
                password=password,
                timeout=timeout,
            )
        raise RuntimeError(
            "Set GOLDARB_BASE_URL+GOLDARB_TOKEN or GOLDARB_USERNAME+GOLDARB_PASSWORD"
        )


class StrategyRunner:
    """Build providers, execution models and broker from one validated config."""

    def __init__(self, config: AppConfig, *, client: Any | None = None) -> None:
        config.validate()
        self.config = config
        self.client = client
        self._owns_client = False
        self._broker: Broker | None = None
        self._execution: ExecutionDriver | None = None
        self._strategy: Strategy | None = None

    @classmethod
    def from_config(
        cls,
        config: AppConfig | AppConfigBuilder | str | Path,
        *,
        client: Any | None = None,
    ) -> StrategyRunner:
        if isinstance(config, AppConfigBuilder):
            loaded = config.build()
        elif isinstance(config, (str, Path)):
            loaded = AppConfig.from_file(config)
        else:
            loaded = config
        return cls(loaded, client=client)

    def set_broker(self, broker: Broker | None) -> Self:
        """Inject a paper/remote broker; ``None`` restores mode defaults."""
        self._broker = broker
        return self

    def set_execution(self, execution: ExecutionDriver | None) -> Self:
        """Override market-ingress driver (LocalFeed vs ServerSide)."""
        self._execution = execution
        return self

    def set_strategy(self, strategy: Strategy | None) -> Self:
        """Bind a strategy instance for ``run()`` when no argument is passed."""
        self._strategy = strategy
        return self

    def set_client(self, client: Any | None) -> Self:
        """Use an existing ``LabClient`` (runner will not close it)."""
        self.client = client
        self._owns_client = False
        return self

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        self.client = _client_from_env()
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

    def run(self, strategy: Strategy | None = None) -> RunResult:
        """Run ``strategy``, or the bound/config strategy when omitted."""
        built = (
            strategy
            if strategy is not None
            else self._strategy
            if self._strategy is not None
            else build_strategy(self.config.strategy)
        )
        try:
            return self._run(built)
        finally:
            if self._owns_client and self.client is not None:
                self.client.close()
                self.client = None
                self._owns_client = False

    def _resolve_broker_and_execution(
        self,
        *,
        slippage: SlippageModel,
        latency: LatencyModel,
    ) -> tuple[Broker | None, ExecutionDriver]:
        runtime = self.config.runtime
        if self._broker is not None:
            if self._execution is not None:
                return self._broker, self._execution
            if isinstance(self._broker, RemoteSimulator):
                return self._broker, ServerSideExecution()
            return self._broker, LocalFeedExecution()

        if runtime.mode == "live_paper_remote":
            if not isinstance(slippage, NoSlippage) or not isinstance(latency, NoLatency):
                raise ValueError(
                    "remote paper matching only supports NoSlippage and NoLatency; "
                    "configure execution effects on the server"
                )
            return self._client().simulation, self._execution or ServerSideExecution()

        return None, self._execution or LocalFeedExecution()

    def _run(self, strategy: Strategy) -> RunResult:
        runtime = self.config.runtime
        is_live = runtime.mode.startswith("live_")
        fee = build_fee(self.config.fee)
        slippage = build_slippage(self.config.slippage)
        latency = build_latency(self.config.latency)
        provider = self._live_provider() if is_live else self._historical_provider()
        engine = LiveSimulationEngine() if is_live else BacktestEngine()
        broker, execution = self._resolve_broker_and_execution(
            slippage=slippage,
            latency=latency,
        )
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
    "STRATEGY_REGISTRY",
    "StrategyRunner",
    "build_fee",
    "build_latency",
    "build_slippage",
    "build_strategy",
]
