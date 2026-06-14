"""Difficulty-grid feasibility/tightness map at a fixed estate size.

For each (dep_density x budget_tightness x deadline_pressure) cell, report the
fraction of instances CP-SAT proves OPTIMAL, the infeasible fraction, the mean
realized budget tightness, and solve-time stats. This tells us which grid cells
are viable for the headline RQ2 study (proven optima available, infeasibility not
so high that the feasible subset is a biased sliver) and confirms the budget axis
is actually controllable. Run on the target box. Flushed output.
"""

from __future__ import annotations

import sys
from collections import Counter

from pqcsched import generate, GenParams, RiskModel, solve_cpsat

RM = RiskModel()


def main(size, T, workers, time_limit, seeds):
    print(f"size={size} T={T} workers={workers} time_limit={time_limit}s seeds={seeds}", flush=True)
    print(f"{'dens':>5} {'tight':>5} {'press':>5} | {'OPT%':>5} {'INF%':>5} | "
          f"{'rtight':>6} {'tmean':>6} {'tmax':>6}", flush=True)
    for dens in (0.1, 0.4, 0.7):
        for tight in (0.4, 0.6, 0.8, 0.95):
            for press in (0.1, 0.4, 0.8):
                c = Counter(); times = []; rts = []
                for s in range(seeds):
                    inst = generate(GenParams(size=size, T=T, dep_density=dens,
                                              budget_tightness=tight, deadline_pressure=press,
                                              cluster_frac=0.1, t_crqc=13, seed=7000 + s))
                    rts.append(inst.meta["stats"]["realized_tightness"])
                    r = solve_cpsat(inst, RM, time_limit=time_limit, workers=workers)
                    c[r.status] += 1; times.append(r.wall_time)
                n = max(seeds, 1)
                print(f"{dens:>5} {tight:>5} {press:>5} | {100*c['OPTIMAL']/n:>4.0f}% "
                      f"{100*c['INFEASIBLE']/n:>4.0f}% | {sum(rts)/len(rts):>6.3f} "
                      f"{sum(times)/len(times):>6.2f} {max(times):>6.2f}", flush=True)


if __name__ == "__main__":
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    T = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    tl = float(sys.argv[4]) if len(sys.argv) > 4 else 30.0
    seeds = int(sys.argv[5]) if len(sys.argv) > 5 else 12
    main(size, T, workers, tl, seeds)
