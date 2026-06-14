"""Direct driver for the SAMAY study (does not depend on the CLI).

Reads configs/experiment.yaml, and for each study runs
experiment.expand_grid(**study) -> run_grid (checkpointed, resumable, disk-
guarded) -> summarize. Use --quick for a fast end-to-end smoke test, --only to
run a subset of studies, --workers to override the neighbour-policy worker cap.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import yaml

from pqcsched.experiment import Cell, expand_grid, run_grid, summarize
from pqcsched.generate import GenParams

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("run_main_study")


def studies_from_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh)["studies"]


def quick_studies():
    return [{
        "study": "smoke", "sizes": [14], "Ts": [10], "dep_densities": [0.3],
        "budget_tightnesses": [0.6], "deadline_pressures": [0.3], "t_crqcs": [7],
        "risk_forms": ["step"], "residual_factors": [0.1], "cluster_frac": 0.15,
        "delayed_frac": 0.1, "n_instances": 3, "time_limit": 10, "workers": 4,
        "base_seed": 999,
    }]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="configs/experiment.yaml")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--only", nargs="*", default=None, help="study names to run")
    ap.add_argument("--workers", type=int, default=None, help="override worker cap")
    ap.add_argument("--quick", action="store_true", help="tiny smoke study")
    args = ap.parse_args(argv)

    studies = quick_studies() if args.quick else studies_from_yaml(args.grid)
    if args.only:
        studies = [s for s in studies if s["study"] in set(args.only)]
    os.makedirs(args.out, exist_ok=True)

    for s in studies:
        if args.workers is not None:
            s = {**s, "workers": args.workers}
        name = s["study"]
        log.info("=== study %s ===", name)
        cells = expand_grid(**s)
        out_csv = os.path.join(args.out, f"{name}.csv")
        stats = run_grid(cells, out_csv)
        log.info("study %s: %s", name, stats)
        summ = summarize(out_csv, os.path.join(args.out, f"{name}_summary.csv"))
        log.info("study %s: %d summary rows -> %s_summary.csv", name, len(summ), name)
        if stats.get("aborted"):
            log.error("study %s aborted (disk floor) — stopping", name)
            return 2
    log.info("all studies complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
