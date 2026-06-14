"""Re-analyze the study against the HNDL-AWARE greedy (a stronger baseline) WITHOUT
re-solving: regenerate each proven-OPTIMAL instance from its stored seed/params and
score the current-risk greedy, computing its gap vs the stored optimum.

This isolates the value that REMAINS after a sophisticated practitioner accounts
for migration timing — the honesty check on the headline.
"""

from __future__ import annotations

import csv
import sys
import collections

import numpy as np

from pqcsched import generate, GenParams, RiskModel, greedy_current_risk, score_schedule


def regen(r):
    return generate(GenParams(
        size=int(r["size"]), T=int(r["T"]), dep_density=float(r["dep_density"]),
        budget_tightness=float(r["budget_tightness"]),
        deadline_pressure=float(r["deadline_pressure"]),
        cluster_frac=float(r["cluster_frac"]), delayed_frac=float(r["delayed_frac"]),
        t_crqc=int(r["t_crqc"]), seed=int(r["instance_seed"])))


def main(in_csv="runs/main.csv"):
    rm_default = RiskModel()
    rows = [r for r in csv.DictReader(open(in_csv, newline="")) if r["opt_status"] == "OPTIMAL"]
    print(f"{in_csv}: {len(rows)} OPTIMAL instances")
    gaps = []
    feas = []
    by_tight = collections.defaultdict(list)
    out_rows = []
    for r in rows:
        rm = RiskModel(residual_factor=float(r["residual_factor"]), form=r["risk_form"])
        inst = regen(r)
        sched = greedy_current_risk(inst, rm)
        sc = score_schedule(inst, sched, rm)
        opt = int(r["opt_risk"])
        if opt > 0 and sc.feasible:
            g = (sc.risk - opt) / opt
            gaps.append(g)
            by_tight[r["budget_tightness"]].append(g)
        feas.append(int(sc.feasible))
        out_rows.append({**{k: r[k] for k in ("size", "dep_density", "budget_tightness",
                                              "deadline_pressure", "instance_seed", "opt_risk")},
                         "current_risk_risk": sc.risk, "current_risk_feasible": int(sc.feasible),
                         "current_risk_gap": (round((sc.risk - opt) / opt, 6) if opt > 0 and sc.feasible else "")})
    print(f"current-risk (HNDL-aware) greedy: median gap = {100*np.median(gaps):.1f}%  "
          f"mean = {100*np.mean(gaps):.1f}%  feasible_rate = {100*np.mean(feas):.0f}%  (n={len(gaps)})")
    print("by budget_tightness:")
    for k in sorted(by_tight, key=float):
        print(f"  tight={k}: median gap = {100*np.median(by_tight[k]):.1f}%  (n={len(by_tight[k])})")
    with open("runs/main_strong_baseline.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader(); w.writerows(out_rows)
    print("wrote runs/main_strong_baseline.csv")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "runs/main.csv")
