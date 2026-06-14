"""The single, shared schedule scorer.

This module is the linchpin of the entire optimal-vs-greedy study. The CP-SAT
solver, the MILP fallbacks, the matheuristic, and *every* greedy baseline all
produce a ``Schedule`` (asset_id -> migrated period); they are then compared on
the objective computed *here* and nowhere else. If risk were scored even
slightly differently for the MILP than for greedy, the headline gap would be an
artifact. So there is exactly one function.

Risk semantics (consistent with the CP-SAT objective in
:mod:`pqcsched.solve_cpsat`): residual risk accrues for every period *strictly
before* the migration period. Migrating an asset in period ``tau`` removes its
risk from ``tau`` onward; an asset migrated at period 0 contributes zero risk; an
asset never migrated contributes its risk for all ``T`` periods. Because
migration cannot happen before ``earliest``, periods ``[0, earliest)`` always
contribute — the same in the solver and here.

The objective ``R = sum_i sum_{t < tau_i} r_{i,t}`` is well-defined even when a
greedy leaves a *mandated* asset unmigrated (it simply keeps accruing risk), so
deadline misses are penalized naturally — no arbitrary big-M. The scorer also
reports the constraint-violation breakdown (deadline / budget / precedence /
cluster / earliest) so an infeasible greedy schedule is flagged honestly and
counted separately, never silently mixed into the gap.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Instance, Schedule
from .risk import RiskModel


@dataclass(slots=True)
class ScheduleScore:
    risk: int                 # total time-integrated residual risk (the objective)
    cost: int                 # total migration cost incurred
    feasible: bool            # all hard constraints satisfied
    n_migrated: int
    deadline_violations: int  # mandated assets migrated late or never
    budget_violations: int    # periods whose spend exceeds B_t
    precedence_violations: int
    cluster_violations: int
    earliest_violations: int

    @property
    def n_violations(self) -> int:
        return (
            self.deadline_violations
            + self.budget_violations
            + self.precedence_violations
            + self.cluster_violations
            + self.earliest_violations
        )


def cost_at(asset_cost: int, t: int) -> int:
    """Migration cost of an asset in period ``t``.

    Period-independent by default. A period-dependent "rush premium" model can be
    plugged here; whatever is used MUST match the cost expression in the solvers,
    so both call this one function.
    """
    return asset_cost


def score_schedule(
    inst: Instance,
    schedule: Schedule,
    risk_model: RiskModel,
) -> ScheduleScore:
    """Score a schedule on the canonical objective and check every constraint."""
    by_id = inst.by_id()
    t_crqc = inst.t_crqc

    risk = 0
    cost = 0
    n_migrated = 0
    deadline_v = 0
    earliest_v = 0

    # --- objective + per-asset checks (deadline, earliest) ---
    for a in inst.assets:
        tau = schedule.get(a.id)
        end = tau if tau is not None else inst.T
        # residual risk accrues for periods strictly before migration
        for t in range(0, end):
            risk += risk_model.int_weight(a, t, t_crqc)
        if tau is not None:
            n_migrated += 1
            cost += cost_at(a.cost, tau)
            if tau < a.earliest:
                earliest_v += 1
            if a.deadline is not None and tau > a.deadline:
                deadline_v += 1
        else:
            # unmigrated mandated asset == deadline miss
            if a.deadline is not None:
                deadline_v += 1

    # --- per-period budget ---
    budget_v = 0
    spend = [0] * inst.T
    for a in inst.assets:
        tau = schedule.get(a.id)
        if tau is not None and 0 <= tau < inst.T:
            spend[tau] += cost_at(a.cost, tau)
    for t in range(inst.T):
        if spend[t] > inst.budget[t]:
            budget_v += 1

    # --- precedence: edge (j, i) requires done(i,t) <= done(j,t) for all t,
    #     i.e. if i is migrated then j is migrated no later than i. ---
    precedence_v = 0
    for j, i in inst.deps:
        ti = schedule.get(i)
        if ti is None:
            continue  # i never done -> constraint vacuously satisfied
        tj = schedule.get(j)
        if tj is None or tj > ti:
            precedence_v += 1

    # --- co-migration clusters: both migrated, same period ---
    cluster_v = 0
    for i, j in inst.clusters:
        ti = schedule.get(i)
        tj = schedule.get(j)
        if ti != tj:  # covers (one None, other not) and (different periods)
            cluster_v += 1

    feasible = (
        deadline_v == 0
        and budget_v == 0
        and precedence_v == 0
        and cluster_v == 0
        and earliest_v == 0
    )
    return ScheduleScore(
        risk=risk,
        cost=cost,
        feasible=feasible,
        n_migrated=n_migrated,
        deadline_violations=deadline_v,
        budget_violations=budget_v,
        precedence_violations=precedence_v,
        cluster_violations=cluster_v,
        earliest_violations=earliest_v,
    )


def objective_gap(optimal_risk: int, baseline_risk: int) -> float:
    """Relative objective gap of a baseline vs the optimal (paired, same instance).

    ``(baseline - optimal) / optimal``. Guards the degenerate optimal==0 case
    (a zero-risk estate, e.g. everything migratable at period 0 within budget):
    gap is 0 if the baseline also achieves 0, else reported as infinite-ish via a
    large sentinel that callers can filter.
    """
    if optimal_risk == 0:
        return 0.0 if baseline_risk == 0 else float("inf")
    return (baseline_risk - optimal_risk) / optimal_risk
