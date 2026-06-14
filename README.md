# SAMAY · `pqcsched`

**Provably optimal phased scheduling for post-quantum cryptographic migration.**

Takes a cryptographic inventory (a CycloneDX CBOM or a synthetic instance) and
computes a *provably optimal* migration schedule — which assets to migrate, in
which period, in what order — under dependency, budget, performance, and
regulatory-deadline constraints. Then it answers, honestly and falsifiably:

> **Does optimal scheduling actually beat the greedy "migrate-highest-risk-first"
> ranking that every vendor uses today — and if so, under what conditions and by
> how much?**

This is a **research contribution + open-source reference tool**, not a product.
See `PROJECT_BRIEF.md` for the full specification and `REPORT.md` for the study.

> Quickstart, CLI, and results are filled in as the build completes. License:
> Apache-2.0.
