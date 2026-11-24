"""Creative: ad copy variants per product x channel. The LLM writes words only; the rate and
the Reg DD disclosure are inserted from rates.json, so a model can never produce a rate."""
import json

from .. import llm, settings
from ..state import CycleState

SYSTEM = ("You write ad copy for a credit union. Write the {apy} placeholder wherever the rate goes and never write "
          "any number or percentage yourself. No superlatives or unprovable claims (best, lowest, highest, "
          "guaranteed, #1). Headline <= 30 chars for google, <= 40 for meta. Body <= 90 chars.")

SCHEMA = llm.obj({"variants": {"type": "array", "items": llm.obj({
    "product": {"type": "string"}, "channel": {"type": "string"},
    "headline": {"type": "string"}, "body": {"type": "string"}})}})

TEMPLATES = {
    "checking": [("Checking at {apy}% APY", "No monthly fee. Open online in minutes at La Cap."),
                 ("Switch to Rewards Checking", "Earn {apy}% APY with no monthly fee. Local service, 15 branches.")],
    "savings": [("Savings at {apy}% APY", "Grow your savings with La Cap. Open with a small deposit."),
                ("Your Money, Working Harder", "High-Yield Savings at {apy}% APY. Federally insured by NCUA.")],
    "cd": [("12-Month CD: {apy}% APY", "Lock in your rate today at your local credit union."),
           ("Lock In {apy}% APY", "A 12-month certificate from your local credit union.")],
    "money_market": [("Money Market {apy}% APY", "Earn more and keep access to your cash."),
                     ("Flexible Money Market", "{apy}% APY with check-writing. Local service, 15 branches.")],
}


def disclosure(product: str) -> str:
    r = settings.rates()
    p = r["products"][product]
    return r["disclosure_template"].format(apy=f"{p['apy']:.2f}", as_of=r["as_of"],
                                           min_balance=f"{p['min_balance']:,}", monthly_fee=p["monthly_fee"],
                                           extra=p["extra"])


def creative(state: CycleState) -> dict:
    plan, rates = state["plan"], settings.rates()["products"]
    cells = [(p, c) for p in plan["products"] for c in plan["channels"]]

    def fallback():
        return {"variants": [{"product": p, "channel": c, "headline": h, "body": b}
                             for p, c in cells for h, b in TEMPLATES[p]]}

    prompt = ("Write 2 variants for each product/channel cell:\n" + json.dumps(
        [{"product": p, "channel": c, "product_name": rates[p]["name"]} for p, c in cells])
        + f"\nPlan priorities: {plan.get('priorities', [])}")
    out, source = llm.call("creative", SYSTEM, prompt, SCHEMA, fallback)

    creatives = []
    for v in out["variants"]:
        if v["product"] not in rates or (v["product"], v["channel"]) not in cells:
            continue
        apy = f"{rates[v['product']]['apy']:.2f}"
        creatives.append({"product": v["product"], "channel": v["channel"],
                          "headline": v["headline"].replace("{apy}", apy),
                          "body": v["body"].replace("{apy}", apy),
                          "disclosure": disclosure(v["product"])})
    return {"creatives": creatives,
            "_log": {"inputs": {"cells": [f"{p}/{c}" for p, c in cells]},
                     "output": {"variants": len(creatives), "sample": creatives[:2]},
                     "reasoning": f"[{source}] Wrote {len(creatives)} variants; rates and disclosures inserted from rates.json."}}
