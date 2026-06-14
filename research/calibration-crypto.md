# Calibration — cryptography sizes, performance, and PKI estate structure

**Purpose.** Pin the synthetic-estate generator's distributions (`src/pqcsched/generate.py`,
`Calibration` / `GenParams`) to cited public evidence so the optimal-vs-greedy study cannot be
dismissed as "tuned to flatter the optimizer." Every generator knob below is mapped to a source
*or* explicitly labelled as a modeling choice the literature does not constrain (to be
sensitivity-tested, not citation-laundered).

**Evidence tiers** (used throughout):

- **Tier A — hard facts.** Standardized sizes/speeds, measured prevalence. Cited to a primary
  source and cross-checked against a second. Non-negotiable; the generator's *credibility* rests
  here even though it does not consume raw bytes.
- **Tier B — justifiable mappings.** A generator scalar derived from a real measurement (e.g.
  `perf_penalty` from measured handshake-overhead %; `shelf_life` tiers from retention regs + HNDL
  guidance). Defensible shape and range, with judgement in the exact mapping.
- **Tier C — modeling choices.** Distribution *families* and parameters the literature barely
  constrains (lognormal sigmas for criticality/cost, exact tier probabilities, uniform perf,
  binomial in-degree). Labelled as assumptions; the load-bearing ones must be swept in the
  sensitivity analysis (`PROJECT_BRIEF.md` §8), never presented as empirically pinned.

> **Skeptic's note.** Two crypto knobs (`criticality` as abstract 1–100 "risk points", `cost` as
> person-days per crypto asset) have **no direct cryptographic source**. We justify their *shape*
> (heavy-tailed) qualitatively and label the parameters Tier C. Per-asset migration-effort data in
> person-days is genuinely sparse in the public literature; we say so rather than invent it.

All figures verified June 2026. Currency caveat: prevalence numbers (RSA/ECDSA split, PQC
adoption %) move fast; each is dated.

---

## 1. PQC vs classical — sizes and performance (Tier A)

### 1.1 Sizes on the wire (bytes)

Public-key (encapsulation-key) / ciphertext for KEMs; public-key / signature for signatures.
Sources: FIPS 203/204/205; cross-checked against Open Quantum Safe (liboqs) datasheets and the
CRYSTALS / SPHINCS+ specs. One figure was corrected during cross-check (see note).

| Scheme | Role | Public key (B) | Ciphertext / Signature (B) | Security (NIST level / bits) | Source |
|---|---|---:|---:|---|---|
| **ML-KEM-512** (Kyber) | KEM | 800 | 768 (ct) | L1 (~AES-128) | FIPS 203; liboqs [1][7] |
| **ML-KEM-768** | KEM | 1,184 | 1,088 (ct) | L3 (~AES-192) | FIPS 203; liboqs [1][7] |
| **ML-KEM-1024** | KEM | 1,568 | 1,568 (ct) | L5 (~AES-256) | FIPS 203; liboqs [1][7] |
| **ML-DSA-44** (Dilithium) | Sig | 1,312 | 2,420 (sig) | L2 | FIPS 204; liboqs [2][8] |
| **ML-DSA-65** | Sig | 1,952 | **3,309** (sig) | L3 | FIPS 204; liboqs [2][8] |
| **ML-DSA-87** | Sig | 2,592 | **4,627** (sig) | L5 | FIPS 204; liboqs [2][8] |
| **SLH-DSA-128s** (SPHINCS+) | Sig | 32 | 7,856 (sig) | L1 | FIPS 205; SPHINCS+ spec [3][9] |
| **SLH-DSA-128f** | Sig | 32 | 17,088 (sig) | L1 | FIPS 205 [3][9] |
| **SLH-DSA-192s** | Sig | 48 | 16,224 (sig) | L3 | FIPS 205 [3][9] |
| **SLH-DSA-256s** | Sig | 64 | 29,792 (sig) | L5 | FIPS 205 [3][9] |
| **SLH-DSA-256f** | Sig | 64 | 49,856 (sig) | L5 | FIPS 205 [3][9] |

**Classical baselines** (bytes; raw/DER as noted):

