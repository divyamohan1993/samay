"""Cross-solver agreement — the MILP backends must reproduce the CP-SAT optimum.

The study's central claim is that the *same* model, solved by independent exact
engines, yields the *same* optimum. These tests assert exactly that for every free
MILP backend probed available on this machine (CBC always; HiGHS when present):

  * on instances CP-SAT *proves* OPTIMAL, each backend returns OPTIMAL with an
    objective equal to CP-SAT's, and
  * that objective re-scores bit-for-bit through the single shared scorer
    (``score_schedule(...).risk == result.objective``) — the parity that makes the
    optimal-vs-greedy gap an honest number rather than an artifact of two solvers
    counting risk differently.

We assert *objective* agreement, never *schedule* agreement: the optimum value is
unique but the argmin is not (alternate optimal schedules are expected and fine).

A backend that is not installed is skipped cleanly, and the agreement test asserts
that a minimum number of instances were actually exercised so it cannot pass
vacuously by skipping everything.
"""

from __future__ import annotations

import pytest

from pqcsched import (
    RiskModel, score_schedule, solve_cpsat, generate, GenParams, OPTIMAL,
)
from pqcsched.result import INFEASIBLE
from pqcsched import solve_milp as milp_mod
from pqcsched.solve_milp import solve_milp, solve, AVAILABLE_BACKENDS


RM = RiskModel()

# Free backends the study cares about. We only *require* CBC (ships with PuLP);
# HiGHS is asserted-on when available and skipped otherwise. Gurobi is optional
# and excluded from the required set on purpose.
FREE_BACKENDS = [b for b in ("cbc", "highs") if b in AVAILABLE_BACKENDS]

# Looser budget/deadline params than the headline regime so most seeds are
# feasible-and-provably-optimal quickly, giving the agreement test real instances.
_GEN = dict(size=14, T=10, dep_density=0.25, budget_tightness=0.55,
            deadline_pressure=0.2, cluster_frac=0.15, t_crqc=7)


def _instance(seed: int):
    return generate(GenParams(seed=seed, **_GEN))


def _cpsat_optimal(inst):
    """Return CP-SAT's SolveResult, or None if it did not prove optimality."""
    res = solve_cpsat(inst, RM, time_limit=20, workers=4)
    return res if res.status == OPTIMAL else None


def test_cbc_is_available():
    """CBC ships with PuLP; if it is missing the whole cross-check is impossible."""
    assert "cbc" in AVAILABLE_BACKENDS, (
        f"CBC must always be available; probed backends: {AVAILABLE_BACKENDS}"
    )


@pytest.mark.parametrize("backend", FREE_BACKENDS)
def test_backend_agrees_with_cpsat_and_scorer(backend):
    """Each free backend reproduces CP-SAT's optimum and re-scores to parity.

    For every seed where CP-SAT proves OPTIMAL: the backend must also report
    OPTIMAL, its objective must equal CP-SAT's, and that objective must equal the
    risk the shared scorer assigns to the backend's own schedule.
    """
    n_tested = 0
    for seed in range(24):
        inst = _instance(seed)
        ref = _cpsat_optimal(inst)
        if ref is None:
            continue  # not proven optimal in time / infeasible — skip (harness logs)

        res = solve_milp(inst, RM, backend=backend, time_limit=30, threads=4)

        assert res.status == OPTIMAL, (
            f"[{backend}] seed={seed}: expected OPTIMAL (CP-SAT proved it), "
            f"got {res.status}"
        )
        assert res.schedule is not None
        # Same proven optimum value as CP-SAT (schedules may legitimately differ).
        assert res.objective == ref.objective, (
            f"[{backend}] seed={seed}: objective {res.objective} "
            f"!= CP-SAT {ref.objective}"
        )
        # The linchpin: the returned schedule re-scores to exactly that objective.
        sc = score_schedule(inst, res.schedule, RM)
        assert sc.risk == res.objective, (
            f"[{backend}] seed={seed}: re-scored risk {sc.risk} "
            f"!= reported objective {res.objective}"
        )
        # A proven-optimal schedule must be feasible under the scorer's checks.
        assert sc.feasible, (
            f"[{backend}] seed={seed}: optimal schedule reported infeasible: {sc}"
        )
        # Proven-optimal => bound equals objective (honest, conservative).
        assert res.best_bound == float(res.objective)

        n_tested += 1
        if n_tested >= 5:
            break

    # Guard against a vacuous pass: at least a few real instances must have run.
    assert n_tested >= 3, (
        f"[{backend}] only {n_tested} proven-optimal instances tested; "
        "agreement was not meaningfully exercised"
    )


