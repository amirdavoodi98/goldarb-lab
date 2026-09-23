"""Offline simulator facade — alias of ``LocalPaperBroker`` for stable imports."""

from __future__ import annotations

from .paper_broker import LocalPaperBroker, LocalSimulator

__all__ = ["LocalPaperBroker", "LocalSimulator"]