| Scheme | Role | Public key (B) | Ciphertext / Signature (B) | Security (bits) | Source |
|---|---|---:|---:|---|---|
| **RSA-2048** | Sig/KeyTransport | 256 (modulus) | 256 (sig, = key len) | ~112 | [4][5] |
| **RSA-3072** | Sig/KeyTransport | 384 (modulus) | 384 (sig) | ~128 | [4][5] |
| **ECDSA P-256** | Sig | 64 (raw point) | 64 raw / 71–72 DER | ~128 | [5] |
| **ECDSA P-384** | Sig | 96 (raw point) | 96 raw / ~103–104 DER | ~192 | [5] |
| **X25519 (ECDH)** | KEM/KEX | 32 | 32 (peer pubkey) | ~128 | Cloudflare [6][10] |

**Cross-check correction (logged per AGENTS.md §3).** An initial web result reported
ML-DSA-65 signature = 3,293 B and ML-DSA-87 = 4,595 B. The authoritative liboqs datasheet and a
second source both give **3,309 B** and **4,627 B**; the 3,293/4,595 values appear to be a
stale/incorrect draft figure and are **not** used. ML-DSA-44 = 2,420 B agrees everywhere.

**The size story in one line.** Versus X25519 (32 B), ML-KEM-768 is ~37× larger per key. Versus
ECDSA P-256 (~64–72 B sig + 64 B key), ML-DSA-65 is ~30–50× larger; **SLH-DSA signatures are
100–800× larger** (the "huge SPHINCS+ signature" point — relevant only if the estate forces
hash-based fallback). **KEM growth is modest; signature growth is the painful one.**

### 1.2 Speed (compute)

PQC *computation* is generally **fast** — the cost is bytes, not CPU:

- **ML-KEM** runs at ~20,000–70,000 ops/sec depending on variant/role, vs X25519 ~19,000 ops/sec;
  ML-KEM key agreement is "typically significantly faster" than X25519 (Cloudflare) [6][10].
- **ML-DSA** sign/verify are competitive with or faster than RSA-2048 signing
  (RSA-2048 sign ≈ 1,500 ops/sec; ECDSA P-256 sign ≈ 30,000 ops/sec) [2][5][8]. Among PQC
  signatures, Dilithium2/ML-DSA-44 imposes the least handshake slowdown and is "commensurate with
  ECDSA-P256 at low latencies" [11].
- **SLH-DSA** signing is *slow* (hash-tree heavy), especially the small-signature `s` variants;
  this is the speed/size tradeoff baked into the `s` vs `f` naming [3][9].

**Implication for the model:** the migration *penalty* SAMAY cares about (`perf_penalty`) is
dominated by **bandwidth / handshake-size**, not raw crypto CPU. This is the empirical basis for
mapping `perf_penalty` from on-the-wire overhead %, not from ops/sec (see §3.4).

### 1.3 TLS 1.3 handshake overhead — the measured % (Tier A → drives Tier B)

The decisive, repeatedly-measured finding: **in TLS, the KEM is cheap and the signatures are
expensive.** Concrete numbers:

- **Hybrid key agreement (X25519 + ML-KEM-768)** adds ≈ **2.2–2.3 KB** to the handshake (client
  ~1.2 KB, server ~1.1 KB). Chrome measured a **~4% TLS-handshake-time slowdown** for this added
  ~2.3 KB — "practically negligible." Cloudflare reports median handshake latency moving only
  ~0.3–0.9 ms (e.g. 5.55 ms → 5.88–6.50 ms) [6][10].
- **A TLS handshake carries ~5 signatures and 2 public keys** (handshake CertificateVerify + CA
  signatures over the chain + SCTs + OCSP) [10]. The **median certificate chain today (with
  compression) is ~3.2 KB** [10].
- **Migrating those signatures to ML-DSA-44** would add **~15 KB** server→client to the handshake
  [6][10]. A depth-2 chain with ML-DSA-65 + 2 SCTs reaches **~17,500 B** of on-wire certificate
  data — a **~32×** increase over a classical Ed25519 chain (~550 B) [11].
- **Latency cliff:** ~**15% slowdown at +9 KB**; crossing the ~**10 KB** boundary (≈ initial
  congestion window / extra round-trip) can mean **>60% slowdown** [6][10]. Chrome's stated budget
  is a **≤10% handshake-time regression** [10].

