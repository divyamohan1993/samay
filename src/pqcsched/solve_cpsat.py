"""Exact solver: Google OR-Tools CP-SAT (primary, free, CPU-native).

Time-indexed formulation from ``PROJECT_BRIEF.md`` §3 / §10.3. The objective is
built from the *same* :meth:`RiskModel.int_weight` the scorer uses, and is the
residual-risk expression ``sum_i sum_t w_{i,t} (1 - done_{i,t})`` so that
``solver.ObjectiveValue()`` equals ``score_schedule(...).risk`` exactly (verified
by ``tests/test_parity.py``).

Variables ``y[i,t]`` are created only for feasible periods ``t in [earliest_i,
hi_i]`` where ``hi_i = min(deadline_i, T-1)`` for mandated assets, ``T-1``
otherwise. The status (OPTIMAL / FEASIBLE / INFEASIBLE / UNKNOWN) and proven
bound are always recorded.
"""

from __future__ import annotations

import logging
import time

from ortools.sat.python import cp_model

from .model import Instance
from .result import (
    SolveResult,
    OPTIMAL,
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
    MODEL_INVALID,
)
from .risk import RiskModel

log = logging.getLogger("pqcsched.cpsat")

_STATUS = {
    cp_model.OPTIMAL: OPTIMAL,
    cp_model.FEASIBLE: FEASIBLE,
    cp_model.INFEASIBLE: INFEASIBLE,
    cp_model.UNKNOWN: UNKNOWN,
    cp_model.MODEL_INVALID: MODEL_INVALID,
}


def _periods(inst: Instance, a) -> range:
    """Feasible migration periods for asset `a`: [earliest, hi]."""
    hi = inst.T - 1
    if a.deadline is not None:
        hi = min(hi, a.deadline)
    return range(a.earliest, hi + 1)


def solve_cpsat(
    inst: Instance,
    risk_model: RiskModel | None = None,
    *,
    eps_cost: int | None = None,
    time_limit: float = 60.0,
    workers: int = 12,
    log_search: bool = False,
) -> SolveResult:
    """Solve `inst` exactly with CP-SAT, minimizing time-integrated residual risk.

    Parameters
    ----------
    eps_cost:    if given, add the epsilon-constraint ``total_cost <= eps_cost``
                 (used to trace the risk-vs-cost Pareto frontier).
    time_limit:  wall-clock seconds (per solve).
    workers:     CP-SAT search workers (set to the box's 12 vCPUs).
    """
    rm = risk_model or RiskModel()
    m = cp_model.CpModel()
    by_id = inst.by_id()

    # y[(id, t)] = 1 iff asset id migrated in period t (created only for feasible t)
    y: dict[tuple[str, int], cp_model.IntVar] = {}
    for a in inst.assets:
        for t in _periods(inst, a):
            y[(a.id, t)] = m.NewBoolVar(f"y_{a.id}_{t}")

    def done(i: str, t: int):
        """Linear expression: asset i migrated by end of period t."""
        a = by_id[i]
        terms = [y[(i, tau)] for tau in _periods(inst, a) if tau <= t]
        return sum(terms) if terms else 0

    # (1) migrate at most once; mandated assets exactly once within deadline.
    for a in inst.assets:
        ys = [y[(a.id, t)] for t in _periods(inst, a)]
        if not ys:
            # No feasible period (e.g. earliest > deadline) -> instance infeasible.
            return SolveResult(status=INFEASIBLE, solver="cp-sat",
                               params={"reason": f"asset {a.id} has no feasible period"})
        if a.deadline is not None:
            m.Add(sum(ys) == 1)        # window already capped at deadline
        else:
            m.Add(sum(ys) <= 1)

    # (3) per-period budget / throughput.
    for t in range(inst.T):
        terms = [by_id[i].cost * y[(i, t)] for (i, tt) in y if tt == t]
        if terms:
            m.Add(sum(terms) <= inst.budget[t])

    # (4) precedence: edge (j, i) => done(i,t) <= done(j,t) for all t.
    for (j, i) in inst.deps:
        for t in range(inst.T):
            m.Add(done(i, t) <= done(j, t))

    # (5) co-migration clusters: same period.
    for (i, j) in inst.clusters:
        ai, aj = by_id[i], by_id[j]
        pi, pj = set(_periods(inst, ai)), set(_periods(inst, aj))
        # equal where both exist; force-zero where only one can migrate (so they
        # cannot be split across periods).
        for t in pi | pj:
            if t in pi and t in pj:
                m.Add(y[(i, t)] == y[(j, t)])
            elif t in pi:
                m.Add(y[(i, t)] == 0)
            else:
                m.Add(y[(j, t)] == 0)

    # (optional) epsilon-constraint on cost for Pareto tracing.
    if eps_cost is not None:
        cost_terms = [by_id[i].cost * y[(i, t)] for (i, t) in y]
        m.Add(sum(cost_terms) <= eps_cost)

    # Objective: minimize residual risk = sum_i sum_t w_{i,t} (1 - done(i,t)).
    # The "1" is constant per (i,t); keeping it makes ObjectiveValue == scorer.risk.
    risk_terms = []
    for a in inst.assets:
        for t in range(inst.T):
            w = rm.int_weight(a, t, inst.t_crqc)
            if w:
                risk_terms.append(w * (1 - done(a.id, t)))
    m.Minimize(sum(risk_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = bool(log_search)

    t0 = time.perf_counter()
    st = solver.Solve(m)
    wall = time.perf_counter() - t0
    status = _STATUS.get(st, UNKNOWN)

    schedule = None
    objective = None
    bound = None
    if status in (OPTIMAL, FEASIBLE):
        schedule = {}
        for a in inst.assets:
            for t in _periods(inst, a):
                if solver.Value(y[(a.id, t)]) == 1:
                    schedule[a.id] = t
                    break
        objective = int(round(solver.ObjectiveValue()))
        bound = float(solver.BestObjectiveBound())

    return SolveResult(
        status=status,
        solver="cp-sat",
        objective=objective,
        best_bound=bound,
        schedule=schedule,
        wall_time=wall,
        eps_cost=eps_cost,
        params={"workers": workers, "time_limit": time_limit,
                "num_vars": len(y), "num_assets": len(inst.assets), "T": inst.T},
    )
