# RAIN agentic marketing MVP

Agents run RAIN's client workflow for banks and credit unions:
**goal → plan → creative → compliance → one human approval → launch → optimize → report.**

The admin picks a customer bank or credit union from the CRM and types a goal. The agents turn that goal into a strategy
(which products, audiences, geos, channels and budget) using the customer's CRM facts: rates, disclosures, branches and brand voice.

A Thompson-sampling allocator learns which segments (product × channel × audience × geo) bring the most
deposit value per dollar. It learns this from a simulated credit union whose real conversion rates are hidden from it.
In 12 simulated weeks it earns about 30–60% more long-term deposit value than a fixed even split on the same
spend. It does this by moving budget toward a few large-balance accounts instead of many small ones.

## Run it

```bash
# backend (Python 3.12)
cd backend
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                 # optional: add ANTHROPIC_API_KEY / ad credentials
uvicorn app.main:app --port 8000                     # creates rain.db

# frontend
cd frontend
npm install
npm run dev                                          # http://localhost:3000
```

Sign in as `admin@rain` / `admin` (RAIN staff) or `client@acme` / `client` (Acme Community Credit Union, read-only;
always shows Acme's latest campaign).

**Demo:** go to Admin and click **New campaign**. Pick a customer, type a goal (e.g. "Grow CD balances among retirees near our
branches") and click **Start campaign**. The strategist, creative and compliance agents run live in the feed, and the plan panel
shows how the goal was interpreted. Then click **Approve & launch** (the only human click), then **Run 84 days**.
Watch the budget move, the posteriors narrow, and a new set of lessons appear each week. Then sign in as the client to see the KPIs
and the agentic vs fixed-split trend.

Headless: `python scripts/demo.py --reset --days 84 --customer summit-ridge-bank --goal "Grow CDs among retirees"`.
Tests: `pytest tests`.

## Customers (CRM stub)

`app/crm/customers.json` holds three fictional customers: Acme Community Credit Union, Summit Ridge Bank and Pinecrest Teachers
Credit Union. Each has products with APY, minimum balance and fees, plus the insurer disclosure, branches, region, brand voice
and default budget. `app/crm/__init__.py` (`list_customers`, `get_customer`) is the only reader; swap its body for a real CRM call
later. A campaign takes a snapshot of the record when it starts, so the rates it used are recorded. Lessons carry across campaigns
for the same customer.

## How it works

| Layer | Where | Notes |
|---|---|---|
| Simulated core + traffic | `app/sim.py` | Seeded. The real conversion rates, balances and tenures are hidden (`_truth`), and agents never read them. |
| Value scorer | `app/signals.py` | `balance × margin × tenure × direct-deposit multiplier`. Constants are in `config/value.yaml`. |
| Conversion upload | `agents/core_feed.py` | Google Data Manager API `events:ingest` and Meta CAPI (`physical_store`, `value`, `currency`, `predicted_ltv`). In sandbox mode the payload is logged and marked sent. |
| Strategist / creative / reflection / reporter | `agents/*.py` | Claude through `app/llm.py` (structured JSON output). The strategist turns the goal into products, audiences, geos and channels. Without a key, templates are used and the goal is keyword-matched. |
| Compliance | `agents/compliance.py` | Deterministic checks: Reg DD (APY, as-of date, minimum balance, fees), rates that match the CRM record, the insurer disclosure (NCUA/FDIC), and banned claims. |
| Allocator | `agents/allocator.py` | Thompson sampling on value per $, with 15% exploration. Guardrails from `config/policy.yaml`: max shift, geo floor, arm floor. |
| Media | `agents/media.py` + `app/integrations.py` | One campaign per product × channel. The allocator sets the envelope and the platform optimizes inside it. |
| Orchestrator | `app/orchestrator.py` | Ordered node lists: `SETUP`, `LAUNCH`, `DAILY`, `WEEKLY`. Every node is logged to `agent_decisions` and streamed over SSE. |

Rates and APYs come only from the CRM record. The creative LLM writes an `{apy}` placeholder, and the code fills it in.

## Going live with ad platforms

Fill in the `GOOGLE_ADS_*` and `META_*` variables in `backend/.env`. When they are set, `integrations.py` sends real calls (the
admin header shows `Google live` / `Meta live`). Until then, every call returns a stub ID and the exact request is logged in the
agent feed. Notes:
- Google: use a test manager account and a test-access developer token. Test accounts don't serve ads, so metrics still come from `sim.py` while `MODE=sandbox`.
  For the Data Manager API, the refresh token needs the `https://www.googleapis.com/auth/datamanager` scope. Check the field
  names in `signals.google_event` against the current Data Manager docs before setting `MODE=live`.
- Meta: use a sandbox ad account and a system user token. Campaigns are created with `FINANCIAL_PRODUCTS_SERVICES`, campaign-level
  `lifetime_budget` and `OUTCOME_SALES`. Set `META_DATASET_ID` for CAPI.

## Adding LangGraph / LangSmith later

Each agent is `def node(state: CycleState) -> dict`, which is LangGraph's node contract.
- **LangGraph:** replace `orchestrator.run()` with a `StateGraph(CycleState)` built from the same lists. Use
  `interrupt_before=["media_launch"]` for the approval step and a SQLite checkpointer in place of `run_state.state`.
- **LangSmith:** decorate `llm.call` with `@traceable`. The `_log` dict that each node returns maps directly onto run metadata.

## Out of scope
A real CRM connection, real core-banking integration, a trained LTV model, multi-tenant model sharing, production compliance attestation, real user management (demo users are set in `settings.py`).
