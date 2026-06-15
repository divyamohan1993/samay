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
from .scenarios import sample_instance, SAMPLES
try:  # CBOM ingest is optional at import (heavy parsing deps), but ships here
    from .cbom import cbom_to_instance
except Exception:  # noqa: BLE001
    cbom_to_instance = None


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


# ---------------------------------------------------------------------------
# Enterprise planning: a named estate or an uploaded CBOM -> an actionable,
# named, quarter-by-quarter migration roadmap (the thing a CISO can act on).
# ---------------------------------------------------------------------------
def _period_label(t: int, unit: str, start_year: int = 2026) -> str:
    if unit == "quarter":
        return f"{start_year + t // 4} Q{t % 4 + 1}"
    return str(start_year + t)


def _reason(asset: Asset, period: int, n_dependents: int) -> str:
    if n_dependents > 0:
        return f"unblocks {n_dependents} dependent" + ("s" if n_dependents != 1 else "")
    if asset.deadline is not None and period >= asset.deadline - 2:
        return "meets a regulatory deadline"
    if asset.shelf_life >= 40 and period <= 6:
        return "limits harvest-now-decrypt-later exposure"
    return "scheduled for least total risk"


def build_roadmap(inst: Instance, schedule, rm: RiskModel) -> dict:
    unit = inst.meta.get("period_unit", "year")
    dep_count: dict[str, int] = {}
    for j, _i in inst.deps:
        dep_count[j] = dep_count.get(j, 0) + 1
    items = []
    for a in inst.assets:
        t = schedule.get(a.id)
        items.append({
            "id": a.id, "label": a.label or a.id, "kind": a.kind or "asset",
            "criticality": a.criticality,
            "period": t, "period_label": (_period_label(t, unit) if t is not None else None),
            "deadline_label": (_period_label(a.deadline, unit) if a.deadline is not None else None),
            "on_time": (a.deadline is None or (t is not None and t <= a.deadline)),
            "reason": (_reason(a, t, dep_count.get(a.id, 0)) if t is not None else "not scheduled"),
        })
    items.sort(key=lambda x: (x["period"] if x["period"] is not None else 10 ** 9, -x["criticality"]))
    timeline: dict[int, list] = {}
    for it in items:
        if it["period"] is not None:
            timeline.setdefault(it["period"], []).append(it)
    sc = score_schedule(inst, schedule, rm)
    return {
        "period_unit": unit,
        "summary": {
            "n_assets": len(inst.assets),
            "n_mandated": sum(1 for a in inst.assets if a.deadline is not None),
            "all_mandates_met": sc.deadline_violations == 0,
            "deadline_violations": sc.deadline_violations,
            "residual_risk": sc.risk, "effort": sc.cost,
            "first_period": (_period_label(min(timeline), unit) if timeline else None),
            "last_period": (_period_label(max(timeline), unit) if timeline else None),
        },
        "timeline": [{"period": t, "period_label": _period_label(t, unit), "assets": timeline[t]}
                     for t in sorted(timeline)],
    }


def naive_comparison(inst: Instance, rm: RiskModel, opt_objective, opt_optimal: bool) -> dict:
    sched = greedy_schedule(inst, "highest_risk", rm, seed=0)
    sc = score_schedule(inst, sched, rm)
    missed = [(a.label or a.id) for a in inst.assets
              if a.deadline is not None and (a.id not in sched or sched[a.id] > a.deadline)]
    gap = ((sc.risk - opt_objective) / opt_objective) if (opt_optimal and opt_objective) else None
    return {"approach": "highest-risk-first (the usual approach)", "feasible": sc.feasible,
            "missed_mandates": missed[:12], "n_missed": len(missed), "residual_risk": sc.risk,
            "extra_risk_vs_optimal": (round(gap, 4) if gap is not None else None)}


class PlanRequest(BaseModel):
    sample: str | None = None
    cbom: dict | None = None
    instance: InstanceIn | None = None
    capacity: conint(ge=1, le=10_000) | None = None
    time_limit: confloat(gt=0, le=Limits.MAX_TIME_LIMIT) = 8.0


