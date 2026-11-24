"""SQLAlchemy models and small query helpers. Agents touch the DB only through here."""
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from . import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    assets_musd: Mapped[float] = mapped_column(Float, default=0)
    branches: Mapped[int] = mapped_column(Integer, default=0)
    goal: Mapped[str] = mapped_column(String(60), default="deposits")
    seed: Mapped[int] = mapped_column(Integer, default=7)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    product: Mapped[str] = mapped_column(String(30))
    channel: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|live|paused
    platform_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    envelope: Mapped[float] = mapped_column(Float, default=0)  # $/day
    spend: Mapped[float] = mapped_column(Float, default=0)


class Creative(Base):
    __tablename__ = "creatives"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    product: Mapped[str] = mapped_column(String(30))
    channel: Mapped[str] = mapped_column(String(10))
    headline: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    disclosure: Mapped[str] = mapped_column(Text)
    # pending_approval | failed_compliance | approved | rejected
    status: Mapped[str] = mapped_column(String(30), default="pending_approval")
    findings: Mapped[list] = mapped_column(JSON, default=list)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Arm(Base):
    __tablename__ = "arms"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    key: Mapped[str] = mapped_column(String(80), index=True)  # product|channel|audience|geo
    product: Mapped[str] = mapped_column(String(30))
    channel: Mapped[str] = mapped_column(String(10))
    audience: Mapped[str] = mapped_column(String(20))
    geo: Mapped[str] = mapped_column(String(20))
    spend: Mapped[float] = mapped_column(Float, default=0)   # cumulative
    value: Mapped[float] = mapped_column(Float, default=0)   # cumulative
    sumsq: Mapped[float] = mapped_column(Float, default=0)   # sum of spend * (value/spend)^2, for variance
    days: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Allocation(Base):
    __tablename__ = "allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    day: Mapped[int] = mapped_column(Integer, index=True)
    arm_key: Mapped[str] = mapped_column(String(80))
    budget: Mapped[float] = mapped_column(Float)
    explore: Mapped[bool] = mapped_column(Boolean, default=False)
    mean: Mapped[float] = mapped_column(Float, default=0)
    sd: Mapped[float] = mapped_column(Float, default=0)


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    day: Mapped[int] = mapped_column(Integer, index=True)
    arm_key: Mapped[str] = mapped_column(String(80))
    baseline: Mapped[bool] = mapped_column(Boolean, default=False)  # fixed even-split shadow run
    spend: Mapped[float] = mapped_column(Float, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    accounts: Mapped[int] = mapped_column(Integer, default=0)
    deposits: Mapped[float] = mapped_column(Float, default=0)
    value: Mapped[float] = mapped_column(Float, default=0)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    day: Mapped[int] = mapped_column(Integer, index=True)
    click_id: Mapped[str] = mapped_column(String(120))
    arm_key: Mapped[str] = mapped_column(String(80))
    product: Mapped[str] = mapped_column(String(30))
    balance: Mapped[float] = mapped_column(Float)
    tenure_months: Mapped[float] = mapped_column(Float)
    direct_deposit: Mapped[bool] = mapped_column(Boolean)
    member: Mapped[bool] = mapped_column(Boolean)
    email: Mapped[str] = mapped_column(String(120))
    value: Mapped[float] = mapped_column(Float, default=0)


class ConversionUpload(Base):
    __tablename__ = "conversion_uploads"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    platform: Mapped[str] = mapped_column(String(10))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))  # sent | sent_sandbox | failed
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AgentDecision(Base):
    __tablename__ = "agent_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    day: Mapped[int] = mapped_column(Integer, default=0)
    agent: Mapped[str] = mapped_column(String(40))
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    reasoning: Mapped[str] = mapped_column(Text, default="")


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    week: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    week: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class RunState(Base):
    """One row per tenant: run controls + the checkpointed CycleState (LangGraph checkpointer later)."""
    __tablename__ = "run_state"
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    day: Mapped[int] = mapped_column(Integer, default=0)
    phase: Mapped[str] = mapped_column(String(30), default="idle")  # idle|awaiting_approval|running
    killed: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_agents: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[dict] = mapped_column(JSON, default=dict)


def init_db():
    Base.metadata.create_all(engine)


@contextmanager
def session() -> Session:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------- helpers used by agents ----------

def rows(model, tenant_id: int, *where, order=None, limit=None) -> list:
    with session() as s:
        q = select(model).where(model.tenant_id == tenant_id, *where)
        if order is not None:
            q = q.order_by(order)
        if limit:
            q = q.limit(limit)
        return list(s.scalars(q))


def add_all(objs: list) -> list:
    with session() as s:
        s.add_all(objs)
        s.flush()
        return objs


def arms(tenant_id: int, active_only=True) -> list[Arm]:
    return rows(Arm, tenant_id, *( [Arm.active.is_(True)] if active_only else [] ), order=Arm.key)


def lessons(tenant_id: int, limit=10) -> list[str]:
    return [l.text for l in rows(Lesson, tenant_id, order=Lesson.id.desc(), limit=limit)]


def run_state(tenant_id: int) -> RunState:
    with session() as s:
        rs = s.get(RunState, tenant_id)
        if rs is None:
            rs = RunState(tenant_id=tenant_id, state={}, paused_agents=[])
            s.add(rs)
            s.flush()
        return rs


def save_run_state(tenant_id: int, **fields) -> None:
    with session() as s:
        rs = s.get(RunState, tenant_id) or RunState(tenant_id=tenant_id)
        for k, v in fields.items():
            setattr(rs, k, v)
        s.merge(rs)


def totals(tenant_id: int, baseline: bool, since_day: int = 0) -> dict:
    with session() as s:
        r = s.execute(
            select(func.sum(DailyMetric.spend), func.sum(DailyMetric.accounts), func.sum(DailyMetric.deposits),
                   func.sum(DailyMetric.value), func.sum(DailyMetric.clicks))
            .where(DailyMetric.tenant_id == tenant_id, DailyMetric.baseline.is_(baseline), DailyMetric.day >= since_day)
        ).one()
    spend, accts, dep, val, clicks = (x or 0 for x in r)
    return {"spend": spend, "accounts": accts, "deposits": dep, "value": val, "clicks": clicks}
