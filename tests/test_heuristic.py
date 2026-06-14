"""Tests for the matheuristics (RQ3 scalability).

Two contracts are pinned here, mirroring the two reasons the heuristics exist:

1. **Quality where truth is known.** On small instances that CP-SAT proves
   ``OPTIMAL``, both ``rolling_horizon`` and ``lns`` must return a *feasible*
   schedule (under the shared scorer, the sole arbiter) whose risk is within a
   safe tolerance of the proven optimum. The hard gate is ``1.5x`` optimal —
   deliberately loose so the assertion is robust across machines and seeds — but
   the methods do far better in practice (verified during development: rolling
   horizon matches optimal exactly on every solvable seed; LNS is within ~1.2% of
   optimal worst-case over 20+ seeds at the budget used here, reaching the exact
   optimum on the large majority). We assert the robust gate and additionally pin
   the *typical* behaviour with a tighter aggregate check so a regression in
   solution quality is caught, not just an outright blow-up.

2. **Speed + feasibility at scale.** On a large instance (size 150, T 20) where
   the exact solver does not prove optimality quickly, both methods must finish
   inside their time budget and return a feasible schedule no worse than the
   random-greedy baseline (the trivial status-quo bar).

Determinism: the small-instance LNS is driven by an iteration cap (``iters``), not
wall-clock, so it is reproducible across machines; the large-instance timing tests
assert ``wall_time <= budget + slack`` (never equality — CP-SAT's per-solve limit
is soft and the final sub-solve can overrun slightly).
"""

from __future__ import annotations

import math

import pytest

from pqcsched import (
    RiskModel, generate, GenParams, solve_cpsat, score_schedule,
    greedy_schedule, OPTIMAL, FEASIBLE,
)
# CORE's public __init__ is locked; the heuristics are imported from their module.
from pqcsched.heuristic import rolling_horizon, lns, solve_heuristic

RM = RiskModel()

# Hard quality gate: a heuristic schedule must not exceed this multiple of the
# proven optimum. Loose on purpose (robust); typical performance is near-optimal.
QUALITY_GATE = 1.5

# Small-instance config. These params yield a proven OPTIMAL the large majority of
# the time (non-optimal seeds are skipped, as the parity tests do). The LNS budget
# is an iteration cap for cross-machine reproducibility.
_SMALL = dict(size=16, T=12, dep_density=0.25, budget_tightness=0.65,
              deadline_pressure=0.25, cluster_frac=0.15, t_crqc=8)
_LNS_ITERS = 60
_RH_TLP_SMALL = 5.0
_SMALL_SEEDS = range(12)


def _small_instance(seed: int):
    return generate(GenParams(seed=seed, **_SMALL))


# ---------------------------------------------------------------------------
# 1. Quality vs. proven optimum on small instances.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", _SMALL_SEEDS)
def test_rolling_horizon_matches_optimal_on_small(seed):
    """Rolling horizon returns a feasible schedule within the quality gate."""
    inst = _small_instance(seed)
    opt = solve_cpsat(inst, RM, time_limit=25, workers=8)
    if opt.status != OPTIMAL:
        pytest.skip("instance not proven optimal within the time limit")

    res = rolling_horizon(inst, RM, window=6, step=4,
                          time_limit_per=_RH_TLP_SMALL, workers=8)

    assert res.status == FEASIBLE
    assert res.solver == "heuristic-rolling"
    assert res.schedule is not None
    sc = score_schedule(inst, res.schedule, RM)
    assert sc.feasible, f"rolling-horizon schedule infeasible: {sc}"
    # objective is the canonical re-scored risk.
    assert res.objective == sc.risk
    assert res.objective >= opt.objective  # can never beat the proven optimum
    assert res.objective <= QUALITY_GATE * opt.objective, (
        f"rolling-horizon risk {res.objective} > {QUALITY_GATE}x optimal {opt.objective}"
    )


@pytest.mark.parametrize("seed", _SMALL_SEEDS)
def test_lns_matches_optimal_on_small(seed):
    """LNS returns a feasible schedule within the quality gate (iteration-capped)."""
    inst = _small_instance(seed)
    opt = solve_cpsat(inst, RM, time_limit=25, workers=8)
    if opt.status != OPTIMAL:
        pytest.skip("instance not proven optimal within the time limit")

    res = lns(inst, RM, iters=_LNS_ITERS, neighborhood=0.25, workers=8, seed=seed)

    assert res.status == FEASIBLE
    assert res.solver == "heuristic-lns"
    assert res.schedule is not None
    sc = score_schedule(inst, res.schedule, RM)
    assert sc.feasible, f"LNS schedule infeasible: {sc}"
    assert res.objective == sc.risk
    assert res.objective >= opt.objective
    assert res.objective <= QUALITY_GATE * opt.objective, (
        f"LNS risk {res.objective} > {QUALITY_GATE}x optimal {opt.objective}"
    )


