# SAMAY / pqcsched — PQC Migration Timelines, CRQC Estimates, and Related Work

**Author:** `researcher-policy` (SAMAY team) · **Date:** 15 June 2026
**Purpose:** Give SAMAY a defensible, cited basis for (A) mapping model periods → real calendar dates and setting `t_crqc` / regulatory deadlines, and (B) positioning the paper's novelty claim accurately.

> **Method note.** Every load-bearing claim was cross-checked against at least two sources, and primary documents (NIST IR 8547 PDF, India DST report PDF, arXiv full texts via ar5iv) were read directly where possible. The brief (`PROJECT_BRIEF.md`) was treated as a **hypothesis to verify, not ground truth**. Three brief claims were corrected by this verification; they are flagged inline with **[BRIEF CORRECTION]**. Unknowns and figures that are ranges (not points) are flagged rather than hardened into false precision.

---

## 0. Executive summary (the three things that changed)

1. **Standards/timeline claims SURVIVE and are now primary-sourced.** FIPS 203/204/205 (13 Aug 2024); NIST IR 8547 IPD (12 Nov 2024) with RSA/ECC **deprecated after 2030, disallowed after 2035** (verbatim table + definitions below); CNSA 2.0 per-category 2025/2026/2027/2030/2033 chart (reproduced). NSM-10 sets **2035** as the federal completion target.
2. **[BRIEF CORRECTION] The "Quantum Readiness Index" is Singapore's, not India's.** India's National Quantum Mission DST Task Force report (4 Feb 2026) is real and strong — it mandates cryptographic inventory, dependency discovery/assessment, CBOM-in-procurement, and a phased *risk-prioritized* migration (CII by 2029, enterprises by 2033) — but it does **not** brand its own "Quantum Readiness Index." That named instrument belongs to **Singapore's CSA** (Oct 2025), which India's report cites as a model. Both are excellent motivation for SAMAY; the paper must attribute them correctly.
3. **The novelty claim SURVIVES adversarial stressing.** No combinatorial-optimization / MILP / CP / scheduling formulation of *estate* migration exists. The closest works are (a) the patent family (per-asset, ML-based *algorithm selection*, not estate scheduling), (b) arXiv:2408.05997 (a formal *definitional/complexity* model — migration graph + strongly-connected-component clusters + condensation DAG, **explicitly no optimization layer**), and (c) qualitative timeline/strategy frameworks (MDPI, NIST CSWP 39, national roadmaps). SAMAY's optimization layer sits in a genuine gap, and arXiv:2408.05997 is the formalization our dependency/cluster constraints build directly upon.

**Horizon flag for the modelers (load-bearing):** a credible *conservative* `t_crqc` lands ~2039–2044, **outside** a 2025→2035 horizon. To keep the `t_crqc` sensitivity sweep (RQ5b) non-degenerate, extend the model horizon to **~2045 (≈80 quarterly periods)**, not 2035. Details in §6.

---

## A. Timelines, standards, and CRQC estimates

### A.1 NIST PQC standards — FIPS 203 / 204 / 205 (FINAL)

Published as final Federal Information Processing Standards on **13 August 2024** (Secretary of Commerce approval; effective same date):

| FIPS | Title | Algorithm | Basis | Status / Date |
|---|---|---|---|---|
| **203** | Module-Lattice-Based Key-Encapsulation Mechanism Standard | **ML-KEM** | CRYSTALS-Kyber | Final, 2024-08-13 |
| **204** | Module-Lattice-Based Digital Signature Standard | **ML-DSA** | CRYSTALS-Dilithium | Final, 2024-08-13 |
| **205** | Stateless Hash-Based Digital Signature Standard | **SLH-DSA** | SPHINCS+ | Final, 2024-08-13 |

(A fourth standard, FIPS 206 / FN-DSA from FALCON, was still forthcoming as of this writing.) Sources: [1], [2].

### A.2 NIST IR 8547 — "Transition to Post-Quantum Cryptography Standards" (Initial Public Draft)

