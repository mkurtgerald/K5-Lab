"""Bounded, version-pinned checkpoint codec for the S2 streaming candidate.

The codec emits canonical JSON bytes only. It never uses pickle and never reads or
writes files. SHA-256 detects accidental corruption; it is not an authenticity
mechanism, so downstream integrations must authenticate checkpoint storage at a
separate trust boundary.
"""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import hmac
import importlib.metadata
import json
from math import isfinite
from typing import Any

from .contracts import token, utc
from .streaming import MAX_FEATURES, MAX_SOURCES, MAX_UPDATES, MODEL_ID, RiverBinaryAdapter

CHECKPOINT_VERSION = 1
MAX_CHECKPOINT_BYTES = 512_000
MAX_NATIVE_STATE_BYTES = 256_000


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _strict_int(name: str, value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {name}")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"invalid {name}")
    return result


def _exact_keys(name: str, value: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"invalid {name} fields")
    return value


def _components(adapter: RiverBinaryAdapter):
    if not isinstance(adapter, RiverBinaryAdapter):
        raise TypeError("RiverBinaryAdapter required")
    model = adapter._model
    if len(model) != 2:
        raise RuntimeError("unexpected streaming pipeline shape")
    scaler = model[0]
    classifier = model[1]
    if type(scaler).__name__ != "StandardScaler" or type(classifier).__name__ != "LogisticRegression":
        raise RuntimeError("unexpected streaming pipeline components")
    return scaler, classifier


def export_stream_checkpoint(adapter: RiverBinaryAdapter) -> bytes:
    """Export a bounded in-memory checkpoint for the exact pinned S2 candidate."""
    scaler, classifier = _components(adapter)
    expected_features = {f"f{i}" for i in range(adapter.feature_count)}

    counts = {str(key): int(value) for key, value in scaler.counts.items()}
    means = {str(key): float(value) for key, value in scaler.means.items()}
    variances = {str(key): float(value) for key, value in scaler.vars.items()}
    weights = {str(key): float(value) for key, value in classifier.weights.items()}
    for name, mapping in (("scaler counts", counts), ("scaler means", means), ("scaler vars", variances), ("weights", weights)):
        if not set(mapping).issubset(expected_features):
            raise RuntimeError(f"unexpected {name} feature")
    for mapping in (means, variances, weights):
        if any(not isfinite(value) for value in mapping.values()):
            raise RuntimeError("non-finite model state")
    if any(value < 0 for value in variances.values()) or any(value < 0 for value in counts.values()):
        raise RuntimeError("invalid scaler state")

    helper_state = adapter._drift._helper.__getstate__()
    if not isinstance(helper_state, (bytes, bytearray)):
        raise RuntimeError("unexpected native drift state")
    helper_state = bytes(helper_state)
    if not 0 < len(helper_state) <= MAX_NATIVE_STATE_BYTES:
        raise RuntimeError("native drift state out of bounds")

    payload = {
        "checkpoint_version": CHECKPOINT_VERSION,
        "model_id": MODEL_ID,
        "river_version": importlib.metadata.version("river"),
        "partition": adapter.partition,
        "feature_count": adapter.feature_count,
        "abstain_margin": adapter.abstain_margin,
        "max_updates": adapter.max_updates,
        "drift_delta": adapter.drift_delta,
        "updates": adapter.updates,
        "sources": sorted(
            [source_id, utc(observed_at).isoformat()]
            for source_id, observed_at in adapter._last_by_source.items()
        ),
        "scaler": {"counts": counts, "means": means, "vars": variances},
        "classifier": {
            "weights": weights,
            "intercept": float(classifier.intercept),
            "optimizer_iterations": int(classifier.optimizer.n_iterations),
        },
        "drift": {
            "detected": bool(adapter._drift.drift_detected),
            "native_state_b64": base64.b64encode(helper_state).decode("ascii"),
            "native_state_sha256": hashlib.sha256(helper_state).hexdigest(),
        },
        "state_receipt": adapter.state_receipt(),
    }
    payload_bytes = _canonical(payload)
    envelope = {
        "algorithm": "sha256",
        "payload": payload,
        "sha256": hashlib.sha256(payload_bytes).hexdigest(),
    }
    encoded = _canonical(envelope)
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise RuntimeError("checkpoint exceeds size limit")
    return encoded


def restore_stream_checkpoint(
    encoded: bytes,
    *,
    expected_partition: str | None = None,
) -> RiverBinaryAdapter:
    """Restore a trusted-origin checkpoint after strict integrity and schema validation."""
    if not isinstance(encoded, bytes) or not 1 <= len(encoded) <= MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint bytes out of bounds")
    try:
        envelope = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid checkpoint encoding") from exc
    envelope = _exact_keys("checkpoint envelope", envelope, {"algorithm", "payload", "sha256"})
    if envelope["algorithm"] != "sha256" or not isinstance(envelope["sha256"], str):
        raise ValueError("unsupported checkpoint integrity scheme")
    payload = envelope["payload"]
    payload_bytes = _canonical(payload)
    calculated = hashlib.sha256(payload_bytes).hexdigest()
    if not hmac.compare_digest(envelope["sha256"], calculated):
        raise ValueError("checkpoint integrity mismatch")

    payload = _exact_keys(
        "checkpoint payload",
        payload,
        {
            "checkpoint_version",
            "model_id",
            "river_version",
            "partition",
            "feature_count",
            "abstain_margin",
            "max_updates",
            "drift_delta",
            "updates",
            "sources",
            "scaler",
            "classifier",
            "drift",
            "state_receipt",
        },
    )
    if payload["checkpoint_version"] != CHECKPOINT_VERSION or payload["model_id"] != MODEL_ID:
        raise ValueError("unsupported checkpoint model/version")
    if payload["river_version"] != importlib.metadata.version("river"):
        raise ValueError("checkpoint donor version mismatch")

    partition = token(payload["partition"])
    if expected_partition is not None and partition != token(expected_partition):
        raise ValueError("checkpoint partition mismatch")
    feature_count = _strict_int("feature_count", payload["feature_count"], 1, MAX_FEATURES)
    max_updates = _strict_int("max_updates", payload["max_updates"], 1, MAX_UPDATES)
    updates = _strict_int("updates", payload["updates"], 0, max_updates)
    abstain_margin = _finite_number("abstain_margin", payload["abstain_margin"])
    drift_delta = _finite_number("drift_delta", payload["drift_delta"])

    adapter = RiverBinaryAdapter(
        partition,
        feature_count=feature_count,
        abstain_margin=abstain_margin,
        max_updates=max_updates,
        drift_delta=drift_delta,
    )
    expected_features = {f"f{i}" for i in range(feature_count)}

    scaler_state = _exact_keys("scaler", payload["scaler"], {"counts", "means", "vars"})
    for key in ("counts", "means", "vars"):
        if not isinstance(scaler_state[key], dict):
            raise ValueError("invalid scaler mapping")
    scaler_keys = set(scaler_state["counts"])
    if scaler_keys != set(scaler_state["means"]) or scaler_keys != set(scaler_state["vars"]):
        raise ValueError("inconsistent scaler features")
    if not scaler_keys.issubset(expected_features):
        raise ValueError("unexpected scaler feature")
    counts = {
        key: _strict_int("scaler count", value, 0, updates)
        for key, value in scaler_state["counts"].items()
    }
    means = {key: _finite_number("scaler mean", value) for key, value in scaler_state["means"].items()}
    variances = {key: _finite_number("scaler variance", value) for key, value in scaler_state["vars"].items()}
    if any(value < 0 for value in variances.values()):
        raise ValueError("negative scaler variance")

    classifier_state = _exact_keys(
        "classifier",
        payload["classifier"],
        {"weights", "intercept", "optimizer_iterations"},
    )
    if not isinstance(classifier_state["weights"], dict):
        raise ValueError("invalid classifier weights")
    if not set(classifier_state["weights"]).issubset(expected_features):
        raise ValueError("unexpected classifier feature")
    weights = {
        key: _finite_number("classifier weight", value)
        for key, value in classifier_state["weights"].items()
    }
    intercept = _finite_number("classifier intercept", classifier_state["intercept"])
    optimizer_iterations = _strict_int(
        "optimizer_iterations", classifier_state["optimizer_iterations"], 0, updates
    )
    if optimizer_iterations != updates:
        raise ValueError("optimizer/update mismatch")

    sources_raw = payload["sources"]
    if not isinstance(sources_raw, list) or len(sources_raw) > MAX_SOURCES:
        raise ValueError("invalid checkpoint sources")
    last_by_source: dict[str, datetime] = {}
    for item in sources_raw:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("invalid source checkpoint entry")
        source_id = token(item[0])
        if source_id in last_by_source or not isinstance(item[1], str):
            raise ValueError("invalid source checkpoint entry")
        try:
            observed_at = utc(datetime.fromisoformat(item[1]))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid source timestamp") from exc
        last_by_source[source_id] = observed_at

    drift_state = _exact_keys(
        "drift",
        payload["drift"],
        {"detected", "native_state_b64", "native_state_sha256"},
    )
    if not isinstance(drift_state["detected"], bool):
        raise ValueError("invalid drift flag")
    if not isinstance(drift_state["native_state_b64"], str) or not isinstance(
        drift_state["native_state_sha256"], str
    ):
        raise ValueError("invalid native drift state")
    try:
        helper_state = base64.b64decode(drift_state["native_state_b64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid native drift encoding") from exc
    if not 0 < len(helper_state) <= MAX_NATIVE_STATE_BYTES:
        raise ValueError("native drift state out of bounds")
    if not hmac.compare_digest(
        drift_state["native_state_sha256"], hashlib.sha256(helper_state).hexdigest()
    ):
        raise ValueError("native drift integrity mismatch")

    scaler, classifier = _components(adapter)
    scaler.counts.update(counts)
    scaler.means.update(means)
    scaler.vars.update(variances)
    for key, value in weights.items():
        classifier._weights[key] = value
    classifier.intercept = intercept
    classifier.optimizer.n_iterations = optimizer_iterations
    adapter._last_by_source = last_by_source
    adapter._updates = updates
    try:
        adapter._drift._helper.__setstate__(helper_state)
    except Exception as exc:
        raise ValueError("native drift state rejected") from exc
    adapter._drift._drift_detected = drift_state["detected"]

    if not isinstance(payload["state_receipt"], str) or not hmac.compare_digest(
        adapter.state_receipt(), payload["state_receipt"]
    ):
        raise ValueError("checkpoint state receipt mismatch")
    return adapter
