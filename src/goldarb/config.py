"""Serializable configuration for data sources and strategy runtimes."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
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
    end: str = "17:00:00"
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
            end=str(item.get("end") or "17:00:00"),
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


__all__ = [
    "AppConfig",
    "DataConfig",
    "ModelConfig",
    "RUNTIME_MODES",
    "RuntimeConfig",
    "SessionConfig",
    "StrategyConfig",
]