- **Status / date:** Initial Public Draft, **12 November 2024** (CSRC landing page [3]; one secondary lists "Nov 14" [4] — the CSRC date governs). Not yet finalized as of June 2026.
- **Definitions (verbatim, from the IPD PDF [5]):**
  - *"**Deprecated** means that the algorithm and key length/strength may be used, but there is some security risk… the data owner must examine this risk potential and decide whether to continue to use a deprecated algorithm or key length."*
  - *"**Disallowed** means that the algorithm, key length/strength, parameter set, or scheme is no longer approved for the indicated use."*
- **Transition table (verbatim from the IPD PDF [5]):**

| Algorithm family | Security strength | Transition |
|---|---|---|
| **ECDSA** [FIPS 186] | 112 bits | **Deprecated after 2030; Disallowed after 2035** |
| **ECDSA / EdDSA** [FIPS 186] | ≥128 bits | **Disallowed after 2035** |
| **RSA** (signatures) [FIPS 186] | 112 bits | **Deprecated after 2030; Disallowed after 2035** |
| **Finite-Field DH & MQV** [SP 800-56A] | 112 bits | **Deprecated after 2030; Disallowed after 2035** |
| **Elliptic-Curve DH & MQV** [SP 800-56A] | 112 bits | **Deprecated after 2030; Disallowed after 2035** |

  Net: **all quantum-vulnerable public-key crypto (RSA/ECC/DH) is deprecated after 2030 and disallowed after 2035** in NIST standards. NSM-10 establishes **2035 as the primary target** for completing the migration across U.S. federal systems [5]. Sources cross-checked: [3], [4], [5], [6].

### A.3 CNSA 2.0 (NSA / CNSS) — per-category transition timeline

CNSA 2.0 algorithms: **ML-KEM-1024** (key establishment, all classification levels), **ML-DSA-87** (general signatures), **LMS/XMSS** (firmware/software signing), **AES-256**, **SHA-384/512** [7], [8]. The transition is a **per-category chart** (not one date) — reproduced from NSA's CSI and consistent secondaries [7], [9], [10]:

| Technology category | Support & prefer CNSA 2.0 | Exclusive use |
|---|---|---|
| Software & firmware signing | **2025** | 2030 |
| Web browsers / servers / cloud services | 2025 | **2033** |
| Traditional networking (VPN, routers) | **2026** | 2030 |
| Operating systems | **2027** | 2033 |
| Niche / constrained devices, large PKI | 2030 | 2033 |
| Custom applications & legacy equipment | (update/replace) | **2033** |

> **Modeling note.** The brief's "2025/2027/2030/2033" maps to *different columns* of this chart. Treat each category as a distinct **deadline class** `D_i` in the generator (signing assets get the earliest deadlines; custom apps the latest). Flattening them to one date misplaces deadlines.

### A.4 Other jurisdictions (brief, for the related-work breadth)

- **EU — NIS Cooperation Group**, *Coordinated Implementation Roadmap* (June 2025): phased milestones at **2026 / 2030 / 2035** [11].
- **Germany — BSI**: PQC for critical infrastructure by **2030**, others by **2032**; mandates **hybrid** key exchange (FrodoKEM, Classic McEliece as conservative fallbacks) [12], [11].
- **France — ANSSI**: phased; **hybrid** for both KEM and signatures; quantum resistance becoming a required security property post-2025 [12].
- **UK — NCSC**: published *Timelines for migration to post-quantum cryptography* (discovery → high-priority migration → completion by 2035) [13].
- **Singapore — CSA**: *Quantum-Safe Handbook* + **Quantum Readiness Index (QRI)**, public consultation 23 Oct – 31 Dec 2025 (see §A.6) [14], [15].

### A.5 India — National Quantum Mission (NQM) / DST Task Force **[BRIEF CORRECTION]**

