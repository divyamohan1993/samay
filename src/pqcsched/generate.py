"""Synthetic cryptographic-estate generator — the reusable benchmark.

No public benchmark exists for PQC migration *scheduling*, so the generator is
itself a contribution. It produces realistic assets + a dependency DAG +
cost/risk/deadline/shelf-life distributions, controllable along the four axes the
study sweeps (``PROJECT_BRIEF.md`` §8):

    size · dependency density · budget tightness · deadline pressure

plus shelf-life mix, co-migration clusters, and delayed PQC availability. The
numeric calibration constants live in :data:`CALIB` and ``configs/gen.yaml`` and
are documented with their public sources in ``PROGRESS.md`` / ``REPORT.md`` — do
not tune them to flatter the optimizer; that would invalidate the study.

The generator aims for feasibility by construction: dependency edges only go
forward in a random topological order (acyclic), ``earliest`` is propagated along
dependencies, deadlines are clamped at/after ``earliest``, and aggregate budget
covers aggregate cost for ``budget_tightness <= 1``. Residual infeasibility (rare,
from per-period bottlenecks) is detected by the solver and handled by the
experiment harness, which logs the rate rather than hiding it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .model import Asset, Instance


# ---------------------------------------------------------------------------
# Calibration constants (see PROGRESS.md for sources; refined by research pass).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Calibration:
    # Criticality (exposure/impact "risk points"), heavy-tailed: most assets
    # moderate, a few internet-facing crown jewels. Lognormal then clipped.
    crit_log_mean: float = 3.0
    crit_log_sigma: float = 0.8
    crit_min: int = 1
    crit_max: int = 100
    # Migration effort (person-days), lognormal, clipped.
    cost_log_mean: float = 1.6
    cost_log_sigma: float = 0.7
    cost_min: int = 1
    cost_max: int = 40
    # Shelf-life (HNDL horizon, in periods): transient / medium / long-lived.
    # Probabilities reflect a mixed estate (ephemeral TLS sessions vs long-lived
    # signed/records data). Calibrated qualitatively from HNDL literature.
    shelf_life_tiers: tuple = ((2, 0.40), (8, 0.40), (20, 0.20))
    # PQC/hybrid performance penalty (handshake/bandwidth overhead), in [0,1].
    perf_min: float = 0.0
    perf_max: float = 0.6


CALIB = Calibration()


@dataclass
class GenParams:
    size: int = 200
    T: int = 40
    dep_density: float = 0.3        # 0..1 ; controls expected in-degree
    budget_tightness: float = 0.6   # (0,1] ; higher == less capacity == harder
    deadline_pressure: float = 0.3  # 0..1 ; more mandates + earlier deadlines
    cluster_frac: float = 0.10      # fraction of assets placed in co-migration pairs
    delayed_frac: float = 0.15      # fraction with earliest > 0 (late PQC support)
    t_crqc: int = 28                # projected CRQC period (sensitivity-tested)
    max_in_degree: int = 4          # cap dependency in-degree (realistic, keeps DAG sane)
    seed: int = 0
    calib: Calibration = field(default_factory=lambda: CALIB)


def _draw_shelf_life(rng: np.random.Generator, tiers: tuple) -> int:
    vals = [t[0] for t in tiers]
    probs = np.array([t[1] for t in tiers], dtype=float)
    probs /= probs.sum()
    return int(rng.choice(vals, p=probs))


def generate(params: GenParams | None = None, **overrides) -> Instance:
    """Generate one synthetic estate instance."""
    p = params or GenParams()
    if overrides:
        p = GenParams(**{**p.__dict__, **overrides})
    c = p.calib
    rng = np.random.default_rng(p.seed)
    n = p.size

    # --- asset attributes -------------------------------------------------
    crit = np.clip(np.round(rng.lognormal(c.crit_log_mean, c.crit_log_sigma, n)),
                   c.crit_min, c.crit_max).astype(int)
    cost = np.clip(np.round(rng.lognormal(c.cost_log_mean, c.cost_log_sigma, n)),
                   c.cost_min, c.cost_max).astype(int)
    shelf = np.array([_draw_shelf_life(rng, c.shelf_life_tiers) for _ in range(n)])
    perf = rng.uniform(c.perf_min, c.perf_max, n)

    # earliest period: most 0; a delayed fraction gets late PQC support.
    earliest = np.zeros(n, dtype=int)
    n_delayed = int(round(p.delayed_frac * n))
    if n_delayed:
        idx = rng.choice(n, size=n_delayed, replace=False)
        earliest[idx] = rng.integers(1, max(2, p.T // 4), size=n_delayed)

    # --- dependency DAG: edges go forward in a random topological order ----
    order = rng.permutation(n)
    pos = np.empty(n, dtype=int)
    pos[order] = np.arange(n)
    deps: list[tuple[str, str]] = []
    ids = [f"a{k}" for k in range(n)]
    # Expected in-degree scales with dep_density; capped.
    for v_rank in range(1, n):
        v = order[v_rank]
        # Each of up to `max_in_degree` candidate predecessor slots is filled
        # with probability `dep_density`; expected in-degree grows with density,
        # capped at max_in_degree and at the number of earlier assets available.
        n_slots = min(v_rank, p.max_in_degree)
        n_pred = int(rng.binomial(n_slots, p.dep_density))
        if n_pred <= 0:
            continue
        cand = order[:v_rank]
        chosen = rng.choice(cand, size=min(n_pred, len(cand)), replace=False)
        for u in np.atleast_1d(chosen):
            deps.append((ids[int(u)], ids[int(v)]))

    # propagate earliest along dependencies (a successor cannot start before its
    # predecessors are feasible) -> keeps precedence + earliest mutually feasible.
    succ: dict[int, list[int]] = {k: [] for k in range(n)}
    for (j, i) in deps:
        succ[int(j[1:])].append(int(i[1:]))
    for v in order:  # topo order
        for w in succ[int(v)]:
            if earliest[w] < earliest[v]:
                earliest[w] = earliest[v]

    # --- co-migration clusters (pairs with unified windows) ---------------
    clusters: list[tuple[str, str]] = []
    dep_pairs = {(j, i) for (j, i) in deps} | {(i, j) for (j, i) in deps}
    n_pairs = int(round(p.cluster_frac * n / 2))
    if n_pairs:
        pool = list(rng.permutation(n))
        used: set[int] = set()
        while n_pairs > 0 and len(pool) >= 2:
            a_ = pool.pop()
            b_ = pool.pop()
            if a_ in used or b_ in used:
                continue
            if (ids[a_], ids[b_]) in dep_pairs:  # don't cluster a dependency pair
                continue
            # unify windows so a common migration period always exists
            e = int(max(earliest[a_], earliest[b_]))
            earliest[a_] = earliest[b_] = e
            clusters.append((ids[a_], ids[b_]))
            used.add(a_); used.add(b_)
            n_pairs -= 1

    # --- deadlines: mandated fraction + tightness from deadline_pressure ---
    deadline = np.full(n, -1, dtype=int)  # -1 sentinel == no deadline
    mandated_frac = min(0.95, 0.15 + 0.65 * p.deadline_pressure)
    n_mand = int(round(mandated_frac * n))
    if n_mand:
        mand_idx = rng.choice(n, size=n_mand, replace=False)
        lo_base = int(round(p.T * (1.0 - 0.8 * p.deadline_pressure)))
        for k in mand_idx:
            lo = max(int(earliest[k]) + 1, lo_base, 1)
            hi = p.T - 1
            if lo > hi:
                lo = hi
            deadline[k] = int(rng.integers(lo, hi + 1))
    # clusters share the tightest deadline among members
    for (x, y) in clusters:
        xi, yi = int(x[1:]), int(y[1:])
        ds = [d for d in (deadline[xi], deadline[yi]) if d >= 0]
        if ds:
            deadline[xi] = deadline[yi] = min(ds)

    assets = [
        Asset(
            id=ids[k],
            criticality=int(crit[k]),
            shelf_life=int(shelf[k]),
            cost=int(cost[k]),
            perf_penalty=float(perf[k]),
            earliest=int(earliest[k]),
            deadline=(None if deadline[k] < 0 else int(deadline[k])),
        )
        for k in range(n)
    ]

    # --- per-period budget: aggregate capacity = total_cost / tightness ----
    # Feasibility floor: the per-period budget must be at least the largest single
    # asset cost, otherwise that asset can never fit in any period (structural
    # infeasibility unrelated to the scheduling difficulty we want to study). The
    # capacity term still sets tightness when n/T is large (the study regime).
    total_cost = int(cost.sum())
    tightness = min(max(p.budget_tightness, 1e-3), 1.0)
    capacity_total = int(np.ceil(total_cost / tightness))
    max_cost = int(cost.max())
    per_period = max(int(np.ceil(capacity_total / p.T)), max_cost)
    budget = [per_period] * p.T
    realized_tightness = round(total_cost / (p.T * per_period), 4)

    inst = Instance(
        assets=assets,
        T=p.T,
        budget=budget,
        deps=deps,
        clusters=clusters,
        t_crqc=p.t_crqc,
        meta={
            "generator": "pqcsched.generate.generate",
            "params": {
                "size": p.size, "T": p.T, "dep_density": p.dep_density,
                "budget_tightness": p.budget_tightness,
                "deadline_pressure": p.deadline_pressure,
                "cluster_frac": p.cluster_frac, "delayed_frac": p.delayed_frac,
                "t_crqc": p.t_crqc, "max_in_degree": p.max_in_degree,
                "seed": p.seed,
            },
            "stats": {
                "n_assets": n, "n_deps": len(deps), "n_clusters": len(clusters),
                "n_mandated": int((deadline >= 0).sum()),
                "total_cost": total_cost, "per_period_budget": per_period,
                "realized_tightness": realized_tightness,
            },
        },
    )
    return inst


def tiny_instance(seed: int = 0) -> Instance:
    """A small, fast, feasible instance for smoke tests and the vertical slice."""
    return generate(GenParams(size=12, T=10, dep_density=0.3,
                              budget_tightness=0.7, deadline_pressure=0.3,
                              cluster_frac=0.2, t_crqc=7, seed=seed))
