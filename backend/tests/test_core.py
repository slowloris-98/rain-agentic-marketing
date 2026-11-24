import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/")
os.environ["ANTHROPIC_API_KEY"] = ""  # templates only: tests are deterministic and free

import numpy as np
import pytest

from app import settings, signals, sim
from app.agents.allocator import allocate, apply_guardrails
from app.agents.compliance import check
from app.agents.creative import disclosure


def simulate(seed: int, days: int = 84, agentic: bool = True) -> float:
    """Pure simulation loop (no DB): allocator vs fixed even split."""
    policy, cfg = settings.policy(), settings.value_cfg()
    keys = sim.all_arm_keys()
    stats = {k: {"spend": 0.0, "value": 0.0, "sumsq": 0.0, "days": 0} for k in keys}
    alloc, total = {}, 0.0
    for day in range(days):
        if agentic:
            alloc, _, _ = allocate(stats, alloc, policy, np.random.default_rng([seed, day, 99]))
        else:
            alloc = {k: policy["daily_budget"] / len(keys) for k in keys}
        res = sim.run_day(seed, day, alloc, stream=0)
        for k, r in res.items():
            v = sum(signals.value_score(a, cfg) for a in r["accounts"])
            total += v
            if r["spend"] > 0:
                s = stats[k]
                s["spend"] += r["spend"]; s["value"] += v; s["sumsq"] += v * v / r["spend"]; s["days"] += 1
    return total


def test_value_score():
    a = {"product": "checking", "balance": 10000, "tenure_months": 24, "direct_deposit": True}
    cfg = settings.value_cfg()
    assert signals.value_score(a, cfg) == pytest.approx(10000 * 0.003 * 24 * 1.5)


def test_baseline_is_stable():
    runs = [simulate(s, agentic=False) for s in range(3)]
    assert max(runs) / min(runs) < 1.5  # same order of magnitude across seeds


def test_allocator_beats_fixed_split():
    lifts = [simulate(s) / simulate(s, agentic=False) for s in range(5)]
    assert min(lifts) > 1.0, lifts
    assert np.mean(lifts) > 1.3, lifts


def test_guardrails():
    policy = {**settings.policy(), "daily_budget": 1000, "max_shift": 0.3, "geo_floor": 0.25}
    keys = sim.all_arm_keys()
    prev = {k: 1000 / len(keys) for k in keys}
    target = {k: (1000.0 if k == keys[0] else 0.0) for k in keys}  # everything into one branch arm
    out = apply_guardrails(target, prev, policy, 1000)
    moved = sum(abs(out[k] - prev[k]) for k in keys) / 2
    assert moved <= 300 + 1
    assert sum(out.values()) == pytest.approx(1000, abs=1)
    for g in sim.GEOS:
        assert sum(v for k, v in out.items() if k.endswith(g)) >= 250 - 1


def test_compliance():
    rates, policy = settings.rates(), settings.policy()
    good = {"product": "cd", "channel": "google", "headline": "12-Month CD: 4.35% APY", "body": "Lock in today.",
            "disclosure": disclosure("cd")}
    assert not [f for f in check(good, rates, policy) if f["severity"] == "error"]
    bad_rate = {**good, "headline": "CD at 5.00% APY"}
    assert any("does not match" in f["msg"] for f in check(bad_rate, rates, policy))
    best = {**good, "body": "The best CD in town."}
    assert any("best" in f["msg"] for f in check(best, rates, policy))
    no_apy = {**good, "headline": "Great CD", "disclosure": "Federally insured."}
    msgs = " ".join(f["msg"] for f in check(no_apy, rates, policy))
    assert "APY" in msgs and "Minimum balance" in msgs


def test_stub_payloads():
    from app.integrations import GoogleAds, MetaAds
    g, m = GoogleAds(), MetaAds()
    r = g.create_campaign("Test", 100)
    assert r["mode"] == "stub" and r["request"]["campaign"]["budget_amount_micros"] == 100_000_000
    r = m.create_campaign("Test", 100, 7)
    assert r["mode"] == "stub" and r["request"]["params"]["lifetime_budget"] == 70000
    acct = {"click_id": "x", "product": "cd", "balance": 20000, "tenure_months": 24, "direct_deposit": False,
            "email": "a@b.com", "value": 384.0}
    ev = signals.meta_event(acct, 3, settings.value_cfg())
    assert ev["action_source"] == "physical_store"
    assert set(ev["custom_data"]) >= {"value", "currency", "predicted_ltv"}
    ge = signals.google_event(acct, 3, settings.value_cfg())
    assert ge["conversionValue"] == 384.0 and ge["currency"] == "USD"


def test_full_cycle_and_tenant_scoping():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        tok = lambda e, p: {"Authorization": "Bearer " + c.post("/auth/login", json={"email": e, "password": p}).json()["token"]}
        admin, client = tok("admin@rain", "admin"), tok("client@lacap", "client")
        assert c.post("/admin/brief", json={}, headers=admin).status_code == 200
        pending = [x["id"] for x in c.get("/admin/approvals", headers=admin).json() if x["status"] == "pending_approval"]
        assert pending
        assert c.post("/admin/approvals", json={"approve": pending, "reject": []}, headers=admin).status_code == 200
        r = c.post("/admin/controls", json={"action": "run_days", "days": 14}, headers=admin).json()
        assert r["ran"] == 14
        k = c.get("/client/kpis", headers=client).json()
        assert k["new_accounts"] > 0
        assert c.get("/client/reports", headers=client).json()
        assert c.get("/admin/lessons", headers=admin).json()
        # client cannot reach admin routes or another tenant
        assert c.get("/admin/decisions", headers=client).status_code == 403
        assert c.get("/client/kpis?tenant_id=2", headers=client).json()["tenant_id"] == 1
