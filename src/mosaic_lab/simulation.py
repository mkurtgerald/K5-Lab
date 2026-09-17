"""Bounded generic simulation for proposal evaluation only.

The environment is synthetic, non-authorizing, and has no external effects. It
exposes one fixed observation/action contract and project-owned hard filtering so
a proposed prohibited action is never executed, even inside the simulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from time import perf_counter

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from ortools.sat.python import cp_model

SIMULATION_VERSION = "1"
OBSERVATION_DIM = 5
ACTION_COUNT = 3
MAX_HORIZON = 128
DEFAULT_HORIZON = 64
CP_SAT_TIME_SECONDS = 0.1
UTILITY_SCALE = 100


def _bounded_horizon(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_HORIZON:
        raise ValueError("horizon out of range")
    return value


def _action(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError("action must be an integer")
    parsed = int(value)
    if not 0 <= parsed < ACTION_COUNT:
        raise ValueError("action out of range")
    return parsed


def validate_observation(value: np.ndarray) -> np.ndarray:
    array = np.asarray(value)
    if array.shape != (OBSERVATION_DIM,):
        raise ValueError("invalid observation shape")
    if not np.issubdtype(array.dtype, np.number):
        raise ValueError("observation must be numeric")
    array = array.astype(np.float32, copy=False)
    if not np.all(np.isfinite(array)):
        raise ValueError("observation must be finite")
    if np.any(array[:2] < -1.0) or np.any(array[:2] > 1.0):
        raise ValueError("utility observation out of range")
    if np.any(array[2:4] < 0.0) or np.any(array[2:4] > 1.0):
        raise ValueError("constraint observation out of range")
    if not np.all(np.isin(array[2:4], np.asarray((0.0, 1.0), dtype=np.float32))):
        raise ValueError("constraint flags must be binary")
    if not 0.0 <= float(array[4]) <= 1.0:
        raise ValueError("phase observation out of range")
    return array


@dataclass(frozen=True)
class ProposalDecision:
    proposed_action: int
    executed_action: int
    allowed: bool
    authorized: bool = False
    external_actions: int = 0
    version: str = SIMULATION_VERSION

    def __post_init__(self) -> None:
        proposed = _action(self.proposed_action)
        executed = _action(self.executed_action)
        if not isinstance(self.allowed, bool):
            raise ValueError("allowed must be boolean")
        if self.version != SIMULATION_VERSION:
            raise ValueError("unsupported proposal decision version")
        if self.authorized is not False or self.external_actions != 0:
            raise ValueError("proposal decisions have no execution authority")
        if self.allowed and executed != proposed:
            raise ValueError("allowed proposal must preserve proposed action")
        if not self.allowed and executed != 0:
            raise ValueError("prohibited proposal must fall back to no-op")


def allowed_actions(observation: np.ndarray) -> tuple[int, ...]:
    obs = validate_observation(observation)
    allowed = [0]
    if float(obs[2]) == 1.0:
        allowed.append(1)
    if float(obs[3]) == 1.0:
        allowed.append(2)
    return tuple(allowed)


def filter_proposal(observation: np.ndarray, proposed_action: int) -> ProposalDecision:
    action = _action(proposed_action)
    permitted = action in allowed_actions(observation)
    return ProposalDecision(action, action if permitted else 0, permitted)


def action_utility(observation: np.ndarray, action: int) -> float:
    obs = validate_observation(observation)
    action = _action(action)
    if action == 0:
        return 0.0
    return float(obs[action - 1])


class BoundedProposalEnv(gym.Env[np.ndarray, int]):
    """Small opaque Gymnasium environment with hard project-owned constraints."""

    metadata = {"render_modes": []}

    def __init__(self, *, horizon: int = DEFAULT_HORIZON, version: str = SIMULATION_VERSION):
        if version != SIMULATION_VERSION:
            raise ValueError("unsupported simulation version")
        self.horizon = _bounded_horizon(horizon)
        self.version = version
        self.observation_space = spaces.Box(
            low=np.asarray([-1.0, -1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            high=np.asarray([1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float32),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(ACTION_COUNT)
        self._observation: np.ndarray | None = None
        self._step_index = 0
        self._constraint_violations = 0
        self._done = False

    def _next_observation(self) -> np.ndarray:
        utilities = self.np_random.integers(-100, 101, size=2).astype(np.float32) / UTILITY_SCALE
        permitted = self.np_random.integers(0, 2, size=2).astype(np.float32)
        phase = np.asarray([self._step_index / self.horizon], dtype=np.float32)
        observation = np.concatenate((utilities, permitted, phase)).astype(np.float32, copy=False)
        return validate_observation(observation).copy()

    def _info(self) -> dict[str, object]:
        return {
            "simulation_version": self.version,
            "step_index": self._step_index,
            "constraint_violations": self._constraint_violations,
            "authorized": False,
            "external_actions": 0,
        }

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        if options is not None:
            raise ValueError("reset options are not supported")
        super().reset(seed=seed)
        self._step_index = 0
        self._constraint_violations = 0
        self._done = False
        self._observation = self._next_observation()
        return self._observation.copy(), self._info()

    def step(self, action: int):
        parsed = _action(action)
        if self._observation is None:
            raise RuntimeError("reset required before step")
        if self._done:
            raise RuntimeError("reset required after truncation")
        current = self._observation.copy()
        decision = filter_proposal(current, parsed)
        if decision.allowed:
            reward = action_utility(current, decision.executed_action)
        else:
            self._constraint_violations += 1
            reward = -1.0
        self._step_index += 1
        truncated = self._step_index >= self.horizon
        self._done = truncated
        if not truncated:
            self._observation = self._next_observation()
        info = self._info() | {
            "proposed_action": decision.proposed_action,
            "executed_action": decision.executed_action,
            "proposal_allowed": decision.allowed,
        }
        observation = current.copy() if truncated else self._observation.copy()
        return observation, float(reward), False, truncated, info

    def state_receipt(self) -> tuple[int, int, bool, tuple[float, ...] | None]:
        observation = None if self._observation is None else tuple(float(v) for v in self._observation)
        return self._step_index, self._constraint_violations, self._done, observation


def select_noop(observation: np.ndarray) -> int:
    validate_observation(observation)
    return 0


def select_heuristic(observation: np.ndarray) -> int:
    obs = validate_observation(observation)
    permitted = allowed_actions(obs)
    if 1 in permitted and float(obs[0]) > 0.0:
        return 1
    if 2 in permitted and float(obs[1]) > 0.0:
        return 2
    return 0


def select_cp_sat(observation: np.ndarray) -> int:
    obs = validate_observation(observation)
    permitted = set(allowed_actions(obs))
    utilities = (
        0,
        int(round(float(obs[0]) * UTILITY_SCALE)),
        int(round(float(obs[1]) * UTILITY_SCALE)),
    )
    model = cp_model.CpModel()
    choices = [model.new_bool_var(f"a_{index}") for index in range(ACTION_COUNT)]
    model.add(sum(choices) == 1)
    for index, choice in enumerate(choices):
        if index not in permitted:
            model.add(choice == 0)
    model.maximize(sum(utilities[index] * choice for index, choice in enumerate(choices)))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = CP_SAT_TIME_SECONDS
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("bounded proposal model was not feasible")
    selected = [index for index, choice in enumerate(choices) if solver.value(choice)]
    if len(selected) != 1 or selected[0] not in permitted:
        raise RuntimeError("solver returned invalid proposal")
    return selected[0]


_POLICIES = {
    "noop": select_noop,
    "heuristic": select_heuristic,
    "cp_sat": select_cp_sat,
}


def run_baseline_episode(*, policy: str, seed: int, horizon: int = DEFAULT_HORIZON) -> dict[str, object]:
    if policy not in _POLICIES:
        raise ValueError("unsupported policy")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed out of range")
    env = BoundedProposalEnv(horizon=horizon)
    observation, _ = env.reset(seed=seed)
    total_reward = 0.0
    actions: list[int] = []
    latencies_ms: list[float] = []
    while True:
        started = perf_counter()
        action = _POLICIES[policy](observation)
        latencies_ms.append((perf_counter() - started) * 1000.0)
        observation, reward, terminated, truncated, info = env.step(action)
        actions.append(action)
        total_reward += reward
        if terminated or truncated:
            break
    latencies = sorted(latencies_ms)
    p50 = latencies[(len(latencies) - 1) // 2]
    p95 = latencies[max(0, ceil(0.95 * len(latencies)) - 1)]
    return {
        "policy": policy,
        "seed": seed,
        "horizon": env.horizon,
        "steps": len(actions),
        "total_reward": round(total_reward, 6),
        "constraint_violations": int(info["constraint_violations"]),
        "actions": tuple(actions),
        "p50_decision_ms": round(p50, 6),
        "p95_decision_ms": round(p95, 6),
        "authorized": False,
        "external_actions": 0,
    }


def benchmark_simulation(
    *, seeds: tuple[int, ...] = (7, 19, 31, 43, 59), horizon: int = DEFAULT_HORIZON
) -> dict[str, object]:
    horizon = _bounded_horizon(horizon)
    if not isinstance(seeds, tuple) or not 3 <= len(seeds) <= 16 or len(set(seeds)) != len(seeds):
        raise ValueError("3-16 unique seeds required")
    for seed in seeds:
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
            raise ValueError("seed out of range")

    per_policy: dict[str, dict[str, object]] = {}
    for policy in _POLICIES:
        episodes = [run_baseline_episode(policy=policy, seed=seed, horizon=horizon) for seed in seeds]
        rewards = [float(episode["total_reward"]) for episode in episodes]
        p95_values = [float(episode["p95_decision_ms"]) for episode in episodes]
        violations = sum(int(episode["constraint_violations"]) for episode in episodes)
        per_policy[policy] = {
            "mean_total_reward": round(float(np.mean(rewards)), 6),
            "min_total_reward": round(min(rewards), 6),
            "max_total_reward": round(max(rewards), 6),
            "max_p95_decision_ms": round(max(p95_values), 6),
            "constraint_violations": violations,
        }
    if per_policy["cp_sat"]["constraint_violations"] != 0:
        raise RuntimeError("constrained baseline produced a prohibited action")
    if float(per_policy["cp_sat"]["mean_total_reward"]) < float(per_policy["noop"]["mean_total_reward"]):
        raise RuntimeError("constrained baseline underperformed no-op on fixed seeds")
    if float(per_policy["cp_sat"]["mean_total_reward"]) < float(per_policy["heuristic"]["mean_total_reward"]):
        raise RuntimeError("constrained baseline underperformed heuristic on fixed seeds")
    return {
        "fixture": "generic-simulation-v1",
        "seeds": list(seeds),
        "horizon": horizon,
        "policies": per_policy,
        "training_performed": False,
        "saved_policy": False,
        "authorized": False,
        "external_actions": 0,
        "commercial_distribution_approved": False,
    }
