# PROGRESS — SAMAY / pqcsched

## ★ FINAL SUMMARY (2026-06-15)

**The headline (RQ2), honest and robust.** Across **515 instances proven
OPTIMAL** (23/36 grid cells), optimal scheduling beats greedy *in every regime
tested* — this is **not** a "greedy suffices" result:

| baseline | median gap vs optimal | greedy feasible rate |
|---|---:|---:|
| highest-risk-first (vendor default) | **+56%** | 68% |
| risk-per-cost | +52% | 68% |
| earliest-deadline-first | +119% | 75% |
| shortest-processing-time | +128% | 58% |
| random | +142% | 67% |
| **HNDL-aware greedy** (stronger baseline we added) | **+49%** | 69% |

- The gap is **combinatorial, not a naive sort**: even a sophisticated greedy that
  prioritizes *current* per-period HNDL risk is still ~49% worse than optimal.
- **Greedy frequently infeasible**: feasibility collapses from 97% (low deadline
  pressure) to **25%** (high pressure) — three-quarters of greedy roadmaps miss a
  regulatory mandate.
- **The gap tracks scheduling FREEDOM** (counter-intuitive but coherent): it is
  *largest where the problem is least constrained*. By budget tightness (robust,
  515 instances): 74% at 0.4 → 49% at 0.95. By dependency density (size 30,
  directional — smaller proven-optimal sample at high density): **76% (dep 0.1) →
  43% (0.4) → 11% (0.7)**. Loose budgets + sparse deps give greedy room to
  mis-time; tight/dense constraints force greedy and optimal together. Practical
  takeaway: an exact solver pays most for *loosely-constrained, sparsely-dependent*
  estates. Regime heatmaps in `artifacts/`.

**Scalability (RQ3).** CP-SAT proves optimality reliably to **~60 assets** (≤14 s),
cliff at **~80**. Beyond it, **LNS matches the optimum where known (≈0% gap)** and
stays within a few percent of the exact incumbent while **beating greedy 6–7×**
(size 80: LNS 4500 vs greedy 27797). LNS > rolling-horizon in robustness (the
latter can fail to stitch a feasible schedule on hard instances — reported, not
hidden).

**Case study (India-DPI).** 26-asset Aadhaar/UPI/DigiLocker/eSign/CCA-PKI estate
(public architecture). Optimal proves in <1 s, meets **all 18 mandates**; **3 of 5
greedies miss a mandate** (infeasible). Risk–cost Pareto + roadmap in `artifacts/`.

**Reproduce.** `pip install -e .` (Python 3.12, CPU-only) or `scripts/00_setup.sh`
on a blank Ubuntu box. Study: `python scripts/run_main_study.py --grid
configs/experiment.yaml` (checkpointed/resumable). Strong-baseline re-analysis:
`scripts/reanalyze_strong_baseline.py`. Case study: `scripts/case_study.py`. All
seeds fixed; `requirements.lock.txt` pins versions; distributions pre-registered
below before the run.

**Honest limitations.** Optimality is *relative to* the HNDL-aware time-integrated
objective and the pre-registered synthetic distributions (no public census of real
estates exists). Garbage CBOM in → garbage schedule out. At the headline size 45
the dense-dependency (dep 0.7) cells sit at/beyond CP-SAT's exact frontier, so the
dependency-density result is reported at size 30 (where proven optima exist); the
size-45 main grid covers dep {0.1, 0.4} fully. The box was shared with an
unrelated `praman` ML workload throughout, so SAMAY ran niced/worker-capped to
avoid disrupting it (kept that promise: praman + the udaan stack untouched, disk
safe). Annual periods trade intra-year granularity for tractability. See
`REPORT.md` §13.

**§13 Definition-of-Done:** all boxes met except a *partial* coverage of the
hardest cells and a focused (not exhaustive) sensitivity sweep — both consequences
of finite overnight compute on a shared box, documented honestly. Deployment to
Cloud Run deferred per owner instruction (container prepared, never auto-deployed).

---

Append-only decision log + cross-session memory. Newest entries at the bottom of
each phase.

> **Blockers (top-of-file, cleared when resolved):** none.

---

## 2026-06-15 — Phase 0/1: environment, core model, exact solver