**Confirmed primary source** (read directly from the DST PDF [16], [17]):
- **Title:** *Implementation of Quantum Safe Ecosystem in India — Report of the Task Force*, **February 2026** (dated 4 Feb 2026). Under the **National Quantum Mission**. Task Force chaired by **Dr. Rajkumar Upadhyay** (CEO, C-DOT); sub-groups led by the **Telecommunication Engineering Centre (TEC/DoT)** and the **Data Security Council of India (DSCI)**.
- **What it actually mandates** (verbatim fragments from the PDF):
  - Phased, risk-prioritized roadmap: **"Milestone 3 — Full PQC Adoption — CII: by 2029 | Enterprises: by 2033"**; for CII, *"Foundations by 2027, High-Priority Migration by 2028, and Full PQC Adoption by 2029"*; other enterprises follow *"2028, 2030, and 2033"* and *"complete discovery and assessment of cryptographic dependencies by 2028, migrate high-priority systems by 2031"*.
  - **Cryptographic inventory + dependency discovery/assessment** as a foundational requirement.
  - **CBOM in procurement:** *"Require all suppliers to submit CBOMs and PQC roadmaps for the products you plan to procure."*
  - **Crypto-agility monitoring** (e.g., demonstrated under IEC 62443 for OT), and **Assurance Levels L1–L4** (L4 = sovereign/national critical infrastructure).
  - It accurately restates the U.S. timeline: *"RSA-2048 and ECC-256 are expected to be deprecated around 2030 and fully disallowed after 2035."*

> **[BRIEF CORRECTION]** The brief states India's NQM roadmap *"explicitly calls for a Quantum Readiness Index to assess exposure and prioritize migration steps."* **Verified false as stated.** The DST report's *only* four occurrences of "Quantum Readiness Index" all **cite Singapore's CSA QRI as exemplary practice** (e.g., *"In 2025, the Cyber Security Agency of Singapore released a Quantum-Safe Handbook and a Quantum Readiness Index… Singapore Operational readiness tooling… turn policy into measurable action"*). India mandates the **equivalent functional capability** (inventory, dependency discovery/assessment, risk-prioritized phasing, CBOM-in-procurement, assurance levels) but **does not brand its own "Quantum Readiness Index."**
> **How to cite in the paper:** *"National programs are now mandating exactly the inputs SAMAY consumes and the decisions it optimizes: India's National Quantum Mission requires cryptographic inventory, dependency discovery, CBOM-in-procurement and a phased, risk-prioritized migration (CII by 2029, enterprises by 2033) [India-DST]; Singapore's CSA Quantum Readiness Index and Quantum-Safe Handbook call explicitly for 'risk-based prioritisation' and 'phased-migration planning' [SG-CSA]."* This is **stronger** than the original framing (two national programs, correctly attributed) and removes a factual error a reviewer would catch.

### A.6 Singapore CSA — Quantum Readiness Index (the actual QRI)

- **Quantum Readiness Index (QRI):** a **self-assessment tool** for system owners/security practitioners to gauge readiness, **prioritise key actions**, and brief senior management; covers **five domains** — Governance, Risk Assessment, Training & Capability, External Engagement, Technology & Agility [14], [15].
- **Quantum-Safe Handbook** (CSA + GovTech + IMDA): covers *"discovery of cryptographic assets, **risk-based prioritisation, phased-migration planning**, and post-migration monitoring."* Public consultation **23 Oct – 31 Dec 2025** [14], [15].
- **Why this matters for SAMAY:** a national cyber authority explicitly names "risk-based prioritisation" and "phased-migration planning" as the task — which is precisely what SAMAY *automates and proves optimal*. The QRI is a qualitative maturity/checklist instrument; SAMAY is the quantitative engine that turns that policy intent into a provably optimal schedule.

### A.7 CRQC arrival estimate (for `t_crqc`)

**Primary source: Global Risk Institute, *Quantum Threat Timeline Report 2024* (Mosca & Piani, evolutionQ; 6th annual edition; 32 experts surveyed)** [18], [19], [20].

Expert-elicited probability that a **CRQC capable of breaking RSA-2048 within 24 hours** exists within a given horizon (reported as ranges across optimistic→pessimistic experts; cross-checked [18] vs [19], [20]):

| Horizon (from ~2024) | ≈ Calendar | Reported likelihood |
|---|---|---|
| 5 years | ~2029 | **5–14%** (≈14% at the pessimistic end) |
| 10 years | ~2034 | **19–34%** |
| 15 years | ~2039 | **~50–55%** (point estimates near 55%) |
| 20 years | ~2044 | **~75–79%** |