@pytest.mark.parametrize("backend", FREE_BACKENDS)
def test_eps_cost_constrains_cost(backend):
    """The epsilon-constraint must cap total migration cost and not lower risk.

    Solve unconstrained to get cost C and risk R0; re-solve with a strictly
    tighter cost cap. The cost-capped solve must (a) respect the cap and (b) have
    risk >= R0 (a tighter feasible region cannot reduce a minimization objective).
    """
    chosen = None
    for seed in range(24):
        inst = _instance(seed)
        base = solve_milp(inst, RM, backend=backend, time_limit=30, threads=4)
        if base.status != OPTIMAL or base.schedule is None:
            continue
        base_cost = score_schedule(inst, base.schedule, RM).cost
        if base_cost <= 0:
            continue  # need a positive cost to tighten below
        chosen = (inst, base, base_cost)
        break

    if chosen is None:
        pytest.skip(f"[{backend}] no positive-cost optimal instance found to cap")

    inst, base, base_cost = chosen
    cap = base_cost - 1  # strictly tighter than the unconstrained optimum's cost
    capped = solve_milp(inst, RM, backend=backend, eps_cost=cap,
                        time_limit=30, threads=4)

    assert capped.eps_cost == cap
    if capped.status == OPTIMAL:
        assert capped.schedule is not None
        sc = score_schedule(inst, capped.schedule, RM)
        # (a) the cap is respected, and the scorer agrees on cost,
        assert sc.cost <= cap, (
            f"[{backend}] capped cost {sc.cost} exceeds eps_cost {cap}"
        )
        # (b) constraining cost cannot *decrease* the minimized risk objective.
        assert capped.objective >= base.objective, (
            f"[{backend}] cost-capped risk {capped.objective} "
            f"< unconstrained {base.objective}"
        )
        # parity still holds under the eps-constraint.
        assert sc.risk == capped.objective
    else:
        # Tightening may make it infeasible; that is a valid, honest outcome.
        assert capped.status in (INFEASIBLE,), (
            f"[{backend}] unexpected status under tighter cost cap: {capped.status}"
        )


@pytest.mark.parametrize("backend", FREE_BACKENDS)
def test_structural_infeasibility_detected(backend):
    """A backend must report INFEASIBLE on an instance CP-SAT proves infeasible.

    seed=1 / size=12 in the tiny regime has a per-period bottleneck that CP-SAT
    proves infeasible; the MILP backends, solving the identical model, must agree.
    """
    inst = generate(GenParams(size=12, T=10, dep_density=0.3,
                              budget_tightness=0.7, deadline_pressure=0.3,
                              cluster_frac=0.2, t_crqc=7, seed=1))
    ref = solve_cpsat(inst, RM, time_limit=20, workers=4)
    if ref.status != INFEASIBLE:
        pytest.skip("reference instance is not infeasible in this environment")

    res = solve_milp(inst, RM, backend=backend, time_limit=20, threads=4)
    assert res.status == INFEASIBLE, (
        f"[{backend}] expected INFEASIBLE (CP-SAT proved it), got {res.status}"
    )
    assert res.schedule is None


def test_available_backends_probed_and_dispatcher_matches():
    """AVAILABLE_BACKENDS is a non-empty probe; `solve` dispatches like solve_milp."""
    assert isinstance(AVAILABLE_BACKENDS, tuple)
    assert "cbc" in AVAILABLE_BACKENDS
    # Gurobi must never be a hard requirement of the free cross-check.
    assert set(FREE_BACKENDS) <= set(AVAILABLE_BACKENDS)

    inst = _instance(0)
    ref = _cpsat_optimal(inst)
    if ref is None:
        pytest.skip("seed 0 not proven optimal in this environment")
    via_solve = solve(inst, RM, backend="cbc", time_limit=30, threads=4)
    via_milp = solve_milp(inst, RM, backend="cbc", time_limit=30, threads=4)
    assert via_solve.objective == via_milp.objective == ref.objective


def test_unknown_backend_raises():
    """Asking for a backend that was not probed available fails fast and clearly."""
    inst = _instance(0)
    with pytest.raises(ValueError):
        solve_milp(inst, RM, backend="not_a_real_solver")