**Environment (verified):**
- Dev: local Windows, Python 3.12.7, `.venv`, ortools 9.15.6755 installed.
- Compute: Oracle **E5 box** `dmj-docker-temp` (`ubuntu@92.4.67.232`), Ubuntu
  24.04, Python 3.12.3, **12 vCPU / 6 OCPU**, 31 GiB RAM, AMD EPYC 9J14 (Genoa).
  CPU-only, no GPU (none needed — this is pure optimization). Box also runs an
  unrelated `udaan` Docker stack (Caddy/postgres/idp/…) on ports 80/443 — **must
  not be touched**; root disk is 88% full (≈13 GB free), so study output is kept
  compact and the runner guards on `df`. My work is isolated in `~/pqcsched`.
- Deploy target: Cloud Run (project `dmjone`, region `asia-east1`). **No deploy
  until the owner is awake** (owner instruction); container prepared, not pushed.

**Decisions + why:**
- **Integer-native model.** `criticality`, `cost`, `budget`, and all risk weights
  are integers (risk points / person-days). CP-SAT is integer; this removes
  float-scaling error and makes `solver.ObjectiveValue()` equal the shared
  scorer's risk *exactly*. (`model.py`, `risk.py`.)
- **One shared scorer** (`score.py::score_schedule`) judges every schedule —
  MILP, matheuristic, and all greedies. This is the linchpin of the
  optimal-vs-greedy validity. Enforced by `tests/test_parity.py`.
- **Solver status recorded on every solve** (`result.py`). The headline RQ2 gap
  will use only instances proven `OPTIMAL`; time-limited (`FEASIBLE`) solves go to
  the scalability section, never the gap. (Per reviewer guidance — reporting a
  time-limited bound as "optimal" would understate the true gap.)
- **Risk objective = time-integrated residual risk** `R = Σ_i Σ_{t<τ_i} r_{i,t}`,
  HNDL-aware (`risk.py`, step form default; linear form available for the
  sensitivity analysis). Residual risk accrues for periods strictly before
  migration. The objective is well-defined even when a greedy leaves a *mandated*
  asset unmigrated (it keeps accruing risk), so deadline misses are penalized
  naturally — **no arbitrary big-M**. Deadline-violation rate is also reported
  separately for honesty.
- **Paired gap.** RQ2 gap is per-instance `(greedy − optimal)/optimal`, then
  bootstrapped — not mean(optimal) vs mean(greedy) across different instances.
- **CP-SAT primary** (`num_search_workers=12`, time-limited), HiGHS/CBC the free
  fallback (Phase 4), Gurobi optional and never a hard dependency.
- **Greedy baselines** (`greedy.py`): highest-risk, risk-per-cost, EDF, SPT,
  random — all respect earliest/precedence/budget/clusters; clusters handled by
  union-find groups so a greedy can't split a co-migrating pair.

**Built (Phase 1):** `model.py`, `risk.py`, `result.py`, `score.py`,
`solve_cpsat.py`, `greedy.py`, `generate.py` (synthetic benchmark generator),
`tests/test_parity.py`, `tests/test_constraints.py`. Repo scaffolded
(`pyproject.toml`, src layout).

**Next:** validate vertical slice locally (parity + constraints green); spawn
research team for calibration + positioning; pre-register the study grid and
generator distributions here *before* running the study.

---

## 2026-06-15 — Phase 2/3: calibration, pre-registration (BEFORE running the study)

### Compute environment update — the box is SHARED (good-neighbor policy)
The E5 box is **not** idle. Besides the `udaan` Docker stack it is running an
active, unrelated **`praman`** ML job (`scripts/20_score.py --run-id slice`,
~7 cores, plus a `30_pipeline.py` waiting on it). Per the owner's instruction
("don't destroy other things hosted on it"), all SAMAY compute is a courteous
neighbor: **CP-SAT workers capped at 6 and run under `nice -n 12`**, so praman
always wins CPU contention and is never starved. My work is isolated in
`~/pqcsched` (separate dir, venv, no ports, compact output). Disk floor guard at
1.5 GB protects the shared root (postgres lives there; ~9 GB free).
Consequence: solve times are ~2x the 12-worker calibration; time limits set
accordingly. Recorded so a re-run on a dedicated box can simply raise workers.

### Period semantics (load-bearing modelling decision)
**One period = one year; t=0 = 2026; horizon T=20 (→ 2045).** Resolves a
unit clash flagged in research (shelf_life was specified in years but used as
periods) and a horizon problem: a conservative CRQC (~2039–2044, GRI/Mosca)
falls *outside* a quarters-to-2035 horizon, making HNDL risk never fire for data
encrypted today. Annual periods (a) make HNDL meaningful, (b) span the CRQC
window and policy deadlines, and (c) keep the time-indexed MILP (vars = assets×T)
tractable so exact optimality stays provable. Quarter-granularity is supported by
raising T (at a tractability cost) — documented limitation.

