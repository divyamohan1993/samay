"""Solver-agnostic result type.

Every solver (CP-SAT, HiGHS, CBC, optional Gurobi) returns a :class:`SolveResult`
so the experiment harness and the scorer treat them uniformly. Critically, the
``status`` is recorded on *every* solve: the headline optimal-vs-greedy study may
only use instances proven ``OPTIMAL``; time-limited (``FEASIBLE``) solves belong
in the scalability section, never in the gap. Reporting a time-limited bound as
"optimal" would understate the true gap and is dishonest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import Schedule

# Normalized status strings (independent of any solver's native enum).
OPTIMAL = "OPTIMAL"
FEASIBLE = "FEASIBLE"
INFEASIBLE = "INFEASIBLE"
UNKNOWN = "UNKNOWN"
MODEL_INVALID = "MODEL_INVALID"


@dataclass(slots=True)
class SolveResult:
    status: str
    solver: str
    objective: int | None = None          # residual-risk objective (integer)
    best_bound: float | None = None        # solver's proven bound on the objective
    schedule: Schedule | None = None       # asset_id -> migrated period
    wall_time: float = 0.0
    eps_cost: int | None = None            # epsilon-constraint cost cap, if any
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def is_optimal(self) -> bool:
        return self.status == OPTIMAL

    @property
    def is_usable(self) -> bool:
        """True if a schedule was produced (optimal or merely feasible)."""
        return self.schedule is not None and self.status in (OPTIMAL, FEASIBLE)

    @property
    def mip_gap(self) -> float | None:
        """Relative optimality gap (objective - bound) / objective, if known."""
        if self.objective is None or self.best_bound is None:
            return None
        denom = abs(self.objective) if self.objective != 0 else 1.0
        return abs(self.objective - self.best_bound) / denom
