# SAMAY · `pqcsched`

> **Quantum computers will break the encryption (RSA/ECC) protecting almost
> everything today.** Every organisation must migrate its certificates, keys, and
> signatures to quantum-safe cryptography — thousands of them, in a dependency-safe
> order, before regulators' deadlines (2030–2035). Today everyone guesses the order
> ("migrate highest-risk first"). **SAMAY computes the provably optimal order** —
> and shows that the guess often misses mandates outright.

**Provably optimal phased scheduling for post-quantum cryptographic migration —
and an honest test of whether it actually beats greedy.** Live demo:
[pqcsched.dmj.one](https://pqcsched.dmj.one) · once DNS is mapped (Cloud Run URL meanwhile).

समय *(samay)* means *time / schedule*. Post-quantum migration is mandated and on
a clock. Every vendor today prioritises the same way: discover the crypto, score
risk, **migrate highest-risk first.** SAMAY asks the question nobody has answered
rigorously: *is that the right schedule — and if not, how far off is it?*

Give SAMAY a cryptographic inventory (a CycloneDX **CBOM** or a synthetic estate)
and it computes a **provably optimal** phased plan — which asset to migrate, in
which period, in what order — under dependency, budget, earliest-availability,
co-migration, and **regulatory-deadline** constraints, minimising harvest-now-
decrypt-later-aware residual risk. Then it measures, across a difficulty grid,
exactly **when optimal scheduling beats greedy and by how much** — reported
honestly, negative results included.

> A research contribution + open-source reference tool, **not a product**. The
> formulation, the benchmark, and the honest study are the contribution. Read
> `REPORT.md` for the paper and `PROJECT_BRIEF.md` for the full spec.

---

## Why it matters

In a stylised **India Digital Public Infrastructure** estate (Aadhaar / UPI /
DigiLocker / eSign / CCA PKI — public architecture, not internal data), the
optimal schedule doesn't just lower risk versus the best greedy: **three of five
greedy heuristics miss a mandated regulatory deadline entirely** (an infeasible
roadmap), while the optimal plan meets all of them. At larger scale, greedy
heuristics degrade sharply while the exact solver and the matheuristic stay close
to optimal. Optimization here buys **feasibility under regulatory pressure**, not
just a few percent of risk.

## Quickstart

```bash
python3.12 -m venv .venv && . .venv/bin/activate      # (Windows: .venv\Scripts\activate)
pip install -e .                                       # CPU-only; no GPU needed
```

```bash
# generate a synthetic estate, solve it optimally, compare to every greedy
pqcsched gen --size 60 --out estate.json
pqcsched solve --instance estate.json
pqcsched baselines --instance estate.json              # optimal vs each greedy + gaps

# ingest a real CycloneDX CBOM and plan its migration
pqcsched solve --cbom benchmark/sample.cbom.json --periods 20 --pareto

# reproduce the empirical study (checkpointed, resumable)
python scripts/run_main_study.py --grid configs/experiment.yaml
```

```python
from pqcsched import generate, GenParams, RiskModel, solve_cpsat, greedy_schedule, score_schedule
inst = generate(GenParams(size=60, T=20, seed=0))
opt  = solve_cpsat(inst, RiskModel())                  # provably optimal schedule
print(opt.status, opt.objective, opt.schedule)
```

## What's inside

| | |
|---|---|
| **Exact solver** | OR-Tools **CP-SAT** (primary). HiGHS / CBC free fallbacks behind a solver abstraction; Gurobi optional, never required. |
| **Baselines** | highest-risk, risk-per-cost, earliest-deadline, shortest-processing-time, random — all scored on the *same* objective as the optimum. |
| **Benchmark** | a parameterized synthetic-estate generator (size × dependency × budget × deadline pressure) — the first reusable benchmark for PQC migration *scheduling*. |
| **Scale** | rolling-horizon + LNS matheuristics for estates too large to solve exactly. |
| **Ingest** | CycloneDX CBOM → schedulable instance, with a documented default model for fields a CBOM lacks. |
| **Study** | the pre-registered optimal-vs-greedy grid experiment with bootstrap CIs and a regime map. |
| **Demo** | a hardened FastAPI service (`pqcsched.api`) + zero-dependency UI; see `deploy/`. |

## The honest core

The whole point is falsifiable: a single scorer judges the optimal schedule and
every greedy identically (verified by a parity test); only **provably optimal**
instances enter the headline gap; greedy deadline-misses are reported, not
hidden; and the generator distributions were **pre-registered** (`PROGRESS.md`)
so they can't be tuned to flatter the optimizer. If greedy turns out near-optimal
in a regime, we say so and map the boundary where it breaks.

## License

Apache-2.0 (code **and** the synthetic benchmark). Built for Aatmanirbhar Bharat
and the operations-research × cryptography intersection.
