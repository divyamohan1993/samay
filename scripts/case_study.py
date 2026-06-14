"""India-DPI case study: optimal roadmap, greedy comparison, Pareto frontier,
CRQC-timing sensitivity, and figures. Writes artifacts/case_study.json (numbers
for REPORT §12) and artifacts/case_*.png. Run locally (matplotlib)."""

from __future__ import annotations

import json
import os

from pqcsched import BASELINES, RiskModel, greedy_schedule, score_schedule, solve_cpsat
from pqcsched.pareto import pareto_frontier
from pqcsched.scenarios import india_dpi_instance
from pqcsched import viz

ART = "artifacts"
os.makedirs(ART, exist_ok=True)
WORKERS = int(os.environ.get("PQCSCHED_WORKERS", "6"))


def main():
    rm = RiskModel()
    inst = india_dpi_instance()
    opt = solve_cpsat(inst, rm, time_limit=60, workers=WORKERS)
    assert opt.schedule is not None, f"case-study instance did not solve: {opt.status}"
    opt_sc = score_schedule(inst, opt.schedule, rm)

    baselines = {}
    schedules = {"optimal": opt.schedule}
    for b in BASELINES:
        sched = greedy_schedule(inst, b, rm, seed=0)
        sc = score_schedule(inst, sched, rm)
        gap = ((sc.risk - opt.objective) / opt.objective) if opt.is_optimal and opt.objective else None
        baselines[b] = {"risk": sc.risk, "cost": sc.cost, "feasible": sc.feasible,
                        "deadline_violations": sc.deadline_violations,
                        "gap": (round(gap, 4) if gap is not None else None)}
        schedules[b] = sched

    frontier = pareto_frontier(inst, rm, n_points=12, time_limit=30, workers=WORKERS)

    # CRQC-timing sensitivity (quarter-index: ~2032 / 2034 / 2036)
    sens = {}
    for tq in (22, 30, 38):
        i2 = india_dpi_instance(t_crqc=tq)
        r2 = solve_cpsat(i2, rm, time_limit=60, workers=WORKERS)
        sens[str(tq)] = {"status": r2.status, "opt_risk": r2.objective}

    # figures
    viz.roadmap_gantt(inst, opt.schedule, save=f"{ART}/case_roadmap_optimal.png")
    viz.risk_over_time(inst, {"optimal": opt.schedule,
                              "highest_risk": schedules["highest_risk"]}, rm,
                       save=f"{ART}/case_risk_over_time.png")
    if frontier:
        viz.pareto_plot(frontier, save=f"{ART}/case_pareto.png")

    results = {
        "instance": inst.meta["stats"],
        "horizon": inst.meta.get("horizon", ""),
        "optimal": {"status": opt.status, "risk": opt.objective, "cost": opt_sc.cost,
                    "walltime_s": round(opt.wall_time, 2)},
        "baselines": baselines,
        "n_greedies_infeasible": sum(1 for d in baselines.values() if not d["feasible"]),
        "pareto_points": [{"cost": p.cost, "risk": p.risk} for p in frontier],
        "sensitivity_tcrqc": sens,
    }
    with open(f"{ART}/case_study.json", "w") as fh:
        json.dump(results, fh, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
