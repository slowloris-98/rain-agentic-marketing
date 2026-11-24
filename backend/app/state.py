"""Shared state passed between agent nodes.

Every agent is `def node(state: CycleState) -> dict` returning only the keys it changed.
This is exactly LangGraph's node contract, so `StateGraph(CycleState)` can replace the
hand-rolled runner in orchestrator.py without touching the agents.

A node may also return "_log": {"inputs":..., "reasoning":...}; the runner records it in
agent_decisions (maps onto LangSmith run metadata later).
"""
from typing import Any, TypedDict


class CycleState(TypedDict, total=False):
    tenant_id: int
    day: int                      # simulated day (0-based)
    customer: dict                # CRM snapshot (rates, products, disclosures) taken at campaign start
    brief: dict                   # admin goal + budget + customer basics
    lessons: list[str]            # memory from reflection
    plan: dict                    # strategist output
    creatives: list[dict]         # creative output (+ compliance findings)
    approved: bool                # human approval gate
    campaigns: list[dict]         # launched campaigns (product x channel)
    allocation: dict[str, float]  # arm_key -> $ today
    explore: list[str]            # arm keys funded by exploration today
    posteriors: dict[str, dict]   # arm_key -> {mean, sd}
    today: dict[str, Any]         # simulate_day output (spend/clicks/accounts per arm)
    new_accounts: list[dict]      # core_feed output (scored)
    budget_hints: list[dict]      # platform budget recommendations
    week_stats: dict              # weekly roll-up for reflection/reporter
    report: str
