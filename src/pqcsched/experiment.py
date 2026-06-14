"""The empirical study harness: optimal-vs-greedy (RQ2), scalability (RQ3),
sensitivity — checkpointed, resumable, disk-guarded.

Validity rules baked in here (not optional):

* **Paired gaps.** For each instance we solve the exact optimum and every greedy
  and record the per-instance gap ``(greedy - optimal)/optimal``. Aggregation
  bootstraps these paired gaps — never mean(optimal) vs mean(greedy) across
  different instances.
* **OPTIMAL-only headline.** The ``opt_status`` is written on every row. The RQ2
  gap is computed only over instances proven ``OPTIMAL``; ``FEASIBLE`` (time-
  limited) solves are excluded from the gap and belong to the scalability story.
* **Honest infeasibility.** Instances CP-SAT proves ``INFEASIBLE`` are not valid
  scheduling problems; we resample the seed to fill a cell and record how many
  resamples it took (the infeasible rate is itself a reported quantity).
* **Checkpoint + resume.** One compact CSV row per instance, flushed as produced;
  a re-run skips rows already present (keyed by the full cell + index).
* **Disk guard.** Aborts cleanly if free space on the output filesystem drops
  below a floor — protects shared disk (e.g. a co-tenant database).
"""

from __future__ import annotations

import csv
import itertools
import logging
import os
import shutil
import time
from dataclasses import dataclass, field

import numpy as np

from .generate import GenParams, generate
from .greedy import BASELINES, greedy_schedule
from .result import OPTIMAL, FEASIBLE, INFEASIBLE
from .risk import RiskModel
from .score import objective_gap, score_schedule
from .solve_cpsat import solve_cpsat

log = logging.getLogger("pqcsched.experiment")

DISK_FLOOR_BYTES = 1_000_000_000  # 1 GB safety floor on the output filesystem

# Stable column order for the checkpoint CSV.
_CELL_COLS = [
    "study", "size", "T", "dep_density", "budget_tightness", "deadline_pressure",
    "t_crqc", "risk_form", "residual_factor", "cluster_frac", "delayed_frac",
    "index", "instance_seed", "n_resamples_infeasible",
    "realized_tightness", "n_deps", "n_mandated", "n_clusters",
    "opt_status", "opt_risk", "opt_cost", "opt_bound", "opt_mipgap",
    "opt_walltime", "opt_nvars",
]
_BASE_COLS = [
    f"{b}_{m}" for b in BASELINES for m in ("risk", "cost", "feasible", "ddlviol", "gap")
]
COLUMNS = _CELL_COLS + _BASE_COLS


def _disk_ok(path: str) -> tuple[bool, int]:
    free = shutil.disk_usage(path).free
    return free >= DISK_FLOOR_BYTES, free


def _key(row: dict) -> tuple:
    return (
        row["study"], int(row["size"]), int(row["T"]),
        float(row["dep_density"]), float(row["budget_tightness"]),
        float(row["deadline_pressure"]), int(row["t_crqc"]),
        row["risk_form"], float(row["residual_factor"]), int(row["index"]),
    )


def _load_done(path: str) -> set[tuple]:
    done: set[tuple] = set()
    if os.path.exists(path):
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    done.add(_key(row))
                except (KeyError, ValueError):
                    continue
    return done


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------
@dataclass
class Cell:
    """One grid point: generator params + risk model form + how to solve it."""
    study: str
    gen: GenParams
    risk_form: str = "step"
    residual_factor: float = 0.1
    n_instances: int = 30
    time_limit: float = 60.0
    workers: int = 12

    def risk_model(self) -> RiskModel:
        return RiskModel(residual_factor=self.residual_factor, form=self.risk_form)


def expand_grid(
    *,
    study: str,
    sizes,
    Ts,
    dep_densities,
    budget_tightnesses,
    deadline_pressures,
    t_crqcs,
    risk_forms=("step",),
    residual_factors=(0.1,),
    cluster_frac: float = 0.1,
    delayed_frac: float = 0.15,
    n_instances: int = 30,
    time_limit: float = 60.0,
    workers: int = 12,
    base_seed: int = 1000,
) -> list[Cell]:
    """Cartesian product of the axes into a list of cells (one per combination)."""
    cells: list[Cell] = []
    combos = itertools.product(
        sizes, Ts, dep_densities, budget_tightnesses, deadline_pressures,
        t_crqcs, risk_forms, residual_factors,
    )
    for (sz, T, dd, bt, dp, tc, rf, resf) in combos:
        gen = GenParams(
            size=sz, T=T, dep_density=dd, budget_tightness=bt,
            deadline_pressure=dp, cluster_frac=cluster_frac,
            delayed_frac=delayed_frac, t_crqc=tc, seed=base_seed,
        )
        cells.append(Cell(study=study, gen=gen, risk_form=rf,
                          residual_factor=resf, n_instances=n_instances,
                          time_limit=time_limit, workers=workers))
    return cells


