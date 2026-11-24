"""The orchestrator: ordered node lists + a tiny runner.

LangGraph migration: each list below becomes a chain of `add_node`/`add_edge` in a
`StateGraph(CycleState)`; the approval pause becomes `interrupt_before=["media_launch"]`
with the SQLite checkpointer replacing run_state.state. Node functions stay unchanged.
"""
import asyncio
import json
import math
import threading
from typing import Callable

from . import crm, db, sim
from .agents.allocator import allocator
from .agents.compliance import compliance
from .agents.core_feed import core_feed, simulate_day, upload_conversions
from .agents.creative import creative
from .agents.media import media_launch, media_update
from .agents.reflection import reflection, rollup
from .agents.reporter import reporter
from .agents.strategist import strategist
from .state import CycleState

SETUP = [strategist, creative, compliance]          # -> human approval gate
LAUNCH = [media_launch]
DAILY = [allocator, media_update, simulate_day, core_feed, upload_conversions]
WEEKLY = [rollup, reflection, reporter]
TRANSIENT = {"today", "new_accounts", "week_stats"}  # not checkpointed

_lock = threading.Lock()
CURRENT: dict[int, str | None] = {}  # tenant_id -> agent currently executing (for the live agent map)

# ---------------------------------------------------------------- live event bus (SSE)
_subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers.append((asyncio.get_running_loop(), q))
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers[:] = [(l, x) for l, x in _subscribers if x is not q]


def publish(event: dict) -> None:
    for loop, q in list(_subscribers):
        try:
            loop.call_soon_threadsafe(q.put_nowait, event)
        except Exception:
            pass


# ---------------------------------------------------------------- runner
def log_decision(tenant_id: int, day: int, agent: str, log: dict, out: dict) -> None:
    output = log.get("output", {k: v for k, v in out.items() if k not in TRANSIENT})
    d = db.AgentDecision(tenant_id=tenant_id, day=day, agent=agent,
                         inputs=json.loads(json.dumps(log.get("inputs", {}), default=str)),
                         output=json.loads(json.dumps(output, default=str)),
                         reasoning=log.get("reasoning", ""))
    db.add_all([d])
    publish({"type": "decision", "tenant_id": tenant_id, "id": d.id, "day": day, "agent": agent,
             "reasoning": d.reasoning, "ts": d.ts.isoformat()})


def run(nodes: list[Callable], state: CycleState, paused: list[str] | None = None) -> CycleState:
    for node in nodes:
        name = node.__name__
        if name in (paused or []):
            log_decision(state["tenant_id"], state.get("day", 0), name, {"reasoning": "Skipped: agent paused."}, {})
            continue
        tid = state["tenant_id"]
        CURRENT[tid] = name
        publish({"type": "agent_start", "tenant_id": tid, "agent": name})
        try:
            out = node(state)
        finally:
            CURRENT[tid] = None
        log = out.pop("_log", {})
        state.update(out)
        log_decision(state["tenant_id"], state.get("day", 0), name, log, out)
    return state


def _load(tenant_id: int) -> tuple[db.RunState, CycleState]:
    rs = db.run_state(tenant_id)
    state: CycleState = dict(rs.state or {})
    state.setdefault("tenant_id", tenant_id)
    state["day"] = rs.day
    state["lessons"] = db.lessons(tenant_id)
    return rs, state


def _save(tenant_id: int, state: CycleState, **fields) -> None:
    durable = {k: v for k, v in state.items() if k not in TRANSIENT}
    db.save_run_state(tenant_id, state=json.loads(json.dumps(durable, default=str)), **fields)


