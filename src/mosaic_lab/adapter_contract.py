"""Versioned, domain-neutral boundary for optional private adapters.

This public contract carries only opaque identifiers and non-authorizing
recommendations. It defines no transport and performs no network, persistence,
or physical action.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable

from .contracts import token, unit_score

CONTRACT_VERSION = "2"
SUPPORTED_VERSIONS = (CONTRACT_VERSION,)
MIN_TIMEOUT_MS = 1
MAX_TIMEOUT_MS = 5_000
MAX_NEGOTIATED_VERSIONS = 8
_RESPONSE_STATUSES = {"recommendation", "abstain", "unavailable", "incompatible", "error"}


class IncompatibleAdapterContract(ValueError):
    """No mutually supported contract version exists."""


def _timeout_ms(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("timeout_ms must be an integer")
    if not MIN_TIMEOUT_MS <= value <= MAX_TIMEOUT_MS:
        raise ValueError("timeout_ms out of range")
    return value


def negotiate_version(remote_versions: Iterable[str]) -> str:
    if isinstance(remote_versions, (str, bytes)):
        raise IncompatibleAdapterContract("remote versions must be a bounded collection")
    versions = tuple(remote_versions)
    if not versions or len(versions) > MAX_NEGOTIATED_VERSIONS:
        raise IncompatibleAdapterContract("bounded remote version set required")
    if len(set(versions)) != len(versions):
        raise IncompatibleAdapterContract("duplicate remote versions are invalid")
    for version in versions:
        try:
            token(version)
        except ValueError as exc:
            raise IncompatibleAdapterContract("invalid remote version token") from exc
    for version in reversed(SUPPORTED_VERSIONS):
        if version in versions:
            return version
    raise IncompatibleAdapterContract("no mutually supported contract version")


@dataclass(frozen=True)
class AdapterRequest:
    request_id: str
    partition: str
    record_id: str
    timeout_ms: int
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        token(self.request_id)
        token(self.partition)
        token(self.record_id)
        _timeout_ms(self.timeout_ms)
        if self.contract_version != CONTRACT_VERSION:
            raise IncompatibleAdapterContract("unsupported request contract version")


@dataclass(frozen=True)
class AdapterResponse:
    request_id: str
    partition: str
    record_id: str
    status: str
    reason_code: str
    operation: str | None = None
    confidence: float | None = None
    contract_version: str = CONTRACT_VERSION
    authorized: bool = False

    def __post_init__(self) -> None:
        token(self.request_id)
        token(self.partition)
        token(self.record_id)
        token(self.reason_code)
        if self.contract_version != CONTRACT_VERSION:
            raise IncompatibleAdapterContract("unsupported response contract version")
        if self.status not in _RESPONSE_STATUSES:
            raise ValueError("unsupported adapter response status")
        if self.authorized is not False:
            raise ValueError("adapter responses are permanently non-authorizing")
        if self.status == "recommendation":
            if self.operation is None or self.confidence is None:
                raise ValueError("recommendation requires operation and confidence")
            token(self.operation)
            unit_score(self.confidence)
        elif self.operation is not None or self.confidence is not None:
            raise ValueError("non-recommendation response cannot carry operation/confidence")


def _bound_response(request: AdapterRequest, *, status: str, reason_code: str) -> AdapterResponse:
    return AdapterResponse(
        request_id=request.request_id,
        partition=request.partition,
        record_id=request.record_id,
        status=status,
        reason_code=reason_code,
    )


def fallback_response(request: AdapterRequest, *, reason_code: str = "adapter_unavailable") -> AdapterResponse:
    return _bound_response(request, status="unavailable", reason_code=reason_code)


def normalize_response(request: AdapterRequest, candidate: object) -> AdapterResponse:
    """Accept only an exact request-identity-correlated v2 response; otherwise fail closed."""
    if not isinstance(candidate, AdapterResponse):
        return _bound_response(request, status="error", reason_code="malformed_response")
    if (
        candidate.contract_version != request.contract_version
        or candidate.request_id != request.request_id
        or candidate.partition != request.partition
        or candidate.record_id != request.record_id
    ):
        return _bound_response(request, status="error", reason_code="contract_mismatch")
    return candidate


def contract_document() -> dict[str, object]:
    return {
        "schema": "k5-lab.adapter-contract/v2",
        "contract_version": CONTRACT_VERSION,
        "supported_versions": list(SUPPORTED_VERSIONS),
        "request": {
            "fields": ["contract_version", "request_id", "partition", "record_id", "timeout_ms"],
            "opaque_identifiers": ["request_id", "partition", "record_id"],
            "timeout_ms": {"minimum": MIN_TIMEOUT_MS, "maximum": MAX_TIMEOUT_MS},
            "additional_fields": False,
        },
        "response": {
            "fields": [
                "contract_version",
                "request_id",
                "partition",
                "record_id",
                "status",
                "reason_code",
                "operation",
                "confidence",
                "authorized",
            ],
            "opaque_identifiers": ["request_id", "partition", "record_id"],
            "correlation_fields": ["contract_version", "request_id", "partition", "record_id"],
            "statuses": sorted(_RESPONSE_STATUSES),
            "authorized": False,
            "recommendation_requires": ["operation", "confidence"],
            "non_recommendation_forbids": ["operation", "confidence"],
            "additional_fields": False,
        },
        "negotiation": {
            "strategy": "highest-mutual-supported",
            "max_remote_versions": MAX_NEGOTIATED_VERSIONS,
            "no_common_version": "incompatible",
        },
        "failure_semantics": {
            "timeout": "unavailable",
            "exception": "error",
            "malformed": "error",
            "correlation_mismatch": "error",
            "rollback_path": "deterministic-safe",
            "broaden_authority": False,
        },
        "transport": {"network_required": False, "persistence_required": False},
        "privacy": {"opaque_identifiers_only": True, "synthetic_public_fixtures_only": True},
    }


def canonical_contract_text() -> str:
    return json.dumps(contract_document(), sort_keys=True, separators=(",", ":")) + "\n"
