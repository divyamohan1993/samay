"""Core data model for SAMAY / pqcsched.

A cryptographic estate is a set of quantum-vulnerable *assets* (cryptographic
usages) with a dependency graph, scheduled over a horizon of discrete periods
``t in {0, ..., T-1}``.

Design decision: every quantity that enters the objective or a constraint
(``criticality``, ``cost``, ``budget``) is an **integer**. CP-SAT works in
integers; keeping risk points / person-days / per-period budget integral from
the start removes all float-scaling error and makes the solver objective and the
shared scorer agree *exactly* (see :mod:`pqcsched.score`). ``perf_penalty`` is a
float because it never enters the integer objective; it is only used by the
optional coexistence-budget constraint and reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import orjson


@dataclass(slots=True)
class Asset:
    """A single quantum-vulnerable cryptographic usage (a decision variable).

    Attributes
    ----------
    id:           unique identifier.
    criticality:  exposure/impact weight (integer "risk points"). Drives risk.
    shelf_life:   periods the protected data must stay secret (HNDL horizon).
    cost:         migration effort (integer person-days / normalized units).
    perf_penalty: PQC/hybrid overhead (latency/handshake/bandwidth); optional.
    earliest:     earliest feasible period e_i (PQC support availability).
    deadline:     mandated regulatory deadline D_i (None = unmandated).
    label:        human-readable name for roadmaps/UI (display only; defaults to id).
    kind:         asset kind for display (certificate | key | protocol | algorithm).
    """

    id: str
    criticality: int
    shelf_life: int
    cost: int
    perf_penalty: float = 0.0
    earliest: int = 0
    deadline: int | None = None
    label: str | None = None
    kind: str | None = None

    def __post_init__(self) -> None:
        # Integrality is load-bearing for solver/scorer parity — enforce it.
        if not isinstance(self.criticality, int):
            self.criticality = int(round(self.criticality))
        if not isinstance(self.cost, int):
            self.cost = int(round(self.cost))
        if not isinstance(self.shelf_life, int):
            self.shelf_life = int(round(self.shelf_life))
        if not isinstance(self.earliest, int):
            self.earliest = int(round(self.earliest))
        if self.deadline is not None and not isinstance(self.deadline, int):
            self.deadline = int(round(self.deadline))


@dataclass(slots=True)
class Instance:
    """A scheduling instance.

    Attributes
    ----------
    assets:   the vulnerable decision assets.
    T:        horizon length (number of periods).
    budget:   per-period migration capacity B_t (length T, integer units).
    deps:     directed edges ``(j, i)`` meaning "j must complete no later than
              i" (asset i cannot complete its migration before j).
    clusters: pairs ``(i, j)`` that must co-migrate in the *same* period
              (e.g. both ends of a protocol). The generator gives clustered
              assets identical ``earliest``/``deadline`` windows so a common
              period always exists.
    t_crqc:   projected period of a cryptographically-relevant quantum computer.
    meta:     provenance (generator params, seed, calibration notes).
    """

    assets: list[Asset]
    T: int
    budget: list[int]
    deps: list[tuple[str, str]] = field(default_factory=list)
    clusters: list[tuple[str, str]] = field(default_factory=list)
    t_crqc: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.budget = [int(round(b)) for b in self.budget]
        if len(self.budget) != self.T:
            raise ValueError(
                f"budget has length {len(self.budget)} but horizon T={self.T}"
            )

    # -- indexing helpers ---------------------------------------------------

    def by_id(self) -> dict[str, Asset]:
        return {a.id: a for a in self.assets}

    def predecessors(self) -> dict[str, list[str]]:
        """For each asset id, the list of asset ids it depends on (its j's)."""
        preds: dict[str, list[str]] = {a.id: [] for a in self.assets}
        for j, i in self.deps:
            preds.setdefault(i, []).append(j)
        return preds

    # -- (de)serialization --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "assets": [asdict(a) for a in self.assets],
            "T": self.T,
            "budget": self.budget,
            "deps": [list(e) for e in self.deps],
            "clusters": [list(c) for c in self.clusters],
            "t_crqc": self.t_crqc,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Instance":
        assets = [Asset(**a) for a in d["assets"]]
        return cls(
            assets=assets,
            T=int(d["T"]),
            budget=list(d["budget"]),
            deps=[tuple(e) for e in d.get("deps", [])],
            clusters=[tuple(c) for c in d.get("clusters", [])],
            t_crqc=int(d.get("t_crqc", 0)),
            meta=d.get("meta", {}),
        )

    def to_json(self, path: str | None = None) -> bytes:
        blob = orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2)
        if path is not None:
            with open(path, "wb") as fh:
                fh.write(blob)
        return blob

    @classmethod
    def from_json(cls, path: str) -> "Instance":
        with open(path, "rb") as fh:
            return cls.from_dict(orjson.loads(fh.read()))

    @classmethod
    def loads(cls, blob: bytes | str) -> "Instance":
        return cls.from_dict(orjson.loads(blob))


# A schedule is a mapping asset_id -> period it is migrated in.
# Absent key == never migrated within the horizon.
Schedule = dict[str, int]