**Net:** PQC key-exchange overhead is small and bounded (≈ low single-digit %); PQC
**authentication** overhead is large and *nonlinear* (cliff at the congestion-window / MTU
boundary). The overhead is effectively **bimodal** — a low KEM-side cluster and a high
signature/edge cluster — not a uniform spread. A correct `perf_penalty` distribution should
reflect that bimodality (see §3.4). Note this knob only loads the **optional** coexistence-budget
constraint used in the constrained-edge case study (`PROJECT_BRIEF.md` §3.3), so it is a *case-study*
calibration, not a driver of the headline optimal-vs-greedy gap; it is fixed here because the
current `uniform(0,0.6)` shape contradicts the measured bimodal reality, not because it is the most
impactful knob.

---

## 2. TLS / PKI prevalence and estate structure (Tier A)

For dependency-graph, criticality, and estate-shape calibration.

### 2.1 Certificate algorithm prevalence (RSA vs ECDSA)

- **RSA still dominates leaf certs but is being overtaken.** A Certificate-Transparency analysis
  put **RSA ≈ 65.5% / ECDSA ≈ 34.5%** in Q4 2025, shifting toward parity through early 2026 [12].
  **Confidence caveat (cross-check incomplete):** the *precise* split and the "ECDSA majority by
  ~May 2026" projection are **single-sourced** (one CT-analysis blog [12]); Cloudflare Radar [13]
  and CA-issuer trend reports corroborate only the **direction** (RSA-majority → ECDSA-rising), not
  the exact percentages. I could not obtain an independent primary for the precise number (Cloudflare
  Radar's algorithm-breakdown endpoint returned 403; Censys publishes methodology, not a headline
  percentage). Treat 65.5/34.5 as order-of-magnitude, not authoritative.
- **Why this doesn't threaten the calibration:** the split is **not a hard generator input.** Both
  RSA and ECDSA are quantum-vulnerable, so for SAMAY's purposes (which assets are decision variables)
  the ratio does **not** change *whether* an asset must migrate. It only informs heterogeneity of
  `cost`/`perf_penalty` (RSA vs ECC migrate to different PQC replacements with different overheads)
  and serves as a realism check. The low-confidence precision is therefore tolerable here; it would
  not be if the number drove a constraint.

### 2.2 PQC adoption (timeline realism for `earliest` / `delayed_frac`)

- **Key agreement:** PQC hybrid key exchange crossed **>50% of human-initiated Cloudflare
  traffic** by late October 2025, up from ~2% in early 2024; all major browsers enable it by
  default [6][10][14]. → PQC KEM support is **available now** for most TLS endpoints.
- **Signatures:** PQC *signature* migration "is much more difficult and will require more time" —
  it waits on public CAs issuing ML-DSA certs, which had **not** broadly shipped as of late 2025
  [10][14]. → A realistic estate has a **subset of assets (signature/PKI-side) that cannot migrate
  until a later period** — exactly what `earliest > 0` / `delayed_frac` models. This is real,
  cited grounding for delayed feasibility, not an arbitrary knob.

### 2.3 Certificate chain depth (dependency-graph shape)

- Web-PKI chains run **root → (one or more) intermediate → leaf**; measured deployments cluster at
  **depth 2 (root+leaf) and depth 3 (root+intermediate+leaf)** [11][15]. Non-leaf (CA)
  certificates contribute most of the chain's bytes [16].
- This is the canonical **CA-before-leaf precedence**: a leaf cert's trust depends on its issuing
  intermediate, which depends on the root. → **shallow dependency chains (depth ~2–3), with a few
  high-in-degree CA nodes** that many leaves point to. Direct justification for capping in-degree
  and for the hub-like structure where a small number of CAs are predecessors of many assets.

### 2.4 Estate scale and heterogeneity (size axis sanity)

- Enterprises operate **large, poorly-inventoried** crypto estates: a Keyfactor/Ponemon survey of
  600+ practitioners found an **average of ~88,750 certificates and keys per organization**, with
  **74% not knowing their exact count**, and organizations running **~9 different PKI/CA
  solutions** on average (37% > 10) [17].