- **Mosca's inequality / theorem** frames the *decision*, not the date: if **X** = how long data must stay secret (shelf-life `s_i`), **Y** = migration time, **Z** = time until a CRQC exists, then **you are already too late whenever X + Y > Z**. This is the formal justification for SAMAY's HNDL-aware, time-integrated risk objective — HNDL risk is exactly the `X + Y > Z` regime made quantitative per asset [21].
- **Two distinct "central" anchors — keep them separate (a reviewer will):**
  - **Threat-estimate median ≈ 2038.** GRI 2024 gives ~34% by 2034 and ~55% by 2039, so the 50% crossover is ~2038. This is the honest *expert-survey* central value.
  - **Policy-anchored / precautionary ≈ 2035.** The date federal (NSM-10), EU, and most national programs build around. Earlier than the survey median *by design* (precaution).
  - **Recommendation:** run the headline case at the **precautionary `t_crqc = 2035 (p=40)`** because that is what regulators assume and it is the conservative-planning choice; **report the survey-median `2038 (p≈52)` as the primary sensitivity point**, and state explicitly that an earlier `t_crqc` biases the case toward HNDL urgency (so 2035 is the *cautious*, not the *expected*, value). Do **not** call 2035 the "expected" CRQC date — call it precautionary/policy-anchored.
- **Sweep:** **Low (aggressive) 2030 (p=20)** · **Precautionary 2035 (p=40)** · **Survey-median 2038 (p≈52)** · **High (conservative) 2040–2044 (p=60–76)**. See §6.

---

## B. Related work and positioning

### B.1 EUROCRYPT 2026 — MAgiCS workshop (CONFIRMED)

*Workshop on Migration and Agility in Cryptographic Systems (MAgiCS 2026)*, **first edition**, affiliated event of EUROCRYPT 2026, **Sapienza University of Rome, 10 May 2026**; Springer proceedings published [22], [23], [24], [25]. The CfP frames cryptographic migration (especially post-quantum) as *"a challenging and **largely unsolved** task in practice,"* at the intersection of applied IT and cryptographic engineering. **Takeaway:** the venue exists *because* migration modeling is open — direct support for SAMAY's premise.

**Full program scanned directly [23] (this is the sharpest novelty check — same topic, same field, one month before this work):**
- *CBOMs:* "The Anatomy of Cryptography Bills of Materials…" (Hess); "Architecture-Derived CBOMs for Cryptographic Migration…" (Raab).
- *Migration:* **"A Formal Model and Lower-Bound Intuition for Cryptographic Migration" (Loebenberger)** — the arXiv:2408.05997 line (definitional/complexity, **no optimization**); "A Study of PQC Migration Frameworks" (Nzetchuen) — qualitative survey; "Supporting Cryptographic Migration with an IT Infrastructure Digital Twin" (Herzinger) — tooling.
- *Benchmarking:* "…Pitfalls and Methodology in ML-DSA Benchmarking" (Riou).
- *Agility:* "Policy Externalization in 5G-PKI…" (Paudel); "Cryptographic Agility for Applications: An Assessment Framework and Principled API Design" (Messmer); "Post-Quantum Blockchains with Agility in Mind" (Santos).

**Verified: NOT ONE talk presents a combinatorial-optimization / MILP / CP / scheduling formulation of which assets to migrate in which order/period.** The program is CBOM tooling + formal/complexity models + qualitative frameworks + benchmarking + agility APIs. This is the strongest available confirmation of SAMAY's gap.

### B.2 arXiv:1909.07353 — "Identifying Research Challenges in PQC Migration and Cryptographic Agility"

Computing Community Consortium (CCC) workshop report; submitted **16 Sept 2019** (workshop 31 Jan–1 Feb 2019); lead authors incl. **David Ott, Christopher Peikert** et al. [26]. It identifies PQC migration and the *"new science of cryptographic agility"* as open challenges spanning theory, applied cryptography, and real-world deployment, anchored on the core risk that *"failure to transition before sufficiently powerful quantum computers are realized will jeopardize the security of public key cryptosystems."*

> **[BRIEF CORRECTION / soften]** The brief paraphrases this paper as calling to treat *"the migration time horizon explicitly as a first-order design parameter."* I could **not** confirm that exact phrasing in the abstract or via the accessible full text; treat it as the brief's *characterization of the paper's spirit*, not a verbatim quote. **Recommendation:** cite the paper for *establishing migration + agility as open research challenges*, and make the "time horizon as a first-class decision variable" point in SAMAY's own voice (it is, in fact, our contribution — the time-indexed `y_{i,t}` and HNDL-over-`t_crqc` objective). Do not attribute that exact phrase to [26] in quotation marks.

