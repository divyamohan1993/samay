"""CBOM ingest tests: CycloneDX 1.6 -> pqcsched Instance.

These pin the contract the rest of SAMAY relies on when fed a *real* estate:
the right components survive as decision assets, symmetric/hash primitives are
excluded, the dependency edges are FLIPPED correctly (a CA is a prerequisite,
i.e. appears as ``j`` in ``(j, i)`` for the leaves that depend on it), and the
resulting instance is solvable.
"""

from __future__ import annotations

import os

import pytest

from pqcsched.cbom import CbomPolicy, cbom_to_instance, from_cbom
from pqcsched.model import Instance
from pqcsched.risk import RiskModel
from pqcsched.score import score_schedule
from pqcsched.solve_cpsat import solve_cpsat
from pqcsched.result import OPTIMAL, FEASIBLE

# benchmark/sample.cbom.json lives at the repo root, two levels up from tests/.
SAMPLE = os.path.join(os.path.dirname(__file__), os.pardir, "benchmark", "sample.cbom.json")

# Expected kept (quantum-vulnerable) decision assets under the transitive reading.
EXPECTED_KEPT = {
    "crypto/algorithm/rsa-4096@1.2.840.113549.1.1.12",
    "crypto/algorithm/rsa-2048@1.2.840.113549.1.1.11",
    "crypto/algorithm/ecdh-p256@1.2.840.10045.3.1.7",
    "crypto/algorithm/ecdsa-p256@1.2.840.10045.4.3.2",
    "crypto/certificate/root-ca@sha256:cc03",
    "crypto/certificate/intermediate-ca@sha256:bb02",
    "crypto/certificate/leaf-tls@sha256:aa01",
    "crypto/certificate/leaf-docsign@sha256:dd04",
    "crypto/key/rsa-4096-rootca@1.2.840.113549.1.1.1",
    "crypto/key/rsa-2048-ica@1.2.840.113549.1.1.1",
    "crypto/key/ecdsa-p256-leaf@1.2.840.10045.2.1",
    "crypto/key/rsa-2048-docsign@1.2.840.113549.1.1.1",
    "crypto/protocol/tls@1.2",
}

# Must NOT be kept: quantum-safe-rated symmetric / hash primitives.
EXPECTED_EXCLUDED = {
    "crypto/algorithm/aes-256-gcm@2.16.840.1.101.3.4.1.46",  # nqsl=1, ae
    "crypto/algorithm/sha-384@2.16.840.1.101.3.4.2.2",       # nqsl=2, hash
}


@pytest.fixture(scope="module")
def inst() -> Instance:
    return cbom_to_instance(SAMPLE, periods=20, t_crqc=13)


def test_sample_file_ships() -> None:
    assert os.path.exists(SAMPLE), "benchmark/sample.cbom.json must ship with the package"


def test_returns_valid_instance(inst: Instance) -> None:
    assert isinstance(inst, Instance)
    assert inst.T == 20
    assert len(inst.budget) == inst.T          # model.__post_init__ enforces this
    assert inst.t_crqc == 13
    assert inst.meta["source"] == "cbom"
    assert inst.meta["period_unit"] == "year"


def test_vulnerable_assets_kept(inst: Instance) -> None:
    ids = {a.id for a in inst.assets}
    assert ids == EXPECTED_KEPT
    assert len(inst.assets) == 13


def test_symmetric_and_hash_excluded(inst: Instance) -> None:
    ids = {a.id for a in inst.assets}
    for ref in EXPECTED_EXCLUDED:
        assert ref not in ids, f"{ref} (AES/SHA, quantum-safe) must be excluded"
    assert set(inst.meta["excluded_refs"]) >= EXPECTED_EXCLUDED


