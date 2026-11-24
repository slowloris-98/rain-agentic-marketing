"""Allocator: Thompson sampling over product x channel x audience x geo arms.

Reward = deposit value per $ spent. No LLM. Outputs per-arm budgets, which media.py rolls
up into one envelope per product x channel campaign (the platform splits inside it).
"""
import numpy as np

from .. import db, settings
from ..state import CycleState

PRIOR_SPEND = 300.0  # pseudo-$ of prior evidence at the global mean
TOP_K = 12           # arms that share the exploit budget
EXPLORE_K = 8        # most-uncertain arms that share the explore budget


def posteriors(stats: dict[str, dict]) -> dict[str, dict]:
    """Normal posterior on value-per-$ for each arm, shrunk toward the global mean."""
    S = sum(s["spend"] for s in stats.values())
    V = sum(s["value"] for s in stats.values())
    mu0 = V / S if S > 0 else 1.0
    # Pooled per-dollar variance: Var(daily rate) ~= sigma2 / spend_that_day
    resid = sum(max(s["sumsq"] - (s["value"] ** 2 / s["spend"]), 0) for s in stats.values() if s["spend"] > 0)
    nobs = sum(s["days"] for s in stats.values())
    prior_sigma2 = (mu0 ** 2) * PRIOR_SPEND
    sigma2 = (resid + prior_sigma2 * 10) / (max(nobs - len(stats), 0) + 10)
    out = {}
    for k, s in stats.items():
        n = s["spend"] + PRIOR_SPEND
        out[k] = {"mean": (s["value"] + mu0 * PRIOR_SPEND) / n, "sd": float(np.sqrt(sigma2 / n))}
    return out


def apply_guardrails(target: dict[str, float], prev: dict[str, float], policy: dict, budget: float) -> dict[str, float]:
    keys = list(target)
    t = dict(target)
    # 1) geo distribution floor
    geos = sorted({k.split("|")[3] for k in keys})
    floor_amt = policy["geo_floor"] * budget
    for g in geos:
        mine = [k for k in keys if k.split("|")[3] == g]
        have = sum(t[k] for k in mine)
        if have < floor_amt:
            need = floor_amt - have
            others = [k for k in keys if k not in mine]
            pool = sum(t[k] for k in others)
            for k in others:
                t[k] -= need * t[k] / pool
            for k in mine:
                t[k] += need / len(mine) if have == 0 else need * t[k] / have
    # 2) max shift per cycle (convex blend with yesterday keeps floors satisfied)
    if prev and set(prev) == set(keys):
        ps = sum(prev.values())
        p = {k: prev[k] * budget / ps for k in keys}
        moved = sum(abs(t[k] - p[k]) for k in keys) / 2
        cap = policy["max_shift"] * budget
        if moved > cap:
            f = cap / moved
            t = {k: p[k] + (t[k] - p[k]) * f for k in keys}
    return {k: round(max(v, 0), 2) for k, v in t.items()}


def allocate(stats: dict[str, dict], prev: dict[str, float], policy: dict, rng) -> tuple[dict, list, dict]:
    keys = sorted(stats)
    budget = float(policy["daily_budget"])
    post = posteriors(stats)
    if sum(s["spend"] for s in stats.values()) == 0:  # day 0: even split
        even = {k: round(budget / len(keys), 2) for k in keys}
        return even, [], post

    floor = float(policy["arm_floor"])
    free = budget - floor * len(keys)
    explore_budget = policy["explore_share"] * budget
    exploit_budget = free - explore_budget

    theta = {k: max(rng.normal(post[k]["mean"], post[k]["sd"]), 0.0) for k in keys}
    top = sorted(keys, key=lambda k: theta[k], reverse=True)[:TOP_K]
    explore = sorted((k for k in keys if k not in top), key=lambda k: post[k]["sd"], reverse=True)[:EXPLORE_K]
    if not explore:  # narrow campaign (few arms): every arm is already sampled, no separate explore pool
        exploit_budget += explore_budget
    if sum(theta[k] for k in top) == 0:
        theta = {k: 1.0 for k in keys}
    tsum = sum(theta[k] for k in top)

    target = {k: floor for k in keys}
    for k in top:
        target[k] += exploit_budget * theta[k] / tsum
    for k in explore:
        target[k] += explore_budget / len(explore)
    return apply_guardrails(target, prev, policy, budget), explore, post


def allocator(state: CycleState) -> dict:
    """Node: decide today's per-arm budgets."""
    tid, day = state["tenant_id"], state["day"]
    policy = settings.policy()
    if state.get("plan"):  # the campaign's budget (admin form -> strategist), not the global default
        policy["daily_budget"] = state["plan"]["daily_budget"]
    arms = db.arms(tid)
    stats = {a.key: {"spend": a.spend, "value": a.value, "sumsq": a.sumsq, "days": a.days} for a in arms}
    prev = state.get("allocation") or {}
    prev = {k: v for k, v in prev.items() if k in stats}
    rng = np.random.default_rng([state.get("seed", 7), day, 99])
    alloc, explore, post = allocate(stats, prev, policy, rng)

    db.add_all([db.Allocation(tenant_id=tid, day=day, arm_key=k, budget=b, explore=k in explore,
                              mean=post[k]["mean"], sd=post[k]["sd"]) for k, b in alloc.items()])

    best = sorted(post, key=lambda k: post[k]["mean"], reverse=True)[:3]
    hints = state.get("budget_hints") or []
    return {
        "allocation": alloc, "explore": explore, "posteriors": post,
        "_log": {
            "inputs": {"arms": len(stats), "budget": policy["daily_budget"], "budget_hints": hints[:5]},
            "output": {"top_arms": {k: alloc[k] for k in sorted(alloc, key=alloc.get, reverse=True)[:5]},
                       "explore_share": round(sum(alloc[k] for k in explore) / max(sum(alloc.values()), 1), 3)},
            "reasoning": (
                "Even split on day 0 (no evidence yet)." if not prev else
                f"Thompson sample over {len(stats)} arms; highest posterior value/$: "
                + ", ".join(f"{k} ({post[k]['mean']:.2f}±{post[k]['sd']:.2f})" for k in best)
                + f". {len(explore)} most-uncertain arms funded for exploration. Guardrails: "
                f"max shift {policy['max_shift']:.0%}, geo floor {policy['geo_floor']:.0%}, arm floor ${policy['arm_floor']}."
                + (f" Considered {len(hints)} Google budget recommendation(s) as hints only." if hints else "")
            ),
        },
    }