def test_typical_gap_is_near_optimal():
    """Aggregate quality pin: both methods are *near* optimal, not merely <1.5x.

    A single loose per-seed gate would not catch a quality regression that still
    stays under 1.5x. Here we require the mean gap across all solvable small
    instances to be tight (rolling horizon essentially exact; LNS within a few
    percent on average), which is what makes the matheuristics worth reporting.
    """
    rh_gaps: list[float] = []
    ln_gaps: list[float] = []
    for seed in _SMALL_SEEDS:
        inst = _small_instance(seed)
        opt = solve_cpsat(inst, RM, time_limit=25, workers=8)
        if opt.status != OPTIMAL or opt.objective == 0:
            continue
        rh = rolling_horizon(inst, RM, window=6, step=4,
                             time_limit_per=_RH_TLP_SMALL, workers=8)
        ln = lns(inst, RM, iters=_LNS_ITERS, neighborhood=0.25, workers=8, seed=seed)
        assert score_schedule(inst, rh.schedule, RM).feasible
        assert score_schedule(inst, ln.schedule, RM).feasible
        rh_gaps.append((rh.objective - opt.objective) / opt.objective)
        ln_gaps.append((ln.objective - opt.objective) / opt.objective)

    assert rh_gaps, "no optimal instances to compare against"
    mean_rh = sum(rh_gaps) / len(rh_gaps)
    mean_ln = sum(ln_gaps) / len(ln_gaps)
    # Rolling horizon is exact on these instances; allow a hair for safety.
    assert mean_rh <= 0.02, f"rolling-horizon mean gap {mean_rh:.3%} too large"
    # LNS averages well under 5% at this budget (typically near 0).
    assert mean_ln <= 0.05, f"LNS mean gap {mean_ln:.3%} too large"


def test_solve_heuristic_dispatch():
    """The dispatcher routes to each method and rejects unknown names."""
    inst = _small_instance(0)
    opt = solve_cpsat(inst, RM, time_limit=25, workers=8)
    if opt.status != OPTIMAL:
        pytest.skip("instance not proven optimal within the time limit")

    r_roll = solve_heuristic(inst, "rolling", window=6, step=4,
                             time_limit_per=_RH_TLP_SMALL, workers=8)
    r_lns = solve_heuristic(inst, "lns", iters=_LNS_ITERS, workers=8, seed=0)
    assert r_roll.solver == "heuristic-rolling" and r_roll.status == FEASIBLE
    assert r_lns.solver == "heuristic-lns" and r_lns.status == FEASIBLE
    assert score_schedule(inst, r_roll.schedule, RM).feasible
    assert score_schedule(inst, r_lns.schedule, RM).feasible

    with pytest.raises(ValueError):
        solve_heuristic(inst, "no_such_method")


# ---------------------------------------------------------------------------
# 2. Speed + feasibility at scale (size 150, T 20).
# ---------------------------------------------------------------------------
_LARGE = dict(size=150, T=20, dep_density=0.3, budget_tightness=0.6,
              deadline_pressure=0.3, cluster_frac=0.1, t_crqc=13, seed=0)


@pytest.fixture(scope="module")
def large_instance():
    return generate(GenParams(**_LARGE))


@pytest.fixture(scope="module")
def random_greedy_risk(large_instance):
    """Risk of the random-greedy baseline — the bar both heuristics must clear.

    Seed 0 is chosen so this baseline is *feasible*, making the comparison
    meaningful (an infeasible baseline would accrue unbounded deadline risk).
    """
    sched = greedy_schedule(large_instance, "random", RM, seed=0)
    sc = score_schedule(large_instance, sched, RM)
    assert sc.feasible, "random-greedy baseline unexpectedly infeasible on seed 0"
    return sc.risk


def test_rolling_horizon_scales(large_instance, random_greedy_risk):
    """Rolling horizon finishes in budget and beats random-greedy at scale."""
    T, step, tlp = _LARGE["T"], 4, 5.0
    res = rolling_horizon(large_instance, RM, window=6, step=step,
                          time_limit_per=tlp, workers=12)

    assert res.status == FEASIBLE
    sc = score_schedule(large_instance, res.schedule, RM)
    assert sc.feasible, f"large rolling-horizon schedule infeasible: {sc}"
    assert res.objective == sc.risk
    assert res.objective <= random_greedy_risk, (
        f"rolling-horizon risk {res.objective} worse than random-greedy "
        f"{random_greedy_risk}"
    )
    # Total wall is bounded by (#windows + final repair) * per-window cap.
    bound = (math.ceil(T / step) + 1) * tlp
    assert res.wall_time <= bound + 10.0, (
        f"rolling-horizon wall {res.wall_time:.1f}s exceeds bound {bound}s (+slack)"
    )


def test_lns_scales(large_instance, random_greedy_risk):
    """LNS finishes in budget and beats random-greedy at scale."""
    time_limit = 15.0
    res = lns(large_instance, RM, time_limit=time_limit, neighborhood=0.25,
              workers=12, seed=0)

    assert res.status == FEASIBLE
    sc = score_schedule(large_instance, res.schedule, RM)
    assert sc.feasible, f"large LNS schedule infeasible: {sc}"
    assert res.objective == sc.risk
    assert res.objective <= random_greedy_risk, (
        f"LNS risk {res.objective} worse than random-greedy {random_greedy_risk}"
    )
    # CP-SAT's time limit is soft; allow a slice for the last repair to overrun.
    slack = time_limit / 4.0 + 5.0
    assert res.wall_time <= time_limit + slack, (
        f"LNS wall {res.wall_time:.1f}s exceeds budget {time_limit}s (+slack {slack}s)"
    )
