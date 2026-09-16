import unittest

import numpy as np

from mosaic_lab.simulation import (
    BoundedProposalEnv,
    benchmark_simulation,
    filter_proposal,
    run_baseline_episode,
    select_cp_sat,
    select_heuristic,
    validate_observation,
)


class SimulationTests(unittest.TestCase):
    def test_reset_is_seed_reproducible_and_non_authorizing(self):
        env = BoundedProposalEnv(horizon=4)
        first, info = env.reset(seed=31)
        second, info2 = env.reset(seed=31)
        np.testing.assert_array_equal(first, second)
        self.assertTrue(env.observation_space.contains(first))
        self.assertFalse(info["authorized"])
        self.assertFalse(info2["authorized"])
        self.assertEqual(info["external_actions"], 0)

    def test_invalid_action_fails_before_state_mutation(self):
        env = BoundedProposalEnv(horizon=4)
        env.reset(seed=7)
        before = env.state_receipt()
        for action in (True, -1, 3, 1.5, "1"):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    env.step(action)
                self.assertEqual(env.state_receipt(), before)

    def test_prohibited_proposal_falls_back_to_noop_without_authority(self):
        observation = np.asarray([0.8, 0.9, 0.0, 1.0, 0.0], dtype=np.float32)
        decision = filter_proposal(observation, 1)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.executed_action, 0)
        self.assertFalse(decision.authorized)
        allowed = filter_proposal(observation, 2)
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.executed_action, 2)

    def test_nonfinite_and_malformed_observations_fail_closed(self):
        invalid = (
            np.asarray([0.0, 0.0, 1.0, 1.0], dtype=np.float32),
            np.asarray([np.nan, 0.0, 1.0, 1.0, 0.0], dtype=np.float32),
            np.asarray([0.0, np.inf, 1.0, 1.0, 0.0], dtype=np.float32),
            np.asarray([0.0, 0.0, 0.5, 1.0, 0.0], dtype=np.float32),
            np.asarray([1.1, 0.0, 1.0, 1.0, 0.0], dtype=np.float32),
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_observation(value)

    def test_horizon_truncates_and_reset_options_are_rejected(self):
        env = BoundedProposalEnv(horizon=2)
        with self.assertRaises(ValueError):
            env.reset(seed=1, options={"x": 1})
        observation, _ = env.reset(seed=1)
        action = select_heuristic(observation)
        observation, _, terminated, truncated, _ = env.step(action)
        self.assertFalse(terminated)
        self.assertFalse(truncated)
        action = select_heuristic(observation)
        _, _, terminated, truncated, info = env.step(action)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertFalse(info["authorized"])
        self.assertEqual(info["external_actions"], 0)
        after = env.state_receipt()
        with self.assertRaises(RuntimeError):
            env.step(0)
        self.assertEqual(env.state_receipt(), after)

    def test_baselines_are_reproducible_and_constraint_safe(self):
        first = run_baseline_episode(policy="cp_sat", seed=43, horizon=16)
        second = run_baseline_episode(policy="cp_sat", seed=43, horizon=16)
        self.assertEqual(first["actions"], second["actions"])
        self.assertEqual(first["total_reward"], second["total_reward"])
        self.assertEqual(first["constraint_violations"], 0)
        with self.assertRaises(ValueError):
            run_baseline_episode(policy="unknown", seed=43, horizon=16)

    def test_cp_sat_never_selects_a_disallowed_action(self):
        cases = (
            np.asarray([1.0, 1.0, 0.0, 0.0, 0.2], dtype=np.float32),
            np.asarray([-1.0, 1.0, 1.0, 0.0, 0.2], dtype=np.float32),
            np.asarray([0.2, 0.9, 1.0, 1.0, 0.2], dtype=np.float32),
        )
        for observation in cases:
            with self.subTest(observation=observation):
                action = select_cp_sat(observation)
                self.assertTrue(filter_proposal(observation, action).allowed)

    def test_aggregate_benchmark_is_non_executing(self):
        result = benchmark_simulation(seeds=(7, 19, 31), horizon=16)
        self.assertFalse(result["training_performed"])
        self.assertFalse(result["saved_policy"])
        self.assertFalse(result["authorized"])
        self.assertEqual(result["external_actions"], 0)
        self.assertEqual(result["policies"]["cp_sat"]["constraint_violations"], 0)
        self.assertGreaterEqual(
            result["policies"]["cp_sat"]["mean_total_reward"],
            result["policies"]["noop"]["mean_total_reward"],
        )


if __name__ == "__main__":
    unittest.main()
