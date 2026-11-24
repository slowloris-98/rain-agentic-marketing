"""Reporter: weekly client-facing narrative."""
import json

from .. import db, llm
from ..state import CycleState

SYSTEM = ("You write the weekly results note from RAIN to a credit union marketing team. 120-180 words, plain "
          "English, no jargon. Lead with deposits and new accounts, then what changed in the budget and why, then "
          "next week's focus. Use only numbers from the data.")
SCHEMA = llm.obj({"report": {"type": "string"}})


def reporter(state: CycleState) -> dict:
    tid, ws = state["tenant_id"], state["week_stats"]
    a, b = ws["agentic"], ws["baseline"]

    def fallback():
        lift = (a["value"] / b["value"] - 1) if b["value"] else 0
        cpk = a["spend"] / (a["deposits"] / 1000) if a["deposits"] else 0
        top = ws["top_arms"][0]["arm"].replace("|", " / ") if ws["top_arms"] else "n/a"
        return {"report": (
            f"Week {ws['week']}: campaigns opened {a['accounts']} new accounts and brought in "
            f"${a['deposits']:,.0f} in new deposits on ${a['spend']:,.0f} of media (${cpk:,.2f} per $1K of deposits). "
            f"Long-term deposit value was ${a['value']:,.0f}, {lift:+.0%} against a fixed budget split. "
            f"The best segment this week was {top}. ${ws['budget_moved']:,.0f}/day of budget moved toward "
            f"higher-value segments. Next week we keep testing smaller segments with about 15% of the budget "
            f"and keep the rest on what is working.")}

    out, source = llm.call("reporter", SYSTEM, json.dumps(ws, default=str), SCHEMA, fallback)
    db.add_all([db.Report(tenant_id=tid, week=ws["week"], text=out["report"])])
    return {"report": out["report"], "_log": {"inputs": {"week": ws["week"]}, "output": {"report": out["report"]},
                                              "reasoning": f"[{source}] Weekly report written."}}