- **Takeaway for the `size` axis:** estates of **hundreds to tens-of-thousands** of *distinct
  crypto usages* are realistic; the study's exact-solve sizes (≈10²–10³ assets) model a
  business-unit / application-portfolio slice, and the matheuristic targets the full
  10⁴–10⁵ estate. The "~9 CA solutions" and hub-like CA structure also justify **multiple
  co-migration clusters** (e.g. a CA + its dependent service tier, or both ends of an internal
  mTLS channel migrating together).

---

## 3. Calibration → generator parameter mapping

Maps each knob in `Calibration` / `GenParams` to its evidence basis and tier. **Bold = a
recommended change from the current value, with rationale.**

### 3.1 Criticality — `crit_log_*`, `crit_min/max`  *(shape Tier B; parameters Tier C)*

- **Current:** `lognormal(mean=3.0, sigma=0.8)`, clipped `[1,100]` ("risk points").
- **Basis:** Criticality = exposure × impact. There is **no crypto source** that yields a numeric
  1–100 score, so the *number* is a modeling abstraction. What *is* defensible is the **shape**:
  enterprise exposure is **heavy-tailed** — most crypto usages are internal/moderate, a small set
  are internet-facing crown jewels (payment, auth, root CAs). The estate-scale evidence (tens of
  thousands of certs, a handful of high-in-degree CAs §2.3–2.4) supports "many modest, few
  critical." A lognormal (or similar right-skewed) family captures this.
- **Verdict:** **Keep the lognormal shape and `[1,100]` clip; label `mean=3.0, sigma=0.8` as a
  Tier-C assumption.** `exp(3.0) ≈ 20` median with σ=0.8 gives a long upper tail clipped at 100 —
  reasonable. **Sensitivity-test `sigma ∈ {0.5, 0.8, 1.1}`** (tail heaviness changes which assets
  greedy prioritizes, so it can directly move the optimal-vs-greedy gap). Do **not** attach a
  crypto citation to `sigma`.

### 3.2 Migration cost — `cost_log_*`, `cost_min/max`  *(shape Tier B; parameters Tier C)*

- **Current:** `lognormal(mean=1.6, sigma=0.7)`, clipped `[1,40]` person-days.
- **Basis:** Per-asset PQC-migration effort in person-days is **not** available as a public
  distribution (state this plainly). The **lognormal shape is justified on first principles**:
  effort is a product of independent positive factors (code touch-points × testing surface ×
  coordination × vendor readiness), and products of positive factors are approximately lognormal;
  most migrations are small config/library swaps, a few (custom protocols, HSM-backed roots,
  embedded/edge firmware) are large. The wide spread between "rotate a cert" and "re-architect a
  bespoke handshake" is real and supported qualitatively by the deployment-difficulty gradient in
  §1.3/§2.2 (KEM swap easy; signature/PKI migration hard).
- **Verdict:** **Keep lognormal `[1,40]` person-days; label parameters Tier C.** `exp(1.6) ≈ 5`
  median, tail to 40 is a plausible "few days → a couple of person-months" range.
  **Sensitivity-test `sigma ∈ {0.5, 0.7, 1.0}`.** Cost spread interacts with budget tightness to
  determine knapsack hardness, so it is load-bearing for RQ2 and must be swept, not asserted.

### 3.3 Shelf-life — `shelf_life_tiers`  *(Tier B, with a unit caveat — see §4)*

- **Current:** tiers `(2, 0.40), (8, 0.40), (20, 0.20)` (value = periods; probability).
- **Basis (the HNDL evidence is solid):** Data that must stay confidential **≥ 5 years** is in the
  HNDL window; analyses estimate **95–100% of government-classified** and **98–100% of healthcare**
  records encrypted today are exposed to retroactive decryption [18][19]. Concrete retention
  anchors:
  - **Transient / ephemeral** (TLS session keys, short-lived tokens): secrecy needed for ~seconds
    to <1 year. The dominant *count* in a TLS estate.
  - **Medium** (business records, SOX-governed financial/audit ≈ **7 years**; HIPAA documentation
    **≥ 6 years**): ~5–10 years [20][21].
  - **Long-lived** (health records over a patient lifetime, trade secrets / M&A, government
    classified — declassification commonly **25 years**, sensitive categories longer): **decades**
    [18][19][20].
