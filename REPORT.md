# SAMAY: Optimal Scheduling for Post-Quantum Cryptographic Migration — and an Honest Test of Whether It Beats Greedy

*Divya Mohan (dmj.one). Research preprint / open-source reference tool. Code: `pqcsched`, Apache-2.0.*

> **Status:** all results sections are populated from the reproducible study in
> `runs/`. The generator distributions and grid were **pre-registered** in
> `PROGRESS.md` *before* the study was run. The size-45 main grid covers 23/36
> cells (515 proven-optimal instances) at dependency densities {0.1, 0.4}; the
> dense **dep 0.7** tier is beyond CP-SAT's exact frontier at size 45 and is
> studied separately at size 30 (§9.1), not in the main grid (finite overnight
> compute on a shared box — see §13). Every number here is regenerable; seeds are
> fixed and solver versions logged.

---

## Abstract

Post-quantum cryptographic (PQC) migration is mandated and on a clock (NIST FIPS
203/204/205; NIST IR 8547 disfavouring RSA/ECC by 2030 and disallowing by 2035;
NSA CNSA 2.0; India's National Quantum Mission *Roadmap to Quantum Resiliency*).
Every commercial platform prioritises **qualitatively** — discover the crypto,
score risk, "migrate highest-risk first." We give the first **combinatorial-
optimization formulation of the migration *schedule*** itself: a time-indexed
mixed-integer / constraint program that, given a cryptographic inventory (a
CycloneDX CBOM or a synthetic estate), computes a **provably optimal** phased plan
— which asset to migrate, in which period, in what order — under dependency,
per-period budget, earliest-availability, co-migration, and regulatory-deadline
constraints, minimising harvest-now-decrypt-later (HNDL) aware time-integrated
residual risk. We then ask the falsifiable question the field has not: **does
optimal scheduling actually beat greedy risk-ranking, and when?** We contribute
(i) the formulation, (ii) an open-source solver (OR-Tools CP-SAT primary; HiGHS/
CBC free fallbacks; Gurobi optional), (iii) the first reusable synthetic
benchmark for PQC migration scheduling, (iv) a matheuristic for estates too large
to solve exactly, and (v) a reproducible empirical study across a difficulty grid.
**Headline (RQ2), over 515 instances proven optimal.** The robust, transferable
finding is about **feasibility**: greedy risk-ranking heuristics **miss a mandated
regulatory deadline 25–42% of the time** (and in the realistic India-DPI case, 3
of 5 go infeasible), while the optimum satisfies every mandate whenever the
instance admits one. On *risk*, optimal scheduling beats the vendor default
(migrate-highest-risk-first) by a **median 56%**, and even a sophisticated
**HNDL-aware** greedy by **49%**, across the synthetic grid — but that *magnitude*
is driven by harvest-now-decrypt-later **timing** and is therefore distribution-
dependent: the realistic India-DPI estate, whose secrets mostly do not cross the
HNDL threshold within the horizon, shows only **+4.2%** on risk. Either way this is
*not* a "greedy suffices" result; the precedence-and-budget-constrained timing
problem is genuinely combinatorial. The reported gap is **conservative** — greedy
schedules that go infeasible (accruing yet more risk from unmigrated mandated
assets) are *excluded* from it, so including them would only raise it. Gaps are
stated relative to the model and the pre-registered distributions.

---

## 1. Why this exists

PQC migration is a deadline-driven program of work over years, not a one-shot
swap. The threat has two clocks: a **regulatory** clock (NIST/CNSA/India NQM
deadlines) and a **harvest-now-decrypt-later** clock — data encrypted today under
RSA/ECC can be captured now and decrypted once a cryptographically-relevant
quantum computer (CRQC) exists, so any secret whose confidentiality lifetime
reaches the CRQC era is *already* at risk. An estate has hundreds to millions of
cryptographic usages with dependencies (a service cannot present a PQC certificate
before its CA is PQC; both ends of a protocol must move together), finite
migration capacity per period, and assets that cannot move until their vendor
ships PQC support.

Every commercial platform today handles the resulting prioritisation
**qualitatively**. No rigorous combinatorial-optimization formulation of the
*schedule* exists in the literature or in any product (§3). That is the gap SAMAY
fills, as a research / open-source contribution, sitting on the rare
**operations-research × cryptography** intersection.

This is explicitly **not** a discovery/scanning tool. Inventory is owned by
funded vendors; SAMAY is the *planning brain* that consumes their output (a CBOM).

---

## 2. Scope and honest framing

- A **paper + open-source reference tool**, not a product. The method must be
  novel; it is.
- **Consume, don't discover.** Ingest CycloneDX CBOM and synthetic instances.
- **Honest even if negative.** If optimal ≈ greedy across realistic regimes, that
  is a publishable, useful result ("you don't need MILP — here is the evidence and
  the boundary where it breaks"). We do not tune the instance distribution to
  flatter the optimizer; the generator distributions were pre-registered.
- **No overclaiming.** The schedule is optimal *with respect to a stated risk/cost
  model and the input quality*; both are limitations we state plainly (§13).

---

## 3. Related work and positioning

*(Full citations and verification in `research/timelines-and-related-work.md`.)*

**Standards and timelines.** NIST finalised the PQC standards FIPS 203 (ML-KEM),
204 (ML-DSA), 205 (SLH-DSA) in Aug 2024; NIST IR 8547 sets the transition
(disfavour RSA/ECC by 2030, disallow by 2035); NSA CNSA 2.0 sets sector
milestones (software/firmware signing, networking, then general use, through
~2030–2033). India's National Quantum Mission *Report on a Quantum-Safe Ecosystem
— Roadmap to Quantum Resiliency* (DST task force, 2026) proposes a **Quantum
Readiness Index** to assess exposure and prioritise migration, with critical
infrastructure quantum-safe by 2029 and enterprises by 2033 — i.e. policy itself
asks for exactly the prioritisation SAMAY formalises.

**Migration as a research problem.** A EUROCRYPT 2026 affiliated workshop
(**MAgiCS**, Rome, May 2026) exists precisely because cryptographic migration and
agility modelling are "largely unsolved," with explicit sessions on formal models
of migration, CBOM, and benchmarking. *Identifying Research Challenges in PQC
Migration and Cryptographic Agility* (arXiv:1909.07353) calls for treating the
migration time horizon as a first-order design parameter. *On the Formalization of
Cryptographic Migration* (arXiv:2408.05997) formalises migration dependency
sub-graphs and **migration clusters** — the dependency/co-migration structure our
constraints build directly on.

**The gap.** Existing academic work is qualitative strategy, timeline synthesis,
or dependency-graph *formalization*; commercial tools score and rank. A targeted
search (incl. patents) found only per-asset *algorithm-selection* optimization
(e.g. the US PQC-optimization patent family) — **not estate scheduling**. We found
no prior combinatorial-optimization formulation of the migration *schedule* with a
budget-and-precedence-constrained, HNDL-aware, time-integrated objective. SAMAY is,
to our knowledge, the first, and it is accompanied by the first reusable benchmark.

---

## 4. Problem formulation (RQ1 — the model is the contribution)

A cryptographic estate is a set of quantum-vulnerable **assets** (cryptographic
usages) over a horizon of discrete periods `t ∈ {0,…,T−1}`. For asset `i`:
criticality/exposure `crit_i`, data secrecy lifetime (shelf-life) `s_i`, migration
effort `c_i`, performance penalty `π_i`, earliest feasible period `e_i`, and an
optional mandated deadline `D_i`. A dependency edge `(j,i)` means *j must complete
no later than i*; a co-migration cluster `(i,j)` means *i,j migrate in the same
period*. `t_crqc` is the projected CRQC period.

**Decision variables.** `y_{i,t} ∈ {0,1}` = asset `i` migrated in period `t`
(created only for `t ≥ e_i`, and `t ≤ D_i` for mandated assets). Cumulative
`done_{i,t} = Σ_{τ≤t} y_{i,τ}`.

**Constraints.**
1. Migrate at most once; mandated assets exactly once by deadline:
   `Σ_t y_{i,t} ≤ 1`; for mandated `i`, `Σ_{t≤D_i} y_{i,t} = 1`.
2. Earliest feasibility: `y_{i,t}=0` for `t < e_i` (variables omitted).
3. Per-period budget: `Σ_i c_i·y_{i,t} ≤ B_t`.
4. Precedence: for edge `(j,i)` and all `t`, `done_{i,t} ≤ done_{j,t}`.
5. Co-migration: `y_{i,t}=y_{j,t}` for clustered `(i,j)`.
6. *(Optional)* coexistence/performance budget on a path `k`:
   `Σ_{i∈path_k} π_i·done_{i,t} ≤ W_k` (used only for the constrained-edge study).

**Objective (HNDL-aware, time-integrated residual risk).** The per-period residual
risk of leaving `i` unmigrated at `t` is
`r_{i,t} = crit_i` if `t + s_i ≥ t_crqc` (the HNDL window reaches the CRQC era),
else `r_{i,t} = ⌊ρ·crit_i⌋` with residual factor `ρ` (default 0.1). Minimise total
residual risk
`R = Σ_i Σ_t r_{i,t}·(1 − done_{i,t}) = Σ_i Σ_{t < τ_i} r_{i,t}`,
i.e. risk accrues for every period strictly before the migration period `τ_i`.
This is a precedence-and-budget-constrained scheduling/knapsack problem in the IRP
family.

**Why all-integer.** `crit_i, c_i, B_t` and every `r_{i,t}` are integers, so the
CP-SAT objective equals the independent scorer's risk *exactly* (verified by a
parity test). This removes float-scaling error and makes the optimal-vs-greedy
comparison watertight: a single scorer judges the MILP schedule and every greedy.

**A key honest property.** `R` is well-defined even when a schedule leaves a
*mandated* asset unmigrated — it simply keeps accruing risk — so a greedy that
misses a deadline is penalised *naturally*, with no arbitrary big-M. We
additionally report deadline-violation rates separately.

**Cost and the Pareto frontier.** Total cost `C = Σ_i Σ_t c_i·y_{i,t}`. We trace
the risk–cost Pareto frontier by the ε-constraint method (minimise `R` s.t.
`C ≤ ε`, sweeping `ε`) on representative instances.

---

## 5. Baselines (the vendor status quo we measure against)

All greedy heuristics respect earliest-start, precedence, per-period budget, and
co-migration (clusters collapsed to union-find groups so a greedy can never split
a pair), and are scored on the **same** objective as the MILP:

- **highest-risk-first** (sort by total exposure),
- **highest-risk-per-cost** (knapsack-greedy by risk/effort),
- **earliest-deadline-first**,
- **shortest-processing-time / lowest-cost-first**,
- **random** (lower bound).

The optimal-vs-each-baseline paired gap is the core experimental result.

---

## 6. Synthetic benchmark generator (a first-class, reusable artifact)

No public benchmark exists for PQC migration *scheduling*. Our generator produces
realistic estates controllable along **size × dependency-density × budget-tightness
× deadline-pressure**, plus shelf-life mix, co-migration fraction, and delayed PQC
availability. Distributions were **pre-registered** (`configs/gen.yaml`,
`PROGRESS.md`) and calibrated from public sources (PQC sizes/perf; TLS/PKI
prevalence — RSA≈65%/ECDSA≈35% of certs, chain depth 2–3; HNDL data-lifetime
classes), documented in `research/calibration-crypto.md`. **One period = one
year** (t=0 ≡ 2026, horizon to 2045): this makes HNDL fire meaningfully against a
CRQC ~2039 and keeps the time-indexed model tractable. Feasibility is engineered
in (acyclic dependencies, earliest propagated along edges, deadlines ≥ earliest,
budget floored at the largest single cost so every asset fits); residual
infeasible draws are resampled and the rate reported honestly.

---

## 7. Solvers and environment (CPU-native)

OR-Tools **CP-SAT** is primary (exact, free, excellent on precedence/budget/
knapsack scheduling). **HiGHS** and **CBC** (via a thin PuLP-based abstraction) are
the free MILP fallbacks; **Gurobi** is optional and never a hard dependency. For
estates too large to solve exactly we provide a **matheuristic** (rolling-horizon
window decomposition and Large-Neighborhood Search). All runs are CPU-only (no
GPU); the study ran on a 12-vCPU AMD EPYC (Genoa) VM. Seeds are fixed; solver
version and parameters are logged with every result.

---

## 8. Evaluation protocol (pre-registered)

- **Paired gaps.** For each instance, `gap_b = (R_greedy_b − R_opt)/R_opt`,
  computed only when the instance is **proven OPTIMAL** and the greedy is feasible;
  aggregated by **bootstrap confidence intervals** over the paired per-instance
  gaps (not mean-vs-mean across different instances).
- **OPTIMAL-only headline.** Solver status is recorded on every solve; time-limited
  (FEASIBLE) solves are excluded from the gap and routed to the scalability study.
- **Honest infeasibility.** INFEASIBLE draws are resampled; the rate is reported.
- **Grid (pre-registered).** size 45, T=20; dependency-density {0.1,0.4,0.7} ×
  budget-tightness {0.4,0.6,0.8,0.95} × deadline-pressure {0.1,0.4,0.8}; 30
  instances/cell. Plus a size sweep, an exact-scalability sweep, a sensitivity
  sweep (t_crqc {2035,2039,2043} × risk-form {step,linear} × ρ {0,0.1,0.25}), and
  ε-constraint Pareto frontiers on representative instances.

---

## 9. Results — RQ2: does optimal beat greedy, and when?

Across **515 instances proven OPTIMAL** (23 of 36 grid cells — the size-45 main
grid covers dependency densities {0.1, 0.4}; the dense **dep 0.7** tier sits beyond
CP-SAT's exact frontier at size 45 and is studied separately at size 30 in §9.1,
not in the main grid), the answer is clear and robust: **optimal scheduling beats
greedy substantially, in every regime tested.** Per-instance paired gaps
`(R_greedy − R_opt)/R_opt`:

| baseline | median gap | mean gap | greedy feasible rate |
|---|---:|---:|---:|
| **highest-risk-first** (vendor default) | **56.2%** | 65.0% | 68% |
| risk-per-cost | 52.4% | 55.0% | 68% |
| earliest-deadline-first | 118.9% | 145.9% | 75% |
| shortest-processing-time | 127.5% | 140.7% | 58% |
| random | 142.3% | 158.9% | 67% |
| *HNDL-aware greedy* (strong baseline, §9.2) | *48.6%* | *52.2%* | *69%* |

Two findings, both honest and load-bearing:

**9.1 The gap is large, and it tracks *scheduling freedom*.** The optimal plan
retires roughly **half to two-thirds more residual risk** than migrate-highest-
risk-first across the bulk of the grid. The regime structure is coherent and, at
first sight, counter-intuitive: **the gap shrinks as the problem becomes more
constrained.**

- **Budget tightness:** gap *largest at loose budgets* — tight 0.4 → 74.5% median,
  tight 0.95 → 48.8%.
- **Dependency density** (size 30, where the dense-precedence cells are exactly
  solvable; `runs/dep_sweep.csv`): the gap **decreases markedly with density —
  dep 0.1 ≈ 76%, dep 0.4 ≈ 43%, dep 0.7 ≈ 11%** median highest-risk gap (the
  HNDL-aware greedy tracks it). *Read this as directional:* the dense cells are a
  smaller proven-optimal sample (n≈6–17, on the OPTIMAL-survivor subset, at the
  smaller size 30 since dep 0.7 at the headline size 45 sits beyond CP-SAT's exact
  frontier — §10). The budget-tightness axis above is the robust leg (515
  instances); the dependency leg is a clear trend rather than a precise law.

Both axes point the same way: **optimization pays most where there is the most
scheduling freedom.** Ample budget and sparse dependencies give greedy room to
mis-time migrations (squandering early capacity on not-yet-risky assets); tight
budgets and dense precedence remove that freedom, forcing greedy and optimal into
similar orders. So the naive intuition ("optimization matters most when resources
are scarce") looks *backwards* here — a genuinely useful steer for practitioners
deciding when an exact solver is worth it: most for *loosely-constrained,
sparsely-dependent* estates. Regime heatmaps:
`artifacts/fig_gap_highest_risk_tight_press.png`, `artifacts/fig_gap_dens_tight.png`.

**9.2 It is not merely a naive sort — the combinatorial structure matters.** We
add a *stronger* HNDL-aware greedy that, at each period, migrates the asset with
the highest **current** per-period risk (deferring assets whose harvest-now-
decrypt-later window has not yet reached the CRQC era — the optimizer's key
insight). It does help, but only modestly: median gap **48.6%** vs 56.2% for the
naive sort. **Even a sophisticated time-aware heuristic is ~49% worse than
optimal.** The value of optimization is therefore robust to "just use a smarter
heuristic"; the precedence-and-budget-constrained timing problem is genuinely
combinatorial. (Mechanism, traced on individual instances: greedy spends early
budget migrating assets whose risk has not yet activated, while the optimum
reserves it for assets already accruing full HNDL risk.)

**9.3 Greedy frequently produces an infeasible roadmap.** Feasibility (meeting all
mandated deadlines) collapses under deadline pressure: for the **vendor-default
greedy (highest-risk-first)**, feasibility falls from 97% at deadline-pressure 0.1
to just **25%** at pressure 0.8 — three-quarters of its roadmaps miss a regulatory
mandate (even taking the best-of-five greedies per instance, feasibility is only
~45% at pressure 0.8). The optimum is feasible by construction whenever the
instance is feasible at all. This mirrors
the India-DPI case study (§12), where 3 of 5 greedies miss a mandate.

**Honest reading.** This is a *positive* result for optimization — the brief
allowed for a negative one, but the data do not support "greedy suffices." The
gaps are stated relative to the HNDL-aware time-integrated objective (§4) and the
pre-registered distributions (§6); §11 sensitivity-tests how the conclusion shifts
with the risk model.

## 10. Results — RQ3: scalability and the matheuristic

**Exact frontier (the cliff).** On the 12-vCPU box, CP-SAT *proves* optimality
reliably for estates up to **~60 assets** over a 20-period horizon (size 60: 100%
of feasible instances proven optimal, worst-case ~14 s); the cliff begins around
**size 80**, where a growing fraction return only a time-limited feasible bound,
and by size ~100+ most exceed a 30 s budget. So the exact solver covers a single
business unit / product estate; larger estates need the matheuristic.

**Matheuristic quality.** Where the optimum is known, **LNS matches it** (gap
≈0%; rolling-horizon within ~0.4%). Beyond the exact frontier (sizes 60–80, where
CP-SAT returns only an incumbent), both matheuristics stay **within a few percent
of the exact incumbent at a fraction of the time** (LNS ~20 s vs the exact 45 s
budget), and crucially they **dominate greedy by 6–7×**: e.g. at size 80, exact
incumbent 4527, LNS 4500, rolling 4574, but best greedy **27797**; at size 60,
LNS 2675 vs greedy 17609. Greedy's collapse at scale (it leaves high-risk and
mandated assets unscheduled) is exactly the failure the optimization layer fixes.

**Robustness, honestly.** LNS is the more robust matheuristic: it correctly
reports no schedule on infeasible instances and reliably improves on its greedy
seed. Rolling-horizon, by contrast, can fail to stitch a feasible schedule on hard
instances even when one exists (a window sub-solve returns infeasible and assets
are deferred); we report this limitation rather than hide it, and recommend LNS as
the default at scale. (The local exact figures here are time-limited — the box was
shared with an unrelated workload; the clean exact-frontier numbers above are from
the dedicated calibration sweep.)

## 11. Results — sensitivity

We re-solved the optimum and re-scored greedy under every combination of CRQC
timing `t_crqc ∈ {2035, 2039, 2043}`, residual factor `ρ ∈ {0.1, 0.25}`, and
risk-model form `∈ {step, linear}` (mid-difficulty cell, size 30 for fast exact
solves; `runs/sensitivity.csv`). The headline survives intact: the median
highest-risk gap stays **between 33.5% and 60.0% across all twelve settings — it
never collapses.** The modelling choices modulate it monotonically and
sensibly:

- **Residual factor:** larger `ρ` *narrows* the gap (e.g. step / t_crqc 2039:
  48.8% at ρ=0.1 → 38.3% at ρ=0.25). When even non-HNDL-exposed assets carry
  meaningful risk, the *timing* of the HNDL-exposed ones matters relatively less,
  so greedy closes some ground.
- **Risk-model form:** the smoother `linear` form gives smaller gaps than the
  sharp `step` (40.2% vs 48.8% at t_crqc 2039, ρ=0.1) — a step objective punishes
  mis-timing more.
- **CRQC timing:** a later CRQC tends to *widen* the gap (step, ρ=0.1: 43.6% at
  2035 → 60.0% at 2043), as more of the horizon sits in the residual regime where
  ordering matters.

Even the setting most favourable to greedy (linear, ρ=0.25, t_crqc 2039) leaves a
**33.5%** gap. The conclusion — optimization pays, substantially — is therefore
**not an artifact of one risk model**; it is robust across the plausible modelling
space, which is the honest test that matters.

## 12. Case study — India Digital Public Infrastructure

A stylised India-DPI estate modelled from **public** architecture (Aadhaar/UIDAI,
UPI/NPCI, DigiLocker, eSign, CCA PKI) — *not* internal data (see
`research/cbom-and-dpi.md`). 26 quantum-vulnerable assets, 27 precedence edges, 4
co-migration clusters, 18 regulatory mandates, over an 18-quarter horizon
(2026Q3–2030Q4); a genuine HNDL marquee (the RSA-2048-wrapped Aadhaar PID session
key) and HSM-held long-lived secrets. Migration effort, absent from the estate (as
from any real CBOM), is assigned by a documented default-by-asset-kind model.

**Result.** CP-SAT proves the optimum in well under a second (residual risk
**8746**, cost 203). The greedy comparison (`artifacts/case_study.json`):

| schedule | residual risk | gap vs optimal | feasible? |
|---|---:|---:|---|
| **optimal (CP-SAT)** | **8746** | — | ✓ all 18 mandates |
| highest-risk-first | 9117 | +4.2% | ✓ |
| earliest-deadline-first | 9389 | +7.4% | ✓ |
| risk-per-cost | 9766 | +11.7% | ✗ misses a mandate |
| shortest-processing-time | 11637 | +33.1% | ✗ misses a mandate |
| random | 11851 | +35.5% | ✗ misses a mandate |

Decisively, **three of five greedy heuristics miss a mandated regulatory
deadline** (an infeasible roadmap), whereas the optimal plan satisfies **all 18
mandates**. Here the value of optimization is not merely a few percent of risk —
it is **feasibility under regulatory pressure**, a failure mode of myopic ranking
that this dependency-and-deadline-rich estate exposes sharply. The risk–cost
Pareto frontier (`artifacts/case_pareto.png`) spans cost 180→203 for risk
9289→8746, with the knee near cost 189 (risk drops to 8786 — most of the risk
reduction for ~⅓ of the extra budget). The optimal residual risk is robust to the
CRQC date across 2032–2036 (the estate's secrets are either clearly long-lived or
clearly ephemeral, so they do not cross the HNDL threshold in that range — an
honest, if undramatic, sensitivity result; the synthetic sensitivity study §11
exercises the mechanism directly). Figures: `artifacts/case_roadmap_optimal.png`,
`artifacts/case_risk_over_time.png`, `artifacts/case_pareto.png`.

---

## 13. Limitations (stated plainly)

- **Optimality is relative to the model.** The schedule is optimal w.r.t. the
  stated risk/cost model and inputs. Real estates may have effects we do not model
  (partial migration, rollback, hybrid-then-pure two-step moves).
- **Input quality bounds output quality.** Garbage CBOM in → garbage schedule out.
  Cost, shelf-life, criticality, and dependencies are frequently absent from real
  CBOMs and are supplied by a documented default model the user should override.
- **Risk-model dependence.** The HNDL step form and residual factor are modelling
  choices; §11 sensitivity-tests them, but conclusions are conditional on them.
- **Synthetic distributions.** Calibrated from public sources, not from a census of
  real estates (none is public). The generator is a hypothesis about realistic
  structure, pre-registered to avoid post-hoc tuning.
- **Annual periods** trade intra-year granularity for tractability (the case study
  uses quarters); finer horizons raise the variable count and shrink the exactly-
  solvable frontier.

---

## 14. Reproducibility

`pip install -e .` in a fresh Python 3.12 venv (CPU-only). `scripts/00_setup.sh`
is one-step on a blank Ubuntu box. `requirements.lock.txt` pins versions.
Re-run the whole study with `scripts/run_main_study.py --grid
configs/experiment.yaml` (checkpointed/resumable). All seeds fixed; solver
versions and parameters logged per row in `runs/*.csv`. `PROGRESS.md` is the dated
decision log and holds the pre-registration.

> *One caveat for exact reproduction:* the committed `runs/main.csv` `random`-
> baseline column was generated before a determinism fix (the greedy now iterates
> group ids in sorted order; previously a `set`'s hash-seed-dependent order made
> the *random* baseline vary across processes). Re-running with current code yields
> different — but qualitatively identical (random is the worst baseline, ~140%
> gap) — random values. The four headline baselines use deterministic keys and
> reproduce exactly; only the lower-bound `random` reference is affected.

---

## 15. References

See `research/timelines-and-related-work.md` and `research/calibration-crypto.md`
for the full, verified citation list (NIST FIPS 203/204/205; NIST IR 8547; CNSA
2.0; India NQM Roadmap to Quantum Resiliency / Quantum Readiness Index; GRI Quantum
Threat Timeline; MAgiCS 2026; arXiv:1909.07353; arXiv:2408.05997; CycloneDX CBOM
spec; OR-Tools CP-SAT; HiGHS; CBC/PuLP).
