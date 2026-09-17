from dataclasses import replace
import math
import unittest

from mosaic_lab.allocation import (
    MAX_RESOURCES,
    MAX_TASKS,
    AllocationProblem,
    AllocationResult,
    Assignment,
    ResourceSpec,
    TaskSpec,
    benchmark_allocation,
    solve_cp_sat,
    solve_greedy,
    synthetic_problem,
)


class AllocationTests(unittest.TestCase):
    def test_cp_sat_beats_simple_baseline_on_fixture(self):
        problem = synthetic_problem()
        baseline = solve_greedy(problem)
        result = solve_cp_sat(problem)
        self.assertEqual(result.status, "optimal")
        self.assertEqual(baseline.objective, 6)
        self.assertEqual(result.objective, 8)
        self.assertGreaterEqual(result.objective, baseline.objective)
        self.assertFalse(result.authorized)
        self.assertEqual(result.external_actions, 0)

    def test_deadline_excludes_late_resource(self):
        problem = AllocationProblem(
            tasks=(TaskSpec("t1", 1, 5, deadline=1, required=True),),
            resources=(ResourceSpec("r1", 1, slot=2),),
        )
        result = solve_cp_sat(problem)
        self.assertEqual(result.status, "infeasible")
        self.assertEqual(result.assignments, ())
        self.assertFalse(result.authorized)
        self.assertEqual(result.external_actions, 0)

    def test_required_capacity_can_be_infeasible(self):
        problem = AllocationProblem(
            tasks=(TaskSpec("t1", 2, 5, deadline=1, required=True),),
            resources=(ResourceSpec("r1", 1, slot=1),),
        )
        self.assertEqual(solve_cp_sat(problem).status, "infeasible")

    def test_optional_unallocatable_task_does_not_make_model_infeasible(self):
        problem = AllocationProblem(
            tasks=(TaskSpec("t1", 2, 5, deadline=0),),
            resources=(ResourceSpec("r1", 1, slot=1),),
        )
        result = solve_cp_sat(problem)
        self.assertEqual(result.status, "optimal")
        self.assertEqual(result.objective, 0)
        self.assertEqual(result.assignments, ())

    def test_deterministic_replay(self):
        problem = synthetic_problem()
        a = solve_cp_sat(problem)
        b = solve_cp_sat(problem)
        self.assertEqual((a.status, a.objective, a.assignments), (b.status, b.objective, b.assignments))

    def test_invalid_objective_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "objective"):
            solve_cp_sat(synthetic_problem(), objective="other")

    def test_time_limit_is_bounded(self):
        for value in (0, -1, True, 6.0, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                solve_cp_sat(synthetic_problem(), time_limit_s=value)

    def test_duplicate_ids_fail(self):
        with self.assertRaisesRegex(ValueError, "duplicate task"):
            AllocationProblem(
                tasks=(TaskSpec("t1", 1, 1, 1), TaskSpec("t1", 1, 2, 1)),
                resources=(ResourceSpec("r1", 2, 1),),
            )
        with self.assertRaisesRegex(ValueError, "duplicate resource"):
            AllocationProblem(
                tasks=(TaskSpec("t1", 1, 1, 1),),
                resources=(ResourceSpec("r1", 2, 1), ResourceSpec("r1", 2, 2)),
            )

    def test_invalid_integer_fields_fail(self):
        for factory in (
            lambda: TaskSpec("t1", 0, 1, 1),
            lambda: TaskSpec("t1", 1, -1, 1),
            lambda: TaskSpec("t1", 1, 1, -1),
            lambda: ResourceSpec("r1", 0, 1),
            lambda: ResourceSpec("r1", 1, -1),
        ):
            with self.subTest(factory=factory), self.assertRaises(ValueError):
                factory()

    def test_problem_size_is_bounded(self):
        too_many_tasks = tuple(TaskSpec(f"t{i}", 1, 1, 1) for i in range(MAX_TASKS + 1))
        with self.assertRaisesRegex(ValueError, "tasks"):
            AllocationProblem(too_many_tasks, (ResourceSpec("r1", 1, 1),))
        too_many_resources = tuple(ResourceSpec(f"r{i}", 1, 1) for i in range(MAX_RESOURCES + 1))
        with self.assertRaisesRegex(ValueError, "resources"):
            AllocationProblem((TaskSpec("t1", 1, 1, 1),), too_many_resources)

    def test_assignment_and_result_direct_reconstruction_fail_closed(self):
        for args in (("bad id", "r1"), ("t1", "bad id")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Assignment(*args)
        result = solve_cp_sat(synthetic_problem())
        duplicate = result.assignments + (result.assignments[0],)
        for changes in (
            {"authorized": True},
            {"external_actions": 1},
            {"version": "2"},
            {"status": "unsupported"},
            {"status": "infeasible"},
            {"assignments": list(result.assignments)},
            {"assignments": duplicate},
            {"objective": -1},
            {"objective": True},
            {"elapsed_ms": math.nan},
            {"elapsed_ms": -1.0},
            {"solver": "other"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(result, **changes)

    def test_nonfeasible_receipt_cannot_carry_allocation(self):
        safe = AllocationResult("infeasible", (), 0, 0.0, "ortools-cp-sat-9.15.6755")
        self.assertFalse(safe.authorized)
        self.assertEqual(safe.external_actions, 0)
        with self.assertRaises(ValueError):
            replace(safe, assignments=(Assignment("t1", "r1"),))
        with self.assertRaises(ValueError):
            replace(safe, objective=1)

    def test_benchmark_reports_aggregate_reproducible_evidence(self):
        report = benchmark_allocation(repeats=5)
        self.assertEqual(report["fixture"], "synthetic-v1")
        self.assertGreaterEqual(report["objective"], report["baseline_objective"])
        self.assertGreaterEqual(report["p95_ms"], 0.0)
        self.assertEqual(report["repeats"], 5)


if __name__ == "__main__":
    unittest.main()
