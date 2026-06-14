# SAMAY — optimal scheduling for post-quantum cryptographic migration

> **समय (samay), "time / schedule."** SAMAY is a research contribution + open-source reference tool that takes a cryptographic inventory (a CBOM) and computes a *provably optimal* phased migration schedule — which assets to migrate, in which period, in what order — under dependency, budget, performance, and regulatory-deadline constraints. Its core scientific question is honest and falsifiable: **does optimal scheduling actually beat the greedy "migrate-highest-risk-first" ranking that every vendor uses today, and if so, under what conditions and by how much?**

- **Codename:** SAMAY · **pip package:** `pqcsched` · **License:** Apache-2.0 (code + the synthetic benchmark we build)
- **Owner:** Divya Mohan (dmj.one) · This is a **paper + open-source tool**, *not* a product. Read §2.
- **This file is the source of truth.** Read it fully. `AGENTS.md` says *how* to work.

---

## 0. TL;DR for the coding agent

Build an **optimization engine**, not a scanner. Ingest a cryptographic estate (CycloneDX CBOM or a synthetic instance), model PQC migration as a **mixed-integer / constraint-programming scheduling problem**, solve it exactly (OR-Tools CP-SAT primary; HiGHS/CBC fallback; Gurobi optional), compare against **greedy risk-ranking baselines**, and report **when and by how much optimal beats greedy** across a grid of instance conditions. Ship: the solver + a synthetic-estate generator/benchmark + greedy baselines + a migration-roadmap/Pareto-frontier visualizer + a reproducible empirical study (the paper).

This runs entirely on the CPU VM — **optimization is CPU-native; there is no GPU and none is needed.**

**Hard rule: do NOT build cryptographic discovery/inventory.** That layer is owned by funded vendors (IBM Guardium, SandboxAQ, etc.). SAMAY is the *planning brain* that consumes their output (a CBOM).

**Definition of done** is §13. The headline result is the **optimal-vs-greedy study (§4, §8)** — and it is publishable even if the answer is "greedy is usually near-optimal," because that is itself a useful, honest finding.

---

## 1. Why this exists (positioning — backed by what we verified)

