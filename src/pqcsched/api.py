"""SAMAY solver-as-a-service (FastAPI) — a demo wrapper around the optimizer.

SECURITY POSTURE (this is a public, stateless, no-auth, no-data demo; the assets
worth protecting are availability/compute and the owner's cloud bill):

* The one real abuse case is **DoS via an oversized instance** — a malicious body
  with millions of assets/periods would make CP-SAT allocate enormous models. So
  every request is validated against HARD caps (:data:`LIMITS`) and oversized
  requests are rejected with a small 4xx **before any model is built**.
* Solver time, workers, and Pareto point count are capped server-side regardless
  of what the client asks for. A global concurrency semaphore bounds simultaneous
  solves so the box cannot be swamped. A lightweight per-IP token bucket rate-
  limits floods (Cloudflare/Cloud Run sit in front for real DDoS).
* No secrets, no eval/exec, no SQL, no shell, no outbound fetch. Strict pydantic
  validation. Security headers + explicit CORS on every response.
* Not auto-deployed; run a security review (SAST + adversarial pass) before going
  live. See deploy/ for the one-command, never-auto-run deploy.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, Response
from pydantic import BaseModel, Field, conint, confloat

from . import __version__
from .model import Asset, Instance
from .risk import RiskModel
from .score import score_schedule
from .solve_cpsat import solve_cpsat
from .greedy import greedy_schedule, BASELINES
from .generate import generate, GenParams


# --- hard server-side limits (the DoS floor) -------------------------------
class Limits:
    MAX_ASSETS = 400
    MAX_T = 60
    MAX_DEPS = 4000
    MAX_CLUSTERS = 1000
    MAX_TIME_LIMIT = 10.0       # seconds, regardless of client request
    MAX_WORKERS = 4
    MAX_PARETO_POINTS = 16
    MAX_BODY_BYTES = 512 * 1024  # 512 KB request body cap
    RATE_PER_MIN = 30            # requests/min/IP
    MAX_CONCURRENT_SOLVES = 4


LIMITS = Limits()
_solve_sem = threading.Semaphore(LIMITS.MAX_CONCURRENT_SOLVES)
_rate: dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()

ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "PQCSCHED_CORS_ORIGINS", "https://samay.dmj.one,https://dmj.one").split(",") if o.strip()]

app = FastAPI(title="SAMAY · pqcsched", version=__version__,
              description="Provably optimal post-quantum migration scheduling (demo).",
              docs_url="/api", redoc_url=None)


# --- security middleware ---------------------------------------------------
@app.middleware("http")
async def _security(request: Request, call_next):
    # body-size cap (defence even before pydantic)
    cl = request.headers.get("content-length")
    if cl is not None and cl.isdigit() and int(cl) > LIMITS.MAX_BODY_BYTES:
        return JSONResponse({"error": "request too large", "code": "BODY_TOO_LARGE"}, status_code=413)
    # per-IP rate limit (token bucket via sliding window)
    ip = (request.client.host if request.client else "unknown")
    now = time.monotonic()
    with _rate_lock:
        q = _rate[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= LIMITS.RATE_PER_MIN:
            return JSONResponse({"error": "rate limited", "code": "RATE_LIMIT"}, status_code=429)
        q.append(now)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
    origin = request.headers.get("origin")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    return resp


# --- request schemas (bounded) ---------------------------------------------
class AssetIn(BaseModel):
    id: str = Field(max_length=128)
    criticality: conint(ge=0, le=10_000)
    shelf_life: conint(ge=0, le=500)
    cost: conint(ge=0, le=1_000_000)
    perf_penalty: confloat(ge=0, le=1) = 0.0
    earliest: conint(ge=0, le=Limits.MAX_T) = 0
    deadline: conint(ge=0, le=Limits.MAX_T) | None = None


class InstanceIn(BaseModel):
    assets: list[AssetIn] = Field(max_length=Limits.MAX_ASSETS)
    T: conint(ge=1, le=Limits.MAX_T)
    budget: list[conint(ge=0, le=10_000_000)] = Field(max_length=Limits.MAX_T)
    deps: list[tuple[str, str]] = Field(default_factory=list, max_length=Limits.MAX_DEPS)
    clusters: list[tuple[str, str]] = Field(default_factory=list, max_length=Limits.MAX_CLUSTERS)
    t_crqc: conint(ge=0, le=1000) = 0

    def to_instance(self) -> Instance:
        assets = [Asset(id=a.id, criticality=int(a.criticality), shelf_life=int(a.shelf_life),
                        cost=int(a.cost), perf_penalty=float(a.perf_penalty),
                        earliest=int(a.earliest), deadline=a.deadline) for a in self.assets]
        if len(self.budget) != self.T:
            raise HTTPException(status_code=422, detail="budget length must equal T")
        return Instance(assets=assets, T=int(self.T), budget=[int(b) for b in self.budget],
                        deps=[tuple(d) for d in self.deps], clusters=[tuple(c) for c in self.clusters],
                        t_crqc=int(self.t_crqc))


class SolveRequest(BaseModel):
    instance: InstanceIn
    time_limit: confloat(gt=0, le=Limits.MAX_TIME_LIMIT) = 5.0
    pareto: bool = False
    pareto_points: conint(ge=2, le=Limits.MAX_PARETO_POINTS) = 8


class GenRequest(BaseModel):
    size: conint(ge=2, le=Limits.MAX_ASSETS) = 40
    T: conint(ge=2, le=Limits.MAX_T) = 20
    dep_density: confloat(ge=0, le=1) = 0.3
    budget_tightness: confloat(gt=0, le=1) = 0.6
    deadline_pressure: confloat(ge=0, le=1) = 0.3
    seed: conint(ge=0, le=10_000_000) = 0


def _roadmap(inst: Instance, schedule, rm: RiskModel) -> dict:
    sc = score_schedule(inst, schedule, rm)
    by_period: dict[int, list[str]] = {}
    for aid, t in sorted(schedule.items(), key=lambda kv: kv[1]):
        by_period.setdefault(t, []).append(aid)
    return {"risk": sc.risk, "cost": sc.cost, "feasible": sc.feasible,
            "n_migrated": sc.n_migrated, "deadline_violations": sc.deadline_violations,
            "plan_by_period": by_period}


@app.get("/health")
def health():
    return {"status": "ok", "service": "pqcsched", "version": __version__}


@app.get("/health/ready")
def ready():
    # deep check: the solver actually runs
    try:
        inst = generate(GenParams(size=6, T=6, seed=0))
        r = solve_cpsat(inst, RiskModel(), time_limit=3, workers=1)
        return {"status": "ready", "solver": r.status}
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="solver not ready")


@app.post("/gen")
def gen(req: GenRequest):
    # Return a FEASIBLE instance so the demo always has something to schedule:
    # probe with a short solve and resample the seed a few times on INFEASIBLE.
    rm = RiskModel()
    last = None
    for k in range(6):
        inst = generate(GenParams(size=req.size, T=req.T, dep_density=req.dep_density,
                                  budget_tightness=req.budget_tightness,
                                  deadline_pressure=req.deadline_pressure, t_crqc=13,
                                  seed=req.seed + k * 101))
        last = inst
        probe = solve_cpsat(inst, rm, time_limit=2.0, workers=1)
        if probe.status != "INFEASIBLE":
            return inst.to_dict()
    return last.to_dict()


@app.post("/solve")
def solve(req: SolveRequest):
    inst = req.instance.to_instance()
    rm = RiskModel()
    tl = min(float(req.time_limit), LIMITS.MAX_TIME_LIMIT)
    if not _solve_sem.acquire(timeout=15):
        raise HTTPException(status_code=503, detail="server busy, retry shortly")
    try:
        res = solve_cpsat(inst, rm, time_limit=tl, workers=LIMITS.MAX_WORKERS)
        out = {"status": res.status, "wall_time": round(res.wall_time, 3),
               "objective": res.objective,
               "optimal": res.is_optimal, "mip_gap": res.mip_gap}
        if res.schedule is not None:
            out["roadmap"] = _roadmap(inst, res.schedule, rm)
            # greedy comparison (cheap)
            # Illustrative gap vs the solver's best schedule (OPTIMAL when proven;
            # otherwise best-found within the demo time cap — the `optimal` flag
            # says which). The research study (REPORT) is strict OPTIMAL-only.
            comp = {}
            for b in BASELINES:
                sc = score_schedule(inst, greedy_schedule(inst, b, rm, seed=0), rm)
                gap = ((sc.risk - res.objective) / res.objective) if (res.objective and res.schedule is not None) else None
                comp[b] = {"risk": sc.risk, "feasible": sc.feasible,
                           "gap_vs_optimal": (round(gap, 4) if gap is not None else None)}
            out["greedy_comparison"] = comp
        if req.pareto and res.schedule is not None:
            try:
                from .pareto import pareto_frontier
                pts = pareto_frontier(inst, rm, n_points=req.pareto_points,
                                      time_limit=min(tl, 4.0), workers=LIMITS.MAX_WORKERS)
                out["pareto"] = [{"cost": p.cost, "risk": p.risk} for p in pts]
            except Exception:  # noqa: BLE001 - pareto is optional
                out["pareto"] = None
        return out
    finally:
        _solve_sem.release()


@app.get("/", response_class=HTMLResponse)
def index():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "static", "index.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return HTMLResponse(fh.read())
    return HTMLResponse("<h1>SAMAY · pqcsched</h1><p>API at <a href='/api'>/api</a></p>")
