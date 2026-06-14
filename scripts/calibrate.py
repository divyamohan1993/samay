"""Calibrate the exact-solvable regime: for a range of estate sizes, how often
does CP-SAT *prove* optimality within a time limit, and how long does it take?

This pins where the headline RQ2 study (which needs proven optima) can live vs.
where we are in scalability/matheuristic territory (RQ3). Run on the target box
so the numbers reflect the real hardware. Prints a flushed table.
"""

from __future__ import annotations

import sys
from collections import Counter

from pqcsched import generate, GenParams, RiskModel, solve_cpsat

RM = RiskModel()


def sweep(sizes, T_of, time_limit, workers, seeds, dep=0.3, tight=0.6, press=0.3):
    print(f"workers={workers} time_limit={time_limit}s  dep={dep} tight={tight} press={press}",
          flush=True)
    print(f"{'size':>5} {'T':>4} | {'OPT%':>5} {'FEAS':>4} {'INF':>4} | "
          f"{'t_mean':>7} {'t_max':>7} {'nvars':>6}", flush=True)
    for sz in sizes:
        T = T_of(sz)
        c = Counter()
        times = []
        nvars = 0
        for s in range(seeds):
            inst = generate(GenParams(size=sz, T=T, dep_density=dep,
                                      budget_tightness=tight, deadline_pressure=press,
                                      cluster_frac=0.12, t_crqc=int(T * 0.7), seed=4000 + s))
            r = solve_cpsat(inst, RM, time_limit=time_limit, workers=workers)
            c[r.status] += 1
            times.append(r.wall_time)
            nvars = r.params.get("num_vars", nvars)
        n = max(seeds, 1)
        optpct = 100 * c["OPTIMAL"] / n
        tmean = sum(times) / len(times)
        print(f"{sz:>5} {T:>4} | {optpct:>4.0f}% {c['FEASIBLE']:>4} {c['INFEASIBLE']:>4} | "
              f"{tmean:>7.2f} {max(times):>7.2f} {nvars:>6}", flush=True)


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    seeds = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    # horizon grows modestly with size (periods ~ quarters to 2035-ish)
    T_of = lambda sz: 16 if sz <= 30 else (20 if sz <= 60 else 24)
    sweep([20, 30, 40, 50, 60, 80, 100, 120], T_of, tl, workers, seeds)