### B.3 arXiv:2408.05997 — "On the Formalization of Cryptographic Migration" (the formalization we build on)

Authors: **Loebenberger, Gazdag, Herzinger, Hirsch, Näther, Steghöfer**; v1 **12 Aug 2024**, latest v4 31 Jul 2025 [27], [28]. Read in full via ar5iv. **This is the paper our dependency/cluster constraints cite.** Its formal model (Sections: *A Formal Model of the Migration Problem* → *Migration is Hard in General* → *Real-World Dependencies* → *Practical Implications*):

- **Migration graph.** *"Consider a finite set V of components… If the migration of a component v∈V depends on the migration of a component w∈V, we write v→w… Collecting all such dependencies in a set E (without loops) gives us the migration graph G=(V,E)."* → **This is SAMAY's dependency edge set `deps` (precedence `j→i`).**
- **Migration clusters = strongly connected components.** *"The migration cluster c(v) of v is the set of all components w∈V such that w∈dep(v) and v∈dep(w),"* i.e., components that *"have to be migrated at the same time… due to mutual dependencies."* → **This is exactly SAMAY's co-migration cluster constraint `y_{i,t}=y_{j,t}`.**
- **Condensation DAG.** The condensation `G/c` over clusters is proven **acyclic** (their Lemma 3) → the precedence structure SAMAY's `done_{i,t} ≤ done_{j,t}` constraints assume is *well-founded*.
- **It contains NO optimization, scheduling, cost, or MILP/CP formulation.** It is **definitional + complexity-theoretic** — it proves cryptographic migration has a certain "expected complexity" using combinatorics/probability, with GitLab-PQC and power-grid case studies. **This is the precise seam SAMAY fills:** 2408.05997 gives the *structure* (graph, clusters, DAG); SAMAY adds the *decision layer* (when to migrate each asset/cluster, under budget/deadline/HNDL, provably optimally).

> **Cite as:** *"We adopt the migration-graph formalization of Loebenberger et al. [2408.05997] — components V, dependency edges E, and migration clusters as strongly connected components whose condensation is acyclic — and extend it from a descriptive/complexity model into a prescriptive optimization: a time-indexed schedule minimizing HNDL-aware residual risk subject to budget, earliest-feasibility, regulatory-deadline, precedence, and co-migration-cluster constraints. To our knowledge this optimization layer is novel."*

### B.4 The novelty claim — adversarial check (SURVIVED)

**Claim:** no combinatorial-optimization / MILP / CP / scheduling formulation of PQC *estate* migration exists; prior art is qualitative strategy / timeline-synthesis / dependency-graph formalization, plus a patent family on *per-asset algorithm selection* (not estate scheduling).

**I actively tried to falsify it** across: arXiv + Scholar searches for PQC migration × {MILP, integer programming, constraint programming, scheduling, knapsack}; "crypto agility" × optimization; the MAgiCS 2026 program; cite-chasing 2408.05997; and the patent family. What I found, and why none breaks the claim:

