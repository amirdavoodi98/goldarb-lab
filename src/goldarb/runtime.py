"""Configuration-driven Strategy runner and component registries."""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Self, TypeVar, runtime_checkable

from .client import LabClient
from .config import LIVE_PAPER_MODES, AppConfig, AppConfigBuilder, ModelConfig, StrategyConfig
from .data import HistoricalDataProvider, LiveDataProvider
from .engine import BacktestEngine, LiveSimulationEngine, RunConfig, RunResult
from .execution import (
    Broker,
    Closable,
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
from .execution_policy import (
    REMOTE_POLICY_ERROR,
    ExecutionPolicy,
    NoOpExecutionPolicy,
    OffsetLimitPolicy,
    policy_is_noop,
)
from .feed_contracts import historical_endpoint, live_endpoint
from .gateway import (
    LedgerGateway,
    OrderGateway,
    RecordingOrderGateway,
    TransportNotConfigured,
    order_gateway_for,
)
from .session import grain_step
from .simulation import RemoteSimulator
from .simulation.brokers import get_broker
from .simulation.paper_broker import LocalPaperBroker
from .sources import ArchiveDatasetSource, historical_source, live_source
from .strategies import (
    BubbleRankStrategy,
    BubbleSignStrategy,
    MaBandStrategy,
    PairZScoreStrategy,
    PriceMomentumStrategy,
    StreakStrategy,
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


def _noop_execution_policy(params: dict[str, Any]) -> NoOpExecutionPolicy:
    if params:
        raise ValueError("NoOp execution policy does not take parameters")
    return NoOpExecutionPolicy()


EXECUTION_POLICIES: dict[str, Callable[[dict[str, Any]], ExecutionPolicy]] = {
    "noop": _noop_execution_policy,
    "offsetlimit": lambda p: OffsetLimitPolicy.from_params(p),
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
    "streak": lambda p: StreakStrategy(**p),
}


def _normalize_key(name: str) -> str:
    return name.replace("-", "_").strip().lower()


ModelT = TypeVar("ModelT")


def _model(
    config: ModelConfig,
    registry: Mapping[str, Callable[[dict[str, Any]], ModelT]],
) -> ModelT:
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


def build_execution_policy(config: ModelConfig) -> ExecutionPolicy:
    return _model(config, EXECUTION_POLICIES)


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


@runtime_checkable
class RemoteSimulationClient(Protocol):
    @property
    def simulation(self) -> Broker: ...


class StrategyRunner:
    """Build providers, execution models and broker from one validated config."""

    def __init__(self, config: AppConfig, *, client: object | None = None) -> None:
        config.validate()
        self.config = config
        self.client = client
        self._owns_client = False
        self._broker: Broker | None = None
        self._order_gateway: OrderGateway | None = None
        self._execution: ExecutionDriver | None = None
        self._strategy: Strategy | None = None
        self._live_sleep: Callable[[float], None] | None = None
        self._live_now: Callable[[], datetime] | None = None
        self._live_stop_at: datetime | None = None

    @classmethod
    def from_config(
        cls,
        config: AppConfig | AppConfigBuilder | str | Path,
        *,
        client: object | None = None,
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

    def set_order_gateway(self, gateway: OrderGateway | None) -> Self:
        """Register the ``live_broker`` OrderGateway.

        Paper modes ignore this object. ``runtime.broker`` does not register
        one. ``None`` leaves ``live_broker`` with no transport.
        """
        self._order_gateway = gateway
        return self

    def use_recording_gateway(self) -> Self:
        """Build a ``RecordingOrderGateway`` for ``live_broker``.

        The gateway records submit and cancel. It does not open a connection.
        """
        self._order_gateway = RecordingOrderGateway()
        return self

    @property
    def order_gateway(self) -> OrderGateway | None:
        return self._order_gateway

    def set_execution(self, execution: ExecutionDriver | None) -> Self:
        """Override market-ingress driver (LocalFeed vs ServerSide)."""
        self._execution = execution
        return self

    def set_strategy(self, strategy: Strategy | None) -> Self:
        """Bind a strategy instance for ``run()`` when no argument is passed."""
        self._strategy = strategy
        return self

    def set_client(self, client: object | None) -> Self:
        """Use an existing ``LabClient`` (runner will not close it)."""
        self.client = client
        self._owns_client = False
        return self

    def set_live_clock(
        self,
        *,
        sleep: Callable[[float], None] | None = None,
        now: Callable[[], datetime] | None = None,
        stop_at: datetime | None = None,
    ) -> Self:
        """Forward clock hooks to ``LiveDataProvider``. Not an ``AppConfig`` field."""
        self._live_sleep = sleep
        self._live_now = now
        self._live_stop_at = stop_at
        return self

    def _client(self) -> object:
        if self.client is not None:
            return self.client
        self.client = _client_from_env()
        self._owns_client = True
        return self.client

    def _historical_provider(self) -> HistoricalDataProvider:
        data = self.config.data
        session = self.config.session
        schedule = session.resolve_schedule()
        needs_client = data.provider in {"goldarb_api", "api"}
        source = historical_source(
            data.provider,
            data.source,
            client=historical_endpoint(self._client()) if needs_client else None,
        )
        if isinstance(source, ArchiveDatasetSource):
            return source.provider(
                data.symbols,
                start=data.start,
                end=data.end,
                grain=data.grain,
                fill_session=data.fill_session,
                session_hours=data.session_hours,
                session_zone=schedule.timezone,
                session_open=schedule.opens_at,
                session_close=schedule.closes_at,
                quote_fill=data.quote_fill,
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
            session_zone=schedule.timezone,
            session_open=schedule.opens_at,
            session_close=schedule.closes_at,
            quote_fill=data.quote_fill,
        )

    def _live_provider(self) -> LiveDataProvider:
        data = self.config.data
        session = self.config.session
        feed = live_source(data.provider, client=live_endpoint(self._client()))
        schedule = session.resolve_schedule()
        today = datetime.now(schedule.timezone).date()
        stop_at = self._live_stop_at or datetime.combine(
            today, schedule.closes_at, tzinfo=schedule.timezone
        )
        return LiveDataProvider(
            feed,
            symbols=data.symbols,
            poll_seconds=session.poll_seconds,
            bar_grain=data.grain,
            include_session_bars=session.include_session_bars,
            lookback_days=session.lookback_days,
            stop_at=stop_at,
            max_polls=session.max_polls,
            sleep=self._live_sleep,
            now=self._live_now,
            session_zone=schedule.timezone,
            session_open=schedule.opens_at,
            session_close=schedule.closes_at,
            quote_fill=data.quote_fill,
        )

    def _paper_terms(self) -> tuple[bool, ModelConfig]:
        """Fee model and allow_short for the paper account.

        ``runtime.broker`` of ``agah`` or ``mofid`` fills whichever of those
        two the config did not set. The preset object is not the engine broker.
        """
        runtime = self.config.runtime
        allow_short = runtime.allow_short
        fee = self.config.fee
        code = runtime.broker.strip().lower()
        if not code:
            return allow_short, fee
        preset = get_broker(code)
        if not runtime.allow_short_set:
            allow_short = bool(preset.allow_short)
        if not self.config.fee_set:
            fee = ModelConfig("PercentFee", {"fee_rate": str(preset.fee_rate)})
        return allow_short, fee

    def _state_file(self) -> Path | None:
        raw = self.config.runtime.state_path.strip()
        if not raw:
            return None
        return Path(raw)

    def _load_strategy_state(self, strategy: Strategy) -> None:
        path = self._state_file()
        if path is None or not path.is_file():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"strategy state must be an object: {path}")
        strategy.load_state(payload)

    def _save_strategy_state(self, strategy: Strategy) -> None:
        path = self._state_file()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(strategy.export_state(), ensure_ascii=False),
            encoding="utf-8",
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
            if self._owns_client and isinstance(self.client, Closable):
                self.client.close()
                self.client = None
                self._owns_client = False

    def _resolve_broker_and_execution(
        self,
        *,
        fee: FeeModel,
        slippage: SlippageModel,
        latency: LatencyModel,
    ) -> tuple[Broker, ExecutionDriver, OrderGateway, bool]:
        """Build the paper engine, its ingress, and the only OrderGateway.

        ``runtime.broker`` is not transport. ``runtime.mode`` is:
        ``backtest``, ``offline_backtest``, and ``live_paper_local`` use
        ``LocalPaperOrderGateway``; ``live_paper_remote`` uses
        ``RemoteSimulatorOrderGateway``. ``live_broker`` uses the registered
        ``OrderGateway``, or ``RecordingOrderGateway`` when
        ``runtime.gateway`` is ``recording``. It does not build a paper
        matcher. An injected
        ``set_broker`` object keeps its own type on paper modes. The bool
        is true when this method opened the local database and must close it.
        """
        runtime = self.config.runtime
        if runtime.mode == "live_broker":
            return self._resolve_live_broker()
        if self._broker is not None:
            execution = self._execution
            if execution is None:
                execution = (
                    ServerSideExecution()
                    if isinstance(self._broker, RemoteSimulator)
                    else LocalFeedExecution()
                )
            return self._broker, execution, order_gateway_for(self._broker), False

        if runtime.mode == "live_paper_remote":
            if not isinstance(slippage, NoSlippage) or not isinstance(latency, NoLatency):
                raise ValueError(
                    "remote paper matching only supports NoSlippage and NoLatency; "
                    "configure execution effects on the server"
                )
            client = self._client()
            if not isinstance(client, RemoteSimulationClient):
                raise TypeError("remote paper client must expose simulation")
            remote = client.simulation
            return (
                remote,
                self._execution or ServerSideExecution(),
                order_gateway_for(remote),
                False,
            )

        local = LocalPaperBroker(
            runtime.database or ":memory:",
            fee=fee,
            slippage=slippage,
            latency=latency,
        )
        return local, self._execution or LocalFeedExecution(), order_gateway_for(local), True

    def _resolve_live_broker(
        self,
    ) -> tuple[Broker, ExecutionDriver, OrderGateway, bool]:
        """Build the live_broker gateway. No brokerage client.

        ``runtime.broker`` of ``agah`` or ``mofid`` is not a transport.
        ``runtime.gateway=recording`` selects ``RecordingOrderGateway``.
        A gateway registered in code wins. With neither, this raises
        ``TransportNotConfigured``. The recorder does not send orders.
        Its ledger is the account book; matching stays off.
        """
        gateway = self._order_gateway
        if gateway is None and self.config.runtime.gateway == "recording":
            gateway = RecordingOrderGateway()
            self._order_gateway = gateway
        if gateway is None:
            raise TransportNotConfigured("transport not configured")
        if not isinstance(gateway, LedgerGateway) or not isinstance(gateway.ledger, Broker):
            raise TypeError(
                "live_broker OrderGateway must expose a ledger; "
                "this phase does not include a brokerage client"
            )
        return gateway.ledger, ServerSideExecution(), gateway, False

    def _reject_remote_policy(self, policy: ExecutionPolicy) -> None:
        """Remote paper matches on the server, which does not share this policy."""
        remote = self.config.runtime.mode == "live_paper_remote" or isinstance(
            self._broker, RemoteSimulator
        )
        if remote and not policy_is_noop(policy):
            raise ValueError(REMOTE_POLICY_ERROR)

    def _run(self, strategy: Strategy) -> RunResult:
        runtime = self.config.runtime
        policy = build_execution_policy(self.config.execution_policy)
        self._reject_remote_policy(policy)
        allow_short, fee_config = self._paper_terms()
        is_live = runtime.mode in LIVE_PAPER_MODES
        fee = build_fee(fee_config)
        slippage = build_slippage(self.config.slippage)
        latency = build_latency(self.config.latency)
        provider = self._live_provider() if is_live else self._historical_provider()
        engine = LiveSimulationEngine() if is_live else BacktestEngine()
        broker, execution, gateway, owns_broker = self._resolve_broker_and_execution(
            fee=fee,
            slippage=slippage,
            latency=latency,
        )
        strategy_config = {
            str(key): str(value) for key, value in self.config.strategy.params.items()
        }
        if runtime.reset_history:
            strategy_config["reset_history"] = "true"
        run_config = RunConfig(
            strategy_name=self.config.strategy.name or strategy.name,
            strategy_version=self.config.strategy.version or getattr(strategy, "version", "0"),
            initial_cash=runtime.initial_cash,
            allow_short=allow_short,
            label=runtime.label or strategy.name,
            account_id=runtime.account_id,
            database=runtime.database,
            strategy_config=strategy_config,
        )
        try:
            self._load_strategy_state(strategy)
            result = engine.run(
                strategy,
                provider,
                run_config,
                simulator=broker,
                fee=fee,
                slippage=slippage,
                latency=latency,
                execution=execution,
                execution_policy=policy,
                quote_fill=self.config.data.quote_fill,
                gateway=gateway,
            )
            self._save_strategy_state(strategy)
            return result
        finally:
            if owns_broker and isinstance(broker, Closable):
                broker.close()


__all__ = [
    "FEE_MODELS",
    "LATENCY_MODELS",
    "SLIPPAGE_MODELS",
    "STRATEGY_REGISTRY",
    "StrategyRunner",
    "build_execution_policy",
    "build_fee",
    "build_latency",
    "build_slippage",
    "build_strategy",
]
