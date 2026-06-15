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


def _infer_kind(a: dict) -> str:
    if a.get("kind"):
        return a["kind"]
    u = (a.get("crypto_usage", "") + " " + a.get("id", "")).lower()
    if any(k in u for k in ("cert", "ca", "s/mime", "smime")):
        return "certificate"
    if any(k in u for k in ("tls", "ipsec", "ike", "protocol", "mtls", "vpn")):
        return "protocol"
    if any(k in u for k in ("key", "sign", "wrap", "hsm", "token")):
        return "key"
    return "algorithm"


def _resolve(path: str | None, *names: str) -> str:
    if path and os.path.exists(path):
        return path
    here = os.path.dirname(os.path.abspath(__file__))
    for n in names:
        cand = os.path.join(here, "..", "..", n)
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(f"estate json not found: {names}")


def estate_from_json(
    path: str,
    *,
    scenario: str = "estate",
    t_crqc: int = 30,
    budget_tightness: float = 0.55,
) -> Instance:
    """Build a schedulable :class:`Instance` from a named-estate JSON.

    The JSON lists crypto *usages* with a coarse business rating (criticality 1-5,
    shelf-life tier, internet-facing, mandated, earliest, deadline) plus a
    migration-precedence edge list and co-migration clusters. We map those to the
    integer model, attach human-readable ``label``/``kind`` for roadmaps, and size
    the per-period budget so the estate is feasible at the requested tightness.
    Periods are quarters; ``t_crqc`` beyond the horizon makes near-term migration
    deadline-driven while long-lived secrets carry full HNDL risk.
    """
    with open(path) as fh:
        data = json.load(fh)
    T = int(data["horizon_T"])
    assets: list[Asset] = []
    for a in data["assets"]:
        if not a.get("quantum_vulnerable", True):
            continue  # only quantum-vulnerable usages are decision assets
        crit = min(100, a["criticality"] * CRIT_SCALE + (EXPOSURE_BUMP if a.get("internet_facing") else 0))
        shelf = SHELF_QUARTERS.get(a.get("shelf_life_tier", "med"), 40)
        # explicit migration effort if the estate provides it; else default-by-kind
        cost = int(a["cost"]) if a.get("cost") is not None else _effort(a.get("crypto_usage", "") + " " + a.get("id", ""))
        earliest = int(a.get("earliest", 0))
        deadline = int(a["deadline"]) if a.get("mandated") and a.get("deadline") is not None else None
        if deadline is not None:
            deadline = max(deadline, earliest)
        assets.append(Asset(
            id=a["id"], criticality=int(crit), shelf_life=int(shelf), cost=int(cost),
            earliest=earliest, deadline=deadline,
            label=a.get("label") or a.get("crypto_usage") or a["id"],
            kind=_infer_kind(a),
        ))
    kept = {x.id for x in assets}
    deps = [(j, i) for j, i in data.get("deps_precedence_j_to_i", []) if j in kept and i in kept]
    clusters = [(x, y) for x, y in data.get("co_migration_clusters", []) if x in kept and y in kept]
    total = sum(x.cost for x in assets)
    max_cost = max(x.cost for x in assets)
    tight = min(max(budget_tightness, 1e-3), 1.0)
    per = max(math.ceil(total / tight / T), max_cost)
    return Instance(
        assets=assets, T=T, budget=[per] * T, deps=deps, clusters=clusters, t_crqc=t_crqc,
        meta={
            "scenario": scenario, "title": data.get("scenario", scenario),
            "blurb": data.get("blurb", ""), "period_unit": "quarter",
            "horizon": data.get("period_index_note", ""),
            "stats": {"n_assets": len(assets), "n_deps": len(deps), "n_clusters": len(clusters),
                      "n_mandated": sum(1 for x in assets if x.deadline is not None),
                      "total_cost": total, "per_period_budget": per,
                      "realized_tightness": round(total / (T * per), 4)},
            "effort_model": "default-by-asset-kind (an estate/CBOM carries no migration effort)",
        },
    )


def india_dpi_instance(path: str | None = None, *, t_crqc: int = 30,
                       budget_tightness: float = 0.55) -> Instance:
    """India Digital Public Infrastructure case-study estate (public architecture)."""
    p = _resolve(path, "benchmark/india_dpi.json", "research/dpi-estate.json")
    return estate_from_json(p, scenario="india_dpi", t_crqc=t_crqc, budget_tightness=budget_tightness)


def enterprise_instance(path: str | None = None, *, t_crqc: int = 30,
                        budget_tightness: float = 0.55) -> Instance:
    """Stylised mid-size enterprise estate (PKI, edge TLS, identity, HSM secrets)."""
    p = _resolve(path, "benchmark/enterprise.json")
    return estate_from_json(p, scenario="enterprise", t_crqc=t_crqc, budget_tightness=budget_tightness)


# Registry the API/UI use to offer concrete starting points.
SAMPLES = {
    "enterprise": ("Mid-size enterprise", enterprise_instance),
    "india_dpi": ("India Digital Public Infrastructure", india_dpi_instance),
}


def sample_instance(name: str, **kw) -> Instance:
    if name not in SAMPLES:
        raise KeyError(f"unknown sample {name!r}; choose from {list(SAMPLES)}")
    return SAMPLES[name][1](**kw)
