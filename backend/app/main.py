"""FastAPI app: auth, admin + client APIs, SSE stream, optional auto-tick."""
import asyncio
import json
import signal
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import crm, db, integrations, orchestrator, settings


# Set when the server is asked to stop. Open SSE streams watch it and end themselves: uvicorn's
# graceful shutdown waits for every connection to close, and on Python 3.12 even a forced second
# Ctrl+C still blocks in server.wait_closed() while a stream is open, so the process never exits.
SHUTDOWN = threading.Event()


def _watch_shutdown_signals() -> None:
    """Chain onto the server's signal handlers (installed before the app starts) without replacing them."""
    sigs = [signal.SIGINT, signal.SIGTERM] + ([signal.SIGBREAK] if sys.platform == "win32" else [])
    for sig in sigs:
        prev = signal.getsignal(sig)

        def handler(num, frame, prev=prev):
            SHUTDOWN.set()
            if callable(prev):
                prev(num, frame)
            elif num == signal.SIGINT:
                raise KeyboardInterrupt

        try:
            signal.signal(sig, handler)
        except ValueError:
            return  # not the main thread (e.g. TestClient): nothing to chain onto


@asynccontextmanager
async def lifespan(_app):
    SHUTDOWN.clear()
    _watch_shutdown_signals()
    db.init_db()
    task = asyncio.create_task(_ticker()) if settings.TICK_SECONDS > 0 else None
    yield
    if task:
        task.cancel()


async def _ticker():
    """Auto-advance each running tenant by one simulated day every TICK_SECONDS."""
    while True:
        await asyncio.sleep(settings.TICK_SECONDS)
        for t in _all_tenants():
            await asyncio.to_thread(orchestrator.step_day, t)


def _all_tenants() -> list[int]:
    with db.session() as s:
        return list(s.scalars(select(db.Tenant.id)))


