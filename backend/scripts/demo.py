"""Headless demo: seed La Cap, submit the brief, approve everything, run N simulated days.

    python scripts/demo.py --reset --days 84
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
    ap.add_argument("--seed-only", action="store_true", help="seed tenant and stop (use the dashboard for the rest)")
    a = ap.parse_args()

    if a.reset:
        db.Base.metadata.drop_all(db.engine)
    db.init_db()
    with db.session() as s:
        tid = s.query(db.Tenant.id).scalar()
    tid = tid or orchestrator.seed_tenant()
    print(f"tenant {tid} ready")
    if a.seed_only:
        return

    state = orchestrator.submit_brief(tid)
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
