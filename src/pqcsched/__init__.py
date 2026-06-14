"""SAMAY / pqcsched — provably optimal scheduling for post-quantum crypto migration.

Public API (stable; the experiment harness, CLI, and tests build on these):

    Instance, Asset            — the data model
    RiskModel                  — HNDL-aware residual-risk weighting
    score_schedule             — the single shared scorer (the linchpin)
    solve_cpsat                — CP-SAT exact solver (primary)
    greedy_schedule, BASELINES — the greedy risk-ranking baselines
    generate, GenParams        — the synthetic-estate benchmark generator
"""

from __future__ import annotations

from .model import Asset, Instance, Schedule
from .risk import RiskModel
from .score import ScheduleScore, score_schedule, objective_gap
from .result import SolveResult, OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN
from .solve_cpsat import solve_cpsat
from .greedy import greedy_schedule, greedy_current_risk, BASELINES
from .generate import generate, GenParams, tiny_instance

__version__ = "0.1.0"

__all__ = [
    "Asset", "Instance", "Schedule",
    "RiskModel",
    "ScheduleScore", "score_schedule", "objective_gap",
    "SolveResult", "OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN",
    "solve_cpsat",
    "greedy_schedule", "greedy_current_risk", "BASELINES",
    "generate", "GenParams", "tiny_instance",
    "__version__",
]