- **Mapping the three tiers:** transient / medium / long-lived ≈ **(short, ~7-yr, multi-decade)**
  with most assets short — matches "ephemeral TLS dominates by count, a long-secrecy minority drives
  HNDL." The **probabilities (0.40 / 0.40 / 0.20) are Tier C** (the *existence* and rough ordering
  of the tiers is sourced; the exact split is a modeling choice). **Sensitivity-test the mix**, and
  in particular a "transient-heavy" estate (e.g. 0.7/0.2/0.1) vs a "secrets-heavy" estate, since
  the shelf-life mix is what makes HNDL risk (and thus optimal scheduling) bite.
- **Unit/value caveat:** see **§4** — the numeric tier values interact with the period→calendar
  mapping and `t_crqc`, and the current `(2,8,20)` long tail may be too short to represent the
  decade-scale secrets the HNDL literature is about.

### 3.4 Performance penalty — `perf_min/max`  *(Tier B — recommend change)*

- **Current:** `uniform(0.0, 0.6)`.
- **Basis (Tier A → B):** measured TLS overhead (§1.3): **KEM ≈ +4% handshake (negligible);
  signatures large and nonlinear with a cliff past the ~10 KB congestion-window boundary**, and
  Chrome treats **~10%** as the tolerable regression. Mapping overhead onto a normalized `[0,1]`
  penalty (where `perf_penalty` is the asset's relative PQC/hybrid overhead used by the optional
  coexistence-budget constraint, `PROJECT_BRIEF.md` §3.3):
  - **Most assets (KEM-side / well-provisioned TLS): low penalty, ≈ 0.0–0.15** (4% handshake,
    sub-millisecond, well within budget).
  - **Signature/PKI-heavy or constrained-edge assets: high penalty, up to ≈ 0.6–1.0** (15 KB
    added, ~15% slowdown, or the >60% cliff on a constrained path).
- **Verdict / recommended change:** **`uniform(0, 0.6)` is the wrong shape — it over-weights the
  middle and never reaches the real worst case.** The measurements are **bimodal**, so a unimodal
  draw (uniform, or a single Beta) cannot represent both clusters at once. Use a **two-component
  mixture**: with probability ~0.75–0.85 draw the **low/KEM-side** component (e.g. Beta(2,8) or
  uniform `[0, 0.15]`, mass near 0); otherwise draw the **high signature/edge** component (e.g.
  uniform `[0.5, 1.0]` or Beta peaked near 0.8) to populate the costly tail. The mixture weight maps
  naturally to the asset's kind (KEM-side vs signature/PKI/constrained-edge) and ties to the same
  KEM-cheap/signature-expensive evidence as `delayed_frac` (§2.2). Whatever the exact families
  (Tier C), the **referent must be defined**: `perf_penalty = normalized handshake/bandwidth
  overhead of the asset's PQC/hybrid form, 0 = none, 1 = the >10 KB / >60%-slowdown cliff`. The
  constrained-edge case study (brief §3.3) is the only place this knob loads the coexistence-budget
  constraint, so its high component matters there specifically.

### 3.5 Dependency structure — `dep_density`, `max_in_degree`, clusters, `delayed_frac`  *(Tier B shape; Tier C parameters)*

- **`max_in_degree = 4`, binomial in-degree:** justified by **shallow PKI chains (depth ~2–3)** and
  the observation that most crypto usages depend on only a **few** predecessors (their issuing CA,
  the peer endpoint), §2.3. **Keep the cap; label the binomial `dep_density` knob Tier C** and sweep
  it (dependency density is an explicit RQ2 axis — denser graphs are where precedence makes greedy
  ordering go wrong, so this is load-bearing).
- **CA-as-hub:** real PKI has a **few high-in-degree nodes** (a CA is a predecessor of many leaves).
  The current generator builds in-degree per-node from a uniform candidate pool, which yields a
  roughly homogeneous DAG. **Recommendation (optional realism upgrade, not required for validity):**
  optionally designate a small set of "CA" assets that are forced predecessors of a leaf
  population, producing the empirically-correct hub structure and natural co-migration (CA + its
  intermediates). Log whichever choice is made.