# ---------------------------------------------------------------------------
# Per-instance evaluation
# ---------------------------------------------------------------------------
def generate_feasible(cell: Cell, index: int, *, max_resamples: int = 12):
    """Generate a feasible instance for (cell, index), resampling on INFEASIBLE.

    Returns (instance, opt_result, n_resamples). opt_result is the exact solve
    (OPTIMAL or FEASIBLE). Returns (None, last_result, n) if no feasible instance
    was found within max_resamples (rare; logged by the caller).
    """
    rm = cell.risk_model()
    base = cell.gen.seed + index * 7919   # distinct, deterministic per index
    n_resamples = 0
    last = None
    for k in range(max_resamples + 1):
        seed = base + k * 104729
        inst = generate(GenParams(**{**cell.gen.__dict__, "seed": seed}))
        res = solve_cpsat(inst, rm, time_limit=cell.time_limit, workers=cell.workers)
        last = res
        if res.status in (OPTIMAL, FEASIBLE):
            return inst, res, n_resamples
        if res.status == INFEASIBLE:
            n_resamples += 1
            continue
        # UNKNOWN (no solution found in time) — treat as usable-but-not-optimal
        return inst, res, n_resamples
    return None, last, n_resamples


def evaluate(cell: Cell, index: int) -> dict | None:
    """Produce one CSV row for (cell, index): exact optimum + all greedies."""
    rm = cell.risk_model()
    inst, opt, n_resamples = generate_feasible(cell, index)
    if inst is None:
        log.warning("cell %s index %d: no feasible instance found", cell.study, index)
        return None

    g = inst.meta["stats"]
    p = cell.gen
    row: dict = {
        "study": cell.study, "size": p.size, "T": p.T,
        "dep_density": p.dep_density, "budget_tightness": p.budget_tightness,
        "deadline_pressure": p.deadline_pressure, "t_crqc": p.t_crqc,
        "risk_form": cell.risk_form, "residual_factor": cell.residual_factor,
        "cluster_frac": p.cluster_frac, "delayed_frac": p.delayed_frac,
        "index": index, "instance_seed": inst.meta["params"]["seed"],
        "n_resamples_infeasible": n_resamples,
        "realized_tightness": g["realized_tightness"], "n_deps": g["n_deps"],
        "n_mandated": g["n_mandated"], "n_clusters": g["n_clusters"],
        "opt_status": opt.status, "opt_risk": opt.objective,
        "opt_cost": (score_schedule(inst, opt.schedule, rm).cost
                     if opt.schedule is not None else ""),
        "opt_bound": ("" if opt.best_bound is None else round(opt.best_bound, 2)),
        "opt_mipgap": ("" if opt.mip_gap is None else round(opt.mip_gap, 5)),
        "opt_walltime": round(opt.wall_time, 3), "opt_nvars": opt.params.get("num_vars", ""),
    }

    opt_risk = opt.objective if opt.status == OPTIMAL else None
    for b in BASELINES:
        sched = greedy_schedule(inst, b, rm, seed=index)
        sc = score_schedule(inst, sched, rm)
        row[f"{b}_risk"] = sc.risk
        row[f"{b}_cost"] = sc.cost
        row[f"{b}_feasible"] = int(sc.feasible)
        row[f"{b}_ddlviol"] = sc.deadline_violations
        # gap only meaningful vs a proven optimum AND a feasible greedy
        if opt_risk is not None and sc.feasible:
            row[f"{b}_gap"] = round(objective_gap(opt_risk, sc.risk), 6)
        else:
            row[f"{b}_gap"] = ""
    return row


