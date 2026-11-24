"""Strategist: brief + lessons -> campaign plan."""
import json

from .. import llm, settings, sim
from ..state import CycleState

SYSTEM = ("You are the media strategist at RAIN, an agency for banks and credit unions. Turn the client brief "
          "into a deposit-growth plan. Never invent rates; the rate sheet is the only source. Apply past lessons.")

SCHEMA = llm.obj({
    "products": {"type": "array", "items": {"type": "string", "enum": sim.PRODUCTS}},
    "channels": {"type": "array", "items": {"type": "string", "enum": sim.CHANNELS}},
    "daily_budget": {"type": "number"},
    "weeks": {"type": "integer"},
    "kpi": {"type": "string"},
    "priorities": {"type": "array", "items": {"type": "string"}},
    "rationale": {"type": "string"},
})


def strategist(state: CycleState) -> dict:
    brief, lessons = state["brief"], state.get("lessons", [])
    policy = settings.policy()
    max_budget = float(brief.get("daily_budget", policy["daily_budget"]))

    def fallback():
        return {
            "products": [p for p in brief.get("products", sim.PRODUCTS) if p in sim.PRODUCTS] or sim.PRODUCTS,
            "channels": sim.CHANNELS, "daily_budget": max_budget, "weeks": int(brief.get("weeks", 12)),
            "kpi": "deposit value per $ (balance x margin x tenure)",
            "priorities": ["Test every product x audience x geo cell early, then shift to the highest value per $",
                           "Keep at least 25% of spend in each geo (fair-lending distribution)"]
                          + [f"Lesson applied: {l}" for l in lessons[:2]],
            "rationale": "Template plan (no LLM key): run all requested products on Google and Meta and let the "
                         "allocator learn value per dollar.",
        }

    prompt = (f"Brief:\n{json.dumps(brief, indent=2)}\n\nRate sheet:\n{json.dumps(settings.rates()['products'], indent=2)}"
              "\n\nLessons from past cycles:\n" + ("\n".join(f"- {l}" for l in lessons) or "(none yet)")
              + f"\n\nDaily budget must not exceed ${max_budget:,.0f}.")
    plan, source = llm.call("strategist", SYSTEM, prompt, SCHEMA, fallback)
    plan["daily_budget"] = min(float(plan.get("daily_budget") or max_budget), max_budget)
    plan["products"] = [p for p in plan["products"] if p in sim.PRODUCTS] or sim.PRODUCTS
    plan["channels"] = [c for c in plan["channels"] if c in sim.CHANNELS] or sim.CHANNELS
    return {"plan": plan, "_log": {"inputs": {"brief": brief, "lessons": lessons}, "output": plan,
                                   "reasoning": f"[{source}] {plan['rationale']}"}}
