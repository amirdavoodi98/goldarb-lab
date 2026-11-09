"""Static conformance checks, checked by mypy without constructing any clients."""

from goldarb.execution import (
    Broker,
    ConfigurableExecution,
    DelayedOrderSettlement,
    FeeModel,
    LatencyModel,
    NoLatency,
    NoSlippage,
    PercentFee,
    SlippageModel,
)
from goldarb.feed_contracts import FundEndpoint
from goldarb.fund import FundAPI
from goldarb.gateway import LedgerGateway, OrderGateway, RecordingOrderGateway
from goldarb.simulation.paper_broker import LocalPaperBroker
from goldarb.simulation.remote import RemoteSimulator


def verify_implementations(
    local: LocalPaperBroker,
    remote: RemoteSimulator,
    recording: RecordingOrderGateway,
    fund: FundAPI,
) -> None:
    brokers: tuple[Broker, ...] = (local, remote, recording.ledger)
    gateways: tuple[OrderGateway, LedgerGateway] = (recording, recording)
    capabilities: tuple[ConfigurableExecution, DelayedOrderSettlement] = (local, local)
    models: tuple[FeeModel, SlippageModel, LatencyModel] = (
        PercentFee(),
        NoSlippage(),
        NoLatency(),
    )
    endpoint: FundEndpoint = fund
    # Keep these assignments as compile-time interface assertions.
    del brokers, gateways, capabilities, models, endpoint