| Prior art found | What it is | Why it does **not** break the claim |
|---|---|---|
| **Patent family** "Systems and methods for post-quantum cryptography optimization" (US 11,322,050; 11,727,829; 11,240,014; 11,477,016; 11,750,378; 11,727,310; 12,073,300) [29] | ML model selects a PQC algorithm **per asset** from data attributes + risk profile + performance | **Per-asset *algorithm selection*, not estate *scheduling*.** No multi-period schedule, no budget-over-time, no dependency/precedence optimization, no Pareto risk-cost frontier. Exactly the carve-out the brief states. |
| **arXiv:2408.05997** [27] | Formal/complexity model (graph, SCC clusters, DAG) | **Descriptive, not prescriptive — no optimization at all** (§B.3). We build on it. |
| **MDPI Computers 15(1):9**, "Enterprise Migration to PQC: Timeline Analysis and Strategic Frameworks" [30] (read via secondary summary; full text Cloudflare-blocked) | **Qualitative** timeline analysis + strategic frameworks; enterprise migration durations (5–15+ yrs) | **No MILP/CP/scheduling model, no objective+constraints, no Pareto frontier.** This is the "qualitative strategy / timeline-synthesis" category named in the brief. *(Flag: I read summary only; if cited as a contrast, verify full text first.)* |
| **NIST CSWP 39**, "Considerations for Achieving Crypto Agility" [31]; NCCoE *Migration to PQC* project | Strategy/practice survey; tooling to *find & prioritize* vulnerable systems | Qualitative guidance + discovery/prioritization tooling; **no formal optimization of a multi-period schedule.** |
| National roadmaps (NIST IR 8547, CNSA 2.0, EU NIS, BSI, ANSSI, NCSC, India DST, Singapore QRI) | Policy timelines, maturity indices, checklists | **Set the deadlines/constraints SAMAY consumes; none computes an optimal schedule.** They are SAMAY's *inputs*, not competitors. |

**Verdict: the novelty claim survives.** Honest scoping for the paper: *the contribution is the **first combinatorial-optimization (time-indexed MILP/CP) formulation of PQC estate migration scheduling** — HNDL-aware time-integrated risk objective, budget/deadline/precedence/cluster constraints, Pareto risk-cost frontier — together with an open benchmark and an honest optimal-vs-greedy study.* We are **not** the first to formalize migration dependencies (that is [27]), nor to select per-asset algorithms (that is [29]); we are the first to **optimize the schedule of the whole estate over time.** State this precisely — over-claiming "first formalization of migration" would be wrong and [27] would refute it.

---

## 6. Period mapping and `t_crqc` (for the modelers)

**Recommended grid (defensible, deadline-aligned, sweep-safe):**

- **Period 0 = 2025-Q1.** **Period length = 1 quarter.** Period index `p` ↔ calendar via `year = 2025 + p//4`, `quarter = (p%4)+1`.
- **Horizon T = 80 periods (2025-Q1 … 2044-Q4 ≈ 2045).** **[BRIEF CORRECTION]** The brief's "quarters to 2035, ~40 periods" is **too short**: the conservative `t_crqc` (~2040–2044) and the GRI high estimate (~2044) fall *outside* a 2035 horizon, which would make the high-`t_crqc` sensitivity cell **degenerate** (no HNDL pressure, deadline-only). T≈80 keeps the entire `t_crqc` sweep and the shelf-life windows inside the horizon. (If solve time at T=80 is prohibitive for exact CP-SAT on large estates, use a coarser tail or rolling-horizon decomposition for the post-2035 periods — but keep `t_crqc` representable.)

**Where the real deadlines land (deadline classes `D_i`):**

> **Deadline convention — pick one and apply it consistently.** A policy that says *"by YEAR"* or *"exclusive use by YEAR"* is satisfied if migration completes any time in that year. The table below maps such deadlines to the **last period of the year** (`D_i = year_start + 3`, i.e., YEAR-Q4) — the *least* strict, most faithful reading of "by end of YEAR." A *"deprecated/disallowed **after** YEAR"* rule (NIST IR 8547) means the algorithm is still permitted through YEAR and prohibited from YEAR+1, so it maps to **YEAR-Q4 / (YEAR+1)-Q1**. **Do not** map "by 2030" to 2030-Q1 (p=20) — that is a full year stricter and silently inflates deadline pressure. Indices below use the **end-of-year** convention; adjust uniformly if you prefer start-of-year, but never mix.

| Event | Calendar | Period index `p` (end-of-year convention: YEAR → YEAR-Q4 = `4·(YEAR−2025)+3`) |
|---|---|---|
| India CII: Full PQC adoption | by 2029 | **19** (2029-Q4) |
| CNSA: firmware/software signing exclusive | by 2030 | **23** (2030-Q4) |
| CNSA: networking (VPN/routers) exclusive | by 2030 | **23** (2030-Q4) |
| EU NIS roadmap mid-milestone; BSI critical-infra | by 2030 | **23** (2030-Q4) |
| NIST IR 8547: RSA/ECC **deprecated** | after 2030 | **23 → 24** (permitted through 2030-Q4, prohibited from 2031-Q1) |
| CNSA: OS / browsers / cloud / niche-PKI exclusive | by 2033 | **35** (2033-Q4) |
| India: enterprise full PQC adoption | by 2033 | **35** (2033-Q4) |
| NIST IR 8547: RSA/ECC **disallowed**; NSM-10 federal completion | after 2035 | **43 → 44** (permitted through 2035-Q4, prohibited from 2036-Q1) |

