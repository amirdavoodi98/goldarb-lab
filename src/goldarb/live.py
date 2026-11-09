"""Source-aware price snapshots and checkpointed long-poll observations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._http import LabHttp


class LiveAPI:
    def __init__(self, http: LabHttp) -> None:
        self._http = http

    def snapshot(
        self,
        *,
        symbols: list[str] | None = None,
        source: str = "tsetmc",
        require_verified_source_time: bool = True,
    ) -> dict[str, Any]:
        """Read cached pilot observations, including explicit excluded reasons.

        Unverified source-clock candidates are excluded by default. Setting
        `require_verified_source_time=False` is diagnostic, not an assertion
        that candidate times are trade-execution timestamps. Backend pilot
        must be enabled. This method neither fetches vendors nor subscribes.
        """
        if source not in {"tsetmc", "mofid", "agah"}:
            raise ValueError("source must be tsetmc, mofid or agah")
        if symbols is not None and (not symbols or len(symbols) > 31):
            raise ValueError("symbols must contain 1–31 fund symbols")
        params = {
            "source": source,
            "require_verified_source_time": str(require_verified_source_time).lower(),
        }
        if symbols is not None:
            params["symbols"] = ",".join(symbols)
        payload = self._http.get_json("/api/v1/lab/market-data/snapshot/", params)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("Unsupported Lab market-data snapshot schema")
        return payload

    def events(
        self,
        *,
        cursor: str,
        source: str = "mofid",
        symbols: list[str] | None = None,
        require_verified_source_time: bool = True,
        limit: int = 100,
        block_ms: int = 10000,
    ) -> dict[str, Any]:
        """Read after a checkpoint. HTTP 409 means gap: explicitly resnapshot.

        Checkpoint the returned cursor only after processing the entire batch.
        It advances across filtered events too; an empty batch is meaningful.
        """
        import re

        if source not in {"mofid", "tsetmc", "agah"} or not re.fullmatch(r"[0-9]+-[0-9]+", cursor):
            raise ValueError("Invalid source or cursor")
        if not 1 <= limit <= 500 or not 0 <= block_ms <= 10000:
            raise ValueError("Invalid limit or block_ms")
        if symbols is not None and (not symbols or len(symbols) > 31):
            raise ValueError("symbols must contain 1–31 fund symbols")
        params = {
            "cursor": cursor,
            "source": source,
            "limit": str(limit),
            "block_ms": str(block_ms),
            "require_verified_source_time": str(require_verified_source_time).lower(),
        }
        if symbols is not None:
            params["symbols"] = ",".join(symbols)
        result = self._http.get_json("/api/v1/lab/market-data/events/", params)
        if not isinstance(result, dict) or result.get("schema_version") != 1:
            raise ValueError("Unsupported Lab events schema")
        return result

    def subscribe(
        self,
        *,
        cursor: str,
        source: str = "mofid",
        symbols: list[str] | None = None,
        require_verified_source_time: bool = True,
    ):
        """Long-poll batches until closed; resume with your last processed cursor.

        Connection failures propagate so callers retain the last acknowledged
        cursor. This is a long-poll subscription, not a WebSocket transport.
        """
        while True:
            batch = self.events(
                cursor=cursor,
                source=source,
                symbols=symbols,
                require_verified_source_time=require_verified_source_time,
            )
            yield batch
            cursor = batch["cursor"]
