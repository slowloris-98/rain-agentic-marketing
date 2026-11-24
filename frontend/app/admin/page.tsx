"use client";
import { useEffect, useRef, useState } from "react";
import { post, usd, useLive } from "@/lib/api";
import { AdPreview, type Creative } from "@/components/AdPreview";
import { AgentMap } from "@/components/AgentMap";
import { Trail, type Decision } from "@/components/Trail";
import { Block, Chip, DaysPicker, Spread, readPhase } from "@/components/ui";

type Data = { state: any; decisions: Decision[]; approvals: Creative[]; tenants: any[]; customers: any[] };

const RUN_PRESETS = [1, 7, 30, 84];
const LENGTH_PRESETS = [7, 14, 30, 56, 60, 84, 90]; // 56/84 = the CRM's 8- and 12-week defaults

export default function Admin() {
  const [tid, setTidState] = useState(0);
  const [creating, setCreating] = useState(false);
  useEffect(() => setTidState(Number(localStorage.getItem("tid") ?? 0)), []);
  const setTid = (t: number) => { localStorage.setItem("tid", String(t)); setTidState(t); setCreating(false); };
  const q = `?tenant_id=${tid}`;
  const { data, reload } = useLive<Data>({
    state: `/admin/state${q}`, decisions: `/admin/decisions${q}&limit=400`, approvals: `/admin/approvals${q}`,
    tenants: "/admin/tenants", customers: "/admin/customers",
  }, `&tenant_id=${tid}`);
  const tenants = data.tenants ?? [];
  const s = data.state;

  // Fall back to the newest run when nothing (or a run that no longer exists) is selected.
  useEffect(() => {
    // A tid above the newest listed id is a run we just created whose list refresh is still in flight.
    if (tenants.length && !tenants.some((t) => t.id === tid) && tid <= tenants[0].id) setTidState(tenants[0].id);
  }, [tenants, tid]);

  const showForm = creating || (data.tenants !== undefined && !tenants.length);

  return (
    <div className="console">
      <header className="systembar">
        <p className="wordmark">RAIN</p>
        <span className="text-xs" style={{ color: "var(--muted)" }}>Agentic marketing · admin</span>
        <span className="spacer" />
        {s && (
          <span className="health">
            <Chip tone={s.llm ? "good" : "neutral"}>{s.llm ? "LLM on" : "Template mode"}</Chip>
            <Chip tone={s.integrations.google === "live" ? "good" : "neutral"}>Google {s.integrations.google}</Chip>
            <Chip tone={s.integrations.meta === "live" ? "good" : "neutral"}>Meta {s.integrations.meta}</Chip>
          </span>
        )}
        <button className="btn" onClick={() => { localStorage.clear(); location.href = "/login"; }}>Sign out</button>
      </header>

      <Rail tenants={tenants} tid={creating ? -1 : tid} onPick={setTid} onNew={() => setCreating(true)} />

      <main className="pane">
        <div className="pane-inner">
          {showForm && data.customers
            ? <NewCampaign customers={data.customers} onCancel={tenants.length ? () => setCreating(false) : undefined}
                onStarted={(id) => { setTid(id); reload(); }} />
            : s
              ? <RunView tid={tid} s={s} decisions={data.decisions ?? []} creatives={data.approvals ?? []} q={q} reload={reload} />
              : <p className="empty">Loading…</p>}
        </div>
      </main>
    </div>
  );
}

