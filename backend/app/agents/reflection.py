"""Weekly roll-up + reflection: turn the week's results into 3-5 plain-English lessons."""
import json

from sqlalchemy import func, select

from .. import db, llm
from ..state import CycleState

SYSTEM = ("You review a week of bank marketing results and write 3-5 short, specific, plain-English lessons the "
          "strategist and allocator should apply next week. Cite segments and numbers from the data only.")
SCHEMA = llm.obj({"lessons": {"type": "array", "items": {"type": "string"}}})


def rollup(state: CycleState) -> dict:
    """Node: summarize the last 7 days (agentic vs baseline, best/worst arms, budget shift)."""
    tid, day = state["tenant_id"], state["day"]
    since = day - 6
    with db.session() as s:
        per_arm = s.execute(
            select(db.DailyMetric.arm_key, func.sum(db.DailyMetric.spend), func.sum(db.DailyMetric.value),
                   func.sum(db.DailyMetric.accounts), func.sum(db.DailyMetric.deposits))
            .where(db.DailyMetric.tenant_id == tid, db.DailyMetric.baseline.is_(False), db.DailyMetric.day >= since)
            .group_by(db.DailyMetric.arm_key)).all()
        first = dict(s.execute(select(db.Allocation.arm_key, db.Allocation.budget)
                               .where(db.Allocation.tenant_id == tid, db.Allocation.day == since)).all())
    arms = sorted(({"arm": k, "spend": round(sp or 0, 2), "value_per_$": round((v or 0) / sp, 2) if sp else 0,
                    "accounts": a or 0, "deposits": round(d or 0)} for k, sp, v, a, d in per_arm),
                  key=lambda x: x["value_per_$"], reverse=True)
    alloc = state.get("allocation", {})
    by_product = {}
    for k, b in alloc.items():
        by_product[k.split("|")[0]] = by_product.get(k.split("|")[0], 0) + b
    stats = {
        "week": day // 7 + 1,
        "agentic": db.totals(tid, False, since), "baseline": db.totals(tid, True, since),
        "cumulative": {"agentic": db.totals(tid, False), "baseline": db.totals(tid, True)},
        "top_arms": arms[:5], "bottom_arms": arms[-5:],
        "budget_by_product": {k: round(v, 2) for k, v in by_product.items()},
        "budget_moved": round(sum(abs(alloc.get(k, 0) - first.get(k, 0)) for k in set(alloc) | set(first)) / 2, 2),
    }
    return {"week_stats": stats,
            "_log": {"output": {"agentic_value": round(stats["agentic"]["value"]), "baseline_value": round(stats["baseline"]["value"])},
                     "reasoning": f"Week {stats['week']} roll-up."}}


def reflection(state: CycleState) -> dict:
    tid, ws = state["tenant_id"], state["week_stats"]

    def fallback():
        top, bot = ws["top_arms"], ws["bottom_arms"]
        a, b = ws["agentic"], ws["baseline"]
        out = []
        if top:
            out.append(f"{top[0]['arm']} returned ${top[0]['value_per_$']:.2f} of deposit value per $1 this week; keep funding it.")
        if len(top) > 1:
            out.append(f"{top[1]['arm']} is a strong second at ${top[1]['value_per_$']:.2f}/$.")
        if bot:
            out.append(f"{bot[-1]['arm']} returned only ${bot[-1]['value_per_$']:.2f}/$; keep it at the floor unless it improves.")
        if b["value"]:
            out.append(f"Agentic split earned {a['value'] / b['value'] - 1:+.0%} value vs the fixed split this week.")
        best_p = max(ws["budget_by_product"], key=ws["budget_by_product"].get) if ws["budget_by_product"] else None
        if best_p:
            out.append(f"Budget is concentrating in {best_p}; few large-balance accounts beat many small ones per dollar.")
        return {"lessons": out[:5]}

    out, source = llm.call("reflection", SYSTEM, json.dumps(ws, default=str), SCHEMA, fallback)
    lessons = [l for l in out["lessons"] if l.strip()][:5]
    db.add_all([db.Lesson(tenant_id=tid, week=ws["week"], text=l) for l in lessons])
    return {"lessons": (lessons + state.get("lessons", []))[:10],
            "_log": {"inputs": {"week": ws["week"]}, "output": {"lessons": lessons},
                     "reasoning": f"[{source}] Wrote {len(lessons)} lessons for week {ws['week']}."}}