def test_deps_present_and_flipped(inst: Instance) -> None:
    """``A dependsOn B`` -> edge ``(B, A)``; both endpoints must be kept assets."""
    deps = set(inst.deps)
    assert deps, "expected dependency edges between kept assets"

    kept = {a.id for a in inst.assets}
    for j, i in deps:
        assert j in kept and i in kept, "edges may only connect kept assets"

    root = "crypto/certificate/root-ca@sha256:cc03"
    ica = "crypto/certificate/intermediate-ca@sha256:bb02"
    leaf_tls = "crypto/certificate/leaf-tls@sha256:aa01"
    leaf_doc = "crypto/certificate/leaf-docsign@sha256:dd04"
    tls = "crypto/protocol/tls@1.2"

    # CA-before-leaf: the CA is the PREREQUISITE, so it is j in (j, i).
    # CBOM: intermediate-ca dependsOn root-ca  =>  (root-ca, intermediate-ca)
    assert (root, ica) in deps
    # CBOM: leaf-tls dependsOn intermediate-ca =>  (intermediate-ca, leaf-tls)
    assert (ica, leaf_tls) in deps
    # CBOM: leaf-docsign dependsOn intermediate-ca => (intermediate-ca, leaf-docsign)
    assert (ica, leaf_doc) in deps
    # CBOM: tls dependsOn leaf-tls => (leaf-tls, tls): leaf is prerequisite of protocol
    assert (leaf_tls, tls) in deps

    # The reverse (un-flipped) direction must NOT be present.
    assert (ica, root) not in deps
    assert (leaf_tls, ica) not in deps

    # predecessors(): the intermediate CA must list root-ca among its j's, and
    # each leaf must list the intermediate CA among its j's.
    preds = inst.predecessors()
    assert root in preds[ica]
    assert ica in preds[leaf_tls]
    assert ica in preds[leaf_doc]


def test_no_edges_touch_excluded(inst: Instance) -> None:
    flat = {x for edge in inst.deps for x in edge}
    assert not (flat & EXPECTED_EXCLUDED), "no edge may reference AES/SHA"


def test_policy_assigns_kinds(inst: Instance) -> None:
    by_id = inst.by_id()
    pol = CbomPolicy()

    # protocol = crown jewel: highest criticality, short shelf-life.
    tls = by_id["crypto/protocol/tls@1.2"]
    assert tls.criticality == pol.crit_protocol
    assert tls.shelf_life == pol.shelf_protocol

    # root CA cert: CA criticality + long (decade-scale) shelf-life so HNDL fires.
    root = by_id["crypto/certificate/root-ca@sha256:cc03"]
    assert root.criticality == pol.crit_ca
    assert root.shelf_life == pol.shelf_ca
    assert root.shelf_life + 0 >= inst.t_crqc, "CA shelf-life must reach t_crqc (HNDL)"

    # leaf cert: leaf criticality (lower than CA), medium shelf-life.
    leaf = by_id["crypto/certificate/leaf-tls@sha256:aa01"]
    assert leaf.criticality == pol.crit_leaf
    assert leaf.criticality < root.criticality


def test_feasibility_invariants(inst: Instance) -> None:
    """Every asset must be schedulable: earliest in-horizon and <= deadline."""
    for a in inst.assets:
        assert 0 <= a.earliest < inst.T
        if a.deadline is not None:
            assert 0 <= a.deadline < inst.T
            assert a.earliest <= a.deadline, f"{a.id}: earliest > deadline (infeasible)"
    # budget must be able to absorb the single most expensive asset in a period.
    assert min(inst.budget) >= max(a.cost for a in inst.assets)


def test_earliest_reflects_pqc_timeline(inst: Instance) -> None:
    """Signature/PKI-side assets are delayed; key-agreement can start now."""
    by_id = inst.by_id()
    # ECDH (key-agree) can migrate from period 0 (KEM support is available now).
    ecdh = by_id["crypto/algorithm/ecdh-p256@1.2.840.10045.3.1.7"]
    assert ecdh.earliest == 0
    # An RSA signing algorithm is signature-side -> delayed earliest > 0.
    rsa = by_id["crypto/algorithm/rsa-2048@1.2.840.113549.1.1.11"]
    assert rsa.earliest == CbomPolicy().earliest_signature_delay