// ------------------------------------------------------------------ rail
function Rail({ tenants, tid, onPick, onNew }: { tenants: any[]; tid: number; onPick: (t: number) => void; onNew: () => void }) {
  const active = tenants.filter((t) => t.phase === "planning" || t.phase === "awaiting_approval" || t.phase === "running");
  const rest = tenants.filter((t) => !active.includes(t));
  const row = (t: any) => {
    const p = readPhase(t.phase);
    return (
      <button key={t.id} className="rail-row" aria-current={t.id === tid} onClick={() => onPick(t.id)}>
        <div className="headline">
          <span className="who">#{t.id} {t.name}</span>
          <span className="cost">day {t.day}</span>
        </div>
        <div className="sub">
          <span style={{ color: `var(--${p.tone === "live" ? "series-1" : p.tone === "attention" ? "serious" : p.tone === "fault" ? "critical" : p.tone === "good" ? "good" : "muted"})` }}>●</span>
          <span className="state">{p.label} · {t.goal ?? ""}</span>
        </div>
      </button>
    );
  };
  return (
    <nav className="rail" aria-label="Campaign runs">
      <div className="rail-top">
        <button className="btn btn-primary w-full justify-center" onClick={onNew}>New campaign</button>
      </div>
      <div className="rail-scroll">
        <section className="rail-section">
          <h2>In flight <span className="count">{active.length}</span></h2>
          {active.length ? active.map(row) : <p className="rail-empty">No run is in flight.</p>}
        </section>
        <section className="rail-section">
          <h2>Finished / stopped <span className="count">{rest.length}</span></h2>
          {rest.length ? rest.map(row) : <p className="rail-empty">None yet.</p>}
        </section>
      </div>
    </nav>
  );
}

// ------------------------------------------------------------------ one run
function RunView({ tid, s, decisions, creatives, q, reload }:
  { tid: number; s: any; decisions: Decision[]; creatives: Creative[]; q: string; reload: () => void }) {
  const [busy, setBusy] = useState("");
  const [runN, setRunN] = useState(7);
  const [err, setErr] = useState("");
  const phase = readPhase(s.phase, s.killed);
  const c = s.customer ?? {};
  const plan = s.plan;
  const totalDays = plan?.days ?? s.brief?.days ?? (s.brief?.weeks ?? 0) * 7;
  const running: string | null = s.running_agent ?? null;

  async function act(label: string, fn: () => Promise<any>) {
    setBusy(label); setErr("");
    try { await fn(); } catch (e) { setErr(String(e)); }
    setBusy(""); reload();
  }

  return (
    <>
      <div className="pane-head">
        <h1>
          {c.name ?? "Campaign"} <span className="ref">#{tid}</span>
          <Chip tone={phase.tone}>{phase.label}</Chip>
          {running && <Chip tone="live">{running.replace(/_/g, " ")} working</Chip>}
        </h1>
        <div className="meta">
          Day {s.day} of {totalDays || "–"} · {usd(plan?.daily_budget ?? s.brief?.daily_budget)}/day · {decisions.length} agent steps
        </div>
        <div className="gloss">{phase.gloss}</div>
        <div className="flex flex-wrap items-center gap-2 mt-4">
          <span className="text-xs" style={{ color: "var(--muted)" }}>Advance the simulation by</span>
          <DaysPicker value={runN} onChange={setRunN} presets={RUN_PRESETS} max={120} label="Days to run" />
          <button className="btn btn-primary" disabled={!!busy || s.phase !== "running" || s.killed}
            onClick={() => act("run", () => post(`/admin/controls${q}`, { action: "run_days", days: runN }))}>
            {busy === "run" ? "Running…" : "Run"}
          </button>
          {s.killed
            ? <button className="btn" disabled={!!busy} onClick={() => act("resume", () => post(`/admin/controls${q}`, { action: "resume" }))}>Resume</button>
            : <button className="btn btn-danger" disabled={!!busy || s.phase !== "running"} onClick={() => act("kill", () => post(`/admin/controls${q}`, { action: "kill" }))}>Kill switch</button>}
          {err && <span className="text-xs" style={{ color: "var(--critical)" }}>{err}</span>}
        </div>
      </div>

      <Spread>
        <Block title="Company">
          <CompanyFacts c={c} />
        </Block>
        <Block title="Goal">
          <p className="answer">{s.brief?.goal}</p>
          {!plan && (
            <p className="support">{s.phase === "error" ? "Planning failed: see the flow." : "The strategist is reading the goal…"}</p>
          )}
          {plan && (
            <>
              <p className="step-rationale mt-3" style={{ color: "var(--text-secondary)", maxWidth: "70ch" }}>
                <b style={{ color: "var(--text-primary)", fontWeight: 600 }}>How the agents read it: </b>{plan.goal_interpretation}
              </p>
              <dl className="facts mt-3">
                <dt>Products</dt><dd>{plan.products.join(", ")}</dd>
                <dt>Audiences</dt><dd>{plan.audiences.join(", ")}</dd>
                <dt>Geos</dt><dd>{plan.geos.join(", ")}</dd>
                <dt>Channels</dt><dd>{plan.channels.join(", ")}</dd>
                <dt>Budget</dt><dd>{usd(plan.daily_budget)}/day for {totalDays} days</dd>
                {plan.kpi && <><dt>KPI</dt><dd>{plan.kpi}</dd></>}
              </dl>
            </>
          )}
        </Block>
      </Spread>

      <Spread>
        <Block title="Agent map">
          <AgentMap decisions={decisions} runningAgent={running} phase={s.phase} />
        </Block>
        <Block title="Flow · what each agent did and why">
          <FollowScroll dep={`${decisions.length}:${running}`}>
            <Trail decisions={decisions} runningAgent={running} />
          </FollowScroll>
        </Block>
      </Spread>

      {s.phase === "awaiting_approval" && <ApprovalQueue items={creatives} c={c} q={q} onDone={reload} />}

      <Ads items={creatives} c={c} />
    </>
  );
}