Post-quantum migration is mandated and on a clock (NIST/CNSA 2.0; India's National Quantum Mission roadmap, which explicitly calls for a *Quantum Readiness Index* to "assess exposure and prioritize migration steps"). Today, every commercial platform handles prioritization **qualitatively** — discover crypto, score risk, "migrate highest-risk first." A **rigorous combinatorial-optimization formulation of the migration schedule does not exist** in the literature or in any product (verified: academic work is qualitative strategy / timeline-synthesis / dependency-graph formalization; the one relevant patent family covers *per-asset algorithm selection*, not estate scheduling). The cryptography research community is explicitly asking for this — a EUROCRYPT 2026 workshop (MAgiCS) exists because migration modeling and agility are "largely unsolved," and a research-challenges paper calls for treating the migration time horizon "explicitly as a first-order design parameter."

SAMAY fills exactly that gap, as a research/OSS contribution: the formulation, an open-source solver, a benchmark, and the honest optimal-vs-greedy study. It sits on the rarest skill intersection — **operations research × cryptography/security** — and has a concrete Bharat case (India's DPI / a constrained-edge estate).

---

## 2. Scope & honest framing (READ)

- This is a **paper + open-source reference tool**, not a startup product. The "is the market swarmed" question does not apply to a research contribution; the *method* is what must be novel, and it is.
- **Consume, don't discover.** Ingest CycloneDX CBOM (the standard scanners emit) and synthetic instances. Never build inventory/scanning.
- **The contribution is honest even if negative.** If optimal ≈ greedy across realistic regimes, that's a publishable result ("you don't need MILP, greedy suffices — here's the evidence and the boundary where it breaks"). Do not bury or spin a negative finding.
- **Don't overclaim.** The schedule is optimal *with respect to a stated risk/cost model and inputs*; the model's realism and the input (CBOM/cost/dependency) quality are limitations to state plainly. Garbage CBOM in → garbage schedule out.

---

## 3. The problem — formalization (the substance)

A cryptographic estate is a set of **assets** (cryptographic usages) with a **dependency graph**, planned over a horizon of **periods** $t \in \{1,\dots,T\}$ (e.g., quarters to 2035).

### 3.1 Asset attributes (from CBOM + a calibrated risk/cost model)
For each quantum-vulnerable asset $i$:
- $\text{vuln}_i$: quantum-vulnerable? (RSA/ECC/DH = yes). Only vulnerable assets are decision variables.
- $\text{crit}_i$: criticality / exposure (internet-facing, data volume, business impact). Drives risk weight.
- $s_i$: **data secrecy lifetime / shelf-life** (years the protected data must stay confidential). Drives harvest-now-decrypt-later (HNDL) risk.
- $c_i$: migration cost/effort (person-days or normalized). May be period-dependent $c_{i,t}$ (rush premium for early periods).
- $\pi_i$: performance penalty if migrated to PQC/hybrid (latency/handshake/bandwidth overhead) — matters for constrained/edge assets.
- $e_i$: **earliest feasible period** (PQC support for this asset's protocol/vendor not available before $e_i$).
- $D_i$: **mandated deadline period** (regulatory: this class must be migrated by $D_i$).
- Dependencies: directed edges $j \to i$ (asset $i$ cannot complete migration before $j$, e.g., a service before its CA, a client before the server supports PQC) and **co-migration clusters** (pairs/sets that must migrate in the same period, e.g., both ends of a protocol).

### 3.2 Decision variables
- $y_{i,t} \in \{0,1\}$: asset $i$ is migrated in period $t$ (created only for $t \ge e_i$).
- Cumulative "done by end of $t$": $\text{done}_{i,t} = \sum_{\tau \le t} y_{i,\tau}$ (a linear expression in CP-SAT).

### 3.3 Constraints
1. **Migrate at most once / by deadline:** $\sum_t y_{i,t} \le 1$; for mandated assets $\sum_{t \le D_i} y_{i,t} = 1$.
2. **Earliest feasibility:** $y_{i,t}=0$ for $t < e_i$ (omit those variables).
3. **Per-period budget/throughput:** $\sum_i c_{i,t}\, y_{i,t} \le B_t$ (limited migration capacity per period — the knapsack-over-time structure).
4. **Precedence / dependency:** for each edge $j \to i$ and each $t$: $\text{done}_{i,t} \le \text{done}_{j,t}$.
5. **Co-migration cluster:** $y_{i,t} = y_{j,t}\ \forall t$ for clustered pairs.
6. **(Optional) performance/coexistence budget:** on a path/channel with budget $W_k$, limit simultaneously-hybrid assets (handshake-size/bandwidth): $\sum_{i \in \text{path}_k} \pi_i\,\text{done}_{i,t} \le W_k$ — model only if doing the constrained-edge case study.

### 3.4 Objective (bi-objective: risk vs cost)
Per-period residual risk of an unmigrated asset, HNDL-aware:
$$ r_{i,t} = \text{crit}_i \cdot \text{hndl}(s_i, t, t_{\text{CRQC}}) $$
where $\text{hndl}$ is large when data encrypted at period $t$ (sensitive until $t+s_i$) overlaps the projected cryptographically-relevant-quantum-computer period $t_{\text{CRQC}}$.
- **Total residual risk:** $R = \sum_i \sum_t r_{i,t}\,(1 - \text{done}_{i,t})$ (minimize).
- **Total cost:** $C = \sum_i \sum_t c_{i,t}\,y_{i,t}$ (minimize).
- Produce the **Pareto frontier** via the **ε-constraint method** (minimize $R$ s.t. $C \le \varepsilon$, sweep $\varepsilon$) — preferred — or weighted scalarization $\min R + \lambda C$. (CP-SAT needs integer coefficients: scale $r,c$ to integers.)

This is a precedence-and-budget-constrained scheduling/knapsack problem — clean, rich, and genuinely in the OR wheelhouse (the IRP/VRP family).

---

## 4. Research questions (the spine of the paper)
- **RQ1 (formulation):** the MILP/CP model above + the HNDL-aware time-integrated risk objective. *Contribution: the model itself.*
- **RQ2 (the honest core):** does **optimal** scheduling beat **greedy risk-ranking** (the vendor status quo), and **under what conditions / by how much**? Sweep: budget tightness, dependency density, deadline pressure, estate size, risk-model parameters. Identify the regimes where greedy is near-optimal vs badly suboptimal. *This is the headline finding, publishable either way.*
- **RQ3 (scalability):** how large an estate solves exactly? Provide an exact solver **and** a matheuristic (Large-Neighborhood Search / rolling-horizon decomposition — your IRP experience) for large/million-asset estates.
- **RQ4 (case study):** apply to a realistic estate — synthetic enterprise + an **India-DPI-flavored** scenario (UPI/Aadhaar/DigiLocker-style components & dependencies, modeled from public architecture) and/or a **constrained-edge/IoT** estate; produce the roadmap + Pareto frontier.
- **RQ5 (stretch):** (a) joint **algorithm-selection + scheduling** (hybrid vs pure, which PQC scheme); (b) **robustness to uncertain $t_{\text{CRQC}}$** via stochastic/robust/chance-constrained optimization (scenarios over the quantum-arrival date).

---

## 5. Baselines (must be rigorous — this is what the contribution is measured against)
Implement and compare against the greedy heuristics vendors actually use, all respecting precedence/earliest-start/deadline:
- **Highest-risk-first** (sort by $r_i$).
- **Highest-risk-per-cost** (knapsack-greedy by $r_i/c_i$).
- **Earliest-deadline-first.**
- **Shortest-processing-time / lowest-cost-first.**
- **Random** (lower bound).
Optimal-vs-each-baseline gap is the core experimental result.

---

## 6. Data strategy (no real enterprise data needed)
- **Synthetic estate generator (a first-class deliverable):** parameterized generator producing realistic assets + dependency graphs + cost/risk/deadline distributions. Calibrate distributions from public sources: NIST/CNSA timelines; published PQC cert/handshake sizes and performance (e.g., ML-DSA vs ECDSA overhead); typical enterprise PKI/TLS structure; public TLS-algorithm-prevalence scans. Controls: size, dependency density, budget tightness, deadline pressure, shelf-life mix. **This benchmark is itself a contribution — none exists for PQC migration scheduling.**
- **CycloneDX CBOM ingest:** parse the standard CBOM format scanners emit, so the tool runs on real inventories. Map CBOM fields → asset attributes; where CBOM lacks cost/shelf-life/dependency, provide a documented default model + let the user override.
- **India-DPI / constrained-edge scenario:** model a stylized DPI estate from public architecture descriptions (a scenario, not internal data) for the case study.

---

## 7. Solvers & environment (CPU-native)
- **Primary: OR-Tools CP-SAT** (free, excellent for scheduling/precedence/cumulative/knapsack, strong on CPU). Ideal fit.
- **MILP alternative: HiGHS** (`highspy`) or **PuLP + CBC** (free). Provide a thin solver-abstraction so the model runs on any of them.
- **Optional: Gurobi** for exact-performance benchmarking (you have experience) — but the tool **must** work fully without it.
- **Matheuristic for scale:** Large-Neighborhood Search and/or rolling-horizon (period-window) decomposition for estates too large for exact solve.
- **Hardware:** Oracle E5 VM, 6 OCPU / 12 vCPU, **CPU-only, no GPU, none needed.** Set solver threads to 12; set time limits; record solve times.

---

## 8. Evaluation protocol
- **Optimal-vs-greedy gap** across a parameter grid (budget tightness × dependency density × deadline pressure × size), **many random instances per cell**, report mean ± std and bootstrap CIs. Headline plot: % objective gap (optimal vs each greedy) as conditions vary.
- **Regime map:** where greedy is within X% of optimal vs where it's badly off (the actionable finding for practitioners).
- **Pareto frontiers** (risk vs cost) for representative instances.
- **Scalability:** exact solve time vs estate size; matheuristic quality (gap to optimal where optimal is known) and speed at large scale.
- **Sensitivity:** vary $t_{\text{CRQC}}$, shelf-life distributions, and risk-model form; show how conclusions shift (honesty about model dependence).
- **Case study:** the India-DPI / constrained-edge roadmap with interpretation.
- Fix seeds; log solver versions; everything reproducible.

---

## 9. Setup (script as `scripts/00_setup.sh`, run it)
```bash
sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv build-essential git
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install -U pip wheel
pip install -U \
  "ortools" "highspy" "pulp" \
  "numpy" "pandas" "scipy" "networkx" \
  "matplotlib" "plotly" "pyyaml" "tqdm" "pydantic" "cyclonedx-python-lib" "orjson"
# Gurobi is OPTIONAL (gurobipy) and must not be a hard dependency.
pip freeze > requirements.lock.txt
```
Threads: set CP-SAT `num_search_workers=12`; for HiGHS set threads=12.

---

## 10. Reference code (so the formulation is pinned correctly)

### 10.1 Instance model
```python
from dataclasses import dataclass, field
@dataclass
class Asset:
    id: str
    criticality: float        # exposure/impact weight
    shelf_life: int           # periods data must stay secret (HNDL)
    cost: float               # migration effort
    perf_penalty: float       # PQC/hybrid overhead (optional use)
    earliest: int             # earliest feasible period e_i
    deadline: int | None      # mandated deadline D_i (None = none)
@dataclass
class Instance:
    assets: list[Asset]
    T: int                    # horizon (periods)
    budget: list[float]       # B_t per period
    deps: list[tuple[str,str]]      # (j, i): j must complete <= i
    clusters: list[tuple[str,str]]  # (i, j): co-migrate same period
    t_crqc: int               # projected CRQC period
```

### 10.2 HNDL risk
```python
def hndl_risk(a: Asset, t: int) -> float:
    # data encrypted at period t is sensitive until t + shelf_life;
    # at risk if that window reaches the CRQC-capable period.
    if t + a.shelf_life >= INSTANCE.t_crqc:
        return a.criticality            # full at-risk weight
    return a.criticality * 0.1          # residual (document this choice; sensitivity-test it)
```

### 10.3 CP-SAT model (core)
```python
from ortools.sat.python import cp_model
def solve_cpsat(inst, eps_cost=None, time_limit=60):
    m = cp_model.CpModel()
    idx = {a.id: a for a in inst.assets}
    y = {}                                  # y[i,t]
    for a in inst.assets:
        for t in range(a.earliest, inst.T):
            y[(a.id, t)] = m.NewBoolVar(f"y_{a.id}_{t}")
    done = lambda i, t: sum(y[(i, tau)] for tau in range(idx[i].earliest, t+1) if (i,tau) in y)

    for a in inst.assets:                   # at most once / by deadline
        ys = [y[(a.id,t)] for t in range(a.earliest, inst.T)]
        if a.deadline is not None:
            m.Add(sum(yt for t,yt in zip(range(a.earliest,inst.T), ys) if t <= a.deadline) == 1)
        else:
            m.Add(sum(ys) <= 1)
    for t in range(inst.T):                 # per-period budget (scale costs to int)
        m.Add(sum(int(idx[i].cost*100)*y[(i,t)] for i in idx if (i,t) in y) <= int(inst.budget[t]*100))
    for (j,i) in inst.deps:                 # precedence
        for t in range(inst.T):
            m.Add(done(i,t) <= done(j,t))
    for (i,j) in inst.clusters:             # co-migrate
        for t in range(inst.T):
            if (i,t) in y and (j,t) in y: m.Add(y[(i,t)] == y[(j,t)])

    # objective: minimize time-integrated residual risk (scaled to int)
    risk_terms = []
    for a in inst.assets:
        for t in range(inst.T):
            w = int(round(hndl_risk(a, t)*100))
            risk_terms.append(w*(1 - done(a.id, t)))
    total_risk = sum(risk_terms)
    if eps_cost is not None:                # epsilon-constraint for Pareto
        cost = sum(int(idx[i].cost*100)*y[(i,t)] for (i,t) in y)
        m.Add(cost <= int(eps_cost*100))
    m.Minimize(total_risk)

    s = cp_model.CpSolver(); s.parameters.max_time_in_seconds=time_limit
    s.parameters.num_search_workers=12
    st = s.Solve(m)
    return st, s, y
```

### 10.4 Greedy baseline (template)
```python
def greedy(inst, key):   # key: callable(asset)->score, higher=migrate sooner
    done_at = {}; remaining = [a for a in inst.assets]
    for t in range(inst.T):
        b = inst.budget[t]
        elig = [a for a in remaining if a.earliest <= t and _deps_done(a, done_at, t, inst)]
        for a in sorted(elig, key=key, reverse=True):
            if a.cost <= b: done_at[a.id]=t; b-=a.cost; remaining.remove(a)
    return done_at   # then score residual risk identically to the MILP objective
```

---

## 11. Repo layout
```
pqcsched/
├── PROJECT_BRIEF.md  AGENTS.md  PROGRESS.md  README.md  REPORT.md
├── requirements.lock.txt  pyproject.toml  Makefile
├── configs/  gen.yaml  risk.yaml  experiment.yaml
├── src/pqcsched/
│   ├── model.py          # Asset/Instance dataclasses
│   ├── cbom.py           # CycloneDX CBOM ingest -> Instance
│   ├── generate.py       # synthetic estate generator (the benchmark)
│   ├── risk.py           # HNDL risk model (parameterized)
│   ├── solve_cpsat.py    # CP-SAT exact
│   ├── solve_milp.py     # HiGHS/CBC (+ optional Gurobi) via abstraction
│   ├── heuristic.py      # LNS / rolling-horizon for scale
│   ├── greedy.py         # baselines
│   ├── pareto.py         # epsilon-constraint frontier
│   ├── experiment.py     # the optimal-vs-greedy grid study
│   ├── viz.py            # migration-roadmap Gantt, risk-over-time, Pareto plots
│   └── cli.py
├── benchmark/            # generated instances + the India-DPI/edge scenarios
├── runs/ artifacts/
└── tests/
```

---

## 12. Public API / CLI
```bash
pqcsched solve  --cbom estate.cdx.json --periods 40 --budget budget.yaml --pareto   # roadmap + frontier
pqcsched gen    --size 500 --dep-density 0.3 --deadline-pressure high --out inst.json
pqcsched study  --grid configs/experiment.yaml --out runs/             # the optimal-vs-greedy experiment
```
```python
from pqcsched import Instance, solve_cpsat, greedy, pareto_frontier
inst = Instance.from_cbom("estate.cdx.json", periods=40)
status, solver, y = solve_cpsat(inst)          # optimal schedule
frontier = pareto_frontier(inst)               # list of (cost, risk, schedule)
```

---

## 13. Definition of Done (hard)
- [ ] `pip install -e .` in a fresh venv on the VM; `pqcsched solve` and `pqcsched study` run on CPU.
- [ ] CP-SAT exact solver + at least one free MILP fallback (HiGHS or CBC) behind a solver abstraction; **no hard Gurobi dependency**.
- [ ] All greedy baselines implemented and scored on the *same* objective as the MILP.
- [ ] Synthetic generator + a committed benchmark instance set (the reusable artifact).
- [ ] CycloneDX CBOM ingest works on at least one real/sample CBOM.
- [ ] **The optimal-vs-greedy study (RQ2):** objective-gap results across the parameter grid with CIs, and the regime map (where greedy is near-optimal vs not) — reported honestly, negative result included if that's what the data shows.
- [ ] Scalability result: exact solve-time vs size, plus the matheuristic evaluated at large scale.
- [ ] One case study (India-DPI or constrained-edge) with roadmap + Pareto frontier.
- [ ] Sensitivity to $t_{\text{CRQC}}$ / shelf-life / risk-model form reported.
- [ ] `REPORT.md` (the paper): formulation, study, scalability, case study, **limitations stated plainly** (model realism, input quality, optimality-relative-to-model). `README.md` quickstart.
- [ ] `requirements.lock.txt` committed; one-command reproduction from `scripts/`. `PROGRESS.md` has the decision log + final results.

---

## 14. Execution plan (phases — checkpoint after each)
- **Phase 0 — setup (≈1 hr).** Env (§9), verify CPU + CP-SAT import, smoke-solve a tiny instance.
- **Phase 1 — model + exact solver.** Implement `Instance`, `risk.py`, `solve_cpsat.py`; solve small instances; sanity-check constraints (precedence, budget, deadline).
- **Phase 2 — generator + baselines.** Synthetic generator (`generate.py`), all greedy baselines, identical scoring.
- **Phase 3 — the study (RQ2).** Run the parameter-grid experiment; produce the optimal-vs-greedy gap + regime map with CIs. **This is the core; do it before polishing anything.**
- **Phase 4 — scale.** MILP fallback (HiGHS/CBC) + matheuristic (LNS/rolling-horizon); scalability curves.
- **Phase 5 — CBOM + case study.** CycloneDX ingest; the India-DPI / constrained-edge scenario; roadmap + Pareto + sensitivity.
- **Phase 6 — viz + packaging.** Roadmap Gantt, risk-over-time, Pareto plots; CLI; tests.
- **Phase 7 — paper.** `REPORT.md` + `README.md` with all figures and honest limits; run §13.
- **Phase 8 — stretch.** Joint algorithm-selection + scheduling; robust/stochastic $t_{\text{CRQC}}$; optional Gurobi exact-performance comparison.

## 15. Self-research directives
- Verify current APIs at runtime (OR-Tools CP-SAT, highspy, cyclonedx-python-lib); adapt; log discrepancies in `PROGRESS.md`.
- Calibrate the generator's distributions from cited public sources (PQC cert/perf sizes, NIST/CNSA timelines, TLS-algorithm-prevalence scans) — document every calibration choice.
- Read the positioning sources (§17) so the paper's framing and related-work are accurate; match the dependency-cluster idea to the existing formalization paper and cite it.

## 16. Risks & gotchas
- **No GPU needed** — this is pure optimization; don't add ML/CUDA. Set solver threads.
- **Model realism is the main critique vector** — be explicit about every modeling assumption (risk form, cost model, dependency semantics) and sensitivity-test the load-bearing ones.
- **Don't build discovery** — consume CBOM only; that's the whole point of the positioning.
- **Integer scaling in CP-SAT** — scale float risk/cost to ints consistently; watch for overflow on large horizons.
- **Honest negative results** — if greedy ≈ optimal, report it clearly; don't manufacture an instance distribution to make MILP look good.
- **Scalability cliffs** — exact MILP will blow up past some size; have the matheuristic ready and report the exact-feasible frontier.
- **Reproducibility** — seed numpy + solver; log versions and solve parameters with every result.

## 17. References (positioning + method)
- Open problem / venue: EUROCRYPT 2026 MAgiCS workshop (cryptographic migration & agility); "Identifying Research Challenges in PQC Migration and Cryptographic Agility" (arXiv:1909.07353); "On the Formalization of Cryptographic Migration" (arXiv:2408.05997, dependency sub-graphs / migration clusters).
- Standards/timelines: NIST FIPS 203/204/205; NIST IR on disfavoring RSA/ECC by 2030; CNSA 2.0; India NQM "Roadmap to Quantum Resiliency" / Quantum Readiness Index.
- Format: CycloneDX CBOM (cryptographic bill of materials) spec.
- Solvers: Google OR-Tools CP-SAT; HiGHS; CBC/PuLP. (Gurobi optional.)
- OR methods to draw on (your toolkit): time-indexed scheduling formulations; precedence- and budget-constrained knapsack; epsilon-constraint multi-objective; Large-Neighborhood Search / rolling-horizon matheuristics; (stretch) chance-constrained / robust optimization for uncertain CRQC timing.

---

*Build the exact solver and the honest optimal-vs-greedy study first — that's the contribution. Then scale it, add the CBOM ingest and the case study, and write the paper with the limits stated plainly. Log decisions in `PROGRESS.md`. Ship.*
