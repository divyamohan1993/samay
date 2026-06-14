"""Risk-vs-cost Pareto frontier via the epsilon-constraint method.

The headline study answers "how much risk does optimal scheduling retire vs the
greedy status quo". But a decision-maker's *next* question is always budgetary:
"if I can only spend C, how much residual risk am I stuck with?" The Pareto
frontier answers exactly that — it is the set of non-dominated (cost, risk)
trade-offs, so a CISO can read the marginal risk bought by each extra rupee of
migration budget straight off the curve.

We trace it with the **epsilon-constraint method** on the locked CP-SAT model
(``solve_cpsat(..., eps_cost=...)`` adds ``total_cost <= eps_cost``). Risk is the
objective; cost is swept as a parametric upper bound:

    minimise  risk
    s.t.      total_cost <= eps        for eps in [C_lo, C_hi]

* **High-cost / low-risk extreme** — the unconstrained min-risk solve. Its cost is
  ``C_hi`` (spending more buys no further risk reduction, so the frontier ends
  here).
* **Low-cost extreme ``C_lo``** — the *minimum cost that keeps the instance
  feasible*. Mandated assets must migrate and precedence/cluster forcing can drag
  unmandated assets along, so we do not compute this in closed form (that would
  duplicate the locked constraint logic). Instead we **binary-search the smallest
  ``eps_cost`` for which the model is still feasible**. Feasibility is monotonic in
  ``eps_cost`` (relaxing the cap never makes a feasible problem infeasible), so the
  threshold is well-defined; the schedule returned at that threshold has actual
  cost == ``C_lo`` exactly (proof: at ``C_lo - 1`` infeasible ⇒ every schedule
  costs ≥ ``C_lo``; the returned one costs ≤ its eps == ``C_lo``).

Every point's ``(cost, risk)`` is read from :func:`pqcsched.score.score_schedule`
on the *returned schedule*, never from the eps value or the solver's objective, so
the frontier is scored by the single source of truth shared with the rest of the
study. Dominated points are dropped with a strict skyline so risk is strictly
decreasing as cost increases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .model import Instance, Schedule
from .result import INFEASIBLE, OPTIMAL, UNKNOWN
from .risk import RiskModel
from .score import score_schedule
from .solve_cpsat import solve_cpsat

log = logging.getLogger("pqcsched.pareto")


@dataclass(slots=True)
class ParetoPoint:
    """One non-dominated risk-vs-cost trade-off on the frontier.

    ``status`` is the CP-SAT status of the solve that produced ``schedule``
    (``OPTIMAL`` for a proven point; ``FEASIBLE`` for a time-limited one whose
    risk is therefore only an upper bound — surfaced honestly, never relabelled).
    ``cost`` and ``risk`` are scored from ``schedule`` by the shared scorer.
    """

    cost: int
    risk: int
    schedule: Schedule
    status: str


def _min_feasible_cost(
    inst: Instance,
    rm: RiskModel,
    c_hi: int,
    *,
    time_limit: float,
    workers: int,
) -> int:
    """Smallest ``eps_cost`` that keeps `inst` feasible (the low-cost extreme).

    Binary search on ``[0, c_hi]``. ``c_hi`` is already feasible (it is the cost of
    the unconstrained min-risk schedule), which anchors the high end. A solve is
    "feasible" iff it is not proven ``INFEASIBLE``: ``UNKNOWN`` (the time limit
    expired without a proof either way) is explicitly *not* treated as infeasible,
    because doing so would overstate the floor. We treat ``UNKNOWN`` as
    inconclusive and widen conservatively (search the upper half).
    """
    lo, hi = 0, c_hi
    while lo < hi:
        mid = (lo + hi) // 2
        res = solve_cpsat(inst, rm, eps_cost=mid, time_limit=time_limit, workers=workers)
        if res.status == INFEASIBLE:
            lo = mid + 1            # mid too tight -> floor is strictly above mid
        elif res.is_usable:
            hi = mid                # feasible at mid -> floor is at or below mid
        else:
            # UNKNOWN / MODEL_INVALID: cannot prove (in)feasibility here. Do not
            # claim infeasibility; assume this cap is too tight to resolve cheaply
            # and look higher, keeping C_lo a safe (never under-stated) bound.
            log.warning("min-cost search: inconclusive status %s at eps_cost=%d; "
                        "widening upward", res.status, mid)
            lo = mid + 1
    return lo


def pareto_frontier(
    inst: Instance,
    risk_model: RiskModel | None = None,
    *,
    n_points: int = 12,
    time_limit: float = 30.0,
    workers: int = 12,
) -> list[ParetoPoint]:
    """Trace the risk-vs-cost Pareto frontier by the epsilon-constraint method.

    Parameters
    ----------
    n_points:    number of ``eps_cost`` values swept across ``[C_lo, C_hi]``
                 (inclusive endpoints). Dominated results are dropped afterwards,
                 so the returned list is usually shorter.
    time_limit:  wall-clock seconds per CP-SAT solve.
    workers:     CP-SAT search workers.

    Returns
    -------
    list[ParetoPoint]
        Non-dominated points sorted by ``cost`` ascending; ``risk`` is strictly
        decreasing across the list. Empty only if the instance is infeasible.
    """
    rm = risk_model or RiskModel()

    # High-cost / low-risk extreme: unconstrained min-risk solve.
    anchor = solve_cpsat(inst, rm, time_limit=time_limit, workers=workers)
    if not anchor.is_usable or anchor.schedule is None:
        log.warning("pareto_frontier: base solve not usable (status=%s); "
                    "no frontier", anchor.status)
        return []
    anchor_score = score_schedule(inst, anchor.schedule, rm)
    c_hi = anchor_score.cost

    # Low-cost extreme: minimum cost that stays feasible.
    c_lo = _min_feasible_cost(inst, rm, c_hi, time_limit=time_limit, workers=workers)
    log.info("pareto_frontier: cost range [C_lo=%d, C_hi=%d], sweeping %d eps points",
             c_lo, c_hi, n_points)

    # Build the eps sweep across [C_lo, C_hi]. Guard the degenerate zero-width
    # range (mandated/forced set == everything) so we emit one point, not n.
    eps_values = _sweep(c_lo, c_hi, n_points)

    raw: list[ParetoPoint] = []
    for eps in eps_values:
        # Reuse the anchor for the top of the range instead of re-solving it.
        if eps >= c_hi:
            res = anchor
        else:
            res = solve_cpsat(inst, rm, eps_cost=eps, time_limit=time_limit, workers=workers)
        if res.status == INFEASIBLE or not res.is_usable or res.schedule is None:
            # eps below the feasibility floor, or unresolved — skip this point.
            if res.status != INFEASIBLE:
                log.debug("pareto_frontier: skipping eps=%d (status=%s)", eps, res.status)
            continue
        sc = score_schedule(inst, res.schedule, rm)
        raw.append(ParetoPoint(cost=sc.cost, risk=sc.risk,
                               schedule=dict(res.schedule), status=res.status))

    return _skyline(raw)


def _sweep(c_lo: int, c_hi: int, n_points: int) -> list[int]:
    """Evenly spaced integer eps caps over ``[c_lo, c_hi]`` inclusive.

    Collapses to a single value when the range is zero-width, and de-duplicates
    when ``n_points`` exceeds the number of distinct integers in the range.
    """
    n = max(1, n_points)
    if c_hi <= c_lo or n == 1:
        return [c_hi]
    span = c_hi - c_lo
    vals = sorted({c_lo + round(span * k / (n - 1)) for k in range(n)})
    return vals


def _skyline(points: list[ParetoPoint]) -> list[ParetoPoint]:
    """Drop dominated points, leaving a strict risk-vs-cost skyline.

    Sort by ``(cost asc, risk asc)`` and keep a point only if its risk is strictly
    below the best (lowest) risk seen at any lower-or-equal cost. The result has
    strictly increasing cost and strictly decreasing risk, so each retained point
    is genuinely non-dominated: you cannot get its risk for less cost, nor less
    risk for its cost. Ties in cost keep only the lowest-risk variant.
    """
    if not points:
        return []
    ordered = sorted(points, key=lambda p: (p.cost, p.risk))
    frontier: list[ParetoPoint] = []
    best_risk: int | None = None
    for p in ordered:
        if best_risk is None or p.risk < best_risk:
            # Strictly better risk than anything cheaper -> it's on the frontier.
            # If a previous kept point shares this exact cost, replace it (this one
            # has lower risk because of the secondary sort key).
            if frontier and frontier[-1].cost == p.cost:
                frontier[-1] = p
            else:
                frontier.append(p)
            best_risk = p.risk
    return frontier
