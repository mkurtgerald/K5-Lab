"""Bounded generic allocation using OR-Tools CP-SAT.

The adapter exposes one fixed objective and no solver/plugin selection. It accepts only
small immutable integer problems and returns aggregate allocation receipts; it has no
external effects or execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from time import perf_counter

from ortools.sat.python import cp_model

from .contracts import token

MAX_TASKS = 128
MAX_RESOURCES = 32
MAX_INTEGER = 1_000_000
MAX_TIME_SECONDS = 5.0
DEFAULT_TIME_SECONDS = 1.0


def _bounded_int(name: str, value: int, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > MAX_INTEGER:
        raise ValueError(f"{name} out of range")
    return value


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    demand: int
    value: int
    deadline: int
    required: bool = False

    def __post_init__(self) -> None:
        token(self.task_id)
        _bounded_int("demand", self.demand, minimum=1)
        _bounded_int("value", self.value, minimum=0)
        _bounded_int("deadline", self.deadline, minimum=0)
        if not isinstance(self.required, bool):
            raise ValueError("required must be boolean")


@dataclass(frozen=True)
class ResourceSpec:
    resource_id: str
    capacity: int
    slot: int

    def __post_init__(self) -> None:
        token(self.resource_id)
        _bounded_int("capacity", self.capacity, minimum=1)
        _bounded_int("slot", self.slot, minimum=0)


@dataclass(frozen=True)
class AllocationProblem:
    tasks: tuple[TaskSpec, ...]
    resources: tuple[ResourceSpec, ...]
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported allocation version")
        if not isinstance(self.tasks, tuple) or not 1 <= len(self.tasks) <= MAX_TASKS:
            raise ValueError("bounded immutable tasks required")
        if not isinstance(self.resources, tuple) or not 1 <= len(self.resources) <= MAX_RESOURCES:
            raise ValueError("bounded immutable resources required")
        if not all(isinstance(task, TaskSpec) for task in self.tasks):
            raise ValueError("invalid task")
        if not all(isinstance(resource, ResourceSpec) for resource in self.resources):
            raise ValueError("invalid resource")
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("duplicate task id")
        if len({resource.resource_id for resource in self.resources}) != len(self.resources):
            raise ValueError("duplicate resource id")


@dataclass(frozen=True)
class Assignment:
    task_id: str
    resource_id: str


@dataclass(frozen=True)
class AllocationResult:
    status: str
    assignments: tuple[Assignment, ...]
    objective: int
    elapsed_ms: float
    solver: str


_STATUS = {
    cp_model.OPTIMAL: "optimal",
    cp_model.FEASIBLE: "feasible",
    cp_model.INFEASIBLE: "infeasible",
    cp_model.MODEL_INVALID: "invalid",
    cp_model.UNKNOWN: "unknown",
}


def _time_limit(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("time limit must be numeric")
    value = float(value)
    if not 0.0 < value <= MAX_TIME_SECONDS:
        raise ValueError("time limit out of range")
    return value


def solve_cp_sat(
    problem: AllocationProblem,
    *,
    objective: str = "maximize_value",
    time_limit_s: float = DEFAULT_TIME_SECONDS,
) -> AllocationResult:
    """Solve a bounded allocation with deterministic, single-worker CP-SAT."""
    if not isinstance(problem, AllocationProblem):
        raise TypeError("AllocationProblem required")
    if objective != "maximize_value":
        raise ValueError("unsupported objective")
    time_limit_s = _time_limit(time_limit_s)

    model = cp_model.CpModel()
    variables: dict[tuple[int, int], cp_model.IntVar] = {}
    for ti, task in enumerate(problem.tasks):
        eligible = []
        for ri, resource in enumerate(problem.resources):
            if resource.slot <= task.deadline:
                variable = model.new_bool_var(f"x_{ti}_{ri}")
                variables[(ti, ri)] = variable
                eligible.append(variable)
        if task.required and not eligible:
            return AllocationResult("infeasible", (), 0, 0.0, "ortools-cp-sat-9.15.6755")
        if eligible:
            model.add(sum(eligible) == 1 if task.required else sum(eligible) <= 1)

    for ri, resource in enumerate(problem.resources):
        terms = [
            problem.tasks[ti].demand * variable
            for (ti, variable_ri), variable in variables.items()
            if variable_ri == ri
        ]
        if terms:
            model.add(sum(terms) <= resource.capacity)

    model.maximize(
        sum(problem.tasks[ti].value * variable for (ti, _), variable in variables.items())
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.log_search_progress = False

    started = perf_counter()
    status_code = solver.solve(model)
    elapsed_ms = (perf_counter() - started) * 1000.0
    status = _STATUS.get(status_code, "unknown")
    if status not in {"optimal", "feasible"}:
        return AllocationResult(status, (), 0, elapsed_ms, "ortools-cp-sat-9.15.6755")

    assignments = tuple(
        Assignment(problem.tasks[ti].task_id, problem.resources[ri].resource_id)
        for (ti, ri), variable in sorted(variables.items())
        if solver.value(variable)
    )
    objective_value = sum(
        next(task.value for task in problem.tasks if task.task_id == assignment.task_id)
        for assignment in assignments
    )
    return AllocationResult(
        status,
        assignments,
        objective_value,
        elapsed_ms,
        "ortools-cp-sat-9.15.6755",
    )


def solve_greedy(problem: AllocationProblem) -> AllocationResult:
    """Small deterministic baseline; it is intentionally not an optimality claim."""
    if not isinstance(problem, AllocationProblem):
        raise TypeError("AllocationProblem required")
    started = perf_counter()
    remaining = {resource.resource_id: resource.capacity for resource in problem.resources}
    assignments: list[Assignment] = []
    ordered = sorted(problem.tasks, key=lambda task: (not task.required, -task.value, task.task_id))
    resources = sorted(problem.resources, key=lambda resource: (resource.slot, resource.resource_id))

    for task in ordered:
        chosen = next(
            (
                resource
                for resource in resources
                if resource.slot <= task.deadline and remaining[resource.resource_id] >= task.demand
            ),
            None,
        )
        if chosen is None:
            if task.required:
                return AllocationResult(
                    "infeasible", (), 0, (perf_counter() - started) * 1000.0, "deterministic-greedy-v1"
                )
            continue
        remaining[chosen.resource_id] -= task.demand
        assignments.append(Assignment(task.task_id, chosen.resource_id))

    by_id = {task.task_id: task for task in problem.tasks}
    assignments.sort(key=lambda item: (item.task_id, item.resource_id))
    return AllocationResult(
        "feasible",
        tuple(assignments),
        sum(by_id[item.task_id].value for item in assignments),
        (perf_counter() - started) * 1000.0,
        "deterministic-greedy-v1",
    )


def synthetic_problem() -> AllocationProblem:
    """Opaque deterministic fixture where optimization can beat the greedy baseline."""
    return AllocationProblem(
        tasks=(
            TaskSpec("t1", demand=2, value=4, deadline=1),
            TaskSpec("t2", demand=1, value=3, deadline=1),
            TaskSpec("t3", demand=1, value=3, deadline=1),
            TaskSpec("t4", demand=1, value=2, deadline=2),
        ),
        resources=(ResourceSpec("r1", capacity=2, slot=1), ResourceSpec("r2", capacity=1, slot=2)),
    )


def benchmark_allocation(*, repeats: int = 25) -> dict[str, object]:
    """Return aggregate synthetic evidence only; no decisions leave this process."""
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not 5 <= repeats <= 100:
        raise ValueError("repeats out of range")
    problem = synthetic_problem()
    baseline = solve_greedy(problem)
    runs = [solve_cp_sat(problem) for _ in range(repeats)]
    if any(run.status not in {"optimal", "feasible"} for run in runs):
        raise RuntimeError("allocation benchmark did not produce a feasible result")
    latencies = sorted(run.elapsed_ms for run in runs)
    p95 = latencies[max(0, ceil(0.95 * len(latencies)) - 1)]
    objectives = {run.objective for run in runs}
    assignments = {run.assignments for run in runs}
    if len(objectives) != 1 or len(assignments) != 1:
        raise RuntimeError("allocation replay was not deterministic")
    run = runs[-1]
    return {
        "fixture": "synthetic-v1",
        "status": run.status,
        "objective": run.objective,
        "baseline_objective": baseline.objective,
        "p95_ms": round(p95, 3),
        "repeats": repeats,
        "tasks": len(problem.tasks),
        "resources": len(problem.resources),
        "limits": {
            "max_tasks": MAX_TASKS,
            "max_resources": MAX_RESOURCES,
            "max_time_seconds": MAX_TIME_SECONDS,
        },
        "solver": run.solver,
    }
