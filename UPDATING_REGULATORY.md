# Keeping the regulatory data correct

PQC compliance deadlines change. A planning tool that serves **stale dates with
confidence** is worse than one that admits its data's age: it can tell an
organization it is on track when it is about to miss a real mandate. SAMAY is
built so that can't happen silently.

## How staleness is contained (the mechanism)

1. **One dated, sourced source of truth.** Every mandate date lives in
   [`src/pqcsched/data/regulatory.json`](src/pqcsched/data/regulatory.json) with an
   `as_of` date, a `review_due` date, and a cited `source` URL per mandate. No date
   is hardcoded anywhere else — the CBOM default deadlines, the API, and the UI all
   read this file (`pqcsched/regulatory.py`).
2. **Age is shown on every suggestion.** Each `/plan` response carries a
   `regulatory` block (`as_of`, `review_due`, `stale`, `disclaimer`); the UI prints
   it under every roadmap. `GET /regulatory` returns the full profile and its
   runtime staleness. Users are told to verify and override — never to trust blindly.
3. **The tool flags itself when due.** A scheduled GitHub Action
   ([`regulatory-watchdog.yml`](.github/workflows/regulatory-watchdog.yml)) opens a
   tracking issue once the `review_due` date passes. The live banner also flips to a
   visible "may be out of date" warning.

## Why not fully automatic self-update?

There is **no authoritative machine-readable feed** of PQC regulatory deadlines.
Auto-scraping government PDFs and pages would inject wrong dates with false
confidence — the exact failure this design prevents. So updates are
**human-verified**. The automation's job is to *flag*, not to *guess*.

## The update procedure

When the watchdog fires (or whenever a mandate changes), do this:

1. **Re-verify each source.** Open every `mandates[].source` in
   `regulatory.json` (CNSA 2.0, NIST IR 8547, EU roadmap, India NQM) and confirm
   the dates. Add any new mandate relevant to your jurisdiction.
2. **Edit the data.** Update `milestones`, `default_deadline_policy.by_asset_class`
   (the per-asset-class mandated year used when an upload carries no deadline of its
   own), `standards`, and `threat_context`.
3. **Stamp it.** Set `as_of` to today and `review_due` ~6 months out.
4. **Open a PR.** CI runs the full suite; merge deploys to Cloud Run. The live
   `as_of` banner updates automatically. Close the watchdog issue.

> The `default_deadline_policy` is a **conservative starting point**, not legal
> advice. Organizations should override deadlines per asset with their own
> authoritative obligations — an explicit `deadline` on a CBOM component always
> wins over these defaults.
