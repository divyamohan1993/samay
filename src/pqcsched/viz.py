"""Figures for the SAMAY / pqcsched study (matplotlib, headless).

These render the four artifacts a reader of the paper / a CISO looking at the tool
actually needs:

* :func:`roadmap_gantt`     — *what to migrate when* (the deliverable schedule).
* :func:`risk_over_time`    — *how fast each strategy retires risk* (optimal vs the
                              greedy status quo, on one axis).
* :func:`pareto_plot`       — *risk bought per rupee of budget* (the trade-off curve).
* :func:`gap_heatmap`       — *where greedy hurts most* (optimality gap across the
                              budget × deadline difficulty grid).

Design decisions:

* **Agg backend, no display.** Set before importing ``pyplot`` so the module
  imports cleanly on a headless box (the GCP VM, CI). Every function takes
  ``save: str | None`` and returns the :class:`~matplotlib.figure.Figure`; it
  writes a PNG only when ``save`` is given, so callers can compose/inspect figures
  in-process and tests can assert on a written file.
* **Risk is recomputed via the shared model, never re-derived.** Per-period
  residual risk uses :meth:`RiskModel.int_weight` with the exact "risk accrues
  strictly before the migration period" semantics of :func:`score_schedule`, so the
  area under a :func:`risk_over_time` curve equals that schedule's scored risk.
* **matplotlib only.** ``pandas`` is *not* a dependency of this project (the harness
  is stdlib + numpy by design), so :func:`gap_heatmap` reads the summary CSV with
  ``csv.DictReader`` and aggregates with numpy.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")  # headless: must precede pyplot import

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from .model import Instance, Schedule  # noqa: E402
from .risk import RiskModel  # noqa: E402

log = logging.getLogger("pqcsched.viz")

# Perceptually-ordered map from criticality -> color (low=cool, high=hot).
_CRIT_CMAP = plt.get_cmap("viridis")


def _save(fig: Figure, save: str | None) -> Figure:
    """Persist `fig` to `save` (PNG) when a path is given; always return it."""
    if save is not None:
        fig.savefig(save, dpi=150, bbox_inches="tight")
        log.info("wrote figure %s", save)
    return fig


# ---------------------------------------------------------------------------
# 1. Migration roadmap (Gantt)
# ---------------------------------------------------------------------------
def roadmap_gantt(
    inst: Instance,
    schedule: Schedule,
    *,
    max_rows: int = 60,
    save: str | None = None,
) -> Figure:
    """Gantt-style roadmap: one row per asset, a marker at its migration period.

    Rows are sorted by migration period then criticality so the visual reads as a
    wave of work across the horizon. The marker is colored by criticality (the
    risk weight the objective cares about) and each mandated asset's deadline is
    drawn as a red caret, so a slipped deadline would be visible as a bar to the
    right of its caret. Unmigrated assets get no bar (and a deadline caret if
    mandated, making the miss obvious).

    For estates larger than ``max_rows`` the highest-criticality assets are shown
    (the rest would be an unreadable hairline); the title notes the subsample so
    the figure never silently misrepresents the estate size.
    """
    assets = list(inst.assets)
    subsampled = False
    if len(assets) > max_rows:
        # Keep the assets that matter most to the objective: top criticality.
        assets = sorted(assets, key=lambda a: a.criticality, reverse=True)[:max_rows]
        subsampled = True

    # Order rows by (migration period, -criticality); unmigrated sink to the top.
    def sort_key(a):
        tau = schedule.get(a.id)
        return (tau if tau is not None else inst.T + 1, -a.criticality)

    assets = sorted(assets, key=sort_key)

    crits = [a.criticality for a in assets] or [1]
    cmin, cmax = min(crits), max(crits)
    crange = max(cmax - cmin, 1)

    fig, ax = plt.subplots(figsize=(max(8, inst.T * 0.5), max(3, len(assets) * 0.28)))

    for row, a in enumerate(assets):
        tau = schedule.get(a.id)
        if tau is not None:
            color = _CRIT_CMAP((a.criticality - cmin) / crange)
            # a unit-width bar occupying the migration period cell
            ax.barh(row, width=0.9, left=tau - 0.45, height=0.6,
                    color=color, edgecolor="black", linewidth=0.4, zorder=3)
        # earliest-availability shading (asset can't migrate before this)
        if a.earliest > 0:
            ax.barh(row, width=a.earliest, left=-0.5, height=0.6,
                    color="0.92", zorder=1)
        # mandated deadline caret
        if a.deadline is not None:
            ax.scatter(a.deadline + 0.45, row, marker="|", s=140,
                       color="crimson", linewidths=1.6, zorder=4)

    ax.set_yticks(range(len(assets)))
    ax.set_yticklabels([a.id for a in assets], fontsize=7)
    ax.set_ylim(-0.6, len(assets) - 0.4)
    ax.set_xlim(-0.6, inst.T - 0.4)
    ax.set_xticks(range(inst.T))
    ax.set_xlabel("migration period")
    ax.set_ylabel("asset")
    title = "PQC migration roadmap"
    if subsampled:
        title += f"  (top {len(assets)} of {len(inst.assets)} by criticality)"
    ax.set_title(title)
    ax.grid(axis="x", color="0.85", linewidth=0.5, zorder=0)

    # colorbar for criticality + a legend entry for the deadline caret
    sm = plt.cm.ScalarMappable(cmap=_CRIT_CMAP,
                               norm=plt.Normalize(vmin=cmin, vmax=cmax))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.025, pad=0.01)
    cbar.set_label("criticality")
    ax.legend(handles=[Patch(facecolor="crimson", label="mandated deadline")],
              loc="upper right", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    return _save(fig, save)


# ---------------------------------------------------------------------------
# 2. Residual risk over time
# ---------------------------------------------------------------------------
def _residual_risk_curve(inst: Instance, schedule: Schedule, rm: RiskModel) -> list[int]:
    """Residual risk present in each period ``t`` under ``schedule``.

    An asset contributes ``int_weight(a, t, t_crqc)`` in period ``t`` iff it has not
    yet migrated by ``t`` (migration period ``tau > t``; unmigrated ⇒ ``tau = T``).
    This is the per-period decomposition of the scorer's objective, so
    ``sum(curve) == score_schedule(inst, schedule, rm).risk`` exactly.
    """
    t_crqc = inst.t_crqc
    curve = [0] * inst.T
    for a in inst.assets:
        tau = schedule.get(a.id)
        end = tau if tau is not None else inst.T  # periods [0, end) still at risk
        for t in range(0, min(end, inst.T)):
            curve[t] += rm.int_weight(a, t, t_crqc)
    return curve


def risk_over_time(
    inst: Instance,
    schedules: dict[str, Schedule],
    rm: RiskModel,
    *,
    save: str | None = None,
) -> Figure:
    """Plot residual-risk-per-period curves for one or more named schedules.

    Pass e.g. ``{"optimal": opt_sched, "highest_risk": greedy_sched}`` to show how
    much faster the exact schedule retires risk than the greedy status quo: the
    gap *between* the curves, integrated over time, is exactly the headline
    objective gap. A dashed vertical line marks ``t_crqc`` (the projected
    quantum-computer arrival), the point past which unmigrated HNDL-exposed data is
    considered fully compromised.
    """
    fig, ax = plt.subplots(figsize=(9, 5))
    periods = list(range(inst.T))

    for name, sched in schedules.items():
        curve = _residual_risk_curve(inst, sched, rm)
        total = sum(curve)
        ax.plot(periods, curve, marker="o", markersize=4, linewidth=1.8,
                label=f"{name} (R={total})")

    if 0 <= inst.t_crqc < inst.T:
        ax.axvline(inst.t_crqc, color="crimson", linestyle="--", linewidth=1.2,
                   alpha=0.8)
        ymax = ax.get_ylim()[1]
        ax.text(inst.t_crqc, ymax * 0.98, "  t_crqc", color="crimson",
                va="top", ha="left", fontsize=9)

    ax.set_xlabel("period")
    ax.set_ylabel("residual risk in period")
    ax.set_title("Residual risk retired over time")
    ax.set_xticks(periods)
    ax.set_xlim(-0.3, inst.T - 0.7)
    ax.set_ylim(bottom=0)
    ax.grid(color="0.9", linewidth=0.5)
    ax.legend(title="schedule (R = total residual risk)", framealpha=0.9)

    fig.tight_layout()
    return _save(fig, save)


# ---------------------------------------------------------------------------
# 3. Pareto frontier (risk vs cost)
# ---------------------------------------------------------------------------
def pareto_plot(points, *, save: str | None = None) -> Figure:
    """Scatter + step line of a risk-vs-cost Pareto frontier.

    ``points`` is a list of :class:`pqcsched.pareto.ParetoPoint` (anything with
    ``.cost`` and ``.risk``). The curve is read left-to-right as "the least risk
    achievable for each budget"; its convex-ish knee is where extra budget stops
    buying much risk reduction. Proven-optimal points are filled; time-limited
    (``FEASIBLE``) points, whose risk is only an upper bound, are drawn hollow so
    they are never mistaken for exact.
    """
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    pts = sorted(points, key=lambda p: p.cost)

    if pts:
        costs = [p.cost for p in pts]
        risks = [p.risk for p in pts]
        ax.plot(costs, risks, color="0.4", linewidth=1.5, zorder=1)

        opt = [p for p in pts if getattr(p, "status", "OPTIMAL") == "OPTIMAL"]
        nonopt = [p for p in pts if getattr(p, "status", "OPTIMAL") != "OPTIMAL"]
        if opt:
            ax.scatter([p.cost for p in opt], [p.risk for p in opt], s=70,
                       color="#1f77b4", edgecolor="black", linewidth=0.6,
                       zorder=3, label="proven optimal")
        if nonopt:
            ax.scatter([p.cost for p in nonopt], [p.risk for p in nonopt], s=70,
                       facecolor="none", edgecolor="#1f77b4", linewidth=1.4,
                       zorder=3, label="feasible (upper bound)")
        # annotate the two extremes (cheapest and lowest-risk)
        ax.annotate(f"min cost\n({costs[0]}, {risks[0]})",
                    xy=(costs[0], risks[0]), xytext=(6, 8),
                    textcoords="offset points", fontsize=8, color="0.3")
        ax.annotate(f"min risk\n({costs[-1]}, {risks[-1]})",
                    xy=(costs[-1], risks[-1]), xytext=(6, 8),
                    textcoords="offset points", fontsize=8, color="0.3")

    ax.set_xlabel("total migration cost (person-days)")
    ax.set_ylabel("residual risk (objective)")
    ax.set_title("Risk vs cost Pareto frontier")
    ax.grid(color="0.9", linewidth=0.5)
    if pts:  # every non-empty frontier has at least one labelled scatter series
        ax.legend(framealpha=0.9)

    fig.tight_layout()
    return _save(fig, save)


# ---------------------------------------------------------------------------
# 4. Optimality-gap heatmap across the difficulty grid
# ---------------------------------------------------------------------------
def gap_heatmap(
    summary_csv: str,
    *,
    x: str = "budget_tightness",
    y: str = "deadline_pressure",
    metric: str = "highest_risk_gap_mean",
    save: str | None = None,
) -> Figure:
    """Heatmap of a summary metric across two grid axes.

    Reads the per-cell summary written by
    :func:`pqcsched.experiment.summarize` (columns include ``size``, ``T``,
    ``dep_density``, ``budget_tightness``, ``deadline_pressure`` and, per baseline,
    ``<baseline>_gap_mean``). The chosen ``metric`` is averaged (``np.nanmean``)
    over every axis *except* ``x`` and ``y``, so the cell at ``(x_i, y_j)`` is the
    mean metric over all summary rows sharing those two coordinates. Empty metric
    cells (``""`` — e.g. a cell with no proven-optimal instances) are treated as
    missing, not zero.

    No pandas: the harness is deliberately stdlib + numpy, and this stays
    consistent so the figures run anywhere the experiment does.
    """
    with open(summary_csv, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"summary CSV {summary_csv!r} has no rows")
    for col in (x, y, metric):
        if col not in rows[0]:
            raise KeyError(f"column {col!r} not in summary CSV "
                           f"(have: {sorted(rows[0].keys())})")

    def _num(s: str) -> float:
        s = (s or "").strip()
        if s == "":
            return float("nan")
        return float(s)

    # bucket metric values by (x_value, y_value)
    buckets: dict[tuple[float, float], list[float]] = defaultdict(list)
    for r in rows:
        buckets[(_num(r[x]), _num(r[y]))].append(_num(r[metric]))

    xs = sorted({k[0] for k in buckets})
    ys = sorted({k[1] for k in buckets})
    grid = np.full((len(ys), len(xs)), np.nan)
    for (xi, xv) in enumerate(xs):
        for (yi, yv) in enumerate(ys):
            vals = buckets.get((xv, yv))
            if vals:
                arr = np.array(vals, dtype=float)
                if np.isfinite(arr).any():
                    grid[yi, xi] = np.nanmean(arr)

    fig, ax = plt.subplots(figsize=(max(5, len(xs) * 1.0 + 2),
                                    max(4, len(ys) * 0.8 + 2)))
    cmap = plt.get_cmap("magma_r").with_extremes(bad="0.85")  # missing cells grey, not 0
    im = ax.imshow(grid, origin="lower", aspect="auto", cmap=cmap)

    ax.set_xticks(range(len(xs)))
    ax.set_xticklabels([f"{v:g}" for v in xs])
    ax.set_yticks(range(len(ys)))
    ax.set_yticklabels([f"{v:g}" for v in ys])
    ax.set_xlabel(x.replace("_", " "))
    ax.set_ylabel(y.replace("_", " "))
    ax.set_title(f"{metric.replace('_', ' ')} across {x} × {y}")

    # annotate each cell with its value (percent if it looks like a gap fraction)
    is_gap = metric.endswith("_gap_mean") or "gap" in metric
    for yi in range(len(ys)):
        for xi in range(len(xs)):
            v = grid[yi, xi]
            if np.isnan(v):
                txt = "—"
            elif is_gap:
                txt = f"{v * 100:.0f}%"
            else:
                txt = f"{v:.2g}"
            # contrast-aware text color
            norm_v = 0.0 if np.isnan(v) else im.norm(v)
            ax.text(xi, yi, txt, ha="center", va="center", fontsize=8,
                    color="white" if norm_v > 0.55 else "black")

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(metric.replace("_", " "))

    fig.tight_layout()
    return _save(fig, save)
