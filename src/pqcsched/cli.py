"""Command-line interface for SAMAY / pqcsched.

Four subcommands, mirroring ``PROJECT_BRIEF.md`` §12:

    pqcsched gen        — generate a synthetic estate instance, write JSON.
    pqcsched solve      — solve an instance (or a CycloneDX CBOM) into a roadmap.
    pqcsched baselines  — compare the exact optimum against every greedy baseline.
    pqcsched study      — run the optimal-vs-greedy parameter-grid experiment.

This module is the *one* place in the package where printing to stdout is the
point: it is the user-facing surface. Everything it reports is derived from the
locked CORE contract (model / risk / score / solve_cpsat / greedy / generate /
experiment); the CLI never recomputes risk or cost itself, it always routes a
schedule through :func:`pqcsched.score.score_schedule` so the numbers a user
sees are byte-identical to the ones the study reports.

The MILP fallbacks (``solve_milp``), CBOM ingest (``cbom``), and the Pareto
frontier (``pareto``) are optional modules built in parallel; their imports are
guarded so the CLI works before they land. A subcommand that *explicitly* asks
for a missing optional (``--solver highs``, ``--cbom``, ``--pareto``) fails with
a clear message and a non-zero exit code rather than silently degrading.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .generate import GenParams, generate
from .greedy import BASELINES, greedy_schedule
from .model import Instance
from .result import OPTIMAL
from .risk import RiskModel
from .score import objective_gap, score_schedule
from .solve_cpsat import solve_cpsat

# Deadline-pressure presets (documented in `gen` help). One scalar in [0, 1];
# higher == more mandates + earlier deadlines (see generate.GenParams).
DEADLINE_PRESETS = {"low": 0.15, "medium": 0.45, "high": 0.8}


# ---------------------------------------------------------------------------
# Guarded optional-module access
# ---------------------------------------------------------------------------
# Each helper imports its optional module lazily and returns the callable, or
# raises a friendly RuntimeError naming what is missing. Callers turn that into a
# clean non-zero exit instead of a traceback.
def _require_solve_milp():
    try:
        from .solve_milp import solve_milp
    except ImportError as exc:  # module not built yet
        raise RuntimeError(
            "MILP solver backends are unavailable: pqcsched.solve_milp could not "
            f"be imported ({exc}). Use --solver cpsat, or install the MILP extra."
        ) from exc
    return solve_milp


def _require_cbom_to_instance():
    try:
        from .cbom import cbom_to_instance
    except ImportError as exc:
        raise RuntimeError(
            "CBOM ingest is unavailable: pqcsched.cbom could not be imported "
            f"({exc}). Pass --instance with a generated JSON instance instead."
        ) from exc
    return cbom_to_instance


def _require_pareto_frontier():
    try:
        from .pareto import pareto_frontier
    except ImportError as exc:
        raise RuntimeError(
            "Pareto frontier tracing is unavailable: pqcsched.pareto could not be "
            f"imported ({exc}). Re-run without --pareto."
        ) from exc
    return pareto_frontier


# ---------------------------------------------------------------------------
# argparse type helpers
# ---------------------------------------------------------------------------
def _deadline_pressure(value: str) -> float:
    """Parse --deadline-pressure: a preset (low/medium/high) or a float in [0, 1]."""
    key = value.strip().lower()
    if key in DEADLINE_PRESETS:
        return DEADLINE_PRESETS[key]
    try:
        f = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected one of {sorted(DEADLINE_PRESETS)} or a float in [0, 1], "
            f"got {value!r}"
        )
    if not 0.0 <= f <= 1.0:
        raise argparse.ArgumentTypeError(
            f"deadline-pressure float must be in [0, 1], got {f}"
        )
    return f


def _unit_float(value: str) -> float:
    """A float constrained to (0, 1] (used for --budget-tightness, --dep-density)."""
    try:
        f = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a float, got {value!r}")
    if not 0.0 < f <= 1.0:
        raise argparse.ArgumentTypeError(f"expected a float in (0, 1], got {f}")
    return f


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
def _period_to_year(period: int) -> int:
    """Map a period index to a calendar year (one period == one year, t=0 == 2026)."""
    return 2026 + period


def _invert_schedule(schedule: dict[str, int]) -> dict[int, list[str]]:
    """schedule (asset_id -> period) -> period -> sorted list of asset_ids."""
    by_period: dict[int, list[str]] = {}
    for asset_id, period in schedule.items():
        by_period.setdefault(period, []).append(asset_id)
    for ids in by_period.values():
        ids.sort()
    return by_period


def _print_roadmap(inst: Instance, result, rm: RiskModel, *, max_rows: int = 24) -> None:
    """Print a human migration-roadmap summary for a usable solve result."""
    print(f"  solver        : {result.solver}")
    print(f"  status        : {result.status}")
    if not result.is_usable:
        # No schedule was produced (INFEASIBLE / UNKNOWN / MODEL_INVALID).
        print("  (no schedule produced - nothing to migrate)")
        return

    score = score_schedule(inst, result.schedule, rm)
    n_total = len(inst.assets)
    print(f"  residual risk : {score.risk}")
    print(f"  total cost    : {score.cost}")
    print(f"  migrated      : {score.n_migrated}/{n_total} assets")
    print(f"  feasible      : {score.feasible}")
    if not score.feasible:
        print(
            "  violations    : "
            f"deadline={score.deadline_violations} budget={score.budget_violations} "
            f"precedence={score.precedence_violations} cluster={score.cluster_violations} "
            f"earliest={score.earliest_violations}"
        )
    if result.best_bound is not None and result.mip_gap is not None:
        print(f"  bound / gap   : {result.best_bound:.2f}  ({result.mip_gap * 100:.2f}%)")
    print(f"  wall time     : {result.wall_time:.3f}s")

    by_period = _invert_schedule(result.schedule)
    print("\n  Per-period migration plan:")
    if not by_period:
        print("    (no assets migrated within the horizon)")
        return
    shown = 0
    for period in range(inst.T):
        ids = by_period.get(period)
        if not ids:
            continue
        if shown >= max_rows:
            print(f"    ... ({len(by_period) - shown} more periods with migrations)")
            break
        year = _period_to_year(period)
        head = ", ".join(ids[:8])
        more = f" (+{len(ids) - 8} more)" if len(ids) > 8 else ""
        print(f"    period {period:>2} ({year}): {len(ids):>3} assets  [{head}{more}]")
        shown += 1


# ---------------------------------------------------------------------------
# Subcommand: gen
# ---------------------------------------------------------------------------
def cmd_gen(args: argparse.Namespace) -> int:
    """Generate one synthetic estate instance and write it to JSON."""
    params = GenParams(
        size=args.size,
        T=args.T,
        dep_density=args.dep_density,
        budget_tightness=args.budget_tightness,
        deadline_pressure=args.deadline_pressure,
        cluster_frac=args.cluster_frac,
        delayed_frac=args.delayed_frac,
        t_crqc=args.t_crqc,
        max_in_degree=args.max_in_degree,
        seed=args.seed,
    )
    inst = generate(params)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    inst.to_json(args.out)

    stats = inst.meta.get("stats", {})
    print(f"Generated instance -> {args.out}")
    print(f"  assets            : {stats.get('n_assets', len(inst.assets))}")
    print(f"  horizon T         : {inst.T}  (periods; one period == one year, t=0 == 2026)")
    print(f"  dependencies      : {stats.get('n_deps', len(inst.deps))}")
    print(f"  co-migration pairs: {stats.get('n_clusters', len(inst.clusters))}")
    print(f"  mandated assets   : {stats.get('n_mandated', '?')}")
    print(f"  total cost        : {stats.get('total_cost', '?')}")
    print(f"  per-period budget : {stats.get('per_period_budget', '?')}")
    print(f"  realized tightness: {stats.get('realized_tightness', '?')}")
    print(f"  t_crqc            : {inst.t_crqc}  (year {_period_to_year(inst.t_crqc)})")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: solve
# ---------------------------------------------------------------------------
def _load_instance_for_solve(args: argparse.Namespace) -> Instance:
    """Load the instance to solve, from --instance JSON or --cbom (if available)."""
    if args.cbom:
        cbom_to_instance = _require_cbom_to_instance()
        return cbom_to_instance(args.cbom, periods=args.periods, t_crqc=args.t_crqc)
    return Instance.from_json(args.instance)


def cmd_solve(args: argparse.Namespace) -> int:
    """Solve an instance into a migration roadmap; optionally trace the Pareto frontier."""
    # argparse's required mutually-exclusive group already rejects "neither given";
    # this guards the degenerate "--instance '' " (provided but empty) with a clear
    # message instead of a cryptic file-open error.
    if not args.instance and not args.cbom:
        print("error: provide --instance <inst.json> or --cbom <estate.cdx.json>",
              file=sys.stderr)
        return 2

    rm = RiskModel()  # instances carry no risk model; the documented default is in-spec.

    try:
        inst = _load_instance_for_solve(args)
    except RuntimeError as exc:           # optional module missing
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: could not load instance: {exc}", file=sys.stderr)
        return 2

    # --- pick a solver -----------------------------------------------------
    # Resolve a non-default backend *before* announcing the solve, so a missing
    # optional module fails cleanly instead of after a misleading banner.
    solver = args.solver
    solve_milp = None
    if solver in ("highs", "cbc"):
        try:
            solve_milp = _require_solve_milp()
        except RuntimeError as exc:        # optional MILP module missing
            print(f"error: {exc}", file=sys.stderr)
            return 2

    print(f"Solving {len(inst.assets)} assets over T={inst.T} with '{solver}' "
          f"(time_limit={args.time_limit}s)...")
    if solver == "cpsat":
        result = solve_cpsat(
            inst, rm, time_limit=args.time_limit, workers=args.workers
        )
    else:  # highs / cbc — solve_milp resolved above
        # solve_milp takes `threads`, not `workers` — map our flag across.
        result = solve_milp(
            inst, rm, backend=solver,
            time_limit=args.time_limit, threads=args.workers,
        )

    print("\nMigration roadmap:")
    _print_roadmap(inst, result, rm)

    # --- optional Pareto frontier -----------------------------------------
    frontier = None
    if args.pareto:
        try:
            pareto_frontier = _require_pareto_frontier()
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("\nTracing risk-vs-cost Pareto frontier...")
        frontier = pareto_frontier(inst, rm, n_points=args.pareto_points,
                                   time_limit=args.time_limit)
        print(f"  {len(frontier)} non-dominated points:")
        for pt in frontier:
            # Be tolerant of the point shape (object with .cost/.risk or a tuple).
            cost = getattr(pt, "cost", None)
            risk = getattr(pt, "risk", None)
            if cost is None and isinstance(pt, (tuple, list)) and len(pt) >= 2:
                cost, risk = pt[0], pt[1]
            print(f"    cost={cost}  risk={risk}")

    # --- optional save -----------------------------------------------------
    if args.out:
        _save_roadmap(args.out, inst, result, rm, frontier)
        print(f"\nWrote roadmap -> {args.out}")
    return 0


def _save_roadmap(path: str, inst: Instance, result, rm: RiskModel, frontier) -> None:
    """Persist the schedule + a summary (and frontier, if any) as JSON."""
    payload: dict[str, Any] = {
        "solver": result.solver,
        "status": result.status,
        "schedule": result.schedule,
        "wall_time": result.wall_time,
        "T": inst.T,
        "t_crqc": inst.t_crqc,
    }
    if result.is_usable:
        score = score_schedule(inst, result.schedule, rm)
        payload["summary"] = {
            "risk": score.risk,
            "cost": score.cost,
            "n_migrated": score.n_migrated,
            "feasible": score.feasible,
            "deadline_violations": score.deadline_violations,
        }
        payload["per_period"] = {
            str(period): ids for period, ids in sorted(_invert_schedule(result.schedule).items())
        }
    if result.best_bound is not None:
        payload["best_bound"] = result.best_bound
        payload["mip_gap"] = result.mip_gap
    if frontier is not None:
        pts = []
        for pt in frontier:
            cost = getattr(pt, "cost", None)
            risk = getattr(pt, "risk", None)
            if cost is None and isinstance(pt, (tuple, list)) and len(pt) >= 2:
                cost, risk = pt[0], pt[1]
            pts.append({"cost": cost, "risk": risk})
        payload["pareto_frontier"] = pts

    out_dir = os.path.dirname(os.path.abspath(path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


# ---------------------------------------------------------------------------
# Subcommand: baselines
# ---------------------------------------------------------------------------
def cmd_baselines(args: argparse.Namespace) -> int:
    """Solve the exact optimum and every greedy; print a comparison table.

    The gap is shown only when the optimum is *proven* OPTIMAL and the greedy is
    feasible — exactly the honesty rule the experiment harness enforces. Anything
    else is labelled ``n/a`` rather than given a fabricated number.
    """
    rm = RiskModel()
    try:
        inst = Instance.from_json(args.instance)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: could not load instance: {exc}", file=sys.stderr)
        return 2

    print(f"Instance: {len(inst.assets)} assets, T={inst.T}, "
          f"{len(inst.deps)} deps, {len(inst.clusters)} clusters")
    print(f"Solving exact optimum (CP-SAT, time_limit={args.time_limit}s)...\n")
    opt = solve_cpsat(inst, rm, time_limit=args.time_limit, workers=args.workers)

    # Optimal row.
    opt_risk_for_gap = opt.objective if opt.status == OPTIMAL else None
    rows: list[tuple[str, str, str, str, str, str]] = []
    if opt.is_usable:
        osc = score_schedule(inst, opt.schedule, rm)
        opt_tag = "optimal" if opt.status == OPTIMAL else "optimal*"  # * == time-limited
        rows.append((
            opt_tag, str(osc.risk), str(osc.cost), str(osc.feasible),
            str(osc.deadline_violations), "-",
        ))
    else:
        rows.append(("optimal", "-", "-", str(False), "-", "-"))

    # Greedy rows.
    for b in BASELINES:
        sched = greedy_schedule(inst, b, rm, seed=args.seed)
        sc = score_schedule(inst, sched, rm)
        if opt_risk_for_gap is not None and sc.feasible:
            gap = objective_gap(opt_risk_for_gap, sc.risk)
            gap_str = "inf" if gap == float("inf") else f"{gap * 100:.1f}%"
        else:
            gap_str = "n/a"
        rows.append((
            b, str(sc.risk), str(sc.cost), str(sc.feasible),
            str(sc.deadline_violations), gap_str,
        ))

    _print_table(
        ["method", "risk", "cost", "feasible", "ddl_viol", "gap_vs_opt"],
        rows,
    )
    if opt.status != OPTIMAL:
        print("\nnote: optimum not proven within the time limit "
              "(marked 'optimal*'); gaps are withheld (shown as n/a).")
    return 0


def _print_table(headers: list[str], rows: list[tuple[str, ...]]) -> None:
    """Print a simple left/right-aligned ASCII table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    # method left-aligned, the rest right-aligned.
    def fmt(cells: tuple[str, ...]) -> str:
        out = [cells[0].ljust(widths[0])]
        out += [cells[i].rjust(widths[i]) for i in range(1, len(cells))]
        return "  ".join(out)

    print(fmt(tuple(headers)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt(row))


# ---------------------------------------------------------------------------
# Subcommand: study
# ---------------------------------------------------------------------------
# Keys accepted inside a single `studies:` entry. `study` names the run; the rest
# are passed straight to experiment.expand_grid (which is keyword-only).
_STUDY_REQUIRED = {"study"}
_EXPAND_GRID_KEYS = {
    "sizes", "Ts", "dep_densities", "budget_tightnesses", "deadline_pressures",
    "t_crqcs", "risk_forms", "residual_factors", "cluster_frac", "delayed_frac",
    "n_instances", "time_limit", "workers", "base_seed",
}


def _load_studies(grid_path: str) -> list[dict]:
    """Parse the experiment YAML into a list of per-study kwarg dicts."""
    import yaml

    with open(grid_path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict) or "studies" not in doc:
        raise ValueError("experiment YAML must have a top-level 'studies:' list")
    studies = doc["studies"]
    if not isinstance(studies, list) or not studies:
        raise ValueError("'studies' must be a non-empty list")
    return studies


def cmd_study(args: argparse.Namespace) -> int:
    """Run each study in the grid YAML: expand_grid -> run_grid -> summarize."""
    # experiment imports ortools transitively; import lazily so `gen`/`baselines`
    # never pay for it and an import error here is reported cleanly.
    from . import experiment

    try:
        studies = _load_studies(args.grid)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    print(f"Loaded {len(studies)} stud{'y' if len(studies) == 1 else 'ies'} "
          f"from {args.grid}; writing to {args.out}/\n")

    for i, study in enumerate(studies, start=1):
        if not isinstance(study, dict) or "study" not in study:
            print(f"error: study #{i} is missing the required 'study' name",
                  file=sys.stderr)
            return 2
        name = study["study"]
        kwargs = {k: v for k, v in study.items() if k != "study"}

        unknown = set(kwargs) - _EXPAND_GRID_KEYS
        if unknown:
            print(f"error: study {name!r} has unknown keys: {sorted(unknown)}. "
                  f"Allowed: {sorted(_EXPAND_GRID_KEYS)}", file=sys.stderr)
            return 2

        print(f"[{i}/{len(studies)}] study '{name}': expanding grid...")
        try:
            cells = experiment.expand_grid(study=name, **kwargs)
        except TypeError as exc:
            print(f"error: study {name!r} parameters rejected by expand_grid: {exc}",
                  file=sys.stderr)
            return 2

        total = sum(c.n_instances for c in cells)
        print(f"    {len(cells)} cells, {total} instances total - solving "
              "(this can take a while)...")

        out_csv = os.path.join(args.out, f"{name}.csv")
        summary_csv = os.path.join(args.out, f"{name}_summary.csv")
        stats = experiment.run_grid(cells, out_csv)
        print(f"    run_grid: {stats['run']} run, {stats['skipped']} skipped"
              f"{' (ABORTED on disk floor)' if stats.get('aborted') else ''}")

        summary = experiment.summarize(out_csv, summary_csv)
        print(f"    wrote {out_csv} and {summary_csv} "
              f"({len(summary)} summary rows)\n")

    print("Study complete.")
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pqcsched",
        description="SAMAY: provably optimal phased scheduling for "
                    "post-quantum cryptographic migration.",
    )
    parser.set_defaults(func=None)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # --- gen ---------------------------------------------------------------
    p_gen = sub.add_parser(
        "gen", help="generate a synthetic estate instance and write JSON",
        description="Generate one synthetic cryptographic-estate instance.",
    )
    p_gen.add_argument("--size", type=int, default=500,
                       help="number of assets (default: 500)")
    p_gen.add_argument("--T", type=int, default=20,
                       help="horizon length in periods; one period == one year, "
                            "t=0 == 2026 (default: 20)")
    p_gen.add_argument("--dep-density", type=_unit_float, default=0.3,
                       help="dependency density in (0, 1] (default: 0.3)")
    p_gen.add_argument("--deadline-pressure", type=_deadline_pressure, default=0.3,
                       help="regulatory pressure: low|medium|high "
                            "(== 0.15|0.45|0.8) or a float in [0, 1] (default: 0.3)")
    p_gen.add_argument("--budget-tightness", type=_unit_float, default=0.6,
                       help="per-period capacity tightness in (0, 1]; higher == "
                            "harder (default: 0.6)")
    p_gen.add_argument("--cluster-frac", type=float, default=0.10,
                       help="fraction of assets placed in co-migration pairs "
                            "(default: 0.10)")
    p_gen.add_argument("--delayed-frac", type=float, default=0.15,
                       help="fraction with earliest > 0, i.e. delayed PQC support "
                            "(default: 0.15)")
    p_gen.add_argument("--t-crqc", type=int, default=13,
                       help="projected CRQC year-index, ~2039 (default: 13)")
    p_gen.add_argument("--max-in-degree", type=int, default=4,
                       help="cap on dependency in-degree (default: 4)")
    p_gen.add_argument("--seed", type=int, default=0, help="RNG seed (default: 0)")
    p_gen.add_argument("--out", required=True, help="output JSON path")
    p_gen.set_defaults(func=cmd_gen)

    # --- solve -------------------------------------------------------------
    p_solve = sub.add_parser(
        "solve", help="solve an instance (or CBOM) into a migration roadmap",
        description="Solve an instance into a roadmap; optionally trace a Pareto "
                    "frontier and save the result.",
    )
    src = p_solve.add_mutually_exclusive_group(required=True)
    src.add_argument("--instance", help="instance JSON produced by `pqcsched gen`")
    src.add_argument("--cbom", help="CycloneDX CBOM JSON (requires pqcsched.cbom)")
    p_solve.add_argument("--periods", type=int, default=20,
                         help="horizon when ingesting a CBOM (default: 20)")
    p_solve.add_argument("--t-crqc", type=int, default=13,
                         help="projected CRQC year-index when ingesting a CBOM "
                              "(default: 13)")
    p_solve.add_argument("--solver", choices=("cpsat", "highs", "cbc"),
                         default="cpsat",
                         help="exact solver backend (default: cpsat; highs/cbc "
                              "require pqcsched.solve_milp)")
    p_solve.add_argument("--time-limit", type=float, default=60.0,
                         help="solver wall-clock budget in seconds (default: 60)")
    p_solve.add_argument("--workers", type=int, default=12,
                         help="solver worker threads (default: 12)")
    p_solve.add_argument("--pareto", action="store_true",
                         help="also trace the risk-vs-cost Pareto frontier "
                              "(requires pqcsched.pareto)")
    p_solve.add_argument("--pareto-points", type=int, default=12,
                         help="number of Pareto points to trace (default: 12)")
    p_solve.add_argument("--out", help="write schedule + summary JSON here")
    p_solve.set_defaults(func=cmd_solve)

    # --- baselines ---------------------------------------------------------
    p_base = sub.add_parser(
        "baselines", help="compare the optimum against every greedy baseline",
        description="Solve the exact optimum and run all greedy baselines, "
                    "printing a comparison table.",
    )
    p_base.add_argument("--instance", required=True,
                        help="instance JSON produced by `pqcsched gen`")
    p_base.add_argument("--time-limit", type=float, default=60.0,
                        help="CP-SAT wall-clock budget in seconds (default: 60)")
    p_base.add_argument("--workers", type=int, default=12,
                        help="CP-SAT worker threads (default: 12)")
    p_base.add_argument("--seed", type=int, default=0,
                        help="seed for the randomized baseline (default: 0)")
    p_base.set_defaults(func=cmd_baselines)

    # --- study -------------------------------------------------------------
    p_study = sub.add_parser(
        "study", help="run the optimal-vs-greedy parameter-grid experiment",
        description="Parse a grid YAML and run each study: expand_grid -> "
                    "run_grid -> summarize.",
    )
    p_study.add_argument("--grid", required=True,
                         help="experiment YAML (a top-level 'studies:' list)")
    p_study.add_argument("--out", required=True,
                         help="output directory for {study}.csv and "
                              "{study}_summary.csv")
    p_study.set_defaults(func=cmd_study)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 == success)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.func is None:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