# ---------------------------------------------------------------- public API
def create_run(customer_id: str, goal: str, daily_budget: float | None = None, weeks: int | None = None,
               days: int | None = None) -> int:
    """Start a new campaign run (tenant) for a CRM customer. The CRM record is snapshotted into
    state so every agent uses the same rates/disclosures for the whole run."""
    customer = crm.get_customer(customer_id)  # KeyError for unknown ids
    seed = sim._h(customer_id) % 10000        # same bank -> same simulated market across runs
    brief = {
        "goal": goal.strip(),
        "daily_budget": float(daily_budget or customer["default_daily_budget"]),
        "days": int(days or (weeks or customer["default_weeks"]) * 7),
        "customer_id": customer_id, "client": customer["name"],
    }
    brief["weeks"] = max(1, math.ceil(brief["days"] / 7))
    with db.session() as s:
        t = db.Tenant(name=customer["name"], crm_id=customer_id, assets_musd=customer["assets_musd"],
                      branches=customer["branches"], goal=brief["goal"][:60], seed=seed)
        s.add(t)
        s.flush()
        tid = t.id
        for k in sim.all_arm_keys():
            p, c, a, g = k.split("|")
            s.add(db.Arm(tenant_id=tid, key=k, product=p, channel=c, audience=a, geo=g, active=False))
        s.add(db.RunState(tenant_id=tid, phase="planning", paused_agents=[],
                          state={"tenant_id": tid, "seed": seed, "customer": customer, "brief": brief}))
    publish({"type": "phase", "tenant_id": tid, "phase": "planning"})
    return tid


def submit_brief(tenant_id: int) -> CycleState:
    """Run strategist -> creative -> compliance for a run created by create_run, then wait for approval."""
    with _lock:
        rs, state = _load(tenant_id)
        state = run(SETUP, state, rs.paused_agents)
        _save(tenant_id, state, phase="awaiting_approval")
        publish({"type": "phase", "tenant_id": tenant_id, "phase": "awaiting_approval"})
        return state


def decide(tenant_id: int, approve: list[int], reject: list[int]) -> CycleState:
    """The single human click. Approve/reject creatives, then launch."""
    with _lock:
        if db.run_state(tenant_id).phase != "awaiting_approval":
            raise ValueError("Nothing is awaiting approval")
        with db.session() as s:
            for c in s.query(db.Creative).filter(db.Creative.tenant_id == tenant_id,
                                                 db.Creative.id.in_(approve + reject)):
                if c.status == "pending_approval":
                    c.status = "approved" if c.id in approve else "rejected"
                    c.decided_at = db.now()
        rs, state = _load(tenant_id)
        log_decision(tenant_id, state["day"], "human_approval",
                     {"inputs": {"approved": approve, "rejected": reject},
                      "reasoning": f"Human approved {len(approve)} and rejected {len(reject)} creatives."}, {})
        state["approved"] = True
        state = run(LAUNCH, state, rs.paused_agents)
        phase = "running" if state.get("campaigns") else "idle"
        _save(tenant_id, state, phase=phase)
        publish({"type": "phase", "tenant_id": tenant_id, "phase": phase})
        return state


def step_day(tenant_id: int) -> bool:
    with _lock:
        rs, state = _load(tenant_id)
        if rs.killed or rs.phase != "running":
            return False
        state = run(DAILY, state, rs.paused_agents)
        if (state["day"] + 1) % 7 == 0:
            state = run(WEEKLY, state, rs.paused_agents)
        _save(tenant_id, state, day=state["day"] + 1)
        publish({"type": "day", "tenant_id": tenant_id, "day": state["day"] + 1})
        return True


def run_days(tenant_id: int, n: int) -> int:
    done = 0
    for _ in range(n):
        if not step_day(tenant_id):
            break
        done += 1
    return done


def control(tenant_id: int, action: str, agent: str | None = None) -> dict:
    rs = db.run_state(tenant_id)
    paused = list(rs.paused_agents or [])
    if action == "kill":
        db.save_run_state(tenant_id, killed=True)
        with db.session() as s:
            for c in s.query(db.Campaign).filter(db.Campaign.tenant_id == tenant_id, db.Campaign.status == "live"):
                c.status = "paused"
    elif action == "resume":
        db.save_run_state(tenant_id, killed=False)
        with db.session() as s:
            for c in s.query(db.Campaign).filter(db.Campaign.tenant_id == tenant_id, db.Campaign.status == "paused"):
                c.status = "live"
    elif action == "pause" and agent:
        db.save_run_state(tenant_id, paused_agents=sorted(set(paused) | {agent}))
    elif action == "unpause" and agent:
        db.save_run_state(tenant_id, paused_agents=[a for a in paused if a != agent])
    log_decision(tenant_id, rs.day, "human_control", {"inputs": {"action": action, "agent": agent},
                                                      "reasoning": f"Admin control: {action} {agent or ''}".strip()}, {})
    publish({"type": "phase", "tenant_id": tenant_id})
    return {"ok": True}


AGENTS = [n.__name__ for n in SETUP + LAUNCH + DAILY + WEEKLY]
