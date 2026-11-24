"""Creative: ad copy variants per product x channel. The LLM writes words only; the rate and
the Reg DD disclosure are inserted from the customer's CRM record, so a model can never produce a rate."""
import json

from .. import llm
from ..state import CycleState

SYSTEM = ("You write ad copy for a bank or credit union. Write the {apy} placeholder wherever the rate goes and "
          "never write any number or percentage yourself. No superlatives or unprovable claims (best, lowest, "
          "highest, guaranteed, #1). Headline <= 30 chars for google, <= 40 for meta. Body <= 90 chars. "
          "Follow the customer's brand voice and serve the campaign goal.")

SCHEMA = llm.obj({"variants": {"type": "array", "items": llm.obj({
    "product": {"type": "string"}, "channel": {"type": "string"},
    "headline": {"type": "string"}, "body": {"type": "string"}})}})

DISCLOSURE = ("APY = Annual Percentage Yield. {apy}% APY accurate as of {as_of}. Minimum balance to open: "
              "${min_balance}. Monthly fee: ${monthly_fee}. {extra} {insurer}")

TEMPLATES = {
    "checking": [("Checking at {apy}% APY", "Open online in minutes at {bank}."),
                 ("Switch to {product}", "Earn {apy}% APY. Local service from {bank}.")],
    "savings": [("Savings at {apy}% APY", "Grow your savings with {bank}."),
                ("Your Money, Working Harder", "{product} at {apy}% APY from {bank}.")],
    "cd": [("CD at {apy}% APY", "Lock in your rate today with {bank}."),
           ("Lock In {apy}% APY", "{product} from {bank}.")],
    "money_market": [("Money Market {apy}% APY", "Earn more and keep access to your cash at {bank}."),
                     ("Flexible Money Market", "{apy}% APY with check-writing from {bank}.")],
}


def disclosure(customer: dict, product: str) -> str:
    p = customer["products"][product]
    return DISCLOSURE.format(apy=f"{p['apy']:.2f}", as_of=customer["rates_as_of"], min_balance=f"{p['min_balance']:,}",
                             monthly_fee=p["monthly_fee"], extra=p["extra"], insurer=customer["insurer_disclosure"])


def creative(state: CycleState) -> dict:
    plan, customer, goal = state["plan"], state["customer"], state["brief"]["goal"]
    products = customer["products"]
    cells = [(p, c) for p in plan["products"] for c in plan["channels"]]

    def fallback():
        return {"variants": [{"product": p, "channel": c, "headline": h, "body": b}
                             for p, c in cells for h, b in TEMPLATES[p]]}

    prompt = (f"Customer: {customer['name']}. Brand voice: {customer['brand_voice']}\nCampaign goal: {goal}\n"
              f"Audiences: {plan.get('audiences')}; geos: {plan.get('geos')}\n"
              "Write 2 variants for each product/channel cell:\n"
              + json.dumps([{"product": p, "channel": c, "product_name": products[p]["name"]} for p, c in cells]))
    out, source = llm.call("creative", SYSTEM, prompt, SCHEMA, fallback)

    creatives = []
    for v in out["variants"]:
        if v["product"] not in products or (v["product"], v["channel"]) not in cells:
            continue
        fill = {"{apy}": f"{products[v['product']]['apy']:.2f}", "{bank}": customer["name"],
                "{product}": products[v["product"]]["name"]}
        text = {k: v[k] for k in ("headline", "body")}
        for k in text:
            for ph, val in fill.items():
                text[k] = text[k].replace(ph, val)
        creatives.append({"product": v["product"], "channel": v["channel"], **text,
                          "disclosure": disclosure(customer, v["product"])})
    return {"creatives": creatives,
            "_log": {"inputs": {"cells": [f"{p}/{c}" for p, c in cells], "goal": goal},
                     "output": {"variants": len(creatives), "sample": creatives[:2]},
                     "reasoning": f"[{source}] Wrote {len(creatives)} variants for {customer['name']}; "
                                  "rates and disclosures inserted from the CRM record."}}
