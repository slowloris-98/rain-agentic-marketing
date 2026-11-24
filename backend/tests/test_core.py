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


def test_crm_records():
    from app import crm
    cs = crm.list_customers()
    assert len(cs) >= 3 and len({c["id"] for c in cs}) == len(cs)
    for c in cs:
        assert {"id", "name", "institution_type", "insurer_disclosure", "rates_as_of", "products",
                "default_daily_budget", "default_weeks", "brand_voice"} <= set(c)
        assert set(c["products"]) <= set(sim.PRODUCTS)
        for p in c["products"].values():
            assert {"name", "apy", "min_balance", "monthly_fee", "extra"} <= set(p)


def test_compliance():
    from app import crm
    customer, policy = crm.get_customer("acme-ccu"), settings.policy()
    good = {"product": "cd", "channel": "google", "headline": "CD at 4.35% APY", "body": "Lock in today.",
            "disclosure": disclosure(customer, "cd")}
    assert not [f for f in check(good, customer, policy) if f["severity"] == "error"]
    bad_rate = {**good, "headline": "CD at 5.00% APY"}
    assert any("does not match" in f["msg"] for f in check(bad_rate, customer, policy))
    best = {**good, "body": "The best CD in town."}
    assert any("best" in f["msg"] for f in check(best, customer, policy))
    no_apy = {**good, "headline": "Great CD", "disclosure": "Some text."}
    msgs = " ".join(f["msg"] for f in check(no_apy, customer, policy))
    assert "APY" in msgs and "Minimum balance" in msgs and "NCUA" in msgs


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


def _login(c, email, pw):
    return {"Authorization": "Bearer " + c.post("/auth/login", json={"email": email, "password": pw}).json()["token"]}


def _start_and_approve(c, admin, body):
    tid = c.post("/admin/campaigns/start", json=body, headers=admin).json()["tenant_id"]
    q = f"?tenant_id={tid}"
    assert c.get("/admin/state" + q, headers=admin).json()["phase"] == "awaiting_approval"
    creatives = c.get("/admin/approvals" + q, headers=admin).json()
    pending = [x["id"] for x in creatives if x["status"] == "pending_approval"]
    assert pending
    assert c.post("/admin/approvals" + q, json={"approve": pending, "reject": []}, headers=admin).status_code == 200
    return tid, q, creatives


def test_goal_drives_plan_and_customer_facts():
    from fastapi.testclient import TestClient
    from app import crm, db
    from app.main import app

    bank = crm.get_customer("summit-ridge-bank")
    with TestClient(app) as c:
        admin = _login(c, "admin@rain", "admin")
        assert c.post("/admin/campaigns/start", json={"customer_id": "nope", "goal": "grow deposits"},
                      headers=admin).status_code == 404
        tid, q, creatives = _start_and_approve(c, admin, {
            "customer_id": "summit-ridge-bank", "goal": "Grow CDs among retirees near our branches",
            "daily_budget": 1000, "days": 30})
        st = c.get("/admin/state" + q, headers=admin).json()
        plan = st["plan"]
        assert plan["days"] == 30 and plan["weeks"] == 5 and st["running_agent"] is None
        assert plan["products"] == ["cd"] and plan["audiences"] == ["55+"] and plan["geos"] == ["branch"]
        assert all(a.product == "cd" and a.audience == "55+" and a.geo == "branch" for a in db.arms(tid))
        text = " ".join(f"{x['headline']} {x['body']} {x['disclosure']}" for x in creatives)
        assert "Summit Ridge Bank" in text and f"{bank['products']['cd']['apy']:.2f}% APY" in text
        assert "Member FDIC." in text and "NCUA" not in text and "La Cap" not in text
        assert c.post("/admin/controls" + q, json={"action": "run_days", "days": 3}, headers=admin).json()["ran"] == 3
        split = c.get("/admin/allocator" + q, headers=admin).json()["split"]
        for day in split:
            assert abs(sum(v for k, v in day.items() if k in sim.PRODUCTS) - 1000) < 1


def test_full_cycle_and_client_scoping():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        admin, client = _login(c, "admin@rain", "admin"), _login(c, "client@acme", "client")
        tid, q, _ = _start_and_approve(c, admin, {"customer_id": "acme-ccu", "goal": "Grow core deposits this quarter"})
        assert c.post("/admin/controls" + q, json={"action": "run_days", "days": 14}, headers=admin).json()["ran"] == 14
        k = c.get("/client/kpis", headers=client).json()
        assert k["tenant_id"] == tid and k["new_accounts"] > 0
        assert c.get("/client/reports", headers=client).json()
        assert c.get("/admin/lessons" + q, headers=admin).json()
        # a second Acme run starts with the first run's lessons (memory carries across campaigns)
        tid2 = c.post("/admin/campaigns/start", json={"customer_id": "acme-ccu", "goal": "More checking accounts"},
                      headers=admin).json()["tenant_id"]
        state = c.get(f"/admin/decisions?tenant_id={tid2}&agent=strategist", headers=admin).json()[0]
        assert state["inputs"]["lessons"]
        # client follows its own latest run; it can't reach admin routes or another customer's run
        assert c.get("/client/kpis", headers=client).json()["tenant_id"] == tid2
        summit = c.post("/admin/campaigns/start", json={"customer_id": "summit-ridge-bank", "goal": "Grow savings"},
                        headers=admin).json()["tenant_id"]
        assert c.get(f"/client/kpis?tenant_id={summit}", headers=client).json()["tenant_id"] == tid2
        assert c.get("/admin/decisions", headers=client).status_code == 403
