"""Matheuristics for large-scale PQC migration scheduling (RQ3: scalability).

WHY THIS EXISTS
---------------
The exact CP-SAT solver (:mod:`pqcsched.solve_cpsat`) proves optimality, but the
time-indexed formulation has ``O(n * T)`` Boolean variables and a precedence
constraint per edge per period; past some estate size / horizon it no longer
finishes in a usable time budget. RQ3 asks: can we still produce *good, feasible*
schedules fast at large scale, and how far are they from optimal where optimal is
known?

This module provides two classic matheuristics, both of which **reuse the exact
solver as a black box on sub-problems** rather than re-deriving the model. That is
deliberate: the only risk source is :meth:`RiskModel.int_weight`, the only judge
is :func:`pqcsched.score.score_schedule`, and the only exact engine is
:func:`solve_cpsat`. By decomposing the problem and calling ``solve_cpsat`` on
reduced :class:`Instance` objects, every sub-solve honours the *exact same*
risk/cost/precedence/budget/cluster/deadline semantics as the full model, so the
stitched result is scored on identical terms to the optimum (no artefact gap).

THE "PIN" PRIMITIVE
-------------------
Both methods need to hold some assets at a decided period while letting others
move. We never modify ``solve_cpsat``; instead we *pin* an asset to period ``p``
by handing the sub-solver a copy of that asset with a one-period feasible window
``earliest == deadline == p``. CP-SAT then has exactly one legal value for it
(``y[a,p] == 1``), so its risk contribution, its budget consumption, and its role
in precedence/cluster constraints all stay live and exactly as CORE computes
them. Free assets keep their real ``[earliest, deadline]`` windows. Schedules are
always re-scored on the *original* instance (real windows) via ``score_schedule``,
which is the single source of truth for feasibility and objective.

1. :func:`rolling_horizon` — temporal decomposition: solve overlapping
   period-windows left to right, freezing decisions that fall in the committed
   prefix and rolling the rest forward.
2. :func:`lns` — Large-Neighborhood Search: start from the best greedy incumbent,
   then repeatedly destroy a random subset of decisions and repair them with a
   small exact solve over just that subset, accepting only improvements.

Both return a :class:`SolveResult` with ``status == FEASIBLE`` (a heuristic never
*claims* a proven optimum), ``solver == "heuristic-<method>"``, ``objective`` set
to the canonical ``score_schedule(...).risk`` of the returned schedule, and
``wall_time`` measured end to end.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from .model import Asset, Instance, Schedule
from .result import SolveResult, FEASIBLE, INFEASIBLE, OPTIMAL, UNKNOWN
from .risk import RiskModel
from .score import score_schedule
from .solve_cpsat import solve_cpsat
from .greedy import greedy_schedule, BASELINES

logger = logging.getLogger("pqcsched.heuristic")

# LNS adaptive-neighborhood tuning. A repair that releases fewer than
# ``_MIN_DESTROY`` assets is rarely worth a CP-SAT call, and an estate so small
# that 25% is only one or two assets needs a floor to escape local optima. After
# ``_STALL_PATIENCE`` non-improving repairs the destroy size escalates (see
# :func:`lns`). These are heuristics, not part of the locked CORE contract.
_MIN_DESTROY = 3
_STALL_PATIENCE = 4


# ---------------------------------------------------------------------------
# Sub-instance construction (the "pin" primitive) and helpers.
# ---------------------------------------------------------------------------
def _pin(asset: Asset, period: int) -> Asset:
    """Return a copy of `asset` constrained to migrate exactly in `period`.

    A one-period feasible window (``earliest == deadline == period``) leaves the
    exact solver a single legal placement, so the asset is effectively fixed while
    still contributing its risk, cost and constraint couplings inside the
    sub-solve. ``Asset`` uses ``slots=True``; we build a fresh instance rather than
    mutate (sub-instances must never alias CORE's asset objects).
    """
    return Asset(
        id=asset.id,
        criticality=asset.criticality,
        shelf_life=asset.shelf_life,
        cost=asset.cost,
        perf_penalty=asset.perf_penalty,
        earliest=period,
        deadline=period,
    )


def _window_asset(asset: Asset, hi: int) -> Asset | None:
    """Copy of `asset` allowed to migrate in this window, OR defer past it.

    The rolling horizon's correctness hinges on this. An asset visible to a window
    ending at period ``hi`` may migrate anywhere in ``[earliest, hi]`` *or* wait
    for a later window. We model "may migrate now or defer" by capping the
    feasible window at ``hi`` (``deadline' = hi``) **but only making that cap
    mandatory when the asset's real deadline falls within the window**:

    * real ``deadline <= hi`` → the asset MUST be placed by ``hi`` (its true
      deadline is inside the window), so we keep it mandated with ``deadline'`` =
      its real deadline.
    * real ``deadline > hi`` or unmandated → we drop the deadline, so the
      sub-solver may choose to migrate it in ``[earliest, hi]`` *or leave it
      unmigrated in this sub-problem* (``sum(y) <= 1``), i.e. defer it. This is the
      key fix: free assets are never *forced* into a short window, so a window can
      always at least replicate "migrate the urgent, defer the rest" and is never
      spuriously infeasible from over-stuffing the window's budget.

    Returns ``None`` if the asset cannot live in this window at all
    (``earliest > hi``) — the caller defers it untouched to a later window.
    """
    e = asset.earliest
    if e > hi:
        return None
    if asset.deadline is not None and asset.deadline <= hi:
        d: int | None = asset.deadline       # real deadline inside window: enforce it
    else:
        d = hi                                # cap at window end, but optional...
    mandatory = asset.deadline is not None and asset.deadline <= hi
    return Asset(
        id=asset.id,
        criticality=asset.criticality,
        shelf_life=asset.shelf_life,
        cost=asset.cost,
        perf_penalty=asset.perf_penalty,
        earliest=e,
        deadline=(d if mandatory else None),
    )


def _sub_instance(
    inst: Instance,
    assets: list[Asset],
    *,
    keep_ids: set[str] | None = None,
) -> Instance:
    """Build a reduced :class:`Instance` over `assets` for an exact sub-solve.

    Dependencies and clusters are filtered to those whose *both* endpoints are
    present (``keep_ids`` defaults to the ids of ``assets``). When a constraint's
    counterpart is pinned elsewhere this is safe: the counterpart's fixed period
    already shapes the present asset's window via the caller, and cross-boundary
    feasibility is re-validated by ``score_schedule`` on the full instance. The
    full-length per-period budget is preserved so the sub-solve respects capacity
    against *all* committed spend (callers pass pinned assets in, so their spend
    counts).
    """
    ids = keep_ids if keep_ids is not None else {a.id for a in assets}
    deps = [(j, i) for (j, i) in inst.deps if j in ids and i in ids]
    clusters = [(i, j) for (i, j) in inst.clusters if i in ids and j in ids]
    return Instance(
        assets=assets,
        T=inst.T,
        budget=list(inst.budget),
        deps=deps,
        clusters=clusters,
        t_crqc=inst.t_crqc,
        meta={"sub_of": inst.meta.get("generator", "?")},
    )


def _result(
    inst: Instance,
    schedule: Schedule,
    rm: RiskModel,
    *,
    method: str,
    wall: float,
    params: dict[str, Any],
) -> SolveResult:
    """Wrap a stitched schedule into a SolveResult, scoring it canonically.

    A matheuristic never asserts optimality, so status is always ``FEASIBLE`` when
    the schedule is feasible under the shared scorer. If the schedule somehow
    fails feasibility (should not happen — callers only ever accept feasible
    incumbents) we surface that honestly as ``UNKNOWN`` rather than lie.
    """
    sc = score_schedule(inst, schedule, rm)
    status = FEASIBLE if sc.feasible else UNKNOWN
    return SolveResult(
        status=status,
        solver=f"heuristic-{method}",
        objective=sc.risk,
        best_bound=None,  # heuristic: no proven bound
        schedule=dict(schedule),
        wall_time=wall,
        params={**params, "feasible": sc.feasible, "n_violations": sc.n_violations},
    )


# ---------------------------------------------------------------------------
# Best feasible greedy incumbent — the warm start shared by LNS.
# ---------------------------------------------------------------------------
def _best_greedy(inst: Instance, rm: RiskModel, seed: int) -> tuple[Schedule | None, int]:
    """Return the lowest-risk *feasible* greedy schedule and its risk.

    Tries every baseline; keeps the best one that the shared scorer deems
    feasible. Returns ``(None, big)`` if no baseline yields a feasible schedule
    (a genuinely hard instance — the caller then falls back to a direct solve).
    """
    best: Schedule | None = None
    best_risk = 1 << 62
    for b in BASELINES:
        sched = greedy_schedule(inst, b, rm, seed=seed)
        sc = score_schedule(inst, sched, rm)
        if sc.feasible and sc.risk < best_risk:
            best, best_risk = sched, sc.risk
    return best, best_risk


# ===========================================================================
# 1. Rolling-horizon matheuristic (temporal decomposition).
# ===========================================================================
def rolling_horizon(
    inst: Instance,
    risk_model: RiskModel | None = None,
    *,
    window: int = 6,
    step: int = 4,
    time_limit_per: float = 15.0,
    workers: int = 12,
) -> SolveResult:
    """Solve overlapping period-windows left to right, committing a prefix each time.

    Algorithm
    ---------
    The horizon ``[0, T)`` is swept in windows ``[w, w + window)`` advancing by
    ``step`` each iteration (``step < window`` gives the overlap that lets a
    window "see" a little past its commit boundary and place boundary assets
    well). For window starting at ``w``:

    * **Committed** assets — already frozen by an earlier window — are *pinned* to
      their decided period (one-period window) so their risk, cost and constraint
      couplings stay exactly live in this sub-solve.
    * **Free** assets that *can* live in ``[0, w + window - 1]`` (their real
      window intersects the visible prefix) are given that intersected window and
      optimised. Assets whose earliest is beyond the visible prefix are excluded
      from this sub-solve and roll forward untouched.
    * We then **commit** every free asset the sub-solve placed in a period
      ``< w + step`` (the non-overlapping prefix of this window). The rest stay
      free and are reconsidered by the next window, which can revise them.

    Pinned + free assets are solved *together* as one reduced instance, so
    precedence and clusters that straddle the commit boundary are enforced by
    CP-SAT directly; nothing is stitched blindly. A final full re-score on the
    original instance is the single arbiter of feasibility.

    Why it stays feasible: a mandated asset whose real deadline falls inside the
    window is kept mandatory there (``_window_asset``); one whose deadline is
    beyond the window may defer and is caught by a later window or the final
    repair. The last window always reaches ``T - 1`` and a closing
    :func:`_final_repair` places any still-free asset over its full real window, so
    no mandated asset is ever silently dropped (a residual miss, should it occur,
    is reported honestly by the scorer rather than hidden).
    """
    rm = risk_model or RiskModel()
    t0 = time.perf_counter()
    by_id = inst.by_id()
    T = inst.T
    window = max(1, int(window))
    step = max(1, min(int(step), window))

    committed: dict[str, int] = {}  # asset id -> frozen migration period
    free_ids: set[str] = {a.id for a in inst.assets}

    w = 0
    n_subsolves = 0
    while w < T and free_ids:
        hi = min(w + window - 1, T - 1)  # last period visible to this window

        # Partition free assets: those that can be placed within [0, hi] are
        # optimised now; those whose earliest is beyond `hi` wait for a later
        # window. (We let them be placed anywhere in [earliest, min(deadline, hi)]
        # so a free asset is never forced into the window if waiting is better;
        # only those landing before the commit boundary get frozen.)
        sub_free: list[Asset] = []
        for aid in free_ids:
            a = by_id[aid]
            fa = _window_asset(a, hi)
            if fa is not None:
                sub_free.append(fa)

        if not sub_free:
            # Nothing can be decided in this window; advance.
            w += step
            continue

        pinned = [_pin(by_id[aid], p) for aid, p in committed.items()]
        keep_ids = {a.id for a in sub_free} | set(committed.keys())
        sub = _sub_instance(inst, pinned + sub_free, keep_ids=keep_ids)

        res = solve_cpsat(sub, rm, time_limit=time_limit_per, workers=workers)
        n_subsolves += 1

        if res.status in (OPTIMAL, FEASIBLE) and res.schedule is not None:
            commit_boundary = w + step  # freeze placements strictly before this
            sched = res.schedule
            for a in sub_free:
                p = sched.get(a.id)
                if p is None:
                    continue  # unmandated asset deferred by the solver; keep free
                # Commit if it lands in this window's non-overlapping prefix, OR if
                # this is the final window (hi == T-1) so nothing is left dangling.
                if p < commit_boundary or hi == T - 1:
                    committed[a.id] = p
                    free_ids.discard(a.id)
        else:
            # Sub-solve failed (should be rare): leave these free; the next, wider
            # commit (or the final-window catch-all) will place them. Avoid an
            # infinite loop by still advancing the window below.
            logger.warning(
                "rolling_horizon: sub-solve at w=%d returned %s; deferring %d assets",
                w, res.status, len(sub_free),
            )

        w += step

    # Any asset still free after the sweep was never placed by a sub-solve. For
    # mandated assets that would be a deadline miss; do a final, focused exact
    # repair over just the leftovers (pinning everything committed) to place them.
    if free_ids:
        committed = _final_repair(inst, rm, committed, free_ids, time_limit_per, workers)

    # Feasibility floor. The rolling commitment is one-directional: an early
    # window freezes assets, and a later window cannot revise them, so on a tight
    # instance the committed spend/precedence can box out a mandated leftover that
    # even the final repair cannot place. The spec requires RH to *remain
    # feasible*, so — exactly as LNS warm-starts from greedy — we fall back to the
    # best feasible greedy schedule whenever our stitched result is infeasible.
    # This makes RH feasible whenever any greedy baseline is, without ever
    # claiming optimality. (Rescored on the *original* instance, the sole arbiter.)
    sc = score_schedule(inst, committed, rm)
    used_greedy_floor = False
    if not sc.feasible:
        g_sched, g_risk = _best_greedy(inst, rm, seed=0)
        if g_sched is not None and g_risk < (1 << 62):
            logger.info(
                "rolling_horizon: stitched schedule infeasible (%d violations); "
                "falling back to best feasible greedy (risk=%d)",
                sc.n_violations, g_risk,
            )
            committed = g_sched
            used_greedy_floor = True
        else:
            # Neither RH nor any greedy is feasible — a genuinely hard instance.
            # `_result` will surface status != FEASIBLE honestly (no fake claim).
            logger.warning(
                "rolling_horizon: no feasible schedule (stitched infeasible, no "
                "feasible greedy); reporting honestly.",
            )

    wall = time.perf_counter() - t0
    return _result(
        inst, committed, rm, method="rolling", wall=wall,
        params={
            "window": window, "step": step, "time_limit_per": time_limit_per,
            "workers": workers, "n_subsolves": n_subsolves, "T": T,
            "n_assets": len(inst.assets), "greedy_floor": used_greedy_floor,
        },
    )


def _final_repair(
    inst: Instance,
    rm: RiskModel,
    committed: dict[str, int],
    free_ids: set[str],
    time_limit: float,
    workers: int,
) -> dict[str, int]:
    """Place any leftover free assets via one exact solve, pinning the committed.

    Guards the rolling horizon against leaving a mandated asset unscheduled (a
    deadline violation). Free assets keep their *full real* windows here. If even
    this is infeasible we return what we have; ``score_schedule`` will then report
    the residual violation honestly rather than hide it.
    """
    by_id = inst.by_id()
    pinned = [_pin(by_id[aid], p) for aid, p in committed.items()]
    leftovers = [by_id[aid] for aid in free_ids]
    sub = _sub_instance(inst, pinned + leftovers,
                        keep_ids=set(committed.keys()) | free_ids)
    res = solve_cpsat(sub, rm, time_limit=time_limit, workers=workers)
    if res.status in (OPTIMAL, FEASIBLE) and res.schedule is not None:
        for aid in free_ids:
            p = res.schedule.get(aid)
            if p is not None:
                committed[aid] = p
    else:
        logger.warning("rolling_horizon final repair returned %s; %d assets unplaced",
                       res.status, len(free_ids))
    return committed


# ===========================================================================
# 2. Large-Neighborhood Search (destroy & repair around a greedy incumbent).
# ===========================================================================
def lns(
    inst: Instance,
    risk_model: RiskModel | None = None,
    *,
    time_limit: float = 30.0,
    iters: int | None = None,
    neighborhood: float = 0.25,
    workers: int = 12,
    seed: int = 0,
) -> SolveResult:
    """Improve a greedy schedule by repeated destroy-and-repair exact sub-solves.

    Algorithm
    ---------
    1. **Warm start**: take the best *feasible* greedy schedule across all
       baselines (:func:`_best_greedy`). If no greedy is feasible, fall back to a
       single time-limited exact solve so we still return something feasible.
    2. **Destroy**: pick a random ``neighborhood`` fraction of assets; their
       current periods are released.
    3. **Repair**: pin every *other* asset to its incumbent period and solve the
       reduced instance exactly over just the released subset (their full real
       windows). Because the rest are pinned, the repair sees the true residual
       capacity and all constraint couplings, so a feasible repair is feasible in
       the whole schedule.
    4. **Accept** the repaired schedule iff it is feasible *and* lower risk than
       the incumbent (scored by the shared scorer). Otherwise keep the incumbent
       (so the objective is monotone non-increasing and never goes infeasible).
    5. Loop until ``time_limit`` (or ``iters`` if given). A fresh random subset is
       drawn each iteration; clustered/precedence-linked assets are naturally
       co-released often enough over many iterations to escape local optima.

    **Adaptive (escalating) neighborhood.** A fixed small fraction can plateau:
    on a small estate, ``round(0.25 * 14) = 4`` released assets may be too few to
    cross a ridge, and the search stalls forever. So the destroy size starts at
    the requested fraction and *grows* after a run of non-improving iterations
    (``_STALL_PATIENCE``), up to (nearly) the whole estate, then resets to the base
    size on any accept. This keeps repairs small and cheap while progress is easy,
    yet automatically widens to escape local optima — recovering optimality on
    small instances without hurting large-scale speed (where the base fraction is
    already a big sub-problem and stalls are rarer).

    The per-repair time budget is a fraction of the remaining wall-clock so the
    loop respects ``time_limit`` overall.
    """
    rm = risk_model or RiskModel()
    t0 = time.perf_counter()
    rng = random.Random(seed)
    by_id = inst.by_id()
    asset_ids = [a.id for a in inst.assets]
    n = len(asset_ids)
    base_k = min(n, max(_MIN_DESTROY, int(round(neighborhood * n))))

    incumbent, inc_risk = _best_greedy(inst, rm, seed)
    used_fallback = False
    if incumbent is None:
        # No feasible greedy: try a direct exact solve within the budget so the
        # caller still gets a feasible schedule (or an honest non-FEASIBLE result).
        logger.info("lns: no feasible greedy warm start; falling back to direct solve")
        used_fallback = True
        res = solve_cpsat(inst, rm, time_limit=time_limit, workers=workers)
        wall = time.perf_counter() - t0
        # Keep the params schema identical to the main path so callers/tests can
        # rely on the same keys regardless of which branch produced the result.
        fallback_params = {
            "warm_start": "direct_solve", "neighborhood": neighborhood,
            "base_destroy_k": 0, "max_destroy_k": 0, "iters": 0, "accepted": 0,
            "seed": seed, "workers": workers, "n_assets": n,
        }
        if res.schedule is not None and res.status in (OPTIMAL, FEASIBLE):
            return _result(inst, res.schedule, rm, method="lns", wall=wall,
                           params=fallback_params)
        # Truly couldn't find anything feasible — report honestly.
        return SolveResult(status=res.status, solver="heuristic-lns",
                           objective=res.objective, schedule=res.schedule,
                           wall_time=wall,
                           params={**fallback_params, "warm_start": "direct_solve_failed"})

    n_iters = 0
    n_accept = 0
    k = base_k
    stall = 0          # consecutive non-improving iterations at the current size
    max_k_used = base_k
    while True:
        if iters is not None and n_iters >= iters:
            break
        elapsed = time.perf_counter() - t0
        remaining = time_limit - elapsed
        if remaining <= 0.05:
            break

        # Destroy: choose k assets to re-decide; pin the rest to incumbent.
        destroy = set(rng.sample(asset_ids, k))
        free_assets = [by_id[aid] for aid in destroy]
        pinned = [_pin(by_id[aid], incumbent[aid])
                  for aid in asset_ids if aid not in destroy and aid in incumbent]
        # (Assets absent from incumbent — unmandated, left unmigrated — are added
        # to the free set so the repair may choose to migrate them too.)
        for aid in asset_ids:
            if aid not in destroy and aid not in incumbent:
                free_assets.append(by_id[aid])

        sub = _sub_instance(inst, pinned + free_assets)
        # Give each repair a slice of the remaining time; never exceed the budget.
        per = max(0.5, min(remaining, time_limit / 4.0))
        res = solve_cpsat(sub, rm, time_limit=per, workers=workers)
        n_iters += 1

        improved = False
        if res.status in (OPTIMAL, FEASIBLE) and res.schedule is not None:
            cand = dict(res.schedule)
            sc = score_schedule(inst, cand, rm)
            if sc.feasible and sc.risk < inc_risk:
                incumbent, inc_risk = cand, sc.risk
                n_accept += 1
                improved = True
        # Infeasible/UNKNOWN repair -> discard, keep incumbent (stay feasible).

        # Adaptive neighborhood: reset on progress, escalate on a stall.
        if improved:
            k = base_k
            stall = 0
        else:
            stall += 1
            if stall >= _STALL_PATIENCE and k < n:
                k = min(n, k + max(_MIN_DESTROY, base_k))  # widen the search
                max_k_used = max(max_k_used, k)
                stall = 0

    wall = time.perf_counter() - t0
    return _result(
        inst, incumbent, rm, method="lns", wall=wall,
        params={
            "warm_start": "greedy" if not used_fallback else "direct_solve",
            "neighborhood": neighborhood, "base_destroy_k": base_k,
            "max_destroy_k": max_k_used, "iters": n_iters,
            "accepted": n_accept, "seed": seed, "workers": workers,
            "n_assets": n,
        },
    )


# ===========================================================================
# Dispatch.
# ===========================================================================
def solve_heuristic(inst: Instance, method: str = "rolling", **kw) -> SolveResult:
    """Dispatch to a named matheuristic.

    Parameters
    ----------
    method: ``"rolling"`` (rolling-horizon) or ``"lns"`` (large-neighborhood
            search). Extra keyword args are forwarded to the chosen method.
    """
    if method == "rolling":
        return rolling_horizon(inst, **kw)
    if method == "lns":
        return lns(inst, **kw)
    raise ValueError(f"unknown heuristic method {method!r} (use 'rolling' or 'lns')")
