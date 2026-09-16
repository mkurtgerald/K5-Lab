"""Generic non-executing gate. No transport, executor, or production policy."""
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from .contracts import Proposal, utc, unit_score
from .graph import RecordGraph


@dataclass(frozen=True)
class Verdict:
    status: str
    reason: str
    proposal_id: str
    execute: bool = False


class ProposalGate:
    def __init__(self, graph: RecordGraph, *, minimum_score: float = 0.8,
                 max_age_seconds: float = 30.0):
        self.graph = graph
        self.minimum_score = unit_score(minimum_score)
        if (isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float))
                or not isfinite(max_age_seconds) or max_age_seconds <= 0):
            raise ValueError("invalid freshness limit")
        self.max_age_seconds = float(max_age_seconds)

    def assess(self, proposal: Proposal, *, now: datetime) -> Verdict:
        now = utc(now)
        def result(status: str, reason: str) -> Verdict:
            return Verdict(status, reason, proposal.proposal_id)
        if proposal.partition != self.graph.partition:
            return result("denied", "partition_mismatch")
        if proposal.operation not in {"noop", "recommend"}:
            return result("denied", "unsupported_operation")
        record = self.graph.get(proposal.record_id)
        if record is None:
            return result("abstain", "missing_record")
        for timestamp in (record.observed_at, proposal.created_at):
            age = (now - utc(timestamp)).total_seconds()
            if age < 0:
                return result("abstain", "future_timestamp")
            if age > self.max_age_seconds:
                return result("abstain", "stale_input")
        if utc(proposal.created_at) < utc(record.observed_at):
            return result("abstain", "proposal_precedes_record")
        if min(record.score, proposal.score) < self.minimum_score:
            return result("abstain", "insufficient_score")
        return result("recommendation", "non_executing_only")


def audit_digest(verdict: Verdict, previous: str = "0" * 64) -> str:
    """Demonstration digest, not signed, durable, or compliance-grade evidence."""
    if len(previous) != 64 or any(c not in "0123456789abcdef" for c in previous):
        raise ValueError("invalid previous digest")
    payload = json.dumps(asdict(verdict), sort_keys=True, separators=(",", ":"))
    return sha256((previous + payload).encode()).hexdigest()