app = FastAPI(title="RAIN agentic marketing", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- auth
class Login(BaseModel):
    email: str
    password: str


@app.post("/auth/login")
def login(body: Login):
    u = settings.USERS.get(body.email)
    if not u or u["password"] != body.password:
        raise HTTPException(401, "Invalid credentials")
    claims = {"sub": body.email, "role": u["role"], "crm_id": u["crm_id"],
              "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return {"token": jwt.encode(claims, settings.JWT_SECRET, algorithm="HS256"), "role": u["role"]}


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid token")


def user(request: Request) -> dict:
    h = request.headers.get("authorization", "")
    if not h.lower().startswith("bearer "):
        raise HTTPException(401, "Missing token")
    return _decode(h[7:])


def admin(u: dict = Depends(user)) -> dict:
    if u["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return u


def _scope(u: dict, tenant_id: int) -> int:
    """Clients always see their CRM customer's latest run (0 = none yet); admins pick any run."""
    return db.latest_run(u["crm_id"]) if u["role"] == "client" else tenant_id


def tenant(u: dict = Depends(user), tenant_id: int = Query(0)) -> int:
    return _scope(u, tenant_id)


# ---------------------------------------------------------------- SSE
@app.get("/stream")
async def stream(token: str, tenant_id: int = 0):
    u = _decode(token)  # EventSource can't send headers, so the token rides in the query
    tid = _scope(u, tenant_id)
    q = orchestrator.subscribe()

    async def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            idle = 0
            while not SHUTDOWN.is_set():  # end the stream on shutdown so the server can exit
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1)
                except asyncio.TimeoutError:
                    idle += 1
                    if idle >= 15:
                        idle = 0
                        yield ": keepalive\n\n"
                    continue
                idle = 0
                if ev.get("tenant_id") == tid:
                    if u["role"] == "client" and ev["type"] == "decision":
                        continue  # clients see results, not internal agent reasoning
                    yield f"data: {json.dumps(ev)}\n\n"
        finally:
            orchestrator.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- admin
def _d(o) -> dict:
    return {c.name: getattr(o, c.name) for c in o.__table__.columns}


@app.get("/admin/customers")
def customers(_=Depends(admin)):
    """Customer banks / credit unions from the CRM (static stub for now)."""
    return crm.list_customers()


class StartCampaign(BaseModel):
    customer_id: str
    goal: str = Field(min_length=5, max_length=1000)
    daily_budget: float | None = Field(default=None, gt=0, le=100_000)
    weeks: int | None = Field(default=None, ge=1, le=52)
    days: int | None = Field(default=None, ge=1, le=365)


def _plan_in_background(tid: int) -> None:
    try:
        orchestrator.submit_brief(tid)
    except Exception as e:  # surface failures instead of leaving the run stuck in "planning"
        db.save_run_state(tid, phase="error")
        orchestrator.log_decision(tid, 0, "orchestrator", {"reasoning": f"Planning failed: {e}"}, {})


@app.post("/admin/campaigns/start")
def start_campaign(body: StartCampaign, tasks: BackgroundTasks, _=Depends(admin)):
    """Create a new run for a CRM customer and plan it in the background so the UI can watch live."""
    try:
        tid = orchestrator.create_run(body.customer_id, body.goal, body.daily_budget, body.weeks, body.days)
    except KeyError as e:
        raise HTTPException(404, str(e))
    tasks.add_task(_plan_in_background, tid)
    return {"tenant_id": tid}


@app.get("/admin/tenants")
def tenants(_=Depends(admin)):
    with db.session() as s:
        rows = s.execute(select(db.Tenant, db.RunState).join(db.RunState, db.RunState.tenant_id == db.Tenant.id)
                         .order_by(db.Tenant.id.desc())).all()
        return [{"id": t.id, "name": t.name, "crm_id": t.crm_id, "goal": (r.state or {}).get("brief", {}).get("goal"),
                 "phase": r.phase, "day": r.day} for t, r in rows]


@app.get("/admin/state")
def admin_state(tid: int = Depends(tenant), _=Depends(admin)):
    with db.session() as s:
        rs = s.get(db.RunState, tid)
    if rs is None:
        if tid == 0:
            return None  # no run selected yet (fresh install)
        raise HTTPException(404, "Unknown run")
    st = rs.state or {}
    return {"day": rs.day, "phase": rs.phase, "killed": rs.killed, "paused_agents": rs.paused_agents,
            "agents": orchestrator.AGENTS, "running_agent": orchestrator.CURRENT.get(tid), "plan": st.get("plan"), "brief": st.get("brief"),
            "customer": st.get("customer"), "mode": settings.MODE,
            "llm": bool(settings.ANTHROPIC_API_KEY),
            "integrations": {"google": "live" if integrations.google.configured else "stub",
                             "meta": "live" if integrations.meta.configured else "stub"}}


@app.get("/admin/decisions")
def decisions(tid: int = Depends(tenant), _=Depends(admin), limit: int = 200, agent: str | None = None):
    where = [db.AgentDecision.agent == agent] if agent else []
    return [_d(x) for x in db.rows(db.AgentDecision, tid, *where, order=db.AgentDecision.id.desc(), limit=limit)]


@app.get("/admin/approvals")
def approvals(tid: int = Depends(tenant), _=Depends(admin)):
    return [_d(x) for x in db.rows(db.Creative, tid, order=db.Creative.id.desc(), limit=200)]


class Decision(BaseModel):
    approve: list[int] = []
    reject: list[int] = []


@app.post("/admin/approvals")
def approve(body: Decision, tid: int = Depends(tenant), _=Depends(admin)):
    try:
        s = orchestrator.decide(tid, body.approve, body.reject)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"campaigns": s.get("campaigns", [])}


@app.get("/admin/campaigns")
def admin_campaigns(tid: int = Depends(tenant), _=Depends(admin)):
    return [_d(x) for x in db.rows(db.Campaign, tid, order=db.Campaign.id)]


@app.get("/admin/allocator")
def allocator_view(tid: int = Depends(tenant), _=Depends(admin)):
    with db.session() as s:
        by_day = s.execute(select(db.Allocation.day, db.Allocation.arm_key, db.Allocation.budget, db.Allocation.explore)
                           .where(db.Allocation.tenant_id == tid).order_by(db.Allocation.day)).all()
        last = s.scalar(select(func.max(db.Allocation.day)).where(db.Allocation.tenant_id == tid))
        latest = s.scalars(select(db.Allocation).where(db.Allocation.tenant_id == tid, db.Allocation.day == last)).all()
    split: dict[int, dict] = {}
    for day, key, budget, explore in by_day:
        row = split.setdefault(day, {"day": day, "explore": 0.0})
        p = key.split("|")[0]
        row[p] = round(row.get(p, 0) + budget, 2)
        if explore:
            row["explore"] += budget
    arms = db.arms(tid)
    spend = {a.key: a.spend for a in arms}
    return {
        "split": list(split.values()),
        "posteriors": sorted(({"arm": a.arm_key, "mean": round(a.mean, 3), "sd": round(a.sd, 3),
                               "budget": a.budget, "explore": a.explore, "spend": round(spend.get(a.arm_key, 0), 2)}
                              for a in latest), key=lambda x: -x["mean"]),
    }


@app.get("/admin/lessons")
def admin_lessons(tid: int = Depends(tenant), _=Depends(admin)):
    return sorted((_d(x) for x in db.rows(db.Lesson, tid)), key=lambda l: (-l["week"], l["id"]))


@app.get("/admin/conversions")
def conversions(tid: int = Depends(tenant), _=Depends(admin), limit: int = 50):
    return [_d(x) for x in db.rows(db.ConversionUpload, tid, order=db.ConversionUpload.id.desc(), limit=limit)]


@app.get("/admin/policy")
def get_policy(_=Depends(admin)):
    return settings.policy()


@app.put("/admin/policy")
def put_policy(body: dict, _=Depends(admin)):
    p = settings.policy()
    for k, v in body.items():
        if k in p and type(v) in (int, float, list, str):
            p[k] = v
    settings.save_policy(p)
    return p


class Control(BaseModel):
    action: str  # kill | resume | pause | unpause | run_days
    agent: str | None = None
    days: int = 7


@app.post("/admin/controls")
def controls(body: Control, tid: int = Depends(tenant), _=Depends(admin)):
    if body.action == "run_days":
        return {"ran": orchestrator.run_days(tid, max(1, min(body.days, 120)))}
    if body.action not in ("kill", "resume", "pause", "unpause"):
        raise HTTPException(400, "Unknown action")
    return orchestrator.control(tid, body.action, body.agent)


# ---------------------------------------------------------------- client (read-only, tenant-scoped)
@app.get("/client/kpis")
def kpis(tid: int = Depends(tenant)):
    a, b = db.totals(tid, False), db.totals(tid, True)
    with db.session() as s:
        members = dict(s.execute(select(db.Account.member, func.count()).where(db.Account.tenant_id == tid)
                                 .group_by(db.Account.member)).all())
        t = s.get(db.Tenant, tid)
        rs = s.get(db.RunState, tid)
    return {
        "tenant_id": tid, "tenant": t.name if t else None, "day": rs.day if rs else 0,
        "goal": (rs.state or {}).get("brief", {}).get("goal") if rs else None,
        "new_accounts": a["accounts"], "new_deposits": round(a["deposits"], 2),
        "avg_balance": round(a["deposits"] / a["accounts"], 2) if a["accounts"] else 0,
        "cost_per_1k_deposits": round(a["spend"] / (a["deposits"] / 1000), 2) if a["deposits"] else 0,
        "spend": round(a["spend"], 2), "value": round(a["value"], 2),
        "members": members.get(True, 0), "non_members": members.get(False, 0),
        "baseline": {"accounts": b["accounts"], "deposits": round(b["deposits"], 2), "value": round(b["value"], 2)},
        "lift_vs_baseline": round(a["value"] / b["value"] - 1, 4) if b["value"] else None,
    }


def _campaign_rows(tid: int, camp: db.Campaign) -> dict:
    with db.session() as s:
        r = s.execute(select(func.sum(db.DailyMetric.spend), func.sum(db.DailyMetric.clicks),
                             func.sum(db.DailyMetric.accounts), func.sum(db.DailyMetric.deposits),
                             func.sum(db.DailyMetric.value))
                      .where(db.DailyMetric.tenant_id == tid, db.DailyMetric.baseline.is_(False),
                             db.DailyMetric.arm_key.like(f"{camp.product}|{camp.channel}|%"))).one()
    spend, clicks, accts, dep, val = (x or 0 for x in r)
    return {"id": camp.id, "name": camp.name, "product": camp.product, "channel": camp.channel,
            "status": camp.status, "envelope": round(camp.envelope, 2), "spend": round(spend, 2), "clicks": clicks,
            "accounts": accts, "deposits": round(dep, 2), "value": round(val, 2)}


@app.get("/client/campaigns")
def client_campaigns(tid: int = Depends(tenant)):
    return [_campaign_rows(tid, c) for c in db.rows(db.Campaign, tid, order=db.Campaign.id)]


@app.get("/client/campaigns/{cid}")
def client_campaign(cid: int, tid: int = Depends(tenant)):
    camps = db.rows(db.Campaign, tid, db.Campaign.id == cid)
    if not camps:
        raise HTTPException(404)
    c = camps[0]
    with db.session() as s:
        daily = s.execute(select(db.DailyMetric.day, func.sum(db.DailyMetric.spend), func.sum(db.DailyMetric.accounts),
                                 func.sum(db.DailyMetric.deposits))
                          .where(db.DailyMetric.tenant_id == tid, db.DailyMetric.baseline.is_(False),
                                 db.DailyMetric.arm_key.like(f"{c.product}|{c.channel}|%"))
                          .group_by(db.DailyMetric.day).order_by(db.DailyMetric.day)).all()
    creatives = db.rows(db.Creative, tid, db.Creative.product == c.product, db.Creative.channel == c.channel,
                        db.Creative.status == "approved")
    return {**_campaign_rows(tid, c),
            "daily": [{"day": d, "spend": round(sp, 2), "accounts": a, "deposits": round(dp, 2)} for d, sp, a, dp in daily],
            "creatives": [{"headline": x.headline, "body": x.body, "disclosure": x.disclosure} for x in creatives]}


@app.get("/client/trends")
def trends(tid: int = Depends(tenant)):
    with db.session() as s:
        rows = s.execute(select(db.DailyMetric.day, db.DailyMetric.baseline, func.sum(db.DailyMetric.deposits),
                                func.sum(db.DailyMetric.value))
                         .where(db.DailyMetric.tenant_id == tid)
                         .group_by(db.DailyMetric.day, db.DailyMetric.baseline).order_by(db.DailyMetric.day)).all()
    out: dict[int, dict] = {}
    cum = {True: 0.0, False: 0.0}
    for day, base, dep, val in rows:
        cum[base] += val or 0
        r = out.setdefault(day, {"day": day})
        tag = "baseline" if base else "agentic"
        r[f"{tag}_deposits"] = round(dep or 0, 2)
        r[f"{tag}_value_cum"] = round(cum[base], 2)
    return list(out.values())


@app.get("/client/reports")
def reports(tid: int = Depends(tenant)):
    return [{"week": r.week, "text": r.text} for r in db.rows(db.Report, tid, order=db.Report.id.desc())]