def test_smoke_solve_optimal(inst: Instance) -> None:
    res = solve_cpsat(inst, RiskModel(), time_limit=30.0, workers=4)
    assert res.status in (OPTIMAL, FEASIBLE)
    assert res.schedule is not None
    # the produced schedule must be feasible and score-consistent.
    sc = score_schedule(inst, res.schedule, RiskModel())
    assert sc.feasible, f"solver schedule has violations: {sc}"
    assert res.objective == sc.risk, "ObjectiveValue must equal the shared scorer"


def test_risk_actually_fires(inst: Instance) -> None:
    """A non-trivial instance: leaving everything unmigrated has positive risk,
    and the optimal schedule reduces it (otherwise the smoke solve is vacuous)."""
    empty = score_schedule(inst, {}, RiskModel())
    assert empty.risk > 0, "HNDL/criticality must produce real risk to schedule against"
    res = solve_cpsat(inst, RiskModel(), time_limit=30.0, workers=4)
    assert res.objective <= empty.risk


def test_accepts_dict_and_bytes() -> None:
    """Ingest must accept a path, raw bytes, and an already-parsed dict alike."""
    with open(SAMPLE, "rb") as fh:
        raw = fh.read()
    import orjson

    parsed = orjson.loads(raw)

    a = cbom_to_instance(SAMPLE)
    b = cbom_to_instance(raw)
    c = cbom_to_instance(parsed)
    assert {x.id for x in a.assets} == {x.id for x in b.assets} == {x.id for x in c.assets}


def test_from_cbom_wrapper_matches() -> None:
    a = cbom_to_instance(SAMPLE, periods=15, t_crqc=10)
    b = from_cbom(SAMPLE, periods=15, t_crqc=10)
    assert a.to_dict() == b.to_dict()


def test_custom_policy_overrides() -> None:
    """A custom policy must flow through to asset attributes and the budget."""
    pol = CbomPolicy(crit_protocol=42, shelf_ca=30, budget_floor=5, budget_tightness=2.0)
    inst = cbom_to_instance(SAMPLE, periods=20, policy=pol, t_crqc=13)
    by_id = inst.by_id()
    assert by_id["crypto/protocol/tls@1.2"].criticality == 42
    assert by_id["crypto/certificate/root-ca@sha256:cc03"].shelf_life == 30

    # Budget = ceil(tightness * peak-deadline-bucket-load). Derive the expected
    # value from the asset costs/deadlines themselves rather than hard-coding it,
    # so the assertion tracks the documented formula, not a guessed number.
    import math

    bucket: dict[int, int] = {}
    for a in inst.assets:
        p = a.deadline if a.deadline is not None else inst.T - 1
        bucket[p] = bucket.get(p, 0) + a.cost
    peak = max(bucket.values())
    assert inst.budget[0] == max(pol.budget_floor, math.ceil(pol.budget_tightness * peak))
    # tightness 2.0 must produce a strictly larger budget than tightness 1.0.
    base = cbom_to_instance(SAMPLE, periods=20, t_crqc=13)
    assert inst.budget[0] > base.budget[0]


def test_empty_estate_is_safe() -> None:
    """A CBOM with no vulnerable assets yields an empty-but-valid instance."""
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [
            {
                "type": "cryptographic-asset",
                "bom-ref": "crypto/algorithm/aes-256@oid",
                "name": "AES-256-GCM",
                "cryptoProperties": {
                    "assetType": "algorithm",
                    "algorithmProperties": {"primitive": "ae", "nistQuantumSecurityLevel": 1},
                },
            }
        ],
        "dependencies": [],
    }
    inst = cbom_to_instance(doc, periods=10)
    assert inst.assets == []
    assert inst.deps == []
    assert len(inst.budget) == 10
    assert inst.budget[0] == CbomPolicy().budget_floor  # floor applies when no assets
