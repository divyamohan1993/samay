"""Real-world case-study scenarios.

Currently: a stylized **India Digital Public Infrastructure (DPI)** estate
(Aadhaar / UPI / DigiLocker / eSign / CCA PKI), modelled from PUBLIC architecture
descriptions (see ``research/cbom-and-dpi.md``) — NOT internal or proprietary
data. It exercises the optimizer on a realistic, dependency-rich estate with a
genuine HNDL marquee (the RSA-2048-wrapped Aadhaar PID session key) and real
regulatory pressure (CCA / NPCI / UIDAI deadlines).

The estate (``benchmark/india_dpi.json``) carries criticality, exposure,
shelf-life class, dependencies, clusters, earliest availability and mandated
deadlines, but — like a real CBOM/inventory — it does NOT carry *migration
effort* or *budget*. Those come from a DOCUMENTED default model here (effort by
asset kind; uniform budget at a stated tightness), exactly as the brief
prescribes for fields an inventory lacks. Periods are QUARTERS (the estate spans
2026Q3..2030Q4); this finer resolution suits a concrete organisational roadmap
(the synthetic study uses annual periods). The model itself is period-agnostic.
"""

from __future__ import annotations

import json
import math
import os

from .model import Asset, Instance

# shelf-life class -> quarters (HNDL horizon). Ephemeral TLS sessions vs
# long-lived signed records / wrapped long-term secrets.
SHELF_QUARTERS = {"none": 2, "short": 4, "med": 40, "long": 100}

# the estate rates criticality on a 1..5 tier; scale to the model's ~[1,100].
CRIT_SCALE = 18
EXPOSURE_BUMP = 10   # internet-facing assets carry extra exposure

# Default migration-effort model (the estate/CBOM lacks effort). Assigned by
# asset kind from the crypto-usage description. Documented + applied uniformly.
_COST_RULES = [
    (("root", "trust anchor"), 14),          # root CA rotation — estate-wide blast radius
    (("licensed-ca", "licensed ca", "cert-signing"), 12),
    (("hsm",), 11),                           # HSM-held keys / PIN processing
    (("key", "wrap", "tokenization", "pin"), 9),
    (("xml-dsig", "signing", "signature", "signer", "dsc", " sig"), 7),
    (("auth api", "e-kyc", "ekyc", "endpoint", "switch tls"), 6),
    (("tls", "client tls", "portal"), 5),
    (("cdn", "edge"), 3),
]
_DEFAULT_COST = 6


def _effort(usage: str) -> int:
    u = usage.lower()
    for keys, cost in _COST_RULES:
        if any(k in u for k in keys):
            return cost
    return _DEFAULT_COST


def india_dpi_instance(
    path: str | None = None,
    *,
    t_crqc: int = 30,            # CRQC ~2034 in quarter-index from 2026Q3 (aggressive end of GRI range)
    budget_tightness: float = 0.55,
) -> Instance:
    """Build the India-DPI case-study Instance from the public-architecture estate.

    t_crqc default 30 (~2034) places the CRQC beyond the 2026-2030 planning
    horizon, so near-term migration is deadline-driven while long-lived secrets
    (HSM keys, the PID-wrap pubkey, bank key-wrap) carry full HNDL risk — the
    realistic interplay this case study is meant to show.
    """
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        # prefer the committed benchmark copy; fall back to the research artifact
        for cand in (
            os.path.join(here, "..", "..", "benchmark", "india_dpi.json"),
            os.path.join(here, "..", "..", "research", "dpi-estate.json"),
        ):
            if os.path.exists(cand):
                path = cand
                break
    if path is None or not os.path.exists(path):
        raise FileNotFoundError("india_dpi estate json not found (benchmark/india_dpi.json)")

    with open(path) as fh:
        data = json.load(fh)

    T = int(data["horizon_T"])
    assets: list[Asset] = []
    for a in data["assets"]:
        if not a.get("quantum_vulnerable", True):
            continue   # consume only quantum-vulnerable usages as decision assets
        crit = min(100, a["criticality"] * CRIT_SCALE + (EXPOSURE_BUMP if a.get("internet_facing") else 0))
        shelf = SHELF_QUARTERS.get(a.get("shelf_life_tier", "med"), 40)
        cost = _effort(a.get("crypto_usage", ""))
        deadline = int(a["deadline"]) if a.get("mandated") and a.get("deadline") is not None else None
        earliest = int(a.get("earliest", 0))
        if deadline is not None:
            deadline = max(deadline, earliest)  # keep self-consistent
        assets.append(Asset(id=a["id"], criticality=int(crit), shelf_life=int(shelf),
                            cost=int(cost), earliest=earliest, deadline=deadline))

    kept = {x.id for x in assets}
    deps = [(j, i) for j, i in data.get("deps_precedence_j_to_i", []) if j in kept and i in kept]
    clusters = [(x, y) for x, y in data.get("co_migration_clusters", []) if x in kept and y in kept]

    total = sum(x.cost for x in assets)
    max_cost = max(x.cost for x in assets)
    tight = min(max(budget_tightness, 1e-3), 1.0)
    per = max(math.ceil(total / tight / T), max_cost)
    budget = [per] * T

    return Instance(
        assets=assets, T=T, budget=budget, deps=deps, clusters=clusters,
        t_crqc=t_crqc,
        meta={
            "scenario": "india_dpi",
            "period_unit": "quarter", "horizon": data.get("period_index_note", ""),
            "source": "research/cbom-and-dpi.md (public architecture; not internal data)",
            "stats": {"n_assets": len(assets), "n_deps": len(deps),
                      "n_clusters": len(clusters),
                      "n_mandated": sum(1 for x in assets if x.deadline is not None),
                      "total_cost": total, "per_period_budget": per,
                      "realized_tightness": round(total / (T * per), 4)},
            "effort_model": "default-by-asset-kind (estate carries no migration effort)",
        },
    )
