"""Parity tests — the contract that makes the optimal-vs-greedy study valid.

If the CP-SAT objective and the shared scorer ever disagree, the headline gap is
an artifact. These tests assert they agree exactly, on the optimal schedule and
across many random instances, and that greedy schedules are scored by the very
same function.
"""

from __future__ import annotations

import pytest

from pqcsched import (
    RiskModel, score_schedule, solve_cpsat, greedy_schedule, BASELINES,
    generate, GenParams, OPTIMAL,
)
from pqcsched.result import INFEASIBLE


RM = RiskModel()


def _solve(inst):
    return solve_cpsat(inst, RM, time_limit=20, workers=4)


@pytest.mark.parametrize("seed", range(12))
def test_cpsat_objective_equals_scorer(seed):
    """solver.ObjectiveValue() must equal score_schedule(...).risk exactly."""
    inst = generate(GenParams(size=14, T=10, dep_density=0.3,
                              budget_tightness=0.7, deadline_pressure=0.3,
                              cluster_frac=0.2, t_crqc=7, seed=seed))
    res = _solve(inst)
    if res.status == INFEASIBLE:
        pytest.skip("infeasible instance (acceptable; harness logs these)")
    assert res.schedule is not None
    sc = score_schedule(inst, res.schedule, RM)
    assert sc.risk == res.objective, (
        f"MILP objective {res.objective} != re-scored risk {sc.risk}"
    )
    # the optimal schedule must itself be feasible under the scorer's checks
    assert sc.feasible, f"optimal schedule reported infeasible: {sc}"


@pytest.mark.parametrize("seed", range(8))
def test_greedy_no_worse_than_random_is_not_assumed(seed):
    """Every greedy is scored by the same function; optimal <= every greedy risk.

    (Optimality is a mathematical guarantee; this catches scorer/solver drift or
    a greedy that somehow beats the proven optimum — which would signal a bug.)
    """
    inst = generate(GenParams(size=16, T=12, dep_density=0.25,
                              budget_tightness=0.65, deadline_pressure=0.25,
                              cluster_frac=0.15, t_crqc=8, seed=seed))
    res = _solve(inst)
    if res.status != OPTIMAL:
        pytest.skip("not proven optimal within time limit")
    opt_risk = res.objective
    for b in BASELINES:
        sched = greedy_schedule(inst, b, RM, seed=seed)
        sc = score_schedule(inst, sched, RM)
        # A *feasible* greedy can never beat the proven optimum.
        if sc.feasible:
            assert sc.risk >= opt_risk - 0, (
                f"feasible greedy {b} risk {sc.risk} < optimal {opt_risk}"
            )


def test_zero_risk_instance_gap_is_zero():
    """If the optimum is zero risk, a feasible greedy achieving zero gives gap 0."""
    from pqcsched import objective_gap
    assert objective_gap(0, 0) == 0.0
    assert objective_gap(100, 100) == 0.0
    assert objective_gap(100, 150) == pytest.approx(0.5)
