"""Ingest a CycloneDX 1.6 CBOM into a pqcsched :class:`~pqcsched.model.Instance`.

A *Cryptography Bill of Materials* (CBOM) is the real-world artifact a scanner
(e.g. ``cbomkit``, ``sonar-cryptography``) emits when it inventories an estate's
cryptography. This module turns that inventory into the scheduling problem SAMAY
solves: which quantum-vulnerable cryptographic usages must migrate, in what
dependency order, under what windows and budget.

Why this matters
----------------
The synthetic generator (:mod:`pqcsched.generate`) produces *statistically*
realistic estates for the optimal-vs-greedy study; this module lets SAMAY run on
a *real* estate handed to it as a CBOM. The Definition of Done requires ingest to
work on a sample CBOM, so the canonical sample ships at
``benchmark/sample.cbom.json``.

Parsing approach (decision, and why)
------------------------------------
We parse the CBOM JSON **directly with orjson**, not via
``cyclonedx-python-lib``. Rationale:

* The model already depends on ``orjson`` (see :mod:`pqcsched.model`); adding no
  new runtime dependency keeps the package lean.
* We only ever *read* a handful of fields (component type, ``cryptoProperties``,
  ``dependencies``); the library's full object graph and validation are weight we
  do not need on the read path. The canonical sample was already schema-validated
  and round-tripped through ``cyclonedx-python-lib`` 11.x by the producing
  teammate, so structural correctness is covered upstream.
* Direct parsing is robust to optional-field absence, which a strict object model
  is not. We treat every optional field as possibly missing.

What is a "decision asset"
--------------------------
We keep a ``cryptographic-asset`` component as a migratable decision variable iff
it is **quantum-vulnerable** under a *transitive* reading:

* ``algorithm``: vulnerable iff ``nistQuantumSecurityLevel == 0`` **or** its
  ``primitive`` is one of {signature, pke, kem, key-agree} **or** (fallback) its
  name matches a known classical scheme. Symmetric/hash primitives (``ae``,
  ``hash`` with ``nistQuantumSecurityLevel >= 1``: AES, SHA-2/3) are **not** kept.
* ``certificate``: vulnerable iff its ``signatureAlgorithmRef`` or
  ``subjectPublicKeyRef`` resolves (transitively) to a vulnerable algorithm. A
  cert signed with, or carrying a key of, a quantum-broken algorithm must be
  re-issued, so it is a genuine decision asset (calibration §2.3: CA-before-leaf).
* ``related-crypto-material`` (keys): vulnerable iff its ``algorithmRef``
  resolves to a vulnerable algorithm.
* ``protocol``: vulnerable iff any cipher-suite algorithm
  (``protocolProperties.cipherSuites[].algorithms[]``) resolves to a vulnerable
  algorithm.

This *broad* reading is correct, not merely permissive: a CycloneDX
``dependencies`` graph wires certificates/keys/protocols to the algorithms they
use, but algorithm components are only ever the *target* of ``dependsOn`` (they
have no outgoing ``dependsOn`` of their own). Keeping only algorithms would yield
**zero** edges between two kept assets and erase the entire PKI precedence chain.
The certs/keys/protocol are exactly where the CA-before-leaf ordering lives.

The dependency FLIP
-------------------
CycloneDX expresses ``A dependsOn B`` as "dependent A needs prerequisite B".
pqcsched's edge ``(j, i)`` means "prerequisite j must complete no later than i"
(see :class:`pqcsched.model.Instance`). So for each CBOM ``A dependsOn B`` we emit
``(B, A)`` — prerequisite first. Concretely, "leaf dependsOn intermediate-CA"
becomes ``(intermediate-CA, leaf)``: the CA migrates no later than the leaf,
which is the empirically-correct PKI ordering. Edges are kept only when *both*
endpoints are kept (vulnerable) assets; edges touching excluded AES/SHA are
dropped.

Default policy (CBOM does not carry scheduling economics)
---------------------------------------------------------
A CBOM inventories cryptography; it does **not** carry the quantities SAMAY
schedules on — criticality, shelf-life (HNDL horizon), migration cost, regulatory
deadline, or per-period budget. :class:`CbomPolicy` supplies documented,
configurable defaults for these. Every default is justified in that dataclass's
docstring and grounded in ``research/calibration-crypto.md`` where the literature
constrains it (heavy-tailed criticality §3.1; shelf-life-in-years tiers §3.3;
CA-before-leaf precedence §2.3; CRQC timing §3.6). Defaults the literature does
*not* pin (exact cost figures, deadline profile) are labelled as modeling
choices, the same Tier-C honesty the calibration document uses.

Calendar convention: **one period == one year**, ``t = 0`` is 2026 (calibration
§4, option 1). Default ``t_crqc = 13`` therefore reads as 2039.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import orjson

from .model import Asset, Instance

log = logging.getLogger("pqcsched.cbom")

# --- vulnerability heuristics --------------------------------------------------

#: Crypto primitives whose hardness is broken by a CRQC (Shor / Grover-relevant
#: asymmetric). ``ae``/``hash``/``mac``/``drbg`` etc. are *not* here.
_VULNERABLE_PRIMITIVES = frozenset({"signature", "pke", "kem", "key-agree"})

#: Name-substring fallback when ``cryptoProperties`` lacks
#: ``nistQuantumSecurityLevel`` and ``primitive`` (older/sparse scanners). These
#: are classical asymmetric schemes broken by Shor. Lower-cased substring match.
_VULNERABLE_NAME_HINTS = (
    "rsa", "ecdsa", "ecdh", "dh", "elgamal", "dsa", "ecc", "ec-", "ecies",
    "diffie", "secp", "prime256", "p-256", "p-384", "p-521", "curve25519",
    "x25519", "x448", "ed25519", "ed448", "brainpool",
)

#: Names that are explicitly NOT vulnerable even if a weak hint matched (guards
#: e.g. "ecdh" substring inside an unrelated token, and PQC scheme names).
_SAFE_NAME_HINTS = (
    "ml-kem", "ml-dsa", "slh-dsa", "kyber", "dilithium", "sphincs", "falcon",
    "aes", "chacha", "sha-", "sha256", "sha384", "sha512", "sha3", "shake",
    "hmac", "poly1305", "blake",
)


# --- default scheduling policy -------------------------------------------------


@dataclass(frozen=True, slots=True)
class CbomPolicy:
    """Documented, configurable defaults for the scheduling economics a CBOM
    does not carry.

    A CBOM says *what* cryptography exists and how it depends; it is silent on
    *criticality*, *shelf-life*, *cost*, *deadline*, and *budget*. These defaults
    fill that gap. Each is grounded in ``research/calibration-crypto.md`` where
    the literature constrains it, and labelled a modeling choice where it does
    not. Override any field to fit a concrete estate.

    Criticality (integer "risk points", drives the risk objective)
    --------------------------------------------------------------
    Enterprise exposure is heavy-tailed: a few internet-facing crown jewels
    (root/issuing CAs, the TLS protocol surface) dominate, most usages are
    modest (calibration §3.1). We assign by asset kind rather than draw randomly,
    because a CBOM gives us the *kind* deterministically:

    * ``crit_protocol`` — a live protocol endpoint (TLS) is the externally
      exposed crown jewel.
    * ``crit_ca`` — CA certificates / CA public keys sit at the root of trust;
      compromise is catastrophic and fans out to every dependent.
    * ``crit_leaf`` — leaf certificates / leaf keys are exposed but singular.
    * ``crit_algorithm`` — a bare algorithm usage inherits importance from its
      consumers (captured via dependencies), so on its own it is mid-weight.
    * ``crit_default`` — anything unclassified.

    "CA-ness" is detected from the certificate subject (``CN``/``O`` containing
    "CA"/"root"/"issuing") or from a key/algorithm being referenced by a CA cert.

    Shelf-life (YEARS the protected data must stay secret; the HNDL horizon)
    -----------------------------------------------------------------------
    HNDL fires when ``t + shelf_life >= t_crqc`` (see :mod:`pqcsched.risk`).
    Values are **years** (calibration §4, option 1 — one period == one year).
    Calibration §3.3 anchors three tiers; we map by asset role:

    * ``shelf_protocol`` — TLS session/ephemeral material: short secrecy. The
      dominant *count* in a TLS estate but the *least* HNDL-exposed.
    * ``shelf_leaf`` — business documents signed/protected by leaves: ~medium
      (SOX 7y / HIPAA 6y bracket).
    * ``shelf_ca`` / ``shelf_key`` — long-lived trust anchors and the long-secrecy
      data they ultimately protect: multi-decade. This is the population HNDL is
      *about*; it must be long enough to reach ``t_crqc``.

    Cost (integer person-days of migration effort)
    ----------------------------------------------
    Per-asset PQC-migration effort in person-days has **no public distribution**
    (calibration §3.2 says so plainly); these are *modeling choices*, ordered by
    the deployment-difficulty gradient calibration §1.3/§2.2 documents (rotating a
    leaf cert is cheap; re-keying a root CA / re-architecting a protocol is dear):
    ``cost_leaf < cost_key < cost_algorithm < cost_ca < cost_protocol``.

    Deadline (period by which a *mandated* asset must be migrated; ``None`` = unmandated)
    -----------------------------------------------------------------------------------
    A CNSA-2.0 / NIST-style profile: the most exposed and longest-lived assets
    carry the tightest mandates. Expressed as a period offset; ``None`` leaves an
    asset unmandated (it still accrues risk, so it is not ignored). This is a
    modeling choice (the *profile* shape; specific years are policy-dependent).

    Earliest (first period an asset *can* migrate; PQC support availability)
    -----------------------------------------------------------------------
    Calibration §2.2 is cited: PQC **KEM/key-agreement** support is available now,
    but **signature / CA** support ships later. So signature-side and CA assets
    get ``earliest_signature_delay`` > 0; key-agreement and everything else can
    start at period 0.

    Budget (per-period migration capacity, integer units == person-days/period)
    ---------------------------------------------------------------------------
    A CBOM carries no capacity figure. We size the per-period budget as a
    multiple of the single most expensive asset's cost (``budget_tightness``),
    clamped to a floor, so the smoke solve is always feasible (every asset can
    migrate in some period) while still being a real throughput constraint. This
    is a deliberately simple, transparent default; a real estate would set it
    from staffing.
    """

    # criticality by kind (heavy-tailed; calibration §3.1)
    crit_protocol: int = 95
    crit_ca: int = 90
    crit_leaf: int = 55
    crit_algorithm: int = 40
    crit_default: int = 30

    # shelf-life in YEARS by role (calibration §3.3, §4)
    shelf_protocol: int = 2
    shelf_leaf: int = 8
    shelf_ca: int = 25
    shelf_key: int = 20
    shelf_default: int = 8

    # migration cost in person-days by kind (modeling choice; calibration §3.2)
    cost_protocol: int = 30
    cost_ca: int = 25
    cost_algorithm: int = 12
    cost_key: int = 6
    cost_leaf: int = 4
    cost_default: int = 8

    # earliest-feasible delay (years) for signature/CA assets (calibration §2.2)
    earliest_signature_delay: int = 2

    # mandated-deadline profile (period offsets; None = unmandated). Modeling
    # choice shaped like a CNSA-2.0 phase-out, ordered by HNDL urgency AND by
    # precedence depth: the *foundational, long-shelf-life* trust anchors (CAs,
    # long-lived keys) carry the tightest mandates, and the ephemeral protocol
    # surface — least HNDL-exposed and the sink of the dependency graph — the
    # loosest. This is deliberately the inverse of "crown-jewel-soonest": a
    # protocol re-key is cheap and short-secrecy, whereas a root CA protects
    # decades of trust and sits upstream of everything (calibration §2.3, §3.3).
    # Ordering deadlines this way also keeps them precedence-consistent
    # (prerequisite deadline <= dependent deadline), so :func:`_reconcile_deadlines`
    # does not have to collapse the graph to make it feasible.
    deadline_ca: int | None = 8
    deadline_key: int | None = 9
    deadline_leaf: int | None = 12
    deadline_algorithm: int | None = 10
    deadline_protocol: int | None = 15
    deadline_default: int | None = None

    # per-period budget sizing
    budget_tightness: float = 1.0   # budget_t = ceil(tightness * max_asset_cost)
    budget_floor: int = 20          # never below this many person-days/period

    def __post_init__(self) -> None:
        # A deadline earlier than the earliest-feasible period is infeasible by
        # construction; the CBOM ingest must never emit such an asset. We clamp
        # later in `_resolve_asset`, but assert the policy itself is sane here.
        if self.budget_tightness <= 0:
            raise ValueError("budget_tightness must be > 0")


# --- CBOM parsing --------------------------------------------------------------


def _load(source: str | bytes | dict[str, Any]) -> dict[str, Any]:
    """Load a CBOM from a path, raw JSON bytes/str, or an already-parsed dict."""
    if isinstance(source, dict):
        return source
    if isinstance(source, (bytes, bytearray)):
        return orjson.loads(source)
    # str: treat as a path if it points at a file, else as a JSON literal.
    import os

    if os.path.exists(source):
        with open(source, "rb") as fh:
            return orjson.loads(fh.read())
    return orjson.loads(source)


def _is_vulnerable_name(name: str | None) -> bool:
    """Name-substring fallback. Safe hints win ties (PQC/symmetric names)."""
    if not name:
        return False
    low = name.lower()
    if any(h in low for h in _SAFE_NAME_HINTS):
        return False
    return any(h in low for h in _VULNERABLE_NAME_HINTS)


@dataclass(slots=True)
class _Estate:
    """Indexed, resolved view of a CBOM's cryptographic-asset components.

    Holds the ``bom-ref -> component`` index and a memoized transitive
    vulnerability resolver. Kept private; callers use :func:`cbom_to_instance`.
    """

    by_ref: dict[str, dict[str, Any]]
    dependencies: list[dict[str, Any]]
    # memo: bom-ref -> resolved transitive vulnerability (filled lazily).
    _vuln_memo: dict[str, bool] = field(default_factory=dict)

    def crypto_props(self, ref: str) -> dict[str, Any]:
        return self.by_ref.get(ref, {}).get("cryptoProperties", {}) or {}

    def asset_type(self, ref: str) -> str | None:
        return self.crypto_props(ref).get("assetType")

    def _algo_is_vulnerable(self, ref: str) -> bool:
        cp = self.crypto_props(ref)
        ap = cp.get("algorithmProperties", {}) or {}
        nqsl = ap.get("nistQuantumSecurityLevel")
        if nqsl == 0:
            return True
        if nqsl is not None and nqsl >= 1:
            # Explicitly quantum-safe-rated (AES=1, SHA-384=2, ...). Not a
            # decision asset even if a weak name hint would otherwise match.
            return False
        prim = ap.get("primitive")
        if prim in _VULNERABLE_PRIMITIVES:
            return True
        if prim is not None:
            # primitive present but symmetric/hash/etc. -> safe.
            return False
        # No quantum level and no primitive: fall back to the name.
        return _is_vulnerable_name(self.by_ref.get(ref, {}).get("name"))

    def is_vulnerable(self, ref: str) -> bool:
        """Transitive quantum-vulnerability of the component at ``ref`` (memoized).

        Recurses through cert/key/protocol references to the underlying
        algorithm(s). Cycles (pathological CBOMs) are broken by the ``_visiting``
        guard, treating an unresolved cycle as non-vulnerable. Results are cached
        in ``_vuln_memo`` so repeated resolution over the dependency fan-in is
        ``O(components)``, not exponential.
        """
        return self._resolve_vuln(ref, frozenset())

    def _resolve_vuln(self, ref: str, _visiting: frozenset[str]) -> bool:
        if ref in self._vuln_memo:
            return self._vuln_memo[ref]
        if ref in _visiting or ref not in self.by_ref:
            return False  # cycle or dangling ref: do not memoize a partial result
        cp = self.crypto_props(ref)
        at = cp.get("assetType")
        nxt = _visiting | {ref}

        if at == "algorithm":
            result = self._algo_is_vulnerable(ref)
        elif at == "related-crypto-material":
            algo = (cp.get("relatedCryptoMaterialProperties", {}) or {}).get("algorithmRef")
            result = bool(algo) and self._resolve_vuln(algo, nxt)
        elif at == "certificate":
            cpr = cp.get("certificateProperties", {}) or {}
            refs = [cpr.get("signatureAlgorithmRef"), cpr.get("subjectPublicKeyRef")]
            result = any(r and self._resolve_vuln(r, nxt) for r in refs)
        elif at == "protocol":
            pp = cp.get("protocolProperties", {}) or {}
            result = any(
                self._resolve_vuln(algo, nxt)
                for cs in (pp.get("cipherSuites", []) or [])
                for algo in (cs.get("algorithms", []) or [])
            )
        else:
            # Unknown assetType: fall back to the component name.
            result = _is_vulnerable_name(self.by_ref.get(ref, {}).get("name"))

        self._vuln_memo[ref] = result
        return result

    # -- classification used by the default policy ------------------------------

    def is_ca(self, ref: str) -> bool:
        """Heuristic: is this component a certificate authority (or its key)?

        A CA cert is detected from its subject/issuer strings; a key/algorithm is
        "CA-ish" if some CA certificate references it. Drives the heavy-tailed
        criticality and the long shelf-life for trust anchors (calibration §2.3).
        """
        at = self.asset_type(ref)
        if at == "certificate":
            cpr = self.crypto_props(ref).get("certificateProperties", {}) or {}
            subj = (cpr.get("subjectName") or "").lower()
            # self-signed (subject == issuer) or "CA"/"root"/"issuing" in subject
            issuer = (cpr.get("issuerName") or "").lower()
            looks_ca = any(tok in subj for tok in (" ca", "ca ", "root", "issuing", "=ca"))
            self_signed = bool(subj) and subj == issuer
            return looks_ca or self_signed
        # key/algorithm: CA-ish if referenced by a CA certificate
        for other in self.by_ref:
            if self.asset_type(other) == "certificate" and self.is_ca(other):
                cpr = self.crypto_props(other).get("certificateProperties", {}) or {}
                if ref in (cpr.get("signatureAlgorithmRef"), cpr.get("subjectPublicKeyRef")):
                    return True
        return False

    def is_signature_side(self, ref: str) -> bool:
        """True if the component is signature/PKI-side (vs key-agreement/KEM).

        Used for the cited delayed-feasibility default (calibration §2.2): PQC
        signature/CA support lands later than KEM support. Certificates, keys, and
        signature algorithms are signature-side; key-agree/kem algorithms are not.
        """
        at = self.asset_type(ref)
        if at in ("certificate", "related-crypto-material"):
            return True
        if at == "algorithm":
            prim = (self.crypto_props(ref).get("algorithmProperties", {}) or {}).get("primitive")
            return prim in ("signature", "pke")  # pke (e.g. RSA-OAEP) is also cert/PKI-side
        if at == "protocol":
            return False  # a protocol can start migrating its KEM side now
        return False


def _classify_kind(estate: _Estate, ref: str) -> str:
    """Coarse kind label used to pick policy defaults: one of
    ``{"protocol", "ca", "leaf", "key", "algorithm", "default"}``."""
    at = estate.asset_type(ref)
    if at == "protocol":
        return "protocol"
    if at == "certificate":
        return "ca" if estate.is_ca(ref) else "leaf"
    if at == "related-crypto-material":
        return "ca" if estate.is_ca(ref) else "key"
    if at == "algorithm":
        return "ca" if estate.is_ca(ref) else "algorithm"
    return "default"


def _resolve_asset(
    estate: _Estate, ref: str, policy: CbomPolicy, periods: int, t_crqc: int
) -> Asset:
    """Build an :class:`Asset` for a kept (vulnerable) component using ``policy``.

    All scheduling economics come from the policy keyed on the component's kind.
    ``earliest`` and ``deadline`` are clamped into ``[0, periods - 1]`` and a
    deadline is never allowed to fall before ``earliest`` (that would make the
    instance infeasible by construction); if it would, the deadline is pushed to
    ``earliest`` and a warning is logged.
    """
    kind = _classify_kind(estate, ref)

    crit = {
        "protocol": policy.crit_protocol,
        "ca": policy.crit_ca,
        "leaf": policy.crit_leaf,
        "algorithm": policy.crit_algorithm,
    }.get(kind, policy.crit_default)

    shelf = {
        "protocol": policy.shelf_protocol,
        "ca": policy.shelf_ca,
        "leaf": policy.shelf_leaf,
        "key": policy.shelf_key,
    }.get(kind, policy.shelf_default)

    cost = {
        "protocol": policy.cost_protocol,
        "ca": policy.cost_ca,
        "algorithm": policy.cost_algorithm,
        "key": policy.cost_key,
        "leaf": policy.cost_leaf,
    }.get(kind, policy.cost_default)

    deadline = {
        "protocol": policy.deadline_protocol,
        "ca": policy.deadline_ca,
        "key": policy.deadline_key,
        "leaf": policy.deadline_leaf,
        "algorithm": policy.deadline_algorithm,
    }.get(kind, policy.deadline_default)

    earliest = policy.earliest_signature_delay if estate.is_signature_side(ref) else 0

    # Clamp into the horizon and preserve feasibility (earliest <= deadline).
    earliest = max(0, min(earliest, periods - 1))
    if deadline is not None:
        deadline = max(0, min(deadline, periods - 1))
        if deadline < earliest:
            log.warning(
                "asset %s: deadline %d < earliest %d after clamping; "
                "pushing deadline to earliest to keep the instance feasible",
                ref, deadline, earliest,
            )
            deadline = earliest

    return Asset(
        id=ref,
        criticality=int(crit),
        shelf_life=int(shelf),
        cost=int(cost),
        perf_penalty=0.0,  # CBOM carries no overhead figure; left at 0.0
        earliest=int(earliest),
        deadline=deadline,
    )


def _build_deps(estate: _Estate, kept: set[str]) -> list[tuple[str, str]]:
    """Parse ``dependencies[]`` into FLIPPED edges between kept assets.

    CBOM ``A dependsOn B`` -> emit ``(B, A)`` (prerequisite B before dependent A),
    keeping only edges where both endpoints are kept. Deduplicated, order-stable.
    """
    seen: set[tuple[str, str]] = set()
    edges: list[tuple[str, str]] = []
    for dep in estate.dependencies:
        a = dep.get("ref")
        if a not in kept:
            continue
        for b in dep.get("dependsOn", []) or []:
            if b not in kept:
                continue
            edge = (b, a)  # FLIP: prerequisite -> dependent
            if edge not in seen:
                seen.add(edge)
                edges.append(edge)
    return edges


def _build_clusters(estate: _Estate, kept: set[str]) -> list[tuple[str, str]]:
    """Infer co-migration clusters.

    A cluster forces two assets to migrate in the *same* period (e.g. both ends
    of a protocol). For this single-sided server estate "both ends" is not
    expressible from the CBOM, and an over-eager cluster can manufacture
    infeasibility, so we conservatively emit **none** (the task allows "else
    none"). The hook is kept here so a richer CBOM (mTLS with both endpoints
    present) can populate clusters later without an API change.
    """
    return []


def _reconcile_deadlines(
    assets: list[Asset], deps: list[tuple[str, str]]
) -> None:
    """Make the per-kind deadline profile *precedence-consistent*, in place.

    Precedence edge ``(j, i)`` means prerequisite ``j`` finishes no later than
    dependent ``i`` (:mod:`pqcsched.solve_cpsat`). So if ``i`` is mandated by
    ``D_i``, ``j`` must also finish by ``D_i`` — i.e. **a prerequisite's deadline
    can be no later than the tightest deadline among all its (transitive)
    dependents**. The kind-keyed defaults in :class:`CbomPolicy` do not know the
    graph, so a dependent (e.g. the TLS protocol) can be handed an *earlier*
    deadline than its prerequisites (the CA chain), which is infeasible by
    construction (CP-SAT returns INFEASIBLE).

    This propagates the minimum dependent-deadline back onto each prerequisite
    (longest-path / topological relaxation over the DAG). If the tightened
    deadline would fall *before* an asset's own ``earliest`` (the mandate is
    physically impossible — PQC support for that asset does not exist early
    enough), the mandate is **dropped** (set to ``None``) and logged: an
    unmandated asset still accrues residual risk in the objective, so it is not
    ignored, and the instance stays feasible. This is the honest resolution —
    fabricating an impossible deadline would make every solve INFEASIBLE.

    Cycles (a malformed CBOM with a dependency cycle) are tolerated: propagation
    runs a bounded number of passes (``len(assets)``), which is sufficient for a
    DAG and simply stops early otherwise.
    """
    by_id = {a.id: a for a in assets}
    # successors[j] = dependents i that require j (edge (j, i)).
    successors: dict[str, list[str]] = {a.id: [] for a in assets}
    for j, i in deps:
        if j in by_id and i in by_id:
            successors[j].append(i)

    # Relax: deadline_j <- min(deadline_j, min deadline over dependents).
    # Repeat to a fixpoint (bounded by chain length).
    for _ in range(len(assets)):
        changed = False
        for j, succ in successors.items():
            aj = by_id[j]
            for i in succ:
                di = by_id[i].deadline
                if di is None:
                    continue
                if aj.deadline is None or aj.deadline > di:
                    aj.deadline = di
                    changed = True
        if not changed:
            break

    # Drop any mandate now impossible (deadline < earliest); keep feasibility.
    for a in assets:
        if a.deadline is not None and a.deadline < a.earliest:
            log.warning(
                "asset %s: precedence forces deadline %d before earliest %d "
                "(PQC support lands too late to meet a dependent's mandate); "
                "dropping the deadline (asset stays risk-accruing but unmandated)",
                a.id, a.deadline, a.earliest,
            )
            a.deadline = None


def cbom_to_instance(
    source: str | bytes | dict[str, Any],
    *,
    periods: int = 20,
    policy: CbomPolicy | None = None,
    t_crqc: int = 13,
) -> Instance:
    """Parse a CycloneDX 1.6 CBOM into a scheduling :class:`Instance`.

    Parameters
    ----------
    source:
        Path to a ``.json`` CBOM, raw JSON ``bytes``/``str``, or an already-parsed
        ``dict``.
    periods:
        Horizon length ``T`` in periods. One period == one year, ``t = 0`` is 2026
        (calibration §4). Default 20 -> 2026..2045.
    policy:
        :class:`CbomPolicy` supplying the scheduling economics the CBOM does not
        carry. Defaults to ``CbomPolicy()`` (all defaults documented there).
    t_crqc:
        Projected period of a cryptographically-relevant quantum computer.
        Default 13 (== year 2039) per the brief; calibration §3.6 treats CRQC
        timing as a swept sensitivity parameter, so override per scenario.

    Returns
    -------
    Instance
        Decision assets = the quantum-vulnerable cryptographic-asset components
        (transitive reading); ``deps`` = FLIPPED dependency edges between kept
        assets; ``clusters`` = none (see :func:`_build_clusters`); ``budget`` =
        per-period capacity sized by the policy; ``meta`` records provenance.

    Notes
    -----
    Robust to missing optional fields throughout. Components without a
    ``bom-ref`` are skipped (they cannot participate in the dependency graph) with
    a warning.
    """
    if periods < 1:
        raise ValueError(f"periods must be >= 1, got {periods}")
    policy = policy or CbomPolicy()

    doc = _load(source)
    spec = doc.get("specVersion")
    if doc.get("bomFormat") != "CycloneDX":
        log.warning("source bomFormat is %r, expected 'CycloneDX'", doc.get("bomFormat"))
    if spec is not None and not str(spec).startswith("1."):
        log.warning("unexpected CycloneDX specVersion %r (parser targets 1.6)", spec)

    # Index cryptographic-asset components by bom-ref.
    by_ref: dict[str, dict[str, Any]] = {}
    n_crypto = 0
    for comp in doc.get("components", []) or []:
        if comp.get("type") != "cryptographic-asset":
            continue
        n_crypto += 1
        ref = comp.get("bom-ref")
        if not ref:
            log.warning("cryptographic-asset %r has no bom-ref; skipping", comp.get("name"))
            continue
        by_ref[ref] = comp

    estate = _Estate(by_ref=by_ref, dependencies=doc.get("dependencies", []) or [])

    # Keep the transitively quantum-vulnerable components as decision assets.
    kept = {ref for ref in by_ref if estate.is_vulnerable(ref)}
    if not kept:
        log.warning("no quantum-vulnerable cryptographic assets found in CBOM")

    assets = [_resolve_asset(estate, ref, policy, periods, t_crqc) for ref in by_ref if ref in kept]
    # Stable, deterministic order (by id) for reproducible solves/serialization.
    assets.sort(key=lambda a: a.id)

    deps = _build_deps(estate, kept)
    clusters = _build_clusters(estate, kept)

    # Make the deadline profile consistent with precedence so the instance is
    # not infeasible by construction (a dependent cannot be due before its
    # prerequisites can finish). Mutates assets in place.
    _reconcile_deadlines(assets, deps)

    # Per-period budget, sized so that *budget is never the binding cause of
    # infeasibility*. The schedule that places every asset at its (reconciled)
    # deadline — ALAP — is precedence- and window-feasible whenever the deadline
    # profile is itself feasible (every mandated asset has earliest <= deadline,
    # which holds under the default policy): reconciliation guarantees D_j <= D_i
    # on every edge (j, i), so τ_j = D_j <= D_i = τ_i, and each τ_i = D_i lies in
    # [earliest_i, D_i]. The only remaining way to break ALAP is budget, so we
    # bucket assets by their deadline period and size the per-period budget to the
    # *peak* bucket load (scaled by tightness). ``budget_tightness`` is then the
    # study knob: >= 1 ships slack, < 1 deliberately induces budget pressure for
    # the constrained case study. (Caveat: a *custom* policy that mandates a
    # dependent earlier than a prerequisite's ``earliest`` — e.g.
    # ``deadline_ca`` < ``earliest_signature_delay`` — is infeasible on precedence
    # regardless of budget; the default profile keeps every deadline well past the
    # signature-availability delay, so the shipped sample and any default-policy
    # CBOM solve.)
    import math

    bucket: dict[int, int] = {}
    for a in assets:
        p = a.deadline if a.deadline is not None else periods - 1
        bucket[p] = bucket.get(p, 0) + a.cost
    peak = max(bucket.values(), default=0)
    per_period = max(policy.budget_floor, math.ceil(policy.budget_tightness * peak))
    budget = [per_period] * periods

    excluded = [ref for ref in by_ref if ref not in kept]
    log.info(
        "CBOM ingest: %d cryptographic-asset components, %d kept as vulnerable "
        "decision assets, %d excluded, %d deps (flipped), %d clusters; T=%d, "
        "t_crqc=%d, budget/period=%d",
        n_crypto, len(kept), len(excluded), len(deps), len(clusters),
        periods, t_crqc, per_period,
    )

    meta: dict[str, Any] = {
        "source": "cbom",
        "cyclonedx_spec": spec,
        "serial_number": doc.get("serialNumber"),
        "period_unit": "year",
        "period_zero_calendar": 2026,
        "n_crypto_components": n_crypto,
        "n_vulnerable_kept": len(kept),
        "n_excluded": len(excluded),
        "excluded_refs": sorted(excluded),
        "policy": _policy_to_dict(policy),
    }

    return Instance(
        assets=assets,
        T=periods,
        budget=budget,
        deps=deps,
        clusters=clusters,
        t_crqc=t_crqc,
        meta=meta,
    )


def from_cbom(
    source: str | bytes | dict[str, Any],
    *,
    periods: int = 20,
    policy: CbomPolicy | None = None,
    t_crqc: int = 13,
) -> Instance:
    """Convenience wrapper mirroring an ``Instance.from_cbom`` classmethod.

    Lives here (not on :class:`pqcsched.model.Instance`) so the core model takes
    **no** dependency on CBOM ingest — CORE stays locked. Identical to
    :func:`cbom_to_instance`; provided so callers can write
    ``from pqcsched.cbom import from_cbom``.
    """
    return cbom_to_instance(source, periods=periods, policy=policy, t_crqc=t_crqc)


def _policy_to_dict(policy: CbomPolicy) -> dict[str, Any]:
    """Serialize a policy for provenance in ``Instance.meta`` (slots-safe)."""
    from dataclasses import fields

    return {f.name: getattr(policy, f.name) for f in fields(policy)}
