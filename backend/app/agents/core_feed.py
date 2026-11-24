"""Signal-layer nodes: simulate traffic, pull new accounts from the core, upload conversions."""
from sqlalchemy import select

from .. import db, settings, signals, sim
from ..integrations import google, meta
from ..state import CycleState


def simulate_day(state: CycleState) -> dict:
    """Node: in sandbox mode, impressions/clicks/spend/accounts come from the simulator.
    Also runs the fixed even-split baseline on a separate random stream for comparison."""
    seed, day, alloc = state.get("seed", 7), state["day"], state["allocation"]
    agentic = sim.run_day(seed, day, alloc, stream=0)
    total = sum(alloc.values())
    baseline = sim.run_day(seed, day, {k: total / len(alloc) for k in alloc}, stream=1)
    clicks = sum(r["clicks"] for r in agentic.values())
    return {
        "today": {"agentic": agentic, "baseline": baseline},
        "_log": {"inputs": {"spend": round(total, 2)}, "output": {"clicks": clicks},
                 "reasoning": f"Simulated day {day}: ${total:,.0f} spend, {clicks} clicks."},
    }


def core_feed(state: CycleState) -> dict:
    """Node: pull new accounts, join each to its arm via click id, score value, update arm stats."""
    tid, day = state["tenant_id"], state["day"]
    cfg = settings.value_cfg()
    today = state["today"]
    accounts, metrics, new = [], [], []
    per_arm_value: dict[str, float] = {}

    for key, r in today["agentic"].items():
        val = dep = 0.0
        for a in r["accounts"]:
            arm_key = a["click_id"].split("~")[0]  # click -> arm join
            a = {**a, "arm_key": arm_key, "value": signals.value_score(a, cfg)}
            val += a["value"]
            dep += a["balance"]
            accounts.append(db.Account(tenant_id=tid, day=day, **a))
        per_arm_value[key] = val
        metrics.append(db.DailyMetric(tenant_id=tid, day=day, arm_key=key, spend=r["spend"],
                                      impressions=r["impressions"], clicks=r["clicks"],
                                      accounts=len(r["accounts"]), deposits=dep, value=val))
    b = today["baseline"].values()
    metrics.append(db.DailyMetric(
        tenant_id=tid, day=day, arm_key="*", baseline=True,
        spend=sum(r["spend"] for r in b), impressions=sum(r["impressions"] for r in b),
        clicks=sum(r["clicks"] for r in b), accounts=sum(len(r["accounts"]) for r in b),
        deposits=sum(a["balance"] for r in b for a in r["accounts"]),
        value=sum(signals.value_score(a, cfg) for r in b for a in r["accounts"])))
    db.add_all(accounts + metrics)

    with db.session() as s:
        for arm in s.scalars(select(db.Arm).where(db.Arm.tenant_id == tid, db.Arm.active.is_(True))):
            spend = today["agentic"].get(arm.key, {}).get("spend", 0)
            if spend > 0:
                v = per_arm_value.get(arm.key, 0.0)
                arm.spend += spend
                arm.value += v
                arm.sumsq += v * v / spend
                arm.days += 1
        for c in s.scalars(select(db.Campaign).where(db.Campaign.tenant_id == tid, db.Campaign.status == "live")):
            c.spend += sum(r["spend"] for k, r in today["agentic"].items()
                           if k.startswith(f"{c.product}|{c.channel}|"))

    new = [{"id": a.id, "arm_key": a.arm_key, "product": a.product, "balance": a.balance,
            "tenure_months": a.tenure_months, "direct_deposit": a.direct_deposit, "member": a.member,
            "email": a.email, "click_id": a.click_id, "value": a.value} for a in accounts]
    total_v = sum(per_arm_value.values())
    return {
        "new_accounts": new,
        "_log": {"inputs": {"day": day}, "output": {"accounts": len(new), "value": round(total_v, 2),
                                                   "deposits": round(sum(a["balance"] for a in new), 2)},
                 "reasoning": f"{len(new)} new accounts joined to their campaigns; value ${total_v:,.0f} "
                              f"(balance x margin x tenure, direct-deposit x{cfg['direct_deposit_multiplier']})."},
    }


def upload_conversions(state: CycleState) -> dict:
    """Node: send value-weighted conversions back to each platform so their bidding learns account value."""
    tid, day = state["tenant_id"], state["day"]
    cfg = settings.value_cfg()
    by_platform = {"google": [], "meta": []}
    for a in state.get("new_accounts", []):
        by_platform[a["arm_key"].split("|")[1]].append(a)

    rows, summary = [], {}
    for platform, accts in by_platform.items():
        if not accts:
            continue
        if platform == "google":
            events = [signals.google_event(a, day, cfg) for a in accts]
            res = google.upload_conversions(events)
        else:
            events = [signals.meta_event(a, day, cfg) for a in accts]
            res = meta.upload_conversions(events)
        status = {"live": "sent", "sandbox": "sent_sandbox", "stub": "sent_sandbox"}.get(res["mode"], "failed")
        rows += [db.ConversionUpload(tenant_id=tid, account_id=a["id"], platform=platform, payload=e,
                                     status=status, response=res.get("response") or ({"error": res["error"]} if res["error"] else None))
                 for a, e in zip(accts, events)]
        summary[platform] = {"events": len(events), "mode": res["mode"], "status": status}
    if rows:
        db.add_all(rows)
    return {"_log": {"inputs": {"accounts": len(state.get("new_accounts", []))}, "output": summary,
                     "reasoning": "Uploaded value-weighted offline conversions (Google Data Manager API, "
                                  "Meta CAPI physical_store with predicted_ltv)."
                                  + (" Sandbox mode: payloads logged, marked sent." if settings.MODE == "sandbox" else "")}}