@app.get("/samples")
def samples():
    out = []
    for sid, (title, fn) in SAMPLES.items():
        try:
            inst = fn(); s = inst.meta["stats"]
            out.append({"id": sid, "title": inst.meta.get("title", title),
                        "blurb": inst.meta.get("blurb", ""), "n_assets": s["n_assets"],
                        "n_mandated": s["n_mandated"]})
        except Exception:  # noqa: BLE001
            continue
    return {"samples": out}


@app.post("/plan")
def plan(req: PlanRequest):
    """Plan a migration: build an estate (sample / uploaded CBOM / instance), solve
    it to proven optimality, and return an actionable roadmap + what the usual
    'highest-risk-first' approach would do instead."""
    rm = RiskModel()
    if req.sample is not None:
        if req.sample not in SAMPLES:
            raise HTTPException(422, f"unknown sample; choose {list(SAMPLES)}")
        inst = sample_instance(req.sample)
    elif req.cbom is not None:
        if cbom_to_instance is None:
            raise HTTPException(503, "CBOM ingest unavailable in this build")
        comps = req.cbom.get("components", []) if isinstance(req.cbom, dict) else []
        if len(comps) > Limits.MAX_ASSETS:
            raise HTTPException(413, f"CBOM too large: {len(comps)} components (cap {Limits.MAX_ASSETS})")
        try:
            inst = cbom_to_instance(req.cbom, periods=20, t_crqc=30)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, f"could not parse this CBOM: {e}")
        if not inst.assets:
            raise HTTPException(422, "no quantum-vulnerable cryptographic assets found in this CBOM")
    elif req.instance is not None:
        inst = req.instance.to_instance()
    else:
        raise HTTPException(422, "provide one of: sample, cbom, instance")

    if len(inst.assets) > Limits.MAX_ASSETS or inst.T > Limits.MAX_T:
        raise HTTPException(413, "estate too large for the hosted demo")

    if req.capacity is not None:
        floor = max((a.cost for a in inst.assets), default=1)
        cap = max(int(req.capacity), floor)
        inst = Instance(assets=inst.assets, T=inst.T, budget=[cap] * inst.T, deps=inst.deps,
                        clusters=inst.clusters, t_crqc=inst.t_crqc, meta=inst.meta)

    tl = min(float(req.time_limit), Limits.MAX_TIME_LIMIT)
    if not _solve_sem.acquire(timeout=15):
        raise HTTPException(503, "server busy, retry shortly")
    try:
        res = solve_cpsat(inst, rm, time_limit=tl, workers=LIMITS.MAX_WORKERS)
    finally:
        _solve_sem.release()

    out = {
        "estate": {"title": inst.meta.get("title", inst.meta.get("scenario", "your estate")),
                   "blurb": inst.meta.get("blurb", ""), "n_assets": len(inst.assets),
                   "n_mandated": sum(1 for a in inst.assets if a.deadline is not None),
                   "capacity_per_period": (inst.budget[0] if inst.budget else None),
                   "period_unit": inst.meta.get("period_unit", "year")},
        "status": res.status, "proven_optimal": res.is_optimal,
    }
    if res.schedule is None:
        out["error"] = ("No feasible plan at this capacity — even the optimum cannot meet every "
                        "mandate. Increase the migration capacity per period.")
        return out
    out["roadmap"] = build_roadmap(inst, res.schedule, rm)
    out["naive"] = naive_comparison(inst, rm, res.objective, res.is_optimal)
    return out


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    icon = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
            "<rect width='32' height='32' rx='7' fill='#1456d6'/>"
            "<path d='M16 6a10 10 0 1 0 10 10h-2a8 8 0 1 1-8-8z' fill='white'/>"
            "<rect x='15' y='9' width='2' height='8' rx='1' fill='white'/></svg>")
    return Response(content=icon, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.head("/", include_in_schema=False)
def index_head():
    # uptime monitors / proxies often HEAD the root; answer 200 instead of 405
    return Response(status_code=200)


@app.get("/", response_class=HTMLResponse)
def index():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "static", "index.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return HTMLResponse(fh.read())
    return HTMLResponse("<h1>SAMAY · pqcsched</h1><p>API at <a href='/api'>/api</a></p>")
