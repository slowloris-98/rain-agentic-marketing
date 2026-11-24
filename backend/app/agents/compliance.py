"""Compliance: deterministic Reg DD + claims checks. Passing ads go to the human approval queue."""
import re

from .. import db, settings
from ..state import CycleState


def check(c: dict, rates: dict, policy: dict) -> list[dict]:
    p = rates["products"][c["product"]]
    apy = f"{p['apy']:.2f}"
    copy = f"{c['headline']} {c['body']}"
    full = f"{copy} {c['disclosure']}"
    f = []
    if f"{apy}% APY" not in full:
        f.append({"severity": "error", "rule": "Reg DD 1030.8", "msg": f"APY {apy}% must be stated as 'APY'."})
    for m in re.findall(r"(\d+(?:\.\d+)?)\s*%", full):
        if abs(float(m) - p["apy"]) > 1e-9:
            f.append({"severity": "error", "rule": "rate source", "msg": f"Rate {m}% does not match rates.json ({apy}%)."})
    if "Minimum balance" not in c["disclosure"]:
        f.append({"severity": "error", "rule": "Reg DD 1030.8", "msg": "Minimum balance to obtain the APY is missing."})
    if "fee" not in c["disclosure"].lower():
        f.append({"severity": "error", "rule": "Reg DD 1030.8", "msg": "Fee disclosure missing."})
    if rates["as_of"] not in c["disclosure"]:
        f.append({"severity": "error", "rule": "Reg DD 1030.8", "msg": "Rate 'accurate as of' date missing."})
    for w in policy["banned_claims"]:
        if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", copy, re.I):
            f.append({"severity": "error", "rule": "UDAAP / unsubstantiated claim", "msg": f"Claim '{w}' can't be backed up."})
    if len(c["headline"]) > (30 if c["channel"] == "google" else 40):
        f.append({"severity": "warning", "rule": "platform", "msg": "Headline is longer than the platform limit."})
    return f


def compliance(state: CycleState) -> dict:
    tid = state["tenant_id"]
    rates, policy = settings.rates(), settings.policy()
    out = []
    for c in state["creatives"]:
        findings = check(c, rates, policy)
        ok = not any(x["severity"] == "error" for x in findings)
        out.append({**c, "findings": findings, "status": "pending_approval" if ok else "failed_compliance"})
    with db.session() as s:  # replace any previous un-decided queue
        s.query(db.Creative).filter(db.Creative.tenant_id == tid,
                                    db.Creative.status.in_(["pending_approval", "failed_compliance"])).delete()
    rows = db.add_all([db.Creative(tenant_id=tid, **c) for c in out])
    for c, r in zip(out, rows):
        c["id"] = r.id
    passed = sum(c["status"] == "pending_approval" for c in out)
    return {"creatives": out,
            "_log": {"inputs": {"creatives": len(out)},
                     "output": {"passed": passed, "failed": len(out) - passed,
                                "failures": [f"{c['product']}/{c['channel']}: {x['msg']}" for c in out
                                             for x in c["findings"] if x["severity"] == "error"][:10]},
                     "reasoning": f"{passed}/{len(out)} ads pass Reg DD and claims checks; sent to the human approval queue."}}
