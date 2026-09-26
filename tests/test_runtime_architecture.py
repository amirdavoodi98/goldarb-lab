"""Versioned archives, source factories, and configuration-driven runtimes."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from goldarb import AppConfig, Strategy, StrategyRunner, build_strategy
from goldarb.archive import (
    ARCHIVE_SCHEMA_VERSION,
    JsonlDatasetStore,
    download_symbol_bars,
    read_symbol_bars,
    write_symbol_bars,
)
from goldarb.execution import Broker
from goldarb.runtime import build_latency, build_slippage
from goldarb.simulation import RemoteSimulator
from goldarb.simulation.models import MarketSnapshot
from goldarb.sources import ArchiveDatasetSource, historical_source
from goldarb.strategies import PriceMomentumStrategy


class CountingStrategy(Strategy):
    name = "counter"

    def __init__(self) -> None:
        self.events: list[str] = []

    def on_market_data(self, ctx) -> None:
        assert ctx.market is not None
        self.events.append(ctx.market.event_id)


def _bars(day: date, closes=(100, 101)) -> list[dict]:
    origin = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
    return [
        {
            "bar_at": (origin + timedelta(seconds=index)).isoformat(),
            "close": close,
        }
        for index, close in enumerate(closes)
    ]


def test_jsonl_archive_is_versioned_sorted_deduplicated_and_verified(tmp_path):
    rows = list(reversed(_bars(date(2026, 8, 29))))
    rows.append(dict(rows[-1], close=999))
    write_symbol_bars(
        tmp_path,
        {"طلا": rows},
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
        source="https://example.test",
    )
    manifest, restored = read_symbol_bars(tmp_path)
    assert manifest["schema_version"] == ARCHIVE_SCHEMA_VERSION
    assert manifest["source"] == "https://example.test"
    assert manifest["counts"] == {"طلا": 2}
    assert manifest["quality"]["طلا"]["duplicates_removed"] == 1
    assert manifest["quality"]["طلا"]["out_of_order_rows"] >= 1
    assert manifest["quality"]["طلا"]["missing_days"] == []
    assert [row["bar_at"] for row in restored["طلا"]] == sorted(
        row["bar_at"] for row in restored["طلا"]
    )

    (tmp_path / "طلا.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        read_symbol_bars(tmp_path)


def test_v1_jsonl_archive_remains_readable(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"grain": "1s", "symbols": ["طلا"]}), encoding="utf-8"
    )
    (tmp_path / "طلا.jsonl").write_text(
        json.dumps(_bars(date(2026, 8, 29))[0]) + "\n", encoding="utf-8"
    )
    manifest, rows = read_symbol_bars(tmp_path)
    assert manifest["grain"] == "1s"
    assert len(rows["طلا"]) == 1


def test_incremental_download_skips_days_already_in_archive(tmp_path):
    class Fund:
        def __init__(self) -> None:
            self.calls: list[date] = []

        def candles(self, symbol, *, start, end, grain):
            del symbol, end, grain
            self.calls.append(start)
            return _bars(start, (100,))

    class Client:
        def __init__(self) -> None:
            self.fund = Fund()

    client = Client()
    download_symbol_bars(
        client,
        tmp_path,
        days=2,
        end=date(2026, 8, 29),
        symbols=("طلا",),
    )
    assert client.fund.calls == [date(2026, 8, 28), date(2026, 8, 29)]
    download_symbol_bars(
        client,
        tmp_path,
        days=2,
        end=date(2026, 8, 29),
        symbols=("طلا",),
    )
    assert client.fund.calls == [date(2026, 8, 28), date(2026, 8, 29)]


def test_offline_runner_selects_archive_from_config(tmp_path):
    write_symbol_bars(
        tmp_path,
        {"طلا": _bars(date(2026, 8, 29))},
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
    )
    config = AppConfig.from_mapping(
        {
            "data": {
                "provider": "archive",
                "source": str(tmp_path),
                "symbols": ["طلا"],
                "grain": "1s",
                "fill_session": False,
            },
            "runtime": {"mode": "offline_backtest", "initial_cash": "10000"},
            "fee": "NoFee",
        }
    )
    strategy = CountingStrategy()
    result = StrategyRunner.from_config(config).run(strategy)
    assert len(strategy.events) == 2
    assert result.config.strategy_name == "counter"
    assert result.metrics.n_orders == 0


def test_build_strategy_registry_and_runner_auto_build(tmp_path):
    write_symbol_bars(
        tmp_path,
        {"طلا": _bars(date(2026, 8, 29), (100, 101, 99))},
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
    )
    built = build_strategy(
        {"name": "price_momentum", "params": {"quantity": "1", "threshold_pct": "0.1"}}
    )
    assert isinstance(built, PriceMomentumStrategy)
    assert str(built.threshold_pct) == "0.1"
    with pytest.raises(ValueError, match="unknown strategy"):
        build_strategy(name="not_a_strategy")

    config = AppConfig.from_mapping(
        {
            "data": {
                "provider": "archive",
                "source": str(tmp_path),
                "symbols": ["طلا"],
                "grain": "1s",
                "fill_session": False,
            },
            "runtime": {"mode": "offline_backtest", "initial_cash": "100000"},
            "strategy": {
                "name": "price_momentum",
                "params": {"quantity": "1", "threshold_pct": "0.5"},
            },
            "fee": "NoFee",
        }
    )
    result = StrategyRunner.from_config(config).run()
    assert result.config.strategy_name == "price_momentum"
    assert len(result.equity_history) >= 1


def test_app_config_builder_setters(tmp_path):
    write_symbol_bars(
        tmp_path,
        {"طلا": _bars(date(2026, 8, 29), (100, 101))},
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
    )
    config = (
        AppConfig.builder()
        .set_archive(tmp_path, symbols=["طلا"], start="2026-08-29", end="2026-08-29")
        .set_initial_cash(50_000)
        .set_strategy("price_momentum", quantity="1", threshold_pct="0.1")
        .set_fee("NoFee")
        .set_slippage("NoSlippage")
        .set_latency("NoLatency")
        .build()
    )
    assert config.runtime.mode == "offline_backtest"
    assert config.data.provider == "archive"
    assert config.data.symbols == ("طلا",)
    assert config.strategy.name == "price_momentum"
    assert config.fee.name == "NoFee"

    result = StrategyRunner.from_config(config).run()
    assert result.config.strategy_name == "price_momentum"

    live = (
        config.to_builder()
        .set_live(symbols=["طلا", "عیار"], max_polls=3, poll_seconds=2.0)
        .set_strategy_params(threshold_pct="0.2")
        .build()
    )
    assert live.runtime.mode == "live_paper_local"
    assert live.data.provider == "goldarb_api"
    assert live.session.max_polls == 3
    assert live.strategy.params["threshold_pct"] == "0.2"
    assert live.strategy.params["quantity"] == "1"

    with pytest.raises(ValueError, match="runtime.mode"):
        AppConfig.builder().set_mode("not-a-mode")


def test_config_validation_and_model_registries():
    with pytest.raises(ValueError, match="runtime.mode"):
        AppConfig.from_mapping({"runtime": {"mode": "unknown"}})
    with pytest.raises(ValueError, match="requires data.source"):
        AppConfig.from_mapping(
            {
                "data": {"provider": "archive"},
                "runtime": {"mode": "offline_backtest"},
            }
        )
    config = AppConfig.from_mapping(
        {
            "data": {
                "provider": "goldarb_api",
                "start": "2026-08-01",
                "end": "2026-08-02",
            },
            "slippage": {"name": "FixedSlippage", "params": {"amount": "2"}},
            "latency": {"name": "FixedLatency", "params": {"milliseconds": 10}},
        }
    )
    snapshot = MarketSnapshot(
        event_id="x",
        timestamp=datetime(2026, 8, 29, tzinfo=UTC),
        quotes=(),
    )
    assert build_slippage(config.slippage).config() == {"amount": "2"}
    assert build_latency(config.latency).apply_snapshot(snapshot).timestamp == (
        snapshot.timestamp + timedelta(milliseconds=10)
    )


def test_config_file_loader_does_not_contain_credentials(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "data": {
                    "provider": "archive",
                    "source": "file:///tmp/data",
                    "symbols": ["طلا"],
                },
                "runtime": {"mode": "offline_backtest"},
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig.from_file(path)
    assert config.data.source == "file:///tmp/data"
    assert not hasattr(config, "token")


def test_store_protocol_iterates_without_legacy_loader(tmp_path):
    store = JsonlDatasetStore(tmp_path)
    store.write(
        {"طلا": _bars(date(2026, 8, 29))},
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
    )
    assert len(list(store.iter_symbol("طلا"))) == 2


def test_historical_source_registry_uses_client_contract():
    class Fund:
        def candles_many(self, symbols, *, start, end, grain):
            assert (start, end, grain) == ("2026-08-29", "2026-08-29", "1s")
            return {symbol: _bars(date(2026, 8, 29), (100,)) for symbol in symbols}

    class Client:
        fund = Fund()

    source = historical_source("goldarb_api", "https://example.test", client=Client())
    rows = source.bars(("طلا",), start="2026-08-29", end="2026-08-29", grain="1s")
    assert len(rows["طلا"]) == 1
    with pytest.raises(ValueError, match="unknown historical"):
        historical_source("unknown", "")


def test_manifestless_collector_directory_is_a_jsonl_source(tmp_path):
    (tmp_path / "طلا.jsonl").write_text(
        "\n".join(json.dumps(row) for row in _bars(date(2026, 8, 29))),
        encoding="utf-8",
    )
    source = historical_source("jsonl", str(tmp_path))
    assert isinstance(source, ArchiveDatasetSource)
    provider = source.provider(("طلا",), grain="1s", fill_session=False)
    assert len(list(provider.events())) == 2


def test_remote_simulator_satisfies_engine_broker_contract():
    remote = RemoteSimulator(object())  # HTTP is not used for structural check.
    assert isinstance(remote, Broker)


def test_parquet_store_contract_when_extra_is_installed(tmp_path):
    pytest.importorskip("pyarrow")
    archive = tmp_path / "parquet"
    write_symbol_bars(
        archive,
        {"طلا": _bars(date(2026, 8, 29))},
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
        format="parquet",
    )
    manifest, rows = read_symbol_bars(archive)
    assert manifest["format"] == "parquet"
    assert len(rows["طلا"]) == 2
