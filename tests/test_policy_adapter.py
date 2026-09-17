from dataclasses import replace
import unittest

import numpy as np

from mosaic_lab.policy_adapter import PolicyProposalReceipt, evaluate_policy_proposal


class PolicyAdapterTests(unittest.TestCase):
    def test_scalar_and_singleton_array_outputs_are_bounded(self):
        observation = np.asarray([0.1, 1.0, 0.0], dtype=np.float32)
        scalar = evaluate_policy_proposal(lambda _: 2, observation, allowed_actions=(0, 2), action_count=3)
        array = evaluate_policy_proposal(
            lambda _: np.asarray([2], dtype=np.int64), observation, allowed_actions=(0, 2), action_count=3
        )
        self.assertTrue(scalar.accepted)
        self.assertTrue(array.accepted)
        self.assertEqual(scalar.executed_action, 2)
        self.assertFalse(scalar.authorized)
        self.assertEqual(scalar.external_actions, 0)

    def test_prohibited_output_falls_back(self):
        receipt = evaluate_policy_proposal(lambda _: 1, [0.0, 1.0], allowed_actions=(0, 2), action_count=3)
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.proposed_action, 1)
        self.assertEqual(receipt.executed_action, 0)
        self.assertEqual(receipt.fallback_reason, "prohibited_action")

    def test_predictor_exception_fails_closed(self):
        def broken(_):
            raise RuntimeError("boom")

        receipt = evaluate_policy_proposal(broken, [0.0, 1.0], allowed_actions=(0,), action_count=3)
        self.assertFalse(receipt.accepted)
        self.assertIsNone(receipt.proposed_action)
        self.assertEqual(receipt.executed_action, 0)
        self.assertEqual(receipt.fallback_reason, "predictor_error")

    def test_malformed_policy_outputs_fail_closed(self):
        outputs = (True, 1.0, np.asarray([1, 2]), np.asarray([np.nan]))
        for value in outputs:
            with self.subTest(value=value):
                receipt = evaluate_policy_proposal(
                    lambda _, value=value: value, [0.0], allowed_actions=(0,), action_count=3
                )
                self.assertFalse(receipt.accepted)
                self.assertEqual(receipt.executed_action, 0)
                self.assertEqual(receipt.fallback_reason, "invalid_output")

    def test_invalid_input_and_configuration_fail_before_predictor(self):
        called = False

        def predictor(_):
            nonlocal called
            called = True
            return 0

        invalid_calls = (
            dict(observation=[np.nan], allowed_actions=(0,), action_count=3),
            dict(observation=[0.0], allowed_actions=(1,), action_count=3),
            dict(observation=[0.0], allowed_actions=(0, 0), action_count=3),
            dict(observation=[0.0], allowed_actions=(0,), action_count=0),
        )
        for kwargs in invalid_calls:
            called = False
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    evaluate_policy_proposal(predictor, fallback_action=0, **kwargs)
                self.assertFalse(called)

    def test_predictor_receives_copy(self):
        original = np.asarray([0.25, 0.5], dtype=np.float32)

        def mutate(value):
            value[:] = 0.0
            return 0

        evaluate_policy_proposal(mutate, original, allowed_actions=(0,), action_count=1)
        np.testing.assert_array_equal(original, np.asarray([0.25, 0.5], dtype=np.float32))

    def test_direct_receipt_reconstruction_cannot_claim_authority_or_effects(self):
        receipt = evaluate_policy_proposal(lambda _: 0, [0.0], allowed_actions=(0,), action_count=1)
        for changes in (
            {"authorized": True},
            {"external_actions": 1},
            {"version": "2"},
            {"executed_action": 1},
            {"fallback_reason": "predictor_error"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(receipt, **changes)

    def test_fallback_receipt_state_must_be_internally_consistent(self):
        valid = (
            PolicyProposalReceipt(None, 0, False, "predictor_error"),
            PolicyProposalReceipt(None, 0, False, "invalid_output"),
            PolicyProposalReceipt(1, 0, False, "prohibited_action"),
        )
        self.assertEqual(len(valid), 3)
        invalid = (
            (None, 0, True, None),
            (0, 1, True, None),
            (0, 0, True, "predictor_error"),
            (None, 0, False, None),
            (1, 0, False, "invalid_output"),
            (None, 0, False, "prohibited_action"),
            (0, 0, False, "prohibited_action"),
        )
        for args in invalid:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    PolicyProposalReceipt(*args)


if __name__ == "__main__":
    unittest.main()
