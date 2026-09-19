import unittest

import numpy as np

from mosaic_lab.simulation import (
    MAX_HORIZON,
    BoundedProposalEnv,
    filter_proposal,
    run_baseline_episode,
    select_cp_sat,
    select_heuristic,
)


class SimulationExtremeHorizonTests(unittest.TestCase):
    def test_max_horizon_cp_sat_stays_bounded_safe_and_non_authorizing(self):
        seed = 2**31 - 1
        constrained = run_baseline_episode(policy="cp_sat", seed=seed, horizon=MAX_HORIZON)
        heuristic = run_baseline_episode(policy="heuristic", seed=seed, horizon=MAX_HORIZON)
        replay = run_baseline_episode(policy="heuristic", seed=seed, horizon=MAX_HORIZON)

        self.assertEqual(constrained["steps"], MAX_HORIZON)
        self.assertEqual(heuristic["steps"], MAX_HORIZON)
        self.assertEqual(constrained["constraint_violations"], 0)
        self.assertEqual(heuristic["constraint_violations"], 0)
        self.assertGreaterEqual(constrained["total_reward"], heuristic["total_reward"])
        self.assertEqual(heuristic["actions"], replay["actions"])
        self.assertEqual(heuristic["total_reward"], replay["total_reward"])
        for receipt in (constrained, heuristic, replay):
            self.assertFalse(receipt["authorized"])
            self.assertEqual(receipt["external_actions"], 0)

    def test_extreme_valid_states_preserve_hard_constraints(self):
        cases = (
            np.asarray([1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float32),
            np.asarray([-1.0, -1.0, 1.0, 1.0, 0.0], dtype=np.float32),
            np.asarray([1.0, -1.0, 0.0, 1.0, 0.5], dtype=np.float32),
            np.asarray([-1.0, 1.0, 1.0, 0.0, 1.0], dtype=np.float32),
            np.asarray([1.0, 1.0, 0.0, 0.0, 1.0], dtype=np.float32),
        )
        for observation in cases:
            with self.subTest(observation=observation):
                for selector in (select_heuristic, select_cp_sat):
                    decision = filter_proposal(observation, selector(observation))
                    self.assertTrue(decision.allowed)
                    self.assertFalse(decision.authorized)
                    self.assertEqual(decision.external_actions, 0)

                for proposed in (1, 2):
                    decision = filter_proposal(observation, proposed)
                    if not decision.allowed:
                        self.assertEqual(decision.executed_action, 0)
                        self.assertFalse(decision.authorized)
                        self.assertEqual(decision.external_actions, 0)

    def test_horizon_overflow_and_type_confusion_fail_before_execution(self):
        for horizon in (0, MAX_HORIZON + 1, True, 1.0, "128"):
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                BoundedProposalEnv(horizon=horizon)


if __name__ == "__main__":
    unittest.main()
