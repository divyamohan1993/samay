# Deploy — SAMAY demo service

> **Not deployed automatically.** The demo wraps the CPU solver as a web service.
> Run a security review (SAST + the adversarial checklist below) and get owner
> sign-off **before** going live. The owner runs the deploy; the agent does not.

## What ships
A FastAPI app (`pqcsched.api:app`) exposing `/`, `/gen`, `/solve` (+ optional
Pareto), `/health`, `/health/ready`. Stateless, no auth, no data, no secrets.

## Security controls already baked in (see `src/pqcsched/api.py`)
- Hard server-side caps on instance size / horizon / deps / solver time / Pareto
  points; oversized requests rejected **before** any model is built (the DoS floor).
- Global concurrency semaphore + per-IP rate limit + request-body size cap.
- Security headers (HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy,
  nonce-free strict CSP) and **explicit** CORS origins (never `*`).
- Non-root, read-only-friendly container; no secrets in any layer.
- Bill safety: `--max-instances 3` (DoS can't scale the bill), `--min-instances 0`
  (free when idle), Cloudflare proxy in front for real DDoS absorption.

## Local
```bash
pip install -e ".[api]"
uvicorn pqcsched.api:app --port 8080      # open http://localhost:8080
# or:  docker compose up --build
```

## Cloud Run (owner runs this)
```bash
bash deploy/deploy_cloudrun.sh --yes      # project dmjone, region asia-east1
```
Then add the Cloudflare DNS record it prints (CNAME `samay` → `ghs.googlehosted.com`,
proxied) and map the custom domain.

> **Image not yet built.** The Dockerfile and app are written and the app is
> smoke-tested in-process (TestClient: `/health`, `/gen`, `/solve`, oversized-body
> rejection, security headers all pass), but the **container image has not been
> built or run** in this environment (no Docker on the dev box; building on the
> shared compute box was avoided to protect its disk). First step below is to
> build and run it locally.

## Pre-deploy checklist (adversarial)
- [ ] `docker build -t samay .` succeeds; `docker run -p 8080:8080 samay` serves
      `/` and `/health` (the static asset ships via package-data — verify it loads).
- [ ] `pip audit` / dependency scan clean (no high/critical).
- [ ] SAST (semgrep/CodeQL) clean.
- [ ] Confirm caps in `LIMITS` reject a 10k-asset body with a small 4xx (no OOM).
- [ ] Confirm rate limit + concurrency semaphore under a flood.
- [ ] Confirm no secret/PII in logs.
- [ ] Cloudflare WAF + proxy enabled in front; origin locked to the proxy.

## Future (when revenue justifies — per the org scaling policy)
K8s (Kustomize) and Terraform modules are intentionally omitted at this tier;
Cloud Run scale-to-zero is the right cost posture for a portfolio/research demo.
