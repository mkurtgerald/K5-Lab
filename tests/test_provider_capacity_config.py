from mosaic_lab.provider_boundary import ProviderBoundaryContract, ProviderBoundaryGate


def hard_contract(boundary_id: str, max_inflight_calls: int) -> ProviderBoundaryContract:
    return ProviderBoundaryContract(
        boundary_id=boundary_id,
        hard_timeout_enforced=True,
        hard_cancellation_enforced=True,
        worker_termination_enforced=True,
        max_inflight_calls=max_inflight_calls,
    )


def test_conflicting_live_capacity_for_same_boundary_fails_closed():
    first_contract = hard_contract("boundary_capacity", 1)
    first_gate = ProviderBoundaryGate(first_contract)

    try:
        ProviderBoundaryGate(hard_contract("boundary_capacity", 2))
    except ValueError as exc:
        assert "conflicting provider boundary capacity" in str(exc)
    else:
        raise AssertionError("conflicting live capacity must fail closed")

    compatible_gate = ProviderBoundaryGate(first_contract)
    assert first_gate.acquire() is True
    try:
        assert compatible_gate.acquire() is False
    finally:
        first_gate.release()

    separate_boundary = ProviderBoundaryGate(hard_contract("boundary_other", 2))
    assert separate_boundary.acquire() is True
    separate_boundary.release()
