"""Tests for the Pareto frontier (epsilon-constraint) and the viz figures.

The frontier tests pin its defining properties — non-emptiness on a feasible
instance, cost-ascending order, a *strict* non-dominated skyline (risk falls as
cost rises), and per-point feasibility — all scored through the single shared
scorer so they cannot drift from the rest of the study. The viz tests are smoke
tests: each figure must render to a non-empty PNG, plus one free correctness
check that the residual-risk curve integrates to the scored objective.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # never require a display, even if a viz import changes order

from pqcsched import RiskModel, score_schedule, solve_cpsat, greedy_schedule
from pqcsched.generate import tiny_instance
from pqcsched.pareto import ParetoPoint, pareto_frontier
from pqcsched.result import INFEASIBLE, OPTIMAL
from pqcsched.viz import (
    gap_heatmap,
    pareto_plot,
    risk_over_time,
    roadmap_gantt,
)

RM = RiskModel()


def _feasible_instance():
    """A small instance proven feasible (some tiny_instance seeds are not).

    The experiment harness resamples infeasible seeds by construction; tests pick
    the first seed CP-SAT proves OPTIMAL so the frontier has a real range.
    """
    for seed in range(20):
        inst = tiny_instance(seed=seed)
        if solve_cpsat(inst, RM, time_limit=15, workers=4).status == OPTIMAL:
            return inst
    raise AssertionError("no feasible tiny_instance seed found")


# ---------------------------------------------------------------------------
# Pareto frontier
# ---------------------------------------------------------------------------
def test_frontier_nonempty_sorted_strict_and_feasible():
    inst = _feasible_instance()
    pts = pareto_frontier(inst, n_points=10, time_limit=15, workers=4)

    assert pts, "frontier should be non-empty on a feasible instance"
    assert all(isinstance(p, ParetoPoint) for p in pts)

    costs = [p.cost for p in pts]
    risks = [p.risk for p in pts]

    # sorted by cost ascending
    assert costs == sorted(costs)

    # strictly non-dominated skyline: as cost increases, risk strictly decreases
    for i in range(len(pts) - 1):
        assert costs[i] < costs[i + 1], "costs must be strictly increasing on the skyline"
        assert risks[i] > risks[i + 1], "risk must strictly decrease as cost increases"

    # every point feasible, and (cost, risk) consistent with the shared scorer
    for p in pts:
        sc = score_schedule(inst, p.schedule, RM)
        assert sc.feasible, f"frontier point cost={p.cost} is infeasible"
        assert sc.cost == p.cost
        assert sc.risk == p.risk


def test_frontier_top_point_matches_unconstrained_optimum():
    # The highest-cost frontier point is the unconstrained min-risk solution, so
    # its risk equals the plain CP-SAT optimum.
    inst = _feasible_instance()
    pts = pareto_frontier(inst, n_points=8, time_limit=15, workers=4)
    opt = solve_cpsat(inst, RM, time_limit=15, workers=4)
    assert opt.status == OPTIMAL
    assert pts[-1].risk == opt.objective


def test_frontier_points_have_distinct_nondominated_costs():
    inst = _feasible_instance()
    pts = pareto_frontier(inst, n_points=12, time_limit=15, workers=4)
    costs = [p.cost for p in pts]
    assert len(costs) == len(set(costs)), "skyline must not contain duplicate costs"


def test_cheapest_frontier_point_is_truly_minimal():
    # The low-cost extreme C_lo is the novel piece: it must be the *minimum*
    # feasible cost, not merely a feasible one. Pin it directly — capping cost one
    # unit below the cheapest frontier point must render the instance INFEASIBLE.
    inst = _feasible_instance()
    pts = pareto_frontier(inst, n_points=8, time_limit=15, workers=4)
    c_lo = pts[0].cost
    res = solve_cpsat(inst, RM, eps_cost=c_lo - 1, time_limit=15, workers=4)
    assert res.status == INFEASIBLE, (
        f"cost cap {c_lo - 1} should be infeasible if {c_lo} is the true minimum"
    )


# ---------------------------------------------------------------------------
# Visualizations (smoke: render to a non-empty PNG)
# ---------------------------------------------------------------------------
def _png_ok(path) -> None:
    assert path.exists(), f"figure not written: {path}"
    assert path.stat().st_size > 0, f"figure is empty: {path}"


def test_roadmap_gantt_renders(tmp_path):
    inst = _feasible_instance()
    sched = solve_cpsat(inst, RM, time_limit=15, workers=4).schedule
    out = tmp_path / "gantt.png"
    fig = roadmap_gantt(inst, sched, save=str(out))
    assert fig is not None
    _png_ok(out)


def test_risk_over_time_renders_and_integrates_to_scored_risk(tmp_path):
    from pqcsched.viz import _residual_risk_curve

    inst = _feasible_instance()
    opt = solve_cpsat(inst, RM, time_limit=15, workers=4).schedule
    greedy = greedy_schedule(inst, "highest_risk", RM, seed=0)

    # free correctness check: area under each curve == that schedule's scored risk
    for sched in (opt, greedy):
        curve = _residual_risk_curve(inst, sched, RM)
        assert sum(curve) == score_schedule(inst, sched, RM).risk

    out = tmp_path / "risk_over_time.png"
    fig = risk_over_time(inst, {"optimal": opt, "highest_risk": greedy}, RM,
                         save=str(out))
    assert fig is not None
    _png_ok(out)


def test_pareto_plot_renders(tmp_path):
    inst = _feasible_instance()
    pts = pareto_frontier(inst, n_points=8, time_limit=15, workers=4)
    out = tmp_path / "pareto.png"
    fig = pareto_plot(pts, save=str(out))
    assert fig is not None
    _png_ok(out)


def test_pareto_plot_handles_empty_list(tmp_path):
    # An infeasible instance yields no frontier; the plotter must still render.
    out = tmp_path / "pareto_empty.png"
    fig = pareto_plot([], save=str(out))
    assert fig is not None
    _png_ok(out)


def test_gap_heatmap_renders_from_synthetic_summary(tmp_path):
    # A tiny synthetic summary CSV in the shape experiment.summarize emits:
    # two grid axes (budget_tightness × deadline_pressure), an extra axis
    # (dep_density) to aggregate over, and a <baseline>_gap_mean metric column
    # (including one empty cell, which must be treated as missing, not zero).
    summary = tmp_path / "summary.csv"
    summary.write_text(
        "study,size,T,dep_density,budget_tightness,deadline_pressure,t_crqc,"
        "risk_form,residual_factor,highest_risk_gap_mean\n"
        "s,50,20,0.2,0.4,0.2,13,step,0.1,0.05\n"
        "s,50,20,0.5,0.4,0.2,13,step,0.1,0.07\n"   # same (bt,dp) -> averaged with row 1
        "s,50,20,0.2,0.8,0.2,13,step,0.1,0.31\n"
        "s,50,20,0.2,0.4,0.6,13,step,0.1,0.12\n"
        "s,50,20,0.2,0.8,0.6,13,step,0.1,\n"        # empty metric -> missing cell
        ,
        encoding="utf-8",
    )
    out = tmp_path / "heatmap.png"
    fig = gap_heatmap(str(summary), x="budget_tightness", y="deadline_pressure",
                      metric="highest_risk_gap_mean", save=str(out))
    assert fig is not None
    _png_ok(out)

    # the (0.4, 0.2) cell must be the mean of the two rows sharing it (0.06), and
    # the (0.8, 0.6) cell must be NaN (the empty metric), not 0.0.
    import numpy as np
    ax = fig.axes[0]
    img = ax.images[0].get_array()  # masked array: NaN cells are masked, not raw nan
    xs = [0.4, 0.8]
    ys = [0.2, 0.6]
    assert abs(img[ys.index(0.2), xs.index(0.4)] - 0.06) < 1e-9
    assert np.ma.is_masked(img[ys.index(0.6), xs.index(0.8)])