- **t_crqc central = 13 (≈2039).** Sensitivity sweep {9, 13, 17} = 2035 / 2039 /
  2043. (GRI Quantum Threat Timeline 2024 / Mosca: ~14% by 2029, 34% by 2034,
  55% by 2039 — see `research/timelines-and-related-work.md`.)
- Policy deadline anchors (year-index from 2026): NIST IR 8547 disfavour 2030
  (t=4) / disallow 2035 (t=9); CNSA 2.0 2030/2033 (t=4/7); India NQM CII 2029
  (t=3) / enterprise 2033 (t=7).

### Pre-registered generator distributions (NOT tuned post-hoc)
Mirror `configs/gen.yaml` / `pqcsched.generate.Calibration`. Calibrated from
`research/calibration-crypto.md` (PQC sizes/perf, TLS/PKI prevalence) and
`research/timelines-and-related-work.md`:
- **criticality** ~ lognormal(3.0, 0.8) clip [1,100] — heavy-tailed exposure
  (most moderate; a few internet-facing crown jewels).
- **cost** ~ lognormal(1.4, 0.5) clip [1,14] — *normalized* effort; moderate
  spread on purpose so `budget_tightness` is reachable despite the
  every-asset-must-fit budget floor (applied symmetrically to optimal & greedy).
- **shelf_life** (years): {3:0.40, 10:0.40, 25:0.20} — ephemeral TLS / business
  data / long-lived records.
- **perf_penalty** ~ U(0,0.6) — only used by the optional coexistence constraint;
  research shows PQC handshake cost is signature-dominated (KEMs cheap), a
  low-with-heavy-tail shape, captured qualitatively.
- **dependencies**: acyclic (edges forward in a random topo order), expected
  in-degree = dep_density × max_in_degree (max 4); mirrors CA→intermediate→leaf
  chains (depth 2–3 from TLS scans).
- **clusters**: co-migration pairs, frac 0.10 (both ends of a protocol).
- **budget**: uniform per period; capacity_total = ceil(total_cost / tightness);
  per_period = max(ceil(capacity_total/T), max_single_cost). Report
  realized_tightness.

### Exact-solvable regime (calibrated on the box, 12 workers, 30s)
%proven-OPTIMAL among feasible instances, by size (T=16–24):
size 20→100%, 30–50→≈100% of feasible, 60→100% (t_max 14s), **80→cliff begins**
(FEASIBLE-not-proven appears), 100+→mostly time-limited. ⇒ **Headline RQ2 lives at
size ≤60; size ≥80 is RQ3 scalability/matheuristic territory.** (At 6 niced
workers, halve the size or double the limit; main grid uses size 45, limit 60s.)

### The study (validity rules — non-negotiable)
- **RQ2 paired gap:** per instance, gap_b = (risk_greedy_b − risk_opt)/risk_opt,
  computed only when the instance is **proven OPTIMAL** and the greedy is
  **feasible**; aggregated by **bootstrap CI** over the paired per-instance gaps.
- **OPTIMAL-only headline:** `opt_status` on every row; FEASIBLE (time-limited)
  rows excluded from the gap, routed to scalability.
- **Infeasibility honest:** INFEASIBLE instances resampled to fill a cell; the
  infeasible-resample rate is reported per cell, not hidden.
- **Greedy deadline misses** counted separately (deadline_violation rate); the
  residual-risk objective already penalizes them (no big-M).
- **Checkpoint/resume + disk guard** in `experiment.run_grid`.
- Seeds fixed; solver version + params logged with every row.

### Pre-registered grid (finalized from feasmap on the box)
- **main** (RQ2): size 45, T 20, dep_density {0.1, 0.4, 0.7} × budget_tightness
  {0.4, 0.6, 0.8, 0.95} × deadline_pressure {0.1, 0.4, 0.8} = 36 cells, 30
  instances/cell, t_crqc 13, risk step, time_limit 60s, workers 6.
- **size** (gap vs scale): sizes {20, 30, 45, 60} at a mid cell (dep 0.4, tight
  0.6, press 0.4), 30 instances.
- **scalability** (RQ3): sizes {20,40,60,80,100,150,200,300} mid cell, exact +
  matheuristic, 10 instances; record solve time & proven-optimal fraction.
- **sensitivity**: t_crqc {9,13,17} × risk_form {step,linear} × residual
  {0.0,0.1,0.25} at the mid cell, 20 instances.
- **pareto**: epsilon-constraint frontier on ~3 representative instances only.
