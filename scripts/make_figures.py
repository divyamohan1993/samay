"""Generate the study figures from runs/*_summary.csv and runs/*.csv.

Run after the study (locally; needs matplotlib). Writes artifacts/fig_*.png and
copies the summary tables into artifacts/ so the paper is self-contained.
"""

from __future__ import annotations

import csv
import os
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pqcsched import viz

RUNS = "runs"
ART = "artifacts"
os.makedirs(ART, exist_ok=True)


def _have(name):
    return os.path.exists(os.path.join(RUNS, name))


def main_heatmaps():
    summ = os.path.join(RUNS, "main_summary.csv")
    if not os.path.exists(summ):
        print("skip main heatmaps (no main_summary.csv)")
        return
    for b in ("highest_risk", "risk_per_cost", "edf"):
        try:
            viz.gap_heatmap(summ, x="budget_tightness", y="deadline_pressure",
                            metric=f"{b}_gap_mean", save=f"{ART}/fig_gap_{b}_tight_press.png")
        except Exception as e:  # noqa: BLE001 - figure gen is best-effort
            print(f"heatmap {b} failed: {e}")
    try:
        viz.gap_heatmap(summ, x="dep_density", y="budget_tightness",
                        metric="highest_risk_gap_mean", save=f"{ART}/fig_gap_dens_tight.png")
    except Exception as e:  # noqa: BLE001
        print(f"dens/tight heatmap failed: {e}")


def scalability_plot():
    path = os.path.join(RUNS, "scalability_exact.csv")
    if not os.path.exists(path):
        print("skip scalability plot (no scalability_exact.csv)")
        return
    by_size = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            s = int(r["size"])
            by_size.setdefault(s, {"t": [], "opt": 0, "n": 0})
            by_size[s]["t"].append(float(r["opt_walltime"]))
            by_size[s]["opt"] += 1 if r["opt_status"] == "OPTIMAL" else 0
            by_size[s]["n"] += 1
    sizes = sorted(by_size)
    tmean = [np.mean(by_size[s]["t"]) for s in sizes]
    tmax = [np.max(by_size[s]["t"]) for s in sizes]
    optfrac = [by_size[s]["opt"] / by_size[s]["n"] for s in sizes]

    fig, ax1 = plt.subplots(figsize=(7, 4.5))
    ax1.plot(sizes, tmean, "o-", label="mean solve time", color="#1f77b4")
    ax1.plot(sizes, tmax, "s--", label="max solve time", color="#1f77b4", alpha=0.5)
    ax1.set_xlabel("estate size (assets)")
    ax1.set_ylabel("CP-SAT wall time (s)", color="#1f77b4")
    ax2 = ax1.twinx()
    ax2.plot(sizes, optfrac, "^-", color="#d62728", label="proven-optimal fraction")
    ax2.set_ylabel("fraction proven OPTIMAL", color="#d62728")
    ax2.set_ylim(-0.02, 1.05)
    ax1.set_title("Exact-solver scalability: the cliff")
    fig.tight_layout()
    fig.savefig(f"{ART}/fig_scalability.png", dpi=130)
    print("wrote fig_scalability.png")


def size_gap_plot():
    summ = os.path.join(RUNS, "size_summary.csv")
    if not os.path.exists(summ):
        print("skip size-gap plot (no size_summary.csv)")
        return
    rows = list(csv.DictReader(open(summ, newline="")))
    rows.sort(key=lambda r: int(r["size"]))
    sizes = [int(r["size"]) for r in rows]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for b, col in (("highest_risk", "#1f77b4"), ("edf", "#2ca02c"),
                   ("risk_per_cost", "#ff7f0e"), ("random", "#7f7f7f")):
        ys, los, his = [], [], []
        for r in rows:
            try:
                ys.append(float(r[f"{b}_gap_mean"]) * 100)
                los.append(float(r[f"{b}_gap_lo"]) * 100)
                his.append(float(r[f"{b}_gap_hi"]) * 100)
            except (ValueError, KeyError):
                ys.append(np.nan); los.append(np.nan); his.append(np.nan)
        ax.plot(sizes, ys, "o-", label=b, color=col)
        ax.fill_between(sizes, los, his, color=col, alpha=0.15)
    ax.set_xlabel("estate size (assets)")
    ax.set_ylabel("optimal-vs-greedy gap (%)")
    ax.set_title("How the gap grows with estate scale")
    ax.legend()
    fig.tight_layout()
    fig.savefig(f"{ART}/fig_gap_vs_size.png", dpi=130)
    print("wrote fig_gap_vs_size.png")


def copy_summaries():
    for name in os.listdir(RUNS) if os.path.isdir(RUNS) else []:
        if name.endswith("_summary.csv"):
            shutil.copy(os.path.join(RUNS, name), os.path.join(ART, name))
            print(f"copied {name} -> artifacts/")


if __name__ == "__main__":
    main_heatmaps()
    scalability_plot()
    size_gap_plot()
    copy_summaries()
    print("figures + summaries in artifacts/")