# ---------------------------------------------------------------------------
# Grid runner (checkpointed, resumable, disk-guarded)
# ---------------------------------------------------------------------------
def run_grid(cells: list[Cell], out_csv: str, *, progress_every: int = 20) -> dict:
    """Run all (cell, index) instances, appending rows to out_csv. Resumable."""
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    done = _load_done(out_csv)
    total = sum(c.n_instances for c in cells)
    log.info("run_grid: %d cells, %d instances total, %d already done",
             len(cells), total, len(done))

    new_file = not os.path.exists(out_csv)
    fh = open(out_csv, "a", newline="")
    writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
    if new_file:
        writer.writeheader()
        fh.flush()

    n_run = 0
    n_skip = 0
    t0 = time.perf_counter()
    aborted = False
    try:
        for cell in cells:
            for index in range(cell.n_instances):
                probe = {
                    "study": cell.study, "size": cell.gen.size, "T": cell.gen.T,
                    "dep_density": cell.gen.dep_density,
                    "budget_tightness": cell.gen.budget_tightness,
                    "deadline_pressure": cell.gen.deadline_pressure,
                    "t_crqc": cell.gen.t_crqc, "risk_form": cell.risk_form,
                    "residual_factor": cell.residual_factor, "index": index,
                }
                if _key(probe) in done:
                    n_skip += 1
                    continue
                ok, free = _disk_ok(os.path.dirname(os.path.abspath(out_csv)))
                if not ok:
                    log.error("DISK FLOOR hit (%d bytes free) — aborting cleanly", free)
                    aborted = True
                    break
                row = evaluate(cell, index)
                if row is not None:
                    writer.writerow(row)
                    fh.flush()
                    done.add(_key(row))
                n_run += 1
                if n_run % progress_every == 0:
                    rate = n_run / max(time.perf_counter() - t0, 1e-9)
                    log.info("progress: %d run, %d skip / %d total (%.2f inst/s)",
                             n_run, n_skip, total, rate)
            if aborted:
                break
    finally:
        fh.close()
    return {"run": n_run, "skipped": n_skip, "total": total, "aborted": aborted,
            "elapsed": time.perf_counter() - t0}


# ---------------------------------------------------------------------------
# Analysis (stdlib + numpy only, so it runs on the box too)
# ---------------------------------------------------------------------------
def bootstrap_ci(values, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0):
    """Percentile bootstrap CI of the mean. Returns (mean, lo, hi)."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    if v.size == 1:
        return (float(v[0]), float(v[0]), float(v[0]))
    rng = np.random.default_rng(seed)
    means = rng.choice(v, size=(n_boot, v.size), replace=True).mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (float(v.mean()), float(lo), float(hi))


def summarize(in_csv: str, out_csv: str) -> list[dict]:
    """Aggregate per-cell: bootstrap gap CIs (OPTIMAL only), feasibility & infeasible
    rates, solve-time stats. Writes a compact summary CSV and returns the rows."""
    import collections

    rows = []
    with open(in_csv, newline="") as fh:
        rows = list(csv.DictReader(fh))

    # group by cell (everything except index/seed/per-instance results)
    cell_keys = ["study", "size", "T", "dep_density", "budget_tightness",
                 "deadline_pressure", "t_crqc", "risk_form", "residual_factor"]
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in cell_keys)].append(r)

    out = []
    for key, grp in sorted(groups.items()):
        rec = dict(zip(cell_keys, key))
        n_total = len(grp)
        n_opt = sum(1 for r in grp if r["opt_status"] == OPTIMAL)
        n_feas_only = sum(1 for r in grp if r["opt_status"] == FEASIBLE)
        rec["n_instances"] = n_total
        rec["n_optimal"] = n_opt
        rec["frac_proven_optimal"] = round(n_opt / n_total, 4) if n_total else 0
        rec["frac_feasible_not_proven"] = round(n_feas_only / n_total, 4) if n_total else 0
        resamp = [int(r["n_resamples_infeasible"]) for r in grp]
        rec["mean_infeasible_resamples"] = round(float(np.mean(resamp)), 3) if resamp else 0
        opt_times = [float(r["opt_walltime"]) for r in grp if r["opt_walltime"]]
        rec["opt_walltime_mean"] = round(float(np.mean(opt_times)), 3) if opt_times else ""
        rec["opt_walltime_max"] = round(float(max(opt_times)), 3) if opt_times else ""

        opt_rows = [r for r in grp if r["opt_status"] == OPTIMAL]
        for b in BASELINES:
            gaps = [float(r[f"{b}_gap"]) for r in opt_rows
                    if r.get(f"{b}_gap") not in ("", None)]
            mean, lo, hi = bootstrap_ci(gaps)
            rec[f"{b}_gap_mean"] = round(mean, 5) if gaps else ""
            rec[f"{b}_gap_lo"] = round(lo, 5) if gaps else ""
            rec[f"{b}_gap_hi"] = round(hi, 5) if gaps else ""
            rec[f"{b}_n_gap"] = len(gaps)
            feas = [int(r[f"{b}_feasible"]) for r in grp]
            rec[f"{b}_feasible_rate"] = round(float(np.mean(feas)), 4) if feas else ""
        out.append(rec)

    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
        with open(out_csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
    return out