**Where `t_crqc` lands (sweep — note "precautionary" ≠ "expected"; see §A.7):**

| `t_crqc` scenario | Calendar | Period index | Basis |
|---|---|---|---|
| **Low (aggressive)** | 2030 | **20** | GRI ~5–14% by 2029; worst-case planning |
| **Precautionary / policy-anchored** (recommended headline) | **2035** | **40** | Date NSM-10/EU/national policy is built around (cautious, *not* the survey median) |
| **Survey-median** (primary sensitivity point) | **2038** | **≈52** | GRI 50% crossover (~34% by 2034, ~55% by 2039) |
| **High (conservative)** | 2040–2044 | **60–76** | GRI ~55% (2039) → ~79% (2044) |

> **Sweep non-degeneracy check (do this in code).** For HNDL pressure to exist in a given `t_crqc` cell, some assets must have `(encrypt_period + shelf_life) ≥ t_crqc`. With shelf-life `s_i` drawn over, say, 3–25 years (12–100 periods) and encryption ongoing across the horizon, the **precautionary (p=40)**, **survey-median (p≈52)**, and **low (p=20)** cells are strongly HNDL-active. The **high (p=60–76)** cell only has HNDL pressure for **long-shelf-life assets** (those with `s_i` reaching into the 2040s); short-shelf-life assets see deadline-only pressure there. That is a *valid* and *interesting* regime (it isolates regulatory-deadline-driven scheduling from HNDL-driven scheduling) — just report it knowingly, and ensure the shelf-life distribution includes a long-lived tail so the high-`t_crqc` cell is not empty.

**Calibration pointers** (for `generate.py`, all citable here): deadline classes → CNSA 2.0 chart (§A.3) + IR 8547 (§A.2); shelf-life `s_i` long tail → HNDL/Mosca framing (§A.7); `t_crqc` → GRI 2024 (§A.7); PQC performance penalty `π_i` (ML-DSA/ML-KEM handshake/size overhead vs ECDSA/ECDH) → FIPS 204/203 parameter sizes [1] (a dedicated perf-calibration pass is recommended, separate from this policy doc).

---

## Sources