- **Co-migration clusters (`cluster_frac`):** grounded in **both ends of a protocol / mTLS channel
  migrating together** and **a CA tier migrating with its dependent services** (§2.3–2.4). Keep;
  the 0.10 fraction is Tier C — sweepable.
- **`delayed_frac` / `earliest > 0`:** **directly cited** (§2.2) — PQC signature/CA support lands
  *later* than KEM support, so a real subset of assets is infeasible to migrate until a later
  period. `delayed_frac=0.15` is a reasonable Tier-C default; the *direction* (some assets delayed)
  is Tier A.

### 3.6 CRQC period — `t_crqc`  *(Tier B — sensitivity parameter, not a point fact)*

- **Current:** `t_crqc = 28`.
- **Basis:** The Global Risk Institute / Mosca **Quantum Threat Timeline** expert survey (the most
  cited source) puts the probability of a CRQC within **10 years at ~28–49%** (2025 report, highest
  in its 7-year history), **≥50% likely by ~15 years**, and **~92% of experts at ≥50% by 20 years**
  [22][23]. No CRQC exists in 2026. Most credible windows cluster **2030–2040** [18][22][23].
- **Verdict:** `t_crqc` is **inherently uncertain and must be a swept sensitivity parameter, never a
  single asserted date** (`PROJECT_BRIEF.md` §8 already requires this). Anchor the sweep to the
  survey: a **near** scenario (~2030–2032), a **central** scenario (~2033–2035, the survey's
  ≥50%-by-15-years mass), and a **far** scenario (~2040). Map these to periods via the
  period→calendar convention (§4). RQ5(b)'s robust/stochastic-`t_crqc` treatment can draw scenarios
  from this survey distribution — a cited, defensible scenario set.

---

## 4. FINDING: shelf-life units and the HNDL-scaling interaction (must-fix, flagged to team)

**There is a unit inconsistency that materially affects whether HNDL risk fires at all.**

- `PROJECT_BRIEF.md` §3.1 defines `shelf_life` (`s_i`) as **years**.
- `src/pqcsched/model.py` and `Calibration.shelf_life_tiers` treat it as **periods**; the brief's
  horizon example is **"quarters to 2035," T≈40**, which makes **one period ≈ one quarter**.
- The HNDL mechanic (`risk.py`, brief §10.2) fires **full** risk when `t + shelf_life >= t_crqc`,
  with `t_crqc = 28`.

**The problem.** If a period is a quarter, the longest shelf-life tier (`20` periods) is only
**~5 calendar years**, and at encryption time `t = 0` the maximum `0 + 20 = 20 < 28 = t_crqc` —
so **data encrypted in the early periods never reaches full HNDL risk under any tier.** That
**structurally mutes the canonical HNDL case** (10–50-year secrets — health, classified, genomic —
encrypted *today*), which §1–§3 show is precisely the population PQC migration exists to protect.
The model would then under-weight exactly the assets HNDL is about, biasing the study.

**Why it matters for the paper.** HNDL-driven urgency is what gives *optimal* scheduling something
to exploit over deadline-only greedy ordering. If long-secrecy assets can't accrue full risk, the
risk objective flattens and the optimal-vs-greedy comparison is run on a weakened version of the
very effect under study. This is a realism/validity issue, not cosmetic.

**Recommended resolution (pick one; log it in `PROGRESS.md`/`REPORT.md`).** The period length is
**not pinned anywhere in the repo** — team-lead authorized choosing a reasonable assumption and
logging it. Options:

1. **Period = 1 year (simplest, recommended).** Then `T≈10–15` to 2035–2040, tiers `(2, 8, 20)`
   read directly as **2 / 8 / 20 years** (transient-ish / medium / long), and `t_crqc≈7–14` maps
   to 2033–2040. Long-secrecy data encrypted now (`0 + 20 ≥ 14`) **does** reach CRQC — HNDL fires
   correctly. Clean calendar story; loses intra-year scheduling granularity.