/** Scroll box that sticks to the newest step, unless the reader has scrolled up to read history. */
function FollowScroll({ dep, children }: { dep: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [dep]);
  return (
    <div ref={ref} style={{ maxHeight: 720, overflowY: "auto", paddingRight: 6 }}
      onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}>
      {children}
    </div>
  );
}

function CompanyFacts({ c }: { c: any }) {
  if (!c?.name) return <p className="empty">No CRM record.</p>;
  return (
    <>
      <dl className="facts">
        <dt>Type</dt><dd>{c.institution_type === "bank" ? "Bank" : "Credit union"}</dd>
        <dt>Assets</dt><dd>${Number(c.assets_musd).toLocaleString()}M</dd>
        <dt>Branches</dt><dd>{c.branches || "Online only"}</dd>
        <dt>Region</dt><dd>{c.region}</dd>
        <dt>Insurer</dt><dd>{c.insurer_disclosure}</dd>
        <dt>Brand voice</dt><dd style={{ color: "var(--text-secondary)" }}>{c.brand_voice}</dd>
      </dl>
      <table className="mt-4">
        <thead><tr><th>Product</th><th className="num">APY</th><th className="num">Min. balance</th><th className="num">Fee/mo</th></tr></thead>
        <tbody>
          {Object.entries(c.products ?? {}).map(([k, p]: [string, any]) => (
            <tr key={k}><td>{p.name}</td><td className="num">{p.apy.toFixed(2)}%</td><td className="num">{usd(p.min_balance)}</td><td className="num">{usd(p.monthly_fee)}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="support">Rates as of {c.rates_as_of} · read-only, from the CRM</p>
    </>
  );
}

// ------------------------------------------------------------------ ads
function adProps(ad: Creative, c: any) {
  const p = c.products?.[ad.product];
  return { bank: c.name ?? "Bank", productName: p?.name, apy: p?.apy };
}

function ApprovalQueue({ items, c, q, onDone }: { items: Creative[]; c: any; q: string; onDone: () => void }) {
  const queue = items.filter((x) => x.status === "pending_approval" || x.status === "failed_compliance");
  const pending = queue.filter((x) => x.status === "pending_approval");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  // Keyed on the ids themselves: two runs can have the same number of ads, and a count key
  // would keep the previous run's selection (approving nothing, rejecting everything).
  const pendingKey = pending.map((x) => x.id).join(",");
  useEffect(() => {
    setSel(new Set(pending.map((x) => x.id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingKey]);

  async function submit() {
    setBusy(true);
    try {
      await post(`/admin/approvals${q}`, { approve: [...sel].filter((id) => pending.some((x) => x.id === id)), reject: pending.filter((x) => !sel.has(x.id)).map((x) => x.id) });
    } finally { setBusy(false); onDone(); }
  }

  return (
    <Block title={<>Approval queue <Chip tone="attention">{pending.length} passed compliance</Chip></>}
      aside={<button className="btn btn-primary" style={{ marginLeft: "auto" }} disabled={busy} onClick={submit}>
        {busy ? "Launching…" : `Approve ${sel.size} & launch`}</button>}>
      <div className="ads-grid">
        {queue.map((ad) => (
          <AdPreview key={ad.id} ad={ad} {...adProps(ad, c)} select={
            <label className="ad-select">
              <input type="checkbox" disabled={ad.status !== "pending_approval"} checked={sel.has(ad.id)}
                onChange={(e) => { const n = new Set(sel); e.target.checked ? n.add(ad.id) : n.delete(ad.id); setSel(n); }} />
            </label>
          } />
        ))}
      </div>
    </Block>
  );
}

function Ads({ items, c }: { items: Creative[]; c: any }) {
  const approved = items.filter((x) => x.status === "approved");
  const [tab, setTab] = useState<"approved" | "all">("approved");
  const list = tab === "approved" ? approved : items;
  return (
    <Block title={<>Final ads <span style={{ fontWeight: 400 }}>{approved.length} approved · {items.length} written</span></>}
      aside={
        <span className="tabs">
          <button aria-pressed={tab === "approved"} onClick={() => setTab("approved")}>Approved</button>
          <button aria-pressed={tab === "all"} onClick={() => setTab("all")}>All</button>
        </span>
      }>
      {list.length
        ? <div className="ads-grid">{list.map((ad) => <AdPreview key={ad.id} ad={ad} {...adProps(ad, c)} />)}</div>
        : <p className="empty">{items.length ? "No ads approved yet." : "The creative agent has not written any ads yet."}</p>}
    </Block>
  );
}

// ------------------------------------------------------------------ new campaign
function NewCampaign({ customers, onStarted, onCancel }:
  { customers: any[]; onStarted: (tid: number) => void; onCancel?: () => void }) {
  const [cid, setCid] = useState<string>(customers[0]?.id ?? "");
  const c = customers.find((x) => x.id === cid);
  const [goal, setGoal] = useState("");
  const [budget, setBudget] = useState<number>(c?.default_daily_budget ?? 2000);
  const [days, setDays] = useState<number>((c?.default_weeks ?? 12) * 7);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  function pick(id: string) {
    setCid(id);
    const n = customers.find((x) => x.id === id);
    if (n) { setBudget(n.default_daily_budget); setDays(n.default_weeks * 7); }
  }

  async function start() {
    if (goal.trim().length < 5) return setErr("Describe the goal in a sentence.");
    setBusy(true); setErr("");
    try {
      const r = await post("/admin/campaigns/start", { customer_id: cid, goal, daily_budget: budget, days });
      onStarted(r.tenant_id);
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  }

  return (
    <>
      <div className="pane-head">
        <h1>New campaign</h1>
        <div className="gloss">Pick a customer and write the goal in a sentence. The agents plan the strategy, write the ads and check them for compliance; you approve before anything launches.</div>
      </div>
      <Spread>
        <Block title="Company">
          <label className="field mb-4">
            <span>Customer (from CRM)</span>
            <select className="input" value={cid} onChange={(e) => pick(e.target.value)}>
              {customers.map((x) => (
                <option key={x.id} value={x.id}>{x.name} · {x.institution_type === "bank" ? "Bank" : "Credit union"} · {x.region}</option>
              ))}
            </select>
          </label>
          {c && <CompanyFacts c={c} />}
        </Block>
        <Block title="Goal and budget">
          <div className="flex flex-col gap-4">
            <label className="field">
              <span>Goal (the agents plan the strategy from this)</span>
              <textarea className="input h-28" value={goal} onChange={(e) => setGoal(e.target.value)}
                placeholder="e.g. Grow CD balances among retirees near our branches before rates drop" />
            </label>
            <div className="flex flex-wrap gap-6">
              <label className="field">
                <span>Daily budget ($)</span>
                <input className="input w-36" type="number" min={1} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
              </label>
              <div className="field">
                <span>Campaign length</span>
                <DaysPicker key={cid} value={days} onChange={setDays} presets={LENGTH_PRESETS} max={365} label="Campaign length" />
              </div>
            </div>
            {err && <p className="text-xs" style={{ color: "var(--critical)" }}>{err}</p>}
            <div className="flex gap-2">
              <button className="btn btn-primary" disabled={busy || !cid} onClick={start}>{busy ? "Starting…" : "Start campaign"}</button>
              {onCancel && <button className="btn" onClick={onCancel}>Cancel</button>}
            </div>
          </div>
        </Block>
      </Spread>
    </>
  );
}
