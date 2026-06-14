# PROGRESS — SAMAY / pqcsched

Append-only decision log + cross-session memory. Newest entries at the bottom of
each phase. Headline final summary goes at the very top when §13 is complete.

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
