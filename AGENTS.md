# AGENTS.md — operating manual for SAMAY

**Read `PROJECT_BRIEF.md` in full before doing anything.** That is the spec. This file is *how to work*.

## What you are building
`pqcsched` (SAMAY): an optimization engine that turns a cryptographic inventory (CBOM) into a provably optimal phased PQC-migration **schedule**, plus an open-source benchmark and an honest empirical study — **does optimal scheduling beat greedy risk-ranking, and when?** This is a **paper + open-source tool, not a product**. The formulation, research questions (esp. the optimal-vs-greedy core, §4/§8), and definition of done are in `PROJECT_BRIEF.md`.

## Environment (non-negotiable)
- **CPU-only Oracle E5 VM (AMD Genoa, 6 OCPU / 12 vCPU).** This is pure optimization — **no GPU, no ML, no CUDA.** Set solver threads to 12; set time limits.
- Work in `.venv` (Python 3.12). Commit `requirements.lock.txt`. **Gurobi must never be a hard dependency** — CP-SAT (free) is primary, HiGHS/CBC the free fallback.

## Hard rules
- **Do NOT build cryptographic discovery/inventory.** Consume CycloneDX CBOM only. The planning brain is the whole contribution; the scanner layer is owned by funded vendors.
- **Report honest negative results.** If greedy ≈ optimal across realistic regimes, say so plainly with the evidence and the boundary where it breaks — that is a valid, publishable finding. Never tune the instance distribution to flatter the MILP.
- **Don't overclaim.** The schedule is optimal *relative to a stated risk/cost model and the input quality*. State modeling assumptions and sensitivity-test the load-bearing ones.

## How to work
1. **Phases in order (brief §14).** Get the exact solver + the optimal-vs-greedy study working *first* — that's the contribution. Polish later.
2. **Checkpoint after every phase:** commit code + results, append a dated `PROGRESS.md` entry (what, decisions + why, numbers, next). Append-only; it's your cross-session memory.
3. **Verify APIs at runtime** (OR-Tools, highspy, cyclonedx-python-lib); adapt; log discrepancies.
4. **Document every modeling/calibration choice** (risk form, cost model, dependency semantics, generator distributions) and cite public sources for calibration.
5. **Run it on the VM**, read solver output, fix, re-run. `pytest` gates "done" (constraint correctness, baseline scoring parity, generator validity, CBOM ingest).
6. **Fix seeds; log solver versions + parameters** with every result.

## Decide autonomously vs. ask Divya
**Decide and log:** model details, objective/risk form, solver choices, experiment grid, heuristic design, paper structure.
**Ask first:** submitting/publishing externally (prepare the artifact, get the go-ahead before posting a paper or pushing a public release); using any **real, proprietary CBOM / inventory data** (use synthetic + sample CBOM by default; never commit proprietary data or secrets); anything that would spend money.
If blocked, keep progressing on everything else and flag the blocker at the top of `PROGRESS.md`.

## Done
When every box in `PROJECT_BRIEF.md` §13 is checked and committed, write a final summary at the top of `PROGRESS.md` — headline numbers (the optimal-vs-greedy gap + regime map, scalability frontier, case-study roadmap), how to reproduce, and the honest limitations — and stop. Surface stretch ideas (§14 Phase 8) instead of gold-plating.
