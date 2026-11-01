"""P-6 ML Lab Track — offline probability-model experiments via API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._http import LabHttp


class MlAPI:
    """
    Thin client for ``/api/v1/ml/experiments/``.

    Training is **offline / research only** — it does not flip live
    ``PROBABILITY_MODEL_VERSION_ACTIVE`` (stays ``v1_lookup`` until promotion).
    """

    def __init__(self, http: LabHttp) -> None:
        self._http = http

    def list_experiments(self) -> list[dict[str, Any]]:
        return self._http.get_paginated_results("/api/v1/ml/experiments/")

    def get_experiment(self, experiment_id: int) -> dict[str, Any]:
        return self._http.get_json(f"/api/v1/ml/experiments/{int(experiment_id)}/")

    def train_probability_model(
        self,
        *,
        model_type: str = "logistic",
        strategy_id: str | None = None,
        label: str = "",
        force: bool = False,
        n_splits: int | None = None,
    ) -> dict[str, Any]:
        """
        POST offline train (logistic V2).

        ``model_type`` must be ``logistic`` in this release (LightGBM = V3 later).
        Pass ``force=True`` only for dry-runs below the 2000-settled data gate.
        """
        if model_type not in {"logistic", "logistic_v2"}:
            raise ValueError(
                "Only model_type='logistic' is supported in P-6 (LightGBM deferred to V3)"
            )
        body: dict[str, Any] = {
            "label": label or "",
            "force": bool(force),
        }
        if strategy_id:
            body["strategy_id"] = strategy_id
        if n_splits is not None:
            body["n_splits"] = int(n_splits)
        return self._http.post_json("/api/v1/ml/experiments/train/", body)