1. NIST CSRC — FIPS 203/204/205 approved (Aug 13 2024): https://csrc.nist.gov/news/2024/postquantum-cryptography-fips-approved
2. NIST PQC project: https://csrc.nist.gov/projects/post-quantum-cryptography
3. NIST IR 8547 (IPD) landing page (date/status): https://csrc.nist.gov/pubs/ir/8547/ipd
4. PostQuantum.com — NIST IR 8547 explainer: https://postquantum.com/security-pqc/nist-ir-8547-ipd/
5. NIST IR 8547 IPD full PDF (table + definitions, read directly): https://nvlpubs.nist.gov/nistpubs/ir/2024/NIST.IR.8547.ipd.pdf
6. Quantum Security Defence — IR 8547 timeline: https://quantumsecuritydefence.com/insights/nist-ir-8547-transition-timeline/
7. NSA CSI — CNSA 2.0 Algorithms (media.defense.gov): https://media.defense.gov/2022/Sep/07/2003071834/-1/-1/0/CSA_CNSA_2.0_ALGORITHMS_.PDF
8. Encryption Consulting — CNSA 2.0 core algorithms: https://www.encryptionconsulting.com/exploring-cnsa-2-0-the-core-algorithms-for-next-gen-security/
9. PostQuantum.com — CNSA 2.0 complete guide: https://postquantum.com/cnsa-2-0/complete-guide/
10. Encryption Consulting — Quantum-Proof with CNSA 2.0 (per-category table): https://www.encryptionconsulting.com/quantum-proof-with-cnsa-2-0/
11. BSI/EU joint statement on transition (PQC), NIS roadmap: https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Crypto/PQC-joint-statement-2025.pdf
12. BSI — Quantum technologies & quantum-safe cryptography: https://www.bsi.bund.de/EN/Themen/Unternehmen-und-Organisationen/Informationen-und-Empfehlungen/Quantentechnologien-und-Post-Quanten-Kryptografie/quantentechnologien-und-post-quanten-kryptografie_node.html
13. UK NCSC — Timelines for migration to PQC: https://www.ncsc.gov.uk/guidance/pqc-migration-timelines
14. Singapore CSA — Quantum-Safe Handbook & Quantum Readiness Index (press release): https://www.csa.gov.sg/news-events/press-releases/csa-releases-a-quantum-safe-handbook-and-quantum-readiness-index/
15. The Edge Singapore — CSA launches QRI (5 domains, self-assessment): https://www.theedgesingapore.com/digitaledge/cybersecurity/csa-launches-quantum-readiness-index-and-handbook-guide-shift-quantum-safe
16. India DST — Quantum Safe Ecosystem in India (landing): https://dst.gov.in/quantum-safe-ecosystem-in-india
17. India DST — "Implementation of Quantum Safe Ecosystem in India, Report of the Task Force" (4 Feb 2026), full PDF read directly: https://dst.gov.in/sites/default/files/Report_TaskForce_PQMigration_4Feb26%20(v1).pdf
18. Global Risk Institute — Quantum Threat Timeline Report 2024 (Mosca & Piani): https://globalriskinstitute.org/publication/2024-quantum-threat-timeline-report/
19. evolutionQ — Quantum Threat Timeline (probability ranges): https://www.evolutionq.com/post/the-quantum-threat-timeline-why-organizations-must-act-now
20. GRI Quantum Threat Timeline Report 2024 (hosted PDF copy): https://www.quintessencelabs.com/hubfs/PDFs/Global-Risk-Institute-Quantum-Threat-Timeline-Report-2024.pdf
21. Mosca's inequality / theorem (X + Y > Z) — background on quantum-risk timing (GRI/evolutionQ framing, refs 18–20).
22. EUROCRYPT 2026 — affiliated events (IACR): https://eurocrypt.iacr.org/2026/affiliated.php
23. MAgiCS 2026 — workshop site: https://magics-workshop.cs.hs-rm.de/
24. MAgiCS 2026 — CfP / program (NIST pqc-forum announcement): https://groups.google.com/a/list.nist.gov/g/pqc-forum/c/29-wFow5Ses
25. Springer — MAgiCS 2026 proceedings: https://link.springer.com/book/9783032289452
26. arXiv:1909.07353 — Identifying Research Challenges in PQC Migration and Cryptographic Agility: https://arxiv.org/abs/1909.07353
27. arXiv:2408.05997 — On the Formalization of Cryptographic Migration (abs): https://arxiv.org/abs/2408.05997
28. arXiv:2408.05997 full text (ar5iv, read directly): https://ar5iv.labs.arxiv.org/abs/2408.05997
29. USPTO — "Systems and methods for post-quantum cryptography optimization" patent family (e.g., US 11,322,050): https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11322050
30. MDPI Computers 15(1):9 — Enterprise Migration to PQC: Timeline Analysis and Strategic Frameworks (full text Cloudflare-blocked; read via search summary): https://www.mdpi.com/2073-431X/15/1/9
31. NIST CSWP 39 — Considerations for Achieving Crypto Agility / NCCoE Migration to PQC: https://www.nccoe.nist.gov/crypto-agility-considerations-migrating-post-quantum-cryptographic-algorithms

---

### Open items / caveats for the team
- **MDPI [30]** read via secondary summary only (Cloudflare 403 on direct fetch). Verify full text before citing it as a contrast in REPORT.md.
- **GRI probabilities** are reported as **ranges** (optimistic→pessimistic experts), not single points — present them as ranges in the paper, not false-precision figures.
- **arXiv:1909.07353** "time horizon as first-order design parameter" is the **brief's characterization**, not a confirmed verbatim quote — make that point in SAMAY's own voice (§B.2).
- **IR 8547 is still a draft** (IPD, Nov 2024) as of June 2026 — say "proposed" deprecation/disallowance dates, not "finalized," for the IR (the FIPS 203/204/205 *are* final).