2. **Keep period = quarter (T≈40) but lengthen the long tail and align `t_crqc`.** Make the
   long-lived tier represent decades: e.g. tiers `(4, ~30, ~80)` quarters ≈ `(1, 7.5, 20)` years,
   and set `t_crqc` to the calendar-correct quarter (2035 ⇒ period ≈ 36–40 from a 2026 start).
   Preserves quarter granularity; requires re-deriving every period-valued constant.

Either way: **state the period→calendar mapping explicitly**, make the long tail span the
**decade-scale** secrecy the HNDL literature documents (§3.3), and **re-derive `t_crqc` in the same
units**. Then sensitivity-test the shelf-life mix and `t_crqc` together (they jointly control HNDL),
as already required by §8.

**(Assumption logged.)** Until the team decides, this document calibrates *conditional on* the
period length: shelf-life and `t_crqc` ranges above are given in **calendar years**; convert to
periods once the period length is fixed.

---

## 5. Summary of recommended changes

| Knob | Current | Recommendation | Tier | Why |
|---|---|---|---|---|
| `shelf_life_tiers` + units | `(2,8,20)` periods | Resolve period↔year mapping; ensure long tail = **decades**; re-derive `t_crqc` same units | B + finding | HNDL never fully fires today otherwise (§4) |
| `perf_min/max` | `uniform(0,0.6)` | **Two-component mixture**: ~80% low (KEM-cheap, ≈0–0.15) + ~20% high (sig/edge, ≈0.5–1.0); define referent | B | KEM cheap, signatures large + nonlinear cliff; overhead is bimodal (§1.3) |
| `t_crqc` | `28` (fixed) | Treat as **swept** near/central/far (~2030/2033–35/2040) per Mosca survey | B | CRQC date is uncertain, survey-bounded (§3.6) |
| `crit_log_sigma` | `0.8` | Keep shape; **sweep {0.5,0.8,1.1}**; label Tier C | C | No crypto source for the number (§3.1) |
| `cost_log_sigma` | `0.7` | Keep lognormal; **sweep {0.5,0.7,1.0}**; label Tier C | C | Effort=product of factors ⇒ lognormal; no public person-day data (§3.2) |
| in-degree / CA hubs | homogeneous DAG, cap 4 | Keep cap; **optionally** add CA-hub nodes for realism; sweep `dep_density` | B/C | Shallow PKI chains + few high-in-degree CAs (§2.3) |
| `delayed_frac`/`earliest` | `0.15` | Keep; direction is **cited** (sig support lags KEM) | A dir / C param | PQC sig/CA support ships later than KEM (§2.2) |

**Bottom line for the study's defensibility:** the size/perf/prevalence facts (§1–§2) are Tier-A
and solid; the generator's *shapes* (heavy-tailed criticality/cost, transient-dominant shelf-life,
shallow-chain dependencies, KEM-cheap/signature-expensive perf) are evidence-grounded; the exact
distribution *parameters* are honest Tier-C modeling choices that the §8 sensitivity sweep must
exercise. The one substantive correction is `perf_penalty`'s shape; the one must-fix is the
shelf-life/`t_crqc` unit alignment (§4).

---

## Sources

