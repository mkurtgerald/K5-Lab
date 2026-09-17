from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.adapter_contract import (
    AdapterRequest,
    IncompatibleAdapterContract,
    fallback_response,
    negotiate_version,
)
from mosaic_lab.allocation import solve_cp_sat, solve_greedy, synthetic_problem
from mosaic_lab.policy_adapter import evaluate_policy_proposal
from mosaic_lab.stream_checkpoint import restore_stream_checkpoint


def _safe_paths_available() -> dict[str, object]:
    problem = synthetic_problem()
    deterministic = solve_greedy(problem)
    constrained = solve_cp_sat(problem)
    return {
        "deterministic_status": deterministic.status,
        "cp_sat_status": constrained.status,
        "deterministic_available": deterministic.status in {"optimal", "feasible"},
        "cp_sat_available": constrained.status in {"optimal", "feasible"},
        "non_authorizing": (
            deterministic.authorized is False
            and deterministic.external_actions == 0
            and constrained.authorized is False
            and constrained.external_actions == 0
        ),
    }


def _policy_failure(exc: Exception) -> dict[str, object]:
    def failing_predictor(_):
        raise exc

    receipt = evaluate_policy_proposal(
        failing_predictor,
        np.asarray([0.0, 1.0], dtype=np.float32),
        allowed_actions=(0, 1),
        action_count=3,
        fallback_action=0,
    )
    return {
        "fallback_reason": receipt.fallback_reason,
        "fallback_action": receipt.executed_action,
        "fallback_non_authorizing": (
            receipt.accepted is False
            and receipt.authorized is False
            and receipt.external_actions == 0
        ),
        **_safe_paths_available(),
    }


def run() -> dict[str, object]:
    learned_runtime_absent = _policy_failure(ImportError("optional learned runtime unavailable"))
    learned_health_failure = _policy_failure(RuntimeError("optional learned runtime unhealthy"))

    corrupted_checkpoint_rejected = False
    try:
        restore_stream_checkpoint(b"{corrupted")
    except ValueError:
        corrupted_checkpoint_rejected = True
    corrupted_checkpoint = {
        "corrupted_checkpoint_rejected": corrupted_checkpoint_rejected,
        **_safe_paths_available(),
    }

    incompatible_rejected = False
    try:
        negotiate_version(("2",))
    except IncompatibleAdapterContract:
        incompatible_rejected = True
    request = AdapterRequest("req-release", "p1", "r1", timeout_ms=250)
    fallback = fallback_response(request, reason_code="adapter_incompatible")
    incompatible_adapter = {
        "incompatible_contract_rejected": incompatible_rejected,
        "fallback_status": fallback.status,
        "fallback_non_authorizing": (
            fallback.authorized is False
            and fallback.operation is None
            and fallback.confidence is None
        ),
        **_safe_paths_available(),
    }

    cases = {
        "learned_runtime_absent": learned_runtime_absent,
        "learned_health_failure": learned_health_failure,
        "corrupted_checkpoint": corrupted_checkpoint,
        "incompatible_adapter": incompatible_adapter,
    }
    required_true = {
        "deterministic_available",
        "cp_sat_available",
        "non_authorizing",
    }
    passed = True
    for case in cases.values():
        passed = passed and all(case.get(key) is True for key in required_true)
    passed = (
        passed
        and learned_runtime_absent["fallback_reason"] == "predictor_error"
        and learned_health_failure["fallback_reason"] == "predictor_error"
        and learned_runtime_absent["fallback_action"] == 0
        and learned_health_failure["fallback_action"] == 0
        and learned_runtime_absent["fallback_non_authorizing"] is True
        and learned_health_failure["fallback_non_authorizing"] is True
        and corrupted_checkpoint["corrupted_checkpoint_rejected"] is True
        and incompatible_adapter["incompatible_contract_rejected"] is True
        and incompatible_adapter["fallback_status"] == "unavailable"
        and incompatible_adapter["fallback_non_authorizing"] is True
    )
    if not passed:
        raise RuntimeError("release fail-safe qualification failed")
    return {
        "schema": "k5-lab.release-failsafe/v1",
        "scope": "synthetic_release_failure_paths_only",
        "cases": cases,
        "passed": True,
        "authorized": False,
        "external_actions": 0,
        "commercial_distribution": False,
        "production_qualified": False,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
