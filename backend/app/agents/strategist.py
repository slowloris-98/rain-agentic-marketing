"""Strategist: admin goal + CRM profile + lessons -> campaign plan (what to run, for whom, where)."""
import json
import re

from .. import llm, sim
from ..state import CycleState

SYSTEM = ("You are the media strategist at RAIN, an agency for banks and credit unions. Turn the admin's goal "
          "into a deposit campaign plan for this customer: which products, audiences (age bands), geos "
          "(branch radius vs statewide) and channels to run, and the daily budget. Only pick products the "
          "customer offers. Never invent rates; the CRM rate sheet is the only source. Apply past lessons. "
          "Say in goal_interpretation how the goal shaped each choice.")

SCHEMA = llm.obj({
    "goal_interpretation": {"type": "string"},
    "products": {"type": "array", "items": {"type": "string", "enum": sim.PRODUCTS}},
    "audiences": {"type": "array", "items": {"type": "string", "enum": sim.AUDIENCES}},
    "geos": {"type": "array", "items": {"type": "string", "enum": sim.GEOS}},
    "channels": {"type": "array", "items": {"type": "string", "enum": sim.CHANNELS}},
    "daily_budget": {"type": "number"},
    "weeks": {"type": "integer"},
    "kpi": {"type": "string"},
    "priorities": {"type": "array", "items": {"type": "string"}},
    "rationale": {"type": "string"},
})

# Keyword rules for the no-LLM fallback, so the goal still shapes the plan.
PRODUCT_WORDS = {"checking": r"checking|debit|direct deposit", "savings": r"saving",
                 "cd": r"\bcds?\b|certificate|term deposit", "money_market": r"money.?market|\bmma\b"}
AUDIENCE_WORDS = {"18-34": r"young|student|gen ?z|millennial|first.?job|graduate",
                  "35-54": r"famil|parent|mid.?career|professional",
                  "55+": r"retire|senior|older|55\+|boomer"}
GEO_WORDS = {"branch": r"branch|local|near|neighbo|footprint|in.?person", "statewide": r"statewide|digital|online|whole state"}
CHANNEL_WORDS = {"google": r"search|google", "meta": r"social|meta|facebook|instagram"}


def _match(goal: str, rules: dict[str, str], allowed: list[str]) -> list[str]:
    hits = [k for k, rx in rules.items() if k in allowed and re.search(rx, goal, re.I)]
    return hits or list(allowed)


def strategist(state: CycleState) -> dict:
    brief, customer, lessons = state["brief"], state["customer"], state.get("lessons", [])
    goal = brief["goal"]
    offered = [p for p in sim.PRODUCTS if p in customer["products"]]
    max_budget = float(brief["daily_budget"])

    def fallback():
        products = _match(goal, PRODUCT_WORDS, offered)
        audiences = _match(goal, AUDIENCE_WORDS, sim.AUDIENCES)
        geos = _match(goal, GEO_WORDS, sim.GEOS)
        channels = _match(goal, CHANNEL_WORDS, sim.CHANNELS)
        return {
            "goal_interpretation": (f"Goal \"{goal}\" -> products {products}, audiences {audiences}, geos {geos}, "
                                    f"channels {channels} (keyword match; anything not mentioned stays open)."),
            "products": products, "audiences": audiences, "geos": geos, "channels": channels,
            "daily_budget": max_budget, "weeks": int(brief["weeks"]), "days": _days(brief),
            "kpi": "deposit value per $ (balance x margin x tenure)",
            "priorities": ["Test every selected cell early, then shift budget to the highest value per $"]
                          + [f"Lesson applied: {l}" for l in lessons[:2]],
            "rationale": "Template plan (no LLM key): selections come from keywords in the goal.",
        }

    profile = {k: customer[k] for k in ("name", "institution_type", "assets_musd", "branches", "region", "brand_voice")}
    prompt = (f"Admin goal: {goal}\n\nCustomer (from CRM):\n{json.dumps(profile, indent=2)}"
              f"\n\nProducts and rates (CRM, as of {customer['rates_as_of']}):\n{json.dumps(customer['products'], indent=2)}"
              "\n\nLessons from past campaigns for this customer:\n" + ("\n".join(f"- {l}" for l in lessons) or "(none yet)")
              + f"\n\nDaily budget must not exceed ${max_budget:,.0f}. Campaign length: {_days(brief)} days.")
    plan, source = llm.call("strategist", SYSTEM, prompt, SCHEMA, fallback)

    # Never trust the model on hard limits.
    plan["daily_budget"] = min(float(plan.get("daily_budget") or max_budget), max_budget)
    plan["weeks"] = int(brief["weeks"])
    plan["days"] = _days(brief)
    plan["products"] = [p for p in plan["products"] if p in offered] or offered
    plan["audiences"] = [a for a in plan["audiences"] if a in sim.AUDIENCES] or list(sim.AUDIENCES)
    plan["geos"] = [g for g in plan["geos"] if g in sim.GEOS] or list(sim.GEOS)
    plan["channels"] = [c for c in plan["channels"] if c in sim.CHANNELS] or list(sim.CHANNELS)
    return {"plan": plan, "_log": {"inputs": {"goal": goal, "customer": customer["id"], "lessons": lessons},
                                   "output": plan,
                                   "reasoning": f"[{source}] {plan['goal_interpretation']} {plan['rationale']}"}}


def _days(brief: dict) -> int:
    """Campaign length in days (older runs only stored weeks)."""
    return int(brief.get("days") or int(brief["weeks"]) * 7)