1. NIST FIPS 203, *Module-Lattice-Based Key-Encapsulation Mechanism Standard* (ML-KEM). https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.203.pdf
2. NIST FIPS 204, *Module-Lattice-Based Digital Signature Standard* (ML-DSA). https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.204.pdf
3. NIST FIPS 205, *Stateless Hash-Based Digital Signature Standard* (SLH-DSA). https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.205.pdf
4. Mbed-TLS / Wikipedia *Key size* — RSA modulus & signature length (= key length). https://en.wikipedia.org/wiki/Key_size
5. SSL.com / PyCryptodome / The Copenhagen Book — ECDSA P-256 raw (64 B) vs DER (71–72 B), RSA-2048 sig (256 B), security-level equivalences. https://www.ssl.com/article/comparing-ecdsa-vs-rsa/ ; https://thecopenhagenbook.com/cryptography/ecdsa
6. Cloudflare, *The state of the post-quantum Internet* (Feb 2024) — hybrid sizes, ~2% adoption, 15 KB ML-DSA, latency cliff. https://blog.cloudflare.com/pq-2024/
7. Open Quantum Safe — liboqs ML-KEM datasheet (pk/ct byte sizes). https://openquantumsafe.org/liboqs/algorithms/kem/ml-kem.html
8. Open Quantum Safe — liboqs ML-DSA datasheet (pk/sig byte sizes; corrected 3,309 / 4,627). https://openquantumsafe.org/liboqs/algorithms/sig/ml-dsa.html
9. SPHINCS+ / SLH-DSA signature sizes (7,856–49,856 B across parameter sets). https://en.wikipedia.org/wiki/SPHINCS%2B
10. Cloudflare, *State of the post-quantum Internet in 2025* — "5 signatures + 2 public keys," median chain 3.2 KB, Chrome +4% / ≤10% budget, 15 KB ML-DSA-44. https://blog.cloudflare.com/pq-2025/
11. *Signature Placement in Post-Quantum TLS Certificate Hierarchies* (arXiv 2604.06100 / eprint 2026/666) — depth-2 ML-DSA-65 chain ≈ 17,500 B (~32× Ed25519); Dilithium2 ≈ ECDSA-P256 slowdown. https://arxiv.org/abs/2604.06100
12. TechnologyChecker.io — CT analysis: RSA 65.5% / ECDSA 34.5% (Q4 2025) trending to parity 2026. **Single-sourced for the precise split/projection — see §2.1 confidence caveat; direction only is corroborated by [13].** https://technologychecker.io/blog/ssl-certificate-transparency-report-insights
13. Cloudflare Radar — CT / TLS algorithm insights (RSA-majority → ECDSA trend). https://blog.cloudflare.com/new-regional-internet-traffic-and-certificate-transparency-insights-on-radar/
14. postquantum.com — Cloudflare PQC majority-traffic (>50% by late Oct 2025); PQC signatures await CA support. https://postquantum.com/industry-news/cloudflare-pqc-majority-traffic/
15. Web-PKI chain structure (root→intermediate→leaf; depth 2–3 measured). TLS measurement (university servers). https://arianniaki.github.io/TLSprobing/cert.html
16. *On the Interplay between TLS Certificates and QUIC Performance* (arXiv 2211.02421) — non-leaf certs dominate chain bytes; median chain ~2.3 KB (QUIC) / ~4 KB. https://arxiv.org/abs/2211.02421
17. Keyfactor / Ponemon, *State of Machine Identity* — avg ~88,750 certs+keys/org, 74% unknown count, ~9 CA solutions. https://www.keyfactor.com/blog/new-ponemon-survey-why-most-people-think-their-pki-cannot-scale/
18. *Harvest Now, Decrypt Later: A Time-Dependent Threat Model…* — ≥5-yr-secrecy data in HNDL window; 95–100% gov-classified / 98–100% healthcare exposed; CRQC 2030–2040. https://www.researchgate.net/publication/400298687
19. Wikipedia, *Harvest now, decrypt later* + NSA CNSA 2.0 rationale (long-lived classified data). https://en.wikipedia.org/wiki/Harvest_now,_decrypt_later
20. HIPAA Journal — HIPAA documentation retention ≥6 years; state-law variation for medical records. https://www.hipaajournal.com/hipaa-retention-requirements/
21. Sarbanes-Oxley (SOX) — audit/review records retained 7 years. (Via data-retention compliance guides.) https://www.ispartnersllc.com/blog/standards-developing-data-retention-policy/
22. Global Risk Institute, *Quantum Threat Timeline Report 2025* (Mosca & Piani) — CRQC 10-yr ~28–49%, ≥50% by ~15 yr, ~92% ≥50% by 20 yr. https://globalriskinstitute.org/publication/quantum-threat-timeline-report-2025b/
23. evolutionQ / postquantum.com summaries of the Quantum Threat Timeline survey. https://postquantum.com/security-pqc/quantum-threat-timeline-report-2025/

---
*Calibration document for `pqcsched.generate`. Tier-A facts cross-checked; Tier-C parameters
labelled as sweepable modeling choices, not empirically pinned. One must-fix (§4) and one shape
correction (§3.4) recommended. — researcher-crypto, June 2026.*
