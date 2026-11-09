"""Immutable signal domain results; serialization stays at the SDK boundary."""

from dataclasses import dataclass

from .models import (
    BubbleRanking,
    PairSide,
    PairSignal,
    PairSpreadStats,
    RankedPair,
    RankedSymbol,
    SampleStatus,
    SpreadStatus,
)


@dataclass(frozen=True)
class SymbolRanking:
    symbol: str
    current: float | None
    avg20: float | None
    score: float | None
    sample_count: int
    window_days: int
    status: SampleStatus

    def to_dict(self) -> RankedSymbol:
        return {
            "symbol": self.symbol,
            "current": self.current,
            "avg20": self.avg20,
            "score": self.score,
            "sample_count": self.sample_count,
            "window_days": self.window_days,
            "status": self.status,
        }


@dataclass(frozen=True)
class RankingPair:
    active: bool
    long_symbol: str
    short_symbol: str
    long_score: float
    short_score: float
    gap: float
    label_fa: str

    def to_dict(self) -> RankedPair:
        return {
            "active": self.active,
            "long": self.long_symbol,
            "short": self.short_symbol,
            "long_score": self.long_score,
            "short_score": self.short_score,
            "gap": self.gap,
            "label_fa": self.label_fa,
        }


@dataclass(frozen=True)
class RankingResult:
    window_days: int
    rankings: tuple[SymbolRanking, ...]
    best_pair: RankingPair | None

    def to_dict(self) -> BubbleRanking:
        return {
            "window_days": self.window_days,
            "rankings": [row.to_dict() for row in self.rankings],
            "best_pair": None if self.best_pair is None else self.best_pair.to_dict(),
        }


@dataclass(frozen=True)
class PairSignalResult:
    active: bool
    side: PairSide | None
    long_symbol: str | None
    short_symbol: str | None
    abs_z: float | None
    label_fa: str
    detail_fa: str
    premium_long: float | None = None
    premium_short: float | None = None

    def to_dict(self) -> PairSignal:
        result: PairSignal = {
            "active": self.active,
            "side": self.side,
            "long": self.long_symbol,
            "short": self.short_symbol,
            "abs_z": self.abs_z,
            "label_fa": self.label_fa,
            "detail_fa": self.detail_fa,
        }
        if self.active:
            result["premium_long"] = self.premium_long
            result["premium_short"] = self.premium_short
        return result


@dataclass(frozen=True)
class PairSpreadResult:
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
    pair_signal: PairSignalResult

    def to_dict(self) -> PairSpreadStats:
        return {
            "fund_a": self.fund_a,
            "fund_b": self.fund_b,
            "price_a": self.price_a,
            "price_b": self.price_b,
            "spread_pct": self.spread_pct,
            "premium_a": self.premium_a,
            "premium_b": self.premium_b,
            "premium_spread_pct": self.premium_spread_pct,
            "window_days": self.window_days,
            "sample_count": self.sample_count,
            "min_sample_count": self.min_sample_count,
            "min_samples_met": self.min_samples_met,
            "mean": self.mean,
            "std": self.std,
            "percentile": self.percentile,
            "z_score": self.z_score,
            "z_threshold": self.z_threshold,
            "status": self.status,
            "pair_signal": self.pair_signal.to_dict(),
        }
