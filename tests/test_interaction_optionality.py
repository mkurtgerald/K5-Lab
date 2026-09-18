import os
import subprocess
import sys
import textwrap
import unittest


_BLOCKED_INTERACTION_MODULES = (
    "mosaic_lab.approvals",
    "mosaic_lab.audit",
    "mosaic_lab.delegation",
    "mosaic_lab.interaction",
    "mosaic_lab.retrieval",
    "mosaic_lab.rollback",
    "mosaic_lab.rollback_audit",
    "mosaic_lab.text_interaction",
)


class InteractionOptionalityTests(unittest.TestCase):
    def test_independent_baseline_runs_when_interaction_component_is_unavailable(self):
        code = textwrap.dedent(
            """
            import importlib.abc
            import sys

            blocked = {
                "mosaic_lab.approvals",
                "mosaic_lab.audit",
                "mosaic_lab.delegation",
                "mosaic_lab.interaction",
                "mosaic_lab.retrieval",
                "mosaic_lab.rollback",
                "mosaic_lab.rollback_audit",
                "mosaic_lab.text_interaction",
            }

            class BlockInteraction(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname in blocked:
                        raise ModuleNotFoundError(
                            f"interaction component intentionally unavailable: {fullname}"
                        )
                    return None

            sys.meta_path.insert(0, BlockInteraction())

            from mosaic_lab.simulation import run_baseline_episode

            receipt = run_baseline_episode(policy="noop", seed=7, horizon=4)
            assert receipt["steps"] == 4
            assert receipt["authorized"] is False
            assert receipt["external_actions"] == 0
            """
        )

        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            entry for entry in sys.path if isinstance(entry, str)
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
