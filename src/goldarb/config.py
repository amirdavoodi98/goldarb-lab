"""Serializable configuration for data sources and strategy runtimes."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Self

from .universe import GOLD_FUND_SYMBOLS

RUNTIME_MODES = {
    "backtest",
    "offline_backtest",
    "live_paper_local",
    "live_paper_remote",
}


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _symbols(value: Sequence[str] | str) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    else:
        items = [str(symbol) for symbol in value]
    if not items:
        raise ValueError("symbols must not be empty")
    return tuple(items)


@dataclass(frozen=True)
class ModelConfig:
    name: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any, default: str) -> Self:
        if value is None:
            return cls(default)
        if isinstance(value, str):
            return cls(value)
        item = _mapping(value, "model config")
        return cls(str(item.get("name") or default), _mapping(item.get("params"), "params"))


@dataclass(frozen=True)
class DataConfig:
    provider: str = "goldarb_api"
    source: str = ""
    dataset: str = "fund-bars"
    symbols: tuple[str, ...] = GOLD_FUND_SYMBOLS
    grain: str = "1s"
    start: str | None = None
    end: str | None = None
    fill_session: bool = True
    session_hours: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> Self:
        item = _mapping(value, "data")
        symbols = item.get("symbols", GOLD_FUND_SYMBOLS)
        if isinstance(symbols, str) or not isinstance(symbols, (list, tuple)):
            raise ValueError("data.symbols must be an array")
        provider = str(item.get("provider") or "goldarb_api").strip().lower()
        grain = str(item.get("grain") or "1s").strip().lower()
        if grain not in {"1s", "1m", "daily"}:
            raise ValueError("data.grain must be '1s', '1m', or 'daily'")
        return cls(
            provider=provider,
            source=str(item.get("source") or ""),
            dataset=str(item.get("dataset") or "fund-bars"),
            symbols=tuple(str(symbol) for symbol in symbols),
            grain=grain,
            start=None if item.get("start") is None else str(item["start"]),
            end=None if item.get("end") is None else str(item["end"]),
            fill_session=bool(item.get("fill_session", True)),
            session_hours=bool(item.get("session_hours", True)),
        )


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str = "backtest"
    initial_cash: str = "1000000000"
    allow_short: bool = False
    database: str | None = None
    account_id: str | None = None
    label: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> Self:
        item = _mapping(value, "runtime")
        mode = str(item.get("mode") or "backtest").strip().lower()
        if mode not in RUNTIME_MODES:
            raise ValueError(f"runtime.mode must be one of: {', '.join(sorted(RUNTIME_MODES))}")
        return cls(
            mode=mode,
            initial_cash=str(item.get("initial_cash", "1000000000")),
            allow_short=bool(item.get("allow_short", False)),
            database=None if item.get("database") is None else str(item["database"]),
            account_id=None if item.get("account_id") is None else str(item["account_id"]),
            label=str(item.get("label") or ""),
        )


@dataclass(frozen=True)
class SessionConfig:
    timezone: str = "Asia/Tehran"
    start: str = "12:00:00"
    end: str = "18:00:00"
    poll_seconds: float = 1.0
    lookback_days: int = 0
    include_session_bars: bool = False
    max_polls: int | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> Self:
        item = _mapping(value, "session")
        poll = float(item.get("poll_seconds", 1.0))
        if poll <= 0:
            raise ValueError("session.poll_seconds must be positive")
        return cls(
            timezone=str(item.get("timezone") or "Asia/Tehran"),
            start=str(item.get("start") or "12:00:00"),
            end=str(item.get("end") or "18:00:00"),
            poll_seconds=poll,
            lookback_days=max(0, int(item.get("lookback_days", 0))),
            include_session_bars=bool(item.get("include_session_bars", False)),
            max_polls=(None if item.get("max_polls") is None else int(item["max_polls"])),
        )


@dataclass(frozen=True)
class StrategyConfig:
    name: str = ""
    version: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> Self:
        item = _mapping(value, "strategy")
        return cls(
            name=str(item.get("name") or ""),
            version=str(item.get("version") or ""),
            params=_mapping(item.get("params"), "strategy.params"),
        )


@dataclass(frozen=True)
class AppConfig:
    data: DataConfig = field(default_factory=DataConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    fee: ModelConfig = field(
        default_factory=lambda: ModelConfig("PercentFee", {"fee_rate": "0.0005"})
    )
    slippage: ModelConfig = field(default_factory=lambda: ModelConfig("NoSlippage"))
    latency: ModelConfig = field(default_factory=lambda: ModelConfig("NoLatency"))

    @classmethod
    def builder(cls, base: AppConfig | None = None) -> AppConfigBuilder:
        """Start a fluent builder for hardcoded (or file-then-override) config."""
        return AppConfigBuilder(base)

    def to_builder(self) -> AppConfigBuilder:
        """Copy this config into a mutable builder for further setters."""
        return AppConfigBuilder(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        item = _mapping(value, "config")
        config = cls(
            data=DataConfig.from_mapping(item.get("data")),
            runtime=RuntimeConfig.from_mapping(item.get("runtime")),
            session=SessionConfig.from_mapping(item.get("session")),
            strategy=StrategyConfig.from_mapping(item.get("strategy")),
            fee=ModelConfig.from_value(item.get("fee"), "PercentFee"),
            slippage=ModelConfig.from_value(item.get("slippage"), "NoSlippage"),
            latency=ModelConfig.from_value(item.get("latency"), "NoLatency"),
        )
        config.validate()
        return config

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        source = Path(path)
        suffix = source.suffix.lower()
        with source.open("rb") as handle:
            if suffix == ".json":
                payload = json.load(handle)
            elif suffix == ".toml":
                payload = tomllib.load(handle)
            elif suffix in {".yaml", ".yml"}:
                try:
                    import yaml
                except ImportError as exc:
                    raise RuntimeError(
                        "YAML config requires a local extra install: "
                        "uv pip install --python .venv/bin/python -e '.[yaml]'"
                    ) from exc
                payload = yaml.safe_load(handle)
            else:
                raise ValueError("config file must be JSON, TOML, or YAML")
        return cls.from_mapping(_mapping(payload, "config"))

    def validate(self) -> None:
        mode = self.runtime.mode
        archive_provider = self.data.provider in {"jsonl", "parquet", "archive"}
        if mode == "offline_backtest" and not archive_provider:
            raise ValueError("offline_backtest requires jsonl, parquet, or archive provider")
        if mode.startswith("live_") and archive_provider:
            raise ValueError("live runtime requires a GoldArb live/API provider")
        if archive_provider and not self.data.source:
            raise ValueError("archive data provider requires data.source")
        if not self.data.symbols:
            raise ValueError("data.symbols must not be empty")
        try:
            if self.data.start and self.data.end and self.data.start[:10] > self.data.end[:10]:
                raise ValueError("data.start must be <= data.end")
        except TypeError as exc:
            raise ValueError("data.start and data.end must be ISO dates") from exc
        if mode in {"backtest", "offline_backtest"}:
            if self.data.provider in {"goldarb_api", "api"} and (
                self.data.start is None or self.data.end is None
            ):
                raise ValueError("API backtest requires data.start and data.end")


class AppConfigBuilder:
    """Mutable setters for ``AppConfig`` — chain, then ``build()``.

    Example::

        config = (
            AppConfig.builder()
            .set_mode("offline_backtest")
            .set_archive("archive/1s-14d", symbols=["طلا", "عیار"],
                         start="2026-09-15", end="2026-09-15")
            .set_strategy("price_momentum", quantity="1", threshold_pct="0.1")
            .set_fee("PercentFee", fee_rate="0.0005")
            .build()
        )
    """

    def __init__(self, base: AppConfig | None = None) -> None:
        seed = base if base is not None else AppConfig()
        self._data = replace(seed.data)
        self._runtime = replace(seed.runtime)
        self._session = replace(seed.session)
        self._strategy = replace(seed.strategy, params=dict(seed.strategy.params))
        self._fee = ModelConfig(seed.fee.name, dict(seed.fee.params))
        self._slippage = ModelConfig(seed.slippage.name, dict(seed.slippage.params))
        self._latency = ModelConfig(seed.latency.name, dict(seed.latency.params))

    # --- load / merge -------------------------------------------------

    def load_file(self, path: str | Path) -> Self:
        """Reset builder fields from a JSON/TOML/YAML file, then keep chaining."""
        return self._adopt(AppConfig.from_file(path))

    def load_mapping(self, value: Mapping[str, Any]) -> Self:
        return self._adopt(AppConfig.from_mapping(value))

    def _adopt(self, loaded: AppConfig) -> Self:
        self._data = replace(loaded.data)
        self._runtime = replace(loaded.runtime)
        self._session = replace(loaded.session)
        self._strategy = replace(loaded.strategy, params=dict(loaded.strategy.params))
        self._fee = ModelConfig(loaded.fee.name, dict(loaded.fee.params))
        self._slippage = ModelConfig(loaded.slippage.name, dict(loaded.slippage.params))
        self._latency = ModelConfig(loaded.latency.name, dict(loaded.latency.params))
        return self

    # --- runtime ------------------------------------------------------

    def set_mode(self, mode: str) -> Self:
        mode_key = str(mode).strip().lower()
        if mode_key not in RUNTIME_MODES:
            raise ValueError(f"runtime.mode must be one of: {', '.join(sorted(RUNTIME_MODES))}")
        self._runtime = replace(self._runtime, mode=mode_key)
        return self

    def set_initial_cash(self, cash: str | int | float) -> Self:
        self._runtime = replace(self._runtime, initial_cash=str(cash))
        return self

    def set_allow_short(self, allow: bool) -> Self:
        self._runtime = replace(self._runtime, allow_short=bool(allow))
        return self

    def set_database(self, database: str | Path | None) -> Self:
        value = None if database is None else str(database)
        self._runtime = replace(self._runtime, database=value)
        return self

    def set_account_id(self, account_id: str | None) -> Self:
        self._runtime = replace(
            self._runtime,
            account_id=None if account_id is None else str(account_id),
        )
        return self

    def set_label(self, label: str) -> Self:
        self._runtime = replace(self._runtime, label=str(label))
        return self

    def set_runtime(
        self,
        *,
        mode: str | None = None,
        initial_cash: str | int | float | None = None,
        allow_short: bool | None = None,
        database: str | Path | None = ...,  # type: ignore[assignment]
        account_id: str | None = ...,  # type: ignore[assignment]
        label: str | None = None,
    ) -> Self:
        if mode is not None:
            self.set_mode(mode)
        if initial_cash is not None:
            self.set_initial_cash(initial_cash)
        if allow_short is not None:
            self.set_allow_short(allow_short)
        if database is not ...:
            self.set_database(database)  # type: ignore[arg-type]
        if account_id is not ...:
            self.set_account_id(account_id)  # type: ignore[arg-type]
        if label is not None:
            self.set_label(label)
        return self

    # --- data ---------------------------------------------------------

    def set_provider(self, provider: str) -> Self:
        self._data = replace(self._data, provider=str(provider).strip().lower())
        return self

    def set_source(self, source: str | Path) -> Self:
        self._data = replace(self._data, source=str(source))
        return self

    def set_dataset(self, dataset: str) -> Self:
        self._data = replace(self._data, dataset=str(dataset))
        return self

    def set_symbols(self, symbols: Sequence[str] | str) -> Self:
        self._data = replace(self._data, symbols=_symbols(symbols))
        return self

    def set_grain(self, grain: str) -> Self:
        value = str(grain).strip().lower()
        if value not in {"1s", "1m", "daily"}:
            raise ValueError("data.grain must be '1s', '1m', or 'daily'")
        self._data = replace(self._data, grain=value)
        return self

    def set_period(self, start: str | None, end: str | None) -> Self:
        self._data = replace(
            self._data,
            start=None if start is None else str(start),
            end=None if end is None else str(end),
        )
        return self

    def set_fill_session(self, fill: bool) -> Self:
        self._data = replace(self._data, fill_session=bool(fill))
        return self

    def set_session_hours(self, enabled: bool) -> Self:
        self._data = replace(self._data, session_hours=bool(enabled))
        return self

    def set_data(
        self,
        *,
        provider: str | None = None,
        source: str | Path | None = None,
        dataset: str | None = None,
        symbols: Sequence[str] | str | None = None,
        grain: str | None = None,
        start: str | None = ...,  # type: ignore[assignment]
        end: str | None = ...,  # type: ignore[assignment]
        fill_session: bool | None = None,
        session_hours: bool | None = None,
    ) -> Self:
        if provider is not None:
            self.set_provider(provider)
        if source is not None:
            self.set_source(source)
        if dataset is not None:
            self.set_dataset(dataset)
        if symbols is not None:
            self.set_symbols(symbols)
        if grain is not None:
            self.set_grain(grain)
        if start is not ... or end is not ...:
            new_start = self._data.start if start is ... else start
            new_end = self._data.end if end is ... else end
            self.set_period(new_start, new_end)  # type: ignore[arg-type]
        if fill_session is not None:
            self.set_fill_session(fill_session)
        if session_hours is not None:
            self.set_session_hours(session_hours)
        return self

    def set_archive(
        self,
        source: str | Path,
        *,
        symbols: Sequence[str] | str | None = None,
        start: str | None = None,
        end: str | None = None,
        grain: str = "1s",
        fill_session: bool = False,
        session_hours: bool = False,
        mode: str = "offline_backtest",
    ) -> Self:
        """Convenience: archive provider + offline_backtest defaults."""
        self.set_mode(mode)
        self.set_provider("archive")
        self.set_source(source)
        self.set_grain(grain)
        self.set_fill_session(fill_session)
        self.set_session_hours(session_hours)
        if symbols is not None:
            self.set_symbols(symbols)
        if start is not None or end is not None:
            self.set_period(
                start if start is not None else self._data.start,
                end if end is not None else self._data.end,
            )
        return self

    def set_live(
        self,
        *,
        symbols: Sequence[str] | str | None = None,
        provider: str = "goldarb_api",
        source: str = "https://goldarb.ir",
        grain: str = "1s",
        mode: str = "live_paper_local",
        max_polls: int | None = ...,  # type: ignore[assignment]
        poll_seconds: float | None = None,
    ) -> Self:
        """Convenience: live API provider + live_paper_local defaults."""
        self.set_mode(mode)
        self.set_provider(provider)
        self.set_source(source)
        self.set_grain(grain)
        if symbols is not None:
            self.set_symbols(symbols)
        if poll_seconds is not None:
            self.set_poll_seconds(poll_seconds)
        if max_polls is not ...:
            self.set_max_polls(max_polls)  # type: ignore[arg-type]
        return self

    # --- session ------------------------------------------------------

    def set_timezone(self, timezone: str) -> Self:
        self._session = replace(self._session, timezone=str(timezone))
        return self

    def set_session_window(self, start: str, end: str) -> Self:
        self._session = replace(self._session, start=str(start), end=str(end))
        return self

    def set_poll_seconds(self, poll_seconds: float) -> Self:
        value = float(poll_seconds)
        if value <= 0:
            raise ValueError("session.poll_seconds must be positive")
        self._session = replace(self._session, poll_seconds=value)
        return self

    def set_lookback_days(self, days: int) -> Self:
        self._session = replace(self._session, lookback_days=max(0, int(days)))
        return self

    def set_include_session_bars(self, include: bool) -> Self:
        self._session = replace(self._session, include_session_bars=bool(include))
        return self

    def set_max_polls(self, max_polls: int | None) -> Self:
        self._session = replace(
            self._session,
            max_polls=None if max_polls is None else int(max_polls),
        )
        return self

    def set_session(
        self,
        *,
        timezone: str | None = None,
        start: str | None = None,
        end: str | None = None,
        poll_seconds: float | None = None,
        lookback_days: int | None = None,
        include_session_bars: bool | None = None,
        max_polls: int | None = ...,  # type: ignore[assignment]
    ) -> Self:
        if timezone is not None:
            self.set_timezone(timezone)
        if start is not None or end is not None:
            self.set_session_window(
                start if start is not None else self._session.start,
                end if end is not None else self._session.end,
            )
        if poll_seconds is not None:
            self.set_poll_seconds(poll_seconds)
        if lookback_days is not None:
            self.set_lookback_days(lookback_days)
        if include_session_bars is not None:
            self.set_include_session_bars(include_session_bars)
        if max_polls is not ...:
            self.set_max_polls(max_polls)  # type: ignore[arg-type]
        return self

    # --- strategy / models --------------------------------------------

    def set_strategy(self, name: str, *, version: str = "", **params: Any) -> Self:
        self._strategy = StrategyConfig(
            name=str(name),
            version=str(version),
            params=dict(params),
        )
        return self

    def set_strategy_params(self, **params: Any) -> Self:
        merged = dict(self._strategy.params)
        merged.update(params)
        self._strategy = replace(self._strategy, params=merged)
        return self

    def set_fee(self, name: str = "PercentFee", **params: Any) -> Self:
        self._fee = ModelConfig(str(name), dict(params))
        return self

    def set_slippage(self, name: str = "NoSlippage", **params: Any) -> Self:
        self._slippage = ModelConfig(str(name), dict(params))
        return self

    def set_latency(self, name: str = "NoLatency", **params: Any) -> Self:
        self._latency = ModelConfig(str(name), dict(params))
        return self

    # --- finish -------------------------------------------------------

    def build(self) -> AppConfig:
        config = AppConfig(
            data=replace(self._data),
            runtime=replace(self._runtime),
            session=replace(self._session),
            strategy=replace(self._strategy, params=deepcopy(self._strategy.params)),
            fee=ModelConfig(self._fee.name, dict(self._fee.params)),
            slippage=ModelConfig(self._slippage.name, dict(self._slippage.params)),
            latency=ModelConfig(self._latency.name, dict(self._latency.params)),
        )
        config.validate()
        return config


__all__ = [
    "AppConfig",
    "AppConfigBuilder",
    "DataConfig",
    "ModelConfig",
    "RUNTIME_MODES",
    "RuntimeConfig",
    "SessionConfig",
    "StrategyConfig",
]
