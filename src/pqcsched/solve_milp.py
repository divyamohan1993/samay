"""Exact MILP solvers via a single PuLP model dispatched over free backends.

The study's credibility rests on one fact: *the same optimization model* must be
solvable by more than one independent engine and return the *same* optimum. CP-SAT
(:mod:`pqcsched.solve_cpsat`) is the primary exact solver; this module is the
cross-check. It builds the **identical** time-indexed formulation once as a PuLP
:class:`pulp.LpProblem` and hands it to whichever free MILP backend is asked for:

    * **CBC**  — the COIN-OR branch-and-cut solver that *ships inside PuLP*
                 (``PULP_CBC_CMD``); always available, so the cross-check always runs.
    * **HiGHS** — the high-performance open-source MILP solver. Modern PuLP exposes
                 it in-process via ``pulp.HiGHS`` (backed by the installed ``highspy``
                 wheel); if that class is unavailable we fall back to the ``HiGHS_CMD``
                 executable wrapper, and only if neither exists is the backend dropped.
    * **Gurobi** — optional, commercial. Imported behind a guard via
                 :func:`pulp.listSolvers(onlyAvailable=True)`; it is **never** a hard
                 dependency. If no licensed Gurobi is present the backend is simply
                 absent from :data:`AVAILABLE_BACKENDS`.

Why one model, many solvers (and not three hand-written models): a separate model
per engine is three chances to introduce a transcription bug that silently shifts
the optimum. Writing the constraints and objective exactly once — mirroring
``solve_cpsat`` term for term — means any backend that disagrees with CP-SAT
signals a *solver* discrepancy, never a modelling one.

Objective parity is load-bearing. The objective is the residual-risk expression
``sum_i sum_t w_{i,t} (1 - done_{i,t})`` with ``w`` from the one true
:meth:`RiskModel.int_weight`. The constant ``sum_{i,t} w_{i,t}`` is kept (exactly
as CP-SAT keeps the "1") so that the reported integer objective equals
``score_schedule(inst, returned_schedule, rm).risk`` bit-for-bit. PuLP's
``value()`` recomputes the objective in Python from the variable values plus the
expression's constant, so the constant survives; the agreement tests assert it.

Status mapping is deliberately conservative. PuLP reports two things after a solve:
``status`` (termination: optimal / infeasible / not-solved) and ``sol_status``
(whether the returned solution is proven-optimal, merely integer-feasible, or
none). We key the normalized :class:`SolveResult` status off ``sol_status`` so a
*time-limited incumbent never masquerades as OPTIMAL* — reporting a feasible bound
as optimal would understate the optimal-vs-greedy gap and is dishonest. When the
solve is proven optimal the dual bound equals the objective, so ``best_bound`` is
set to it; otherwise the true bound is not surfaced uniformly by PuLP across CBC
and the in-process HiGHS (whose ``solverModel`` is released after solve), so
``best_bound`` is left ``None`` rather than guessed.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import pulp

from .model import Instance
from .result import (
    SolveResult,
    OPTIMAL,
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
    MODEL_INVALID,
)
from .risk import RiskModel
from .score import cost_at

log = logging.getLogger("pqcsched.milp")


# ---------------------------------------------------------------------------
# Backend probing — what can actually solve on this box, decided at import time.
# ---------------------------------------------------------------------------
def _probe_backends() -> dict[str, Callable[..., "pulp.LpSolver"]]:
    """Map canonical backend name -> a zero-arg-ish factory for an available solver.

    Probed against the *live* PuLP install (versions differ in which wrappers they
    ship and which external binaries are on PATH), so the rest of the module never
    assumes a backend exists. CBC is expected always; HiGHS prefers the in-process
    ``pulp.HiGHS`` and falls back to the ``HiGHS_CMD`` executable; Gurobi is added
    only when a licensed install answers ``available()`` truthy.
    """
    available = set(pulp.listSolvers(onlyAvailable=True))
    factories: dict[str, Callable[..., "pulp.LpSolver"]] = {}

    # CBC ships with PuLP; this is the guaranteed cross-check.
    if "PULP_CBC_CMD" in available and hasattr(pulp, "PULP_CBC_CMD"):
        factories["cbc"] = pulp.PULP_CBC_CMD

    # HiGHS: prefer the in-process class (highspy), else the CMD wrapper.
    if "HiGHS" in available and hasattr(pulp, "HiGHS"):
        factories["highs"] = pulp.HiGHS
    elif "HiGHS_CMD" in available and hasattr(pulp, "HiGHS_CMD"):
        factories["highs"] = pulp.HiGHS_CMD

    # Gurobi: optional, guarded, never required. Prefer the in-process binding.
    if "GUROBI" in available and hasattr(pulp, "GUROBI"):
        factories["gurobi"] = pulp.GUROBI
    elif "GUROBI_CMD" in available and hasattr(pulp, "GUROBI_CMD"):
        factories["gurobi"] = pulp.GUROBI_CMD

    return factories


# name -> factory; AVAILABLE_BACKENDS is the public probe result.
_BACKEND_FACTORIES: dict[str, Callable[..., "pulp.LpSolver"]] = _probe_backends()
AVAILABLE_BACKENDS: tuple[str, ...] = tuple(sorted(_BACKEND_FACTORIES))

# Default free backend. Prefer in-process **HiGHS** (via highspy): robust and
# cross-platform with no external process. CBC (PuLP's bundled `PULP_CBC_CMD`) is a
# valid fallback on Linux but has a known subprocess deadlock on Windows — it can
# hang in `cbc.wait()` regardless of the time limit — so it is never the default.
DEFAULT_BACKEND: str | None = (
    "highs" if "highs" in AVAILABLE_BACKENDS
    else ("cbc" if "cbc" in AVAILABLE_BACKENDS else None)
)


def _make_solver(
    backend: str, *, time_limit: float, threads: int
) -> "pulp.LpSolver":
    """Construct a configured PuLP solver for `backend` (quiet, time- and
    thread-limited). Raises ``ValueError`` if the backend was not probed available.
    """
    try:
        factory = _BACKEND_FACTORIES[backend]
    except KeyError:
        raise ValueError(
            f"MILP backend {backend!r} is not available; "
            f"available backends: {AVAILABLE_BACKENDS}"
        )
    # All probed factories (PULP_CBC_CMD, HiGHS, HiGHS_CMD, GUROBI[_CMD]) accept
    # this common kwarg set in PuLP 3.x; keep it minimal and uniform.
    return factory(msg=False, timeLimit=float(time_limit), threads=int(threads))


# ---------------------------------------------------------------------------
# Model construction — the SAME time-indexed formulation as solve_cpsat.
# ---------------------------------------------------------------------------
def _periods(inst: Instance, a) -> range:
    """Feasible migration periods for asset `a`: ``[earliest, hi]`` with
    ``hi = min(deadline, T-1)``. Identical to ``solve_cpsat._periods`` — the two
    must define the same variable domain or the feasible sets diverge.
    """
    hi = inst.T - 1
    if a.deadline is not None:
        hi = min(hi, a.deadline)
    return range(a.earliest, hi + 1)


def _build_problem(
    inst: Instance,
    rm: RiskModel,
    eps_cost: int | None,
) -> tuple["pulp.LpProblem | None", dict[tuple[str, int], "pulp.LpVariable"]]:
    """Build the PuLP problem mirroring :func:`pqcsched.solve_cpsat.solve_cpsat`.

    Returns ``(problem, y)``. ``problem is None`` signals structural infeasibility
    detected during construction (an asset with no feasible period), matching the
    early-INFEASIBLE return CP-SAT makes.
    """
    m = pulp.LpProblem("pqcsched_milp", pulp.LpMinimize)
    by_id = inst.by_id()

    # y[(id, t)] = 1 iff asset id migrated in period t (created only for feasible t).
    y: dict[tuple[str, int], "pulp.LpVariable"] = {}
    for a in inst.assets:
        for t in _periods(inst, a):
            y[(a.id, t)] = pulp.LpVariable(f"y_{a.id}_{t}", cat=pulp.LpBinary)

    def done(i: str, t: int):
        """Linear expression: asset i migrated by the end of period t."""
        a = by_id[i]
        return pulp.lpSum(y[(i, tau)] for tau in _periods(inst, a) if tau <= t)

    # (1) migrate at most once; mandated assets exactly once within the deadline.
    for a in inst.assets:
        ys = [y[(a.id, t)] for t in _periods(inst, a)]
        if not ys:
            # No feasible period -> instance is structurally infeasible.
            log.debug("asset %s has no feasible period -> INFEASIBLE", a.id)
            return None, y
        if a.deadline is not None:
            m += pulp.lpSum(ys) == 1  # window already capped at the deadline
        else:
            m += pulp.lpSum(ys) <= 1

    # (3) per-period budget / throughput: sum of costs migrated in t <= B_t.
    for t in range(inst.T):
        terms = [cost_at(by_id[i].cost, t) * y[(i, tt)] for (i, tt) in y if tt == t]
        if terms:
            m += pulp.lpSum(terms) <= inst.budget[t]

    # (4) precedence: edge (j, i) => done(i,t) <= done(j,t) for all t.
    for (j, i) in inst.deps:
        for t in range(inst.T):
            m += done(i, t) <= done(j, t)

    # (5) co-migration clusters: same period. Equal where both can migrate;
    #     force-zero on periods where only one of the pair is feasible so the
    #     two cannot be split across periods (mirrors solve_cpsat exactly).
    for (i, j) in inst.clusters:
        ai, aj = by_id[i], by_id[j]
        pi, pj = set(_periods(inst, ai)), set(_periods(inst, aj))
        for t in pi | pj:
            if t in pi and t in pj:
                m += y[(i, t)] == y[(j, t)]
            elif t in pi:
                m += y[(i, t)] == 0
            else:
                m += y[(j, t)] == 0

    # (optional) epsilon-constraint on total cost for Pareto tracing.
    if eps_cost is not None:
        m += (
            pulp.lpSum(cost_at(by_id[i].cost, t) * y[(i, t)] for (i, t) in y)
            <= eps_cost
        )

    # Objective: minimize residual risk = sum_i sum_t w_{i,t} (1 - done(i,t)).
    # The "1" is a constant per (i,t); keeping it makes value(objective) equal the
    # scorer's risk exactly (PuLP folds it into the expression's constant term).
    risk_terms = []
    for a in inst.assets:
        for t in range(inst.T):
            w = rm.int_weight(a, t, inst.t_crqc)
            if w:
                risk_terms.append(w * (1 - done(a.id, t)))
    m += pulp.lpSum(risk_terms)

    return m, y


# ---------------------------------------------------------------------------
# Status mapping — key off sol_status; never promote an incumbent to OPTIMAL.
# ---------------------------------------------------------------------------
def _normalize_status(prob: "pulp.LpProblem") -> str:
    """Map PuLP's (status, sol_status) onto the normalized SolveResult status.

    ``sol_status`` is the authoritative signal for the optimal-vs-feasible
    distinction the study depends on:
      * Optimal            -> OPTIMAL   (proven; bound == objective)
      * IntegerFeasible    -> FEASIBLE  (incumbent only; e.g. hit the time limit)
      * Infeasible / "no solution exists" -> INFEASIBLE
      * anything else (not solved / undefined) -> UNKNOWN
    """
    sol = prob.sol_status
    if sol == pulp.LpSolutionOptimal:
        return OPTIMAL
    if sol == pulp.LpSolutionIntegerFeasible:
        return FEASIBLE
    if sol == pulp.LpSolutionInfeasible:
        return INFEASIBLE
    # Fall back on the termination status for the no-incumbent cases.
    if prob.status == pulp.LpStatusInfeasible:
        return INFEASIBLE
    return UNKNOWN


def _extract_schedule(
    inst: Instance, y: dict[tuple[str, int], "pulp.LpVariable"]
) -> dict[str, int]:
    """Read the migration period of each migrated asset from the solved variables.

    LP-based backends return fractional-looking values near 0/1, so threshold at
    0.5 (never ``== 1``) or parity breaks on a 0.9999.
    """
    schedule: dict[str, int] = {}
    for a in inst.assets:
        for t in _periods(inst, a):
            val = y[(a.id, t)].varValue
            if val is not None and val > 0.5:
                schedule[a.id] = t
                break
    return schedule


# ---------------------------------------------------------------------------
# Public solve API.
# ---------------------------------------------------------------------------
def solve_milp(
    inst: Instance,
    risk_model: RiskModel | None = None,
    *,
    backend: str | None = None,
    eps_cost: int | None = None,
    time_limit: float = 60.0,
    threads: int = 12,
) -> SolveResult:
    """Solve `inst` exactly with a free MILP backend, minimizing residual risk.

    Builds the same time-indexed model as :func:`pqcsched.solve_cpsat.solve_cpsat`
    and solves it with `backend` (``"cbc"``, ``"highs"``, or ``"gurobi"`` when
    licensed). The returned :class:`SolveResult` carries the integer objective
    (which equals ``score_schedule(inst, result.schedule, rm).risk``), the proven
    bound when optimal, and a conservative normalized status.

    Parameters
    ----------
    backend:     one of :data:`AVAILABLE_BACKENDS`.
    eps_cost:    if given, add ``total_cost <= eps_cost`` (Pareto frontier tracing).
    time_limit:  wall-clock seconds for the solve.
    threads:     solver threads (box has 12 vCPUs).

    Raises
    ------
    ValueError:  if `backend` is not available on this machine.
    """
    rm = risk_model or RiskModel()
    backend = backend or DEFAULT_BACKEND
    if backend is None:
        raise ValueError(f"no free MILP backend available; probed: {AVAILABLE_BACKENDS}")
    solver_name = f"milp-{backend}"
    params: dict[str, Any] = {
        "backend": backend,
        "time_limit": time_limit,
        "threads": threads,
        "num_assets": len(inst.assets),
        "T": inst.T,
    }

    # Construct the solver first so an unavailable backend fails fast and cleanly.
    solver = _make_solver(backend, time_limit=time_limit, threads=threads)

    m, y = _build_problem(inst, rm, eps_cost)
    params["num_vars"] = len(y)
    if m is None:
        # Structural infeasibility found during construction (no feasible period).
        return SolveResult(
            status=INFEASIBLE,
            solver=solver_name,
            eps_cost=eps_cost,
            params={**params, "reason": "asset with no feasible period"},
        )

    t0 = time.perf_counter()
    try:
        m.solve(solver)
    except pulp.PulpSolverError as exc:  # solver crash / invalid model
        wall = time.perf_counter() - t0
        log.warning("MILP backend %s failed: %s", backend, exc)
        return SolveResult(
            status=MODEL_INVALID,
            solver=solver_name,
            wall_time=wall,
            eps_cost=eps_cost,
            params={**params, "error": str(exc)},
        )
    wall = time.perf_counter() - t0

    status = _normalize_status(m)
    schedule = None
    objective = None
    bound = None
    if status in (OPTIMAL, FEASIBLE):
        schedule = _extract_schedule(inst, y)
        objective = int(round(pulp.value(m.objective)))
        # Proven optimal => the dual bound equals the objective. For a merely
        # feasible incumbent PuLP does not surface the bound uniformly across
        # backends, so we leave it None rather than report a guess.
        if status == OPTIMAL:
            bound = float(objective)

    return SolveResult(
        status=status,
        solver=solver_name,
        objective=objective,
        best_bound=bound,
        schedule=schedule,
        wall_time=wall,
        eps_cost=eps_cost,
        params=params,
    )


def solve(
    inst: Instance,
    risk_model: RiskModel | None = None,
    *,
    backend: str | None = None,
    **kwargs: Any,
) -> SolveResult:
    """Dispatcher: solve `inst` with the named MILP `backend`.

    A thin convenience wrapper over :func:`solve_milp` mirroring its keyword
    arguments (``eps_cost``, ``time_limit``, ``threads``), provided so callers can
    iterate over :data:`AVAILABLE_BACKENDS` uniformly.
    """
    return solve_milp(inst, risk_model, backend=backend, **kwargs)
