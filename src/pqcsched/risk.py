"""HNDL-aware, time-integrated risk model.

The residual risk of leaving asset ``i`` unmigrated during period ``t`` is
``r_{i,t}``. It is *harvest-now-decrypt-later* (HNDL) aware: data encrypted in
period ``t`` stays sensitive until ``t + shelf_life``; if that window reaches the
projected cryptographically-relevant-quantum-computer period ``t_crqc``, the
asset is fully at risk in period ``t``; otherwise it carries only a small
residual.

Every weight is an **integer** so the CP-SAT objective and the shared scorer are
bit-identical (see :mod:`pqcsched.score`). The model *form* is deliberately a
single, explicit, parameterized choice so it can be sensitivity-tested (RQ in
``PROJECT_BRIEF.md`` §8); the default is the step form from §10.2 of the brief.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Asset, Instance


@dataclass(frozen=True)
class RiskModel:
    """Parameterized residual-risk weighting.

    Parameters
    ----------
    residual_factor:
        Fraction of full criticality carried when the asset's HNDL window does
        *not* reach the CRQC period. Default 0.1 (documented, sensitivity-tested).
    form:
        ``"step"``   — full criticality if at risk, else ``residual_factor`` (§10.2).
        ``"linear"`` — risk ramps with how far the HNDL window overshoots t_crqc,
                       capped at full criticality (a smoother alternative for the
                       sensitivity analysis).
    residual_scale:
        Integer scale applied so ``residual_factor`` stays exactly representable
        as an integer weight (weights are computed in fixed point then divided).
        Default 1000.
    """

    residual_factor: float = 0.1
    form: str = "step"
    residual_scale: int = 1000

    def int_weight(self, asset: Asset, t: int, t_crqc: int) -> int:
        """Residual risk weight r_{i,t} (integer) for `asset` unmigrated at `t`.

        This is the single source of truth used by BOTH the solver objective and
        the scorer. Do not duplicate this logic anywhere else.
        """
        crit = asset.criticality
        # HNDL window: data encrypted at t is sensitive through t + shelf_life.
        window_end = t + asset.shelf_life
        if self.form == "step":
            if window_end >= t_crqc:
                return crit
            return (crit * int(round(self.residual_factor * self.residual_scale))) // self.residual_scale
        elif self.form == "linear":
            # Full risk once the window reaches t_crqc; below that, risk ramps
            # linearly with proximity over a one-shelf-life lead-in, floored at
            # the residual factor. Kept in integer fixed point.
            if window_end >= t_crqc:
                return crit
            lead = max(asset.shelf_life, 1)
            # proximity in [0, 1): how close window_end is to t_crqc
            deficit = t_crqc - window_end
            prox_num = max(0, lead - deficit)  # closer -> larger
            base = int(round(self.residual_factor * self.residual_scale))
            ramp = ((self.residual_scale - base) * prox_num) // lead
            return (crit * (base + ramp)) // self.residual_scale
        else:
            raise ValueError(f"unknown risk form: {self.form!r}")

    def asset_total_risk(self, asset: Asset, inst: Instance) -> int:
        """Total exposure if `asset` is never migrated (sum over all periods).

        Used as the natural priority score for greedy baselines so that greedy
        and the MILP rank risk on the *same* underlying weights.
        """
        return sum(self.int_weight(asset, t, inst.t_crqc) for t in range(inst.T))
