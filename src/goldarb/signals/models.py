"""Dictionary contracts for public signal results.

These records stay JSON-compatible dictionaries for SDK consumers. Optional
keys describe fields that are absent from inactive signals, rather than adding
new null-valued keys to the wire format.
"""

from typing import Literal, NotRequired, TypedDict

SampleStatus = Literal["ok", "insufficient_samples"]
SpreadStatus = Literal["ok", "insufficient_samples", "zero_variance"]
PairSide = Literal["long_b_short_a", "long_a_short_b"]


class PairSignal(TypedDict):
    active: bool
    side: PairSide | None
    long: str | None
    short: str | None
    abs_z: float | None
    label_fa: str
    detail_fa: str
    premium_long: NotRequired[float | None]
    premium_short: NotRequired[float | None]


class PairSpreadStats(TypedDict):
    fund_a: str
    fund_b: str
    price_a: float | None
    price_b: float | None
    spread_pct: float | None
    premium_a: float | None
    premium_b: float | None
    premium_spread_pct: float | None
    window_days: int
    sample_count: int
    min_sample_count: int
    min_samples_met: bool
    mean: float | None
    std: float | None
    percentile: float | None
    z_score: float | None
    z_threshold: float
    status: SpreadStatus
    pair_signal: PairSignal


class SymbolScore(TypedDict):
    current: float | None
    avg20: float | None
    score: float | None
    sample_count: int
    window_days: int
    status: SampleStatus


class RankedSymbol(SymbolScore):
    symbol: str


class RankedPair(TypedDict):
    active: bool
    long: str
    short: str
    long_score: float
    short_score: float
    gap: float
    label_fa: str


class BubbleRanking(TypedDict):
    window_days: int
    rankings: list[RankedSymbol]
    best_pair: RankedPair | None
