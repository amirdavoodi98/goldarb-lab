"""LabClient — entry point for strategy notebooks."""

from __future__ import annotations

import os
from typing import Self

from ._http import LabHttp
from .fund import FundAPI
from .market import MarketAPI


class LabClient:
    """
    Thin authenticated client over Gold Arbitrage ``/api/v1/``.

    Prefer ``LabClient.from_env()`` with ``GOLDARB_BASE_URL`` + ``GOLDARB_TOKEN``.
    """

    def __init__(self, *, base_url: str, token: str, timeout: float = 60.0) -> None:
        self._http = LabHttp(base_url=base_url, token=token, timeout=timeout)
        self.fund = FundAPI(self._http)
        self.market = MarketAPI(self._http)

    @classmethod
    def from_env(
        cls,
        *,
        base_url_var: str = "GOLDARB_BASE_URL",
        token_var: str = "GOLDARB_TOKEN",
        timeout: float = 60.0,
    ) -> Self:
        base = os.environ.get(base_url_var, "").strip()
        token = os.environ.get(token_var, "").strip()
        if not base or not token:
            raise RuntimeError(
                f"Set {base_url_var} and {token_var} (see README.md)"
            )
        return cls(base_url=base, token=token, timeout=timeout)

    @classmethod
    def login(
        cls,
        *,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 60.0,
    ) -> Self:
        """Obtain a DRF token via ``POST /api/v1/auth/token/`` then build a client."""
        import httpx

        base = base_url.rstrip("/")
        resp = httpx.post(
            f"{base}/api/v1/auth/token/",
            json={"username": username, "password": password},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        token = payload.get("token") or payload.get("key")
        if not token:
            raise RuntimeError("auth/token response missing token")
        return cls(base_url=base, token=str(token), timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
