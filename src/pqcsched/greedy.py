"""Greedy risk-ranking baselines — the vendor status quo we measure against.

Every commercial PQC platform prioritizes qualitatively: score risk, "migrate
highest-risk-first" under capacity. We implement the family of such heuristics,
all respecting earliest-start, precedence, per-period budget, and co-migration
clusters, then score each on the *same* objective as the MILP (via
:func:`pqcsched.score.score_schedule`). The optimal-vs-each-baseline gap is the
core experimental result (RQ2).

Clusters are handled by collapsing co-migrating assets into a single union-find
*group* that is scheduled as a unit, so a greedy can never accidentally split a
clustered pair. A greedy may still paint itself into a corner and miss a mandated
deadline — that is a real failure mode of greedy, surfaced honestly by the
scorer's ``deadline_violations`` rather than hidden.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .model import Instance, Schedule
from .risk import RiskModel

BASELINES = ("highest_risk", "risk_per_cost", "edf", "spt", "random")

_BIG = 1 << 30


@dataclass(slots=True)
class _Group:
    gid: str
    members: list[str]
    cost: int
    earliest: int
    deadline: int | None
    total_risk: int


def _union_find_groups(inst: Instance, rm: RiskModel) -> list[_Group]:
    """Collapse co-migration clusters into groups scheduled as a unit."""
    by_id = inst.by_id()
    parent: dict[str, str] = {a.id: a.id for a in inst.assets}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    for i, j in inst.clusters:
        if i in parent and j in parent:
            union(i, j)

    members: dict[str, list[str]] = {}
    for a in inst.assets:
        members.setdefault(find(a.id), []).append(a.id)

    groups: list[_Group] = []
    for root, mem in members.items():
        assets = [by_id[m] for m in mem]
        # A group can only migrate once *all* members are feasible (max earliest),
        # and must respect the tightest member deadline (min deadline).
        earliest = max(x.earliest for x in assets)
        deadlines = [x.deadline for x in assets if x.deadline is not None]
        deadline = min(deadlines) if deadlines else None
        groups.append(
            _Group(
                gid=root,
                members=sorted(mem),
                cost=sum(x.cost for x in assets),
                earliest=earliest,
                deadline=deadline,
                total_risk=sum(rm.asset_total_risk(x, inst) for x in assets),
            )
        )
    # deterministic order
    groups.sort(key=lambda g: g.gid)
    return groups


def _key_fn(baseline: str, seed: int):
    """Return ``key(group) -> sortable`` where higher == migrate sooner."""
    if baseline == "highest_risk":
        return lambda g: g.total_risk
    if baseline == "risk_per_cost":
        return lambda g: g.total_risk / max(g.cost, 1)
    if baseline == "edf":  # earliest-deadline-first
        return lambda g: -(g.deadline if g.deadline is not None else _BIG)
    if baseline == "spt":  # shortest-processing-time / lowest-cost-first
        return lambda g: -g.cost
    if baseline == "random":
        rng = random.Random(seed)
        scores: dict[str, float] = {}

        def key(g, _scores=scores, _rng=rng):
            if g.gid not in _scores:
                _scores[g.gid] = _rng.random()
            return _scores[g.gid]

        return key
    raise ValueError(f"unknown baseline {baseline!r}")


def greedy_current_risk(inst: Instance, risk_model: RiskModel | None = None) -> Schedule:
    """A stronger, HNDL-AWARE greedy: at each period migrate the eligible group
    with the highest *current* per-period residual risk ``r_{i,t}`` (not static
    total risk). This captures the optimizer's key insight — defer assets whose
    HNDL risk has not yet activated, fix what is bleeding now — so it is the fair
    sophisticated baseline. The optimal-vs-this gap isolates the value that
    *remains* after a smart practitioner accounts for migration timing. Not one of
    the five standard vendor baselines (`BASELINES`); evaluated separately.
    """
    rm = risk_model or RiskModel()
    groups = _union_find_groups(inst, rm)
    by_id = inst.by_id()
    g_of = {m: g.gid for g in groups for m in g.members}
    preds_by_asset = inst.predecessors()
    pred_groups: dict[str, set[str]] = {}
    for g in groups:
        ext = set()
        for m in g.members:
            for j in preds_by_asset.get(m, []):
                gj = g_of.get(j)
                if gj is not None and gj != g.gid:
                    ext.add(gj)
        pred_groups[g.gid] = ext
    by_gid = {g.gid: g for g in groups}
    done_group: dict[str, int] = {}
    schedule: Schedule = {}
    pending = set(by_gid)
    for t in range(inst.T):
        b = inst.budget[t]

        def cur_risk(g, _t=t):
            return sum(rm.int_weight(by_id[m], _t, inst.t_crqc) for m in g.members)

        while True:
            # sorted(pending) — deterministic iteration (a set of string gids
            # iterates in hash-seed-dependent order, which would make the random
            # baseline irreproducible across processes).
            elig = [by_gid[gid] for gid in sorted(pending)
                    if by_gid[gid].earliest <= t and by_gid[gid].cost <= b
                    and all(pg in done_group and done_group[pg] <= t for pg in pred_groups[gid])]
            if not elig:
                break
            g = max(elig, key=lambda gg: (cur_risk(gg), gg.total_risk, gg.gid))
            done_group[g.gid] = t
            for m in g.members:
                schedule[m] = t
            b -= g.cost
            pending.discard(g.gid)
    return schedule


def greedy_schedule(
    inst: Instance,
    baseline: str = "highest_risk",
    risk_model: RiskModel | None = None,
    *,
    seed: int = 0,
) -> Schedule:
    """Produce a schedule by the named greedy heuristic.

    Sweeps periods left to right; within each period repeatedly migrates the
    best-scoring eligible group that still fits the remaining budget, until none
    fit. Eligibility = all members past their earliest period, all cross-group
    dependencies already migrated by this period (so dependency chains can
    complete within one period when budget allows, matching the MILP's
    capability), and the group cost fits the remaining budget.
    """
    if baseline == "current_risk":
        return greedy_current_risk(inst, risk_model)
    rm = risk_model or RiskModel()
    groups = _union_find_groups(inst, rm)
    keyfn = _key_fn(baseline, seed)

    # asset -> group, and group -> external predecessor groups
    g_of: dict[str, str] = {m: g.gid for g in groups for m in g.members}
    preds_by_asset = inst.predecessors()
    pred_groups: dict[str, set[str]] = {}
    for g in groups:
        ext: set[str] = set()
        for m in g.members:
            for j in preds_by_asset.get(m, []):
                gj = g_of.get(j)
                if gj is not None and gj != g.gid:
                    ext.add(gj)
        pred_groups[g.gid] = ext

    by_gid = {g.gid: g for g in groups}
    done_group: dict[str, int] = {}   # gid -> period migrated
    schedule: Schedule = {}

    def deps_ready(g: _Group, t: int) -> bool:
        return all(
            (pg in done_group and done_group[pg] <= t) for pg in pred_groups[g.gid]
        )

    pending = set(by_gid.keys())
    for t in range(inst.T):
        b = inst.budget[t]
        while True:
            elig = [
                by_gid[gid]
                for gid in sorted(pending)   # deterministic (sets of str gids hash-order)
                if by_gid[gid].earliest <= t
                and by_gid[gid].cost <= b
                and deps_ready(by_gid[gid], t)
            ]
            if not elig:
                break
            # highest score wins; gid breaks ties deterministically
            g = max(elig, key=lambda gg: (keyfn(gg), gg.gid))
            done_group[g.gid] = t
            for m in g.members:
                schedule[m] = t
            b -= g.cost
            pending.discard(g.gid)

    return schedule
