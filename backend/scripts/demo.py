"""Headless demo: start a campaign for a CRM customer with a goal, approve everything, run N days.

    python scripts/demo.py --reset --days 84 --customer acme-ccu --goal "Grow core deposits this quarter"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, orchestrator  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables")
    ap.add_argument("--days", type=int, default=84)
    ap.add_argument("--customer", default="acme-ccu", help="CRM customer id (see app/crm/customers.json)")
    ap.add_argument("--goal", default="Grow core deposits this quarter, especially CDs and money market")
    ap.add_argument("--init-only", action="store_true", help="create the DB and stop (use the dashboard)")
    a = ap.parse_args()

    if a.reset:
        db.Base.metadata.drop_all(db.engine)
    db.init_db()
    if a.init_only:
        print("database ready")
        return

    tid = orchestrator.create_run(a.customer, a.goal)
    state = orchestrator.submit_brief(tid)
    print(f"run {tid}: {state['customer']['name']} | goal: {a.goal}")
    print(f"strategist: {state['plan']['goal_interpretation']}")
    pending = [c["id"] for c in state["creatives"] if c["status"] == "pending_approval"]
    print(f"plan: {state['plan']['products']} on {state['plan']['channels']}; {len(pending)} ads await approval")
    orchestrator.decide(tid, pending, [])
    ran = orchestrator.run_days(tid, a.days)

    ag, bl = db.totals(tid, False), db.totals(tid, True)
    print(f"\nran {ran} days")
    print(f"agentic : {ag['accounts']:>5} accounts  ${ag['deposits']:>14,.0f} deposits  ${ag['value']:>12,.0f} value")
    print(f"baseline: {bl['accounts']:>5} accounts  ${bl['deposits']:>14,.0f} deposits  ${bl['value']:>12,.0f} value")
    if bl["value"]:
        print(f"lift    : {ag['value'] / bl['value'] - 1:+.1%} deposit value on the same spend")
    print("\nlatest lessons:")
    for l in db.lessons(tid, 5):
        print(" -", l)


if __name__ == "__main__":
    main()
