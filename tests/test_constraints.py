"""Constraint-correctness tests for the exact model.

Each test builds a hand-crafted instance where the correct schedule is obvious,
and asserts CP-SAT respects precedence, per-period budget, deadlines, earliest
feasibility, and co-migration clusters. These pin the formulation.
"""

from __future__ import annotations

from pqcsched import Asset, Instance, RiskModel, solve_cpsat, score_schedule
from pqcsched.result import OPTIMAL, INFEASIBLE

RM = RiskModel()


def _solve(inst):
    return solve_cpsat(inst, RM, time_limit=15, workers=4)


def test_precedence_respected():
    # b depends on a: edge (a, b) => a must complete no later than b.
    a = Asset(id="a", criticality=10, shelf_life=20, cost=1, earliest=0)
    b = Asset(id="b", criticality=50, shelf_life=20, cost=1, earliest=0)
    inst = Instance(assets=[a, b], T=5, budget=[1] * 5,
                    deps=[("a", "b")], t_crqc=10)
    res = _solve(inst)
    assert res.status == OPTIMAL
    sched = res.schedule
    assert sched["a"] <= sched["b"]
    assert score_schedule(inst, sched, RM).precedence_violations == 0


def test_budget_caps_per_period():
    # Two unit-cost assets, budget 1/period: cannot both migrate in period 0.
    a = Asset(id="a", criticality=10, shelf_life=20, cost=1, earliest=0)
    b = Asset(id="b", criticality=10, shelf_life=20, cost=1, earliest=0)
    inst = Instance(assets=[a, b], T=4, budget=[1, 1, 1, 1], t_crqc=10)
    res = _solve(inst)
    assert res.status == OPTIMAL
    sched = res.schedule
    assert sched["a"] != sched["b"]  # forced into different periods
    assert score_schedule(inst, sched, RM).budget_violations == 0


def test_deadline_enforced():
    # Mandated asset with deadline 1 must be migrated by period 1.
    a = Asset(id="a", criticality=80, shelf_life=20, cost=1, earliest=0, deadline=1)
    inst = Instance(assets=[a], T=6, budget=[1] * 6, t_crqc=10)
    res = _solve(inst)
    assert res.status == OPTIMAL
    assert res.schedule["a"] <= 1
    assert score_schedule(inst, res.schedule, RM).deadline_violations == 0


def test_earliest_respected():
    a = Asset(id="a", criticality=80, shelf_life=20, cost=1, earliest=3)
    inst = Instance(assets=[a], T=6, budget=[1] * 6, t_crqc=10)
    res = _solve(inst)
    assert res.status == OPTIMAL
    assert res.schedule["a"] >= 3


def test_cluster_co_migration():
    a = Asset(id="a", criticality=10, shelf_life=20, cost=1, earliest=0)
    b = Asset(id="b", criticality=10, shelf_life=20, cost=1, earliest=0)
    inst = Instance(assets=[a, b], T=4, budget=[2, 2, 2, 2],
                    clusters=[("a", "b")], t_crqc=10)
    res = _solve(inst)
    assert res.status == OPTIMAL
    assert res.schedule["a"] == res.schedule["b"]
    assert score_schedule(inst, res.schedule, RM).cluster_violations == 0


def test_infeasible_when_earliest_after_deadline():
    a = Asset(id="a", criticality=80, shelf_life=20, cost=1, earliest=4, deadline=2)
    inst = Instance(assets=[a], T=6, budget=[1] * 6, t_crqc=10)
    res = _solve(inst)
    assert res.status == INFEASIBLE


def test_hndl_drives_optimal_order():
    # Same cost/criticality, but `a` has long shelf-life (HNDL at risk) and `b`
    # short shelf-life (safe). Budget forces a choice in period 0: migrate `a`.
    a = Asset(id="a", criticality=50, shelf_life=20, cost=1, earliest=0)  # at risk
    b = Asset(id="b", criticality=50, shelf_life=1, cost=1, earliest=0)   # residual
    inst = Instance(assets=[a, b], T=4, budget=[1, 1, 1, 1], t_crqc=5)
    res = _solve(inst)
    assert res.status == OPTIMAL
    # `a` (HNDL-exposed) should be migrated no later than `b`
    assert res.schedule["a"] <= res.schedule["b"]
