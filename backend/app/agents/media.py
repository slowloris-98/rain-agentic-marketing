"""Media agents (Google + Meta): launch one campaign per product x channel and keep each
campaign's budget inside the envelope the allocator set. Inside a campaign, bidding and
ad-set/asset-group spend is left to the platform (value-based bidding on our conversions)."""
from sqlalchemy import select

from .. import db, settings
from ..integrations import google, meta
from ..state import CycleState


def _envelopes(alloc: dict[str, float]) -> dict[tuple[str, str], float]:
    env: dict[tuple[str, str], float] = {}
    for k, b in alloc.items():
        p, c, *_ = k.split("|")
        env[(p, c)] = env.get((p, c), 0) + b
    return env


def media_launch(state: CycleState) -> dict:
    """Node (after approval): create campaigns and activate the matching arms."""
    tid, plan = state["tenant_id"], state["plan"]
    approved = {(c.product, c.channel) for c in db.rows(db.Creative, tid, db.Creative.status == "approved")}
    cells = [(p, c) for p in plan["products"] for c in plan["channels"] if (p, c) in approved]
    if not cells:
        return {"_log": {"reasoning": "No approved creatives; nothing launched."}}
    per_cell = plan["daily_budget"] / len(cells)
    days = int(plan.get("weeks", 12)) * 7
    name_of = settings.rates()["products"]

    launched, calls = [], []
    for p, c in cells:
        name = f"{name_of[p]['name']} | {c} | RAIN"
        res = google.create_campaign(name, per_cell) if c == "google" else meta.create_campaign(name, per_cell, days)
        calls.append({"cell": f"{p}/{c}", "mode": res["mode"], "id": res["id"], "error": res["error"],
                      "request": res["request"]})
        launched.append(db.Campaign(tenant_id=tid, product=p, channel=c, name=name, envelope=per_cell,
                                    status="live" if res["mode"] != "error" else "error", platform_id=res["id"]))
    db.add_all(launched)
    with db.session() as s:
        for arm in s.scalars(select(db.Arm).where(db.Arm.tenant_id == tid)):
            arm.active = (arm.product, arm.channel) in set(cells)
    campaigns = [{"id": x.id, "product": x.product, "channel": x.channel, "platform_id": x.platform_id} for x in launched]
    return {"campaigns": campaigns,
            "_log": {"inputs": {"cells": [f"{p}/{c}" for p, c in cells], "daily_budget": plan["daily_budget"]},
                     "output": {"calls": calls},
                     "reasoning": f"Created {len(campaigns)} campaigns (1 per product x channel). Google: Maximize "
                                  "conversion value; Meta: Advantage+ campaign budget with lifetime_budget."}}


def media_update(state: CycleState) -> dict:
    """Node: push today's envelopes to the platforms (only when they move > 2%)."""
    tid, alloc = state["tenant_id"], state["allocation"]
    env = _envelopes(alloc)
    days_left = max(int(state.get("plan", {}).get("weeks", 12)) * 7 - state["day"], 1)
    changes = []
    with db.session() as s:
        for camp in s.scalars(select(db.Campaign).where(db.Campaign.tenant_id == tid, db.Campaign.status == "live")):
            new = round(env.get((camp.product, camp.channel), 0), 2)
            if camp.envelope and abs(new - camp.envelope) / camp.envelope < 0.02:
                continue
            if camp.channel == "google":
                res = google.update_budget(camp.platform_id, new)
            else:  # Meta lifetime budget = spent so far + remaining days at the new daily envelope
                res = meta.update_budget(camp.platform_id, camp.spend + new * days_left)
            changes.append({"campaign": camp.name, "from": round(camp.envelope, 2), "to": new, "mode": res["mode"],
                            "error": res["error"]})
            camp.envelope = new
    hints = google.budget_recommendations()
    return {"budget_hints": hints,
            "_log": {"inputs": {"envelopes": {f"{p}/{c}": round(v, 2) for (p, c), v in env.items()}},
                     "output": {"changes": changes},
                     "reasoning": f"{len(changes)} campaign envelope(s) updated; platforms optimize spend inside them."}}
