"""RQ3: scalability and matheuristic quality/speed vs estate size.

For each size, solve exactly (CP-SAT, time-limited) and with both matheuristics
(rolling-horizon, LNS), plus the best feasible greedy. Records solve time, status,
risk, and — where the exact solve is proven OPTIMAL — the matheuristic's gap to
optimal. At large sizes where exact can no longer prove optimality, the
matheuristic is compared against the exact incumbent and the best greedy. Writes
runs/scalability_heuristic.csv. CPU-only; checkpoint-friendly.
"""

from __future__ import annotations

import csv
import os
import sys

from pqcsched import BASELINES, RiskModel, generate, GenParams, greedy_schedule, score_schedule, solve_cpsat
from pqcsched.heuristic import lns, rolling_horizon

RM = RiskModel()
OUT = "runs/scalability_heuristic.csv"
COLS = ["size", "T", "seed", "opt_status", "opt_risk", "opt_time",
        "rolling_risk", "rolling_time", "rolling_gap",
        "lns_risk", "lns_time", "lns_gap",
        "bestgreedy_risk", "bestgreedy_feasible",
        "rolling_vs_greedy", "lns_vs_greedy"]


def _gap(a, b):
    return round((a - b) / b, 5) if (a is not None and b) else ""


def main(workers=4, exact_limit=45, seeds=5):
    os.makedirs("runs", exist_ok=True)
    sizes = [40, 60, 80, 100, 150, 200]
    done = set()
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT, newline="")):
            done.add((int(r["size"]), int(r["seed"])))
    new = not os.path.exists(OUT)
    fh = open(OUT, "a", newline="")
    w = csv.DictWriter(fh, fieldnames=COLS)
    if new:
        w.writeheader(); fh.flush()

    for sz in sizes:
        T = 20
        for seed in range(seeds):
            if (sz, seed) in done:
                continue
            inst = generate(GenParams(size=sz, T=T, dep_density=0.4, budget_tightness=0.6,
                                      deadline_pressure=0.4, t_crqc=13, seed=5000 + seed))
            opt = solve_cpsat(inst, RM, time_limit=exact_limit, workers=workers)
            rh = rolling_horizon(inst, RM, window=6, step=4, time_limit_per=8, workers=workers)
            ln = lns(inst, RM, time_limit=20, workers=workers, seed=seed)

            # best feasible greedy
            bg_risk, bg_feas = None, False
            for b in BASELINES:
                sc = score_schedule(inst, greedy_schedule(inst, b, RM, seed=seed), RM)
                if sc.feasible and (bg_risk is None or sc.risk < bg_risk):
                    bg_risk, bg_feas = sc.risk, True
                if bg_risk is None or sc.risk < bg_risk:  # fall back to best even if infeasible
                    if not bg_feas:
                        bg_risk = sc.risk if bg_risk is None else min(bg_risk, sc.risk)

            opt_opt = opt.status == "OPTIMAL"
            row = {
                "size": sz, "T": T, "seed": seed,
                "opt_status": opt.status, "opt_risk": opt.objective,
                "opt_time": round(opt.wall_time, 2),
                "rolling_risk": rh.objective, "rolling_time": round(rh.wall_time, 2),
                "rolling_gap": _gap(rh.objective, opt.objective) if opt_opt else "",
                "lns_risk": ln.objective, "lns_time": round(ln.wall_time, 2),
                "lns_gap": _gap(ln.objective, opt.objective) if opt_opt else "",
                "bestgreedy_risk": bg_risk, "bestgreedy_feasible": int(bg_feas),
                "rolling_vs_greedy": _gap(rh.objective, bg_risk),
                "lns_vs_greedy": _gap(ln.objective, bg_risk),
            }
            w.writerow(row); fh.flush()
            print(f"size={sz} seed={seed} opt={opt.status}({opt.objective},{opt.wall_time:.1f}s) "
                  f"rolling={rh.objective}({rh.wall_time:.1f}s) lns={ln.objective}({ln.wall_time:.1f}s) "
                  f"greedy={bg_risk}", flush=True)
    fh.close()
    print("scalability_matheuristic done ->", OUT)


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    main(workers=workers)
