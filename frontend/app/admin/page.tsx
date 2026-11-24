"use client";
import { useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PRODUCT_COLORS, api, post, usd, useLive } from "@/lib/api";

type Data = {
  state: any; decisions: any[]; approvals: any[]; campaigns: any[]; allocator: any; lessons: any[]; policy: any;
};

export default function Admin() {
  const { data, reload } = useLive<Data>({
    state: "/admin/state", decisions: "/admin/decisions?limit=150", approvals: "/admin/approvals",
    campaigns: "/admin/campaigns", allocator: "/admin/allocator", lessons: "/admin/lessons", policy: "/admin/policy",
  });
  const [busy, setBusy] = useState("");
  const s = data.state;

  async function act(label: string, fn: () => Promise<any>) {
    setBusy(label);
    try { await fn(); } catch (e) { alert(String(e)); }
    setBusy("");
    reload();
  }

  return (
    <main className="max-w-[1400px] mx-auto p-6 space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold mr-auto">RAIN admin · La Cap Federal Credit Union</h1>
        {s && (
          <span className="text-sm text-neutral-600">
            Day {s.day} · week {Math.floor(s.day / 7) + 1} · <b>{s.phase}</b>{s.killed && " · KILLED"} · mode {s.mode} ·
            LLM {s.llm ? "on" : "templates"} · Google {s.integrations.google} · Meta {s.integrations.meta}
          </span>
        )}
        <button className="btn" onClick={() => { localStorage.clear(); location.href = "/login"; }}>Sign out</button>
      </header>

      <section className="card flex flex-wrap gap-2 items-center">
        <span className="h !mb-0 mr-2">Controls</span>
        <button className="btn btn-primary" disabled={!!busy} onClick={() => act("brief", () => post("/admin/brief", {}))}>
          {busy === "brief" ? "Planning…" : "Submit La Cap brief"}
        </button>
        {[1, 7, 84].map((n) => (
          <button key={n} className="btn" disabled={!!busy || s?.phase !== "running"}
            onClick={() => act(`run${n}`, () => post("/admin/controls", { action: "run_days", days: n }))}>
            {busy === `run${n}` ? "Running…" : `Run ${n} day${n > 1 ? "s" : ""}`}
          </button>
        ))}
        {s?.killed
          ? <button className="btn" onClick={() => act("resume", () => post("/admin/controls", { action: "resume" }))}>Resume</button>
          : <button className="btn btn-danger" onClick={() => act("kill", () => post("/admin/controls", { action: "kill" }))}>Kill switch</button>}
        <span className="ml-4 text-xs text-neutral-500">Pause agent:</span>
        {s?.agents.map((a: string) => {
          const paused = s.paused_agents.includes(a);
          return (
            <button key={a} className={`btn !px-2 !py-0.5 text-xs ${paused ? "!bg-amber-100" : ""}`}
              onClick={() => act(a, () => post("/admin/controls", { action: paused ? "unpause" : "pause", agent: a }))}>
              {paused ? "▶ " : "⏸ "}{a}
            </button>
          );
        })}
      </section>

      {s?.phase === "awaiting_approval" && <ApprovalQueue items={data.approvals ?? []} onDone={reload} />}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <section className="card xl:col-span-2">
          <div className="h">Allocator · daily budget by product</div>
          <BudgetChart split={data.allocator?.split ?? []} />
        </section>
        <section className="card">
          <div className="h">Lessons memory</div>
          <ul className="space-y-2 text-sm max-h-[300px] overflow-auto">
            {(data.lessons ?? []).map((l) => (
              <li key={l.id}><span className="text-neutral-500 text-xs mr-1">W{l.week}</span>{l.text}</li>
            ))}
            {!data.lessons?.length && <li className="text-neutral-500">Lessons appear after the first simulated week.</li>}
          </ul>
        </section>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <section className="card xl:col-span-2">
          <div className="h">Arm posteriors · value per $ (mean ± 1 sd), today&apos;s budget</div>
          <Posteriors rows={data.allocator?.posteriors ?? []} />
        </section>
        <section className="card space-y-4">
          <div>
            <div className="h">Campaigns (spend vs envelope)</div>
            <table>
              <thead><tr><th>Campaign</th><th>Platform</th><th className="num">Envelope/d</th><th className="num">Spend</th></tr></thead>
              <tbody>
                {(data.campaigns ?? []).map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}<div className="text-xs text-neutral-500">{c.status}</div></td>
                    <td className="text-xs break-all">{c.platform_id}</td>
                    <td className="num">{usd(c.envelope)}</td>
                    <td className="num">{usd(c.spend)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.policy && <Guardrails policy={data.policy} onSaved={reload} />}
        </section>
      </div>

      <section className="card">
        <div className="h">Live agent feed</div>
        <div className="max-h-[520px] overflow-auto divide-y divide-neutral-100">
          {(data.decisions ?? []).map((d) => (
            <details key={d.id} className="py-1.5 text-sm">
              <summary className="cursor-pointer">
                <span className="text-neutral-500 text-xs w-28 inline-block">day {d.day} · {new Date(d.ts + "Z").toLocaleTimeString()}</span>
                <b className="w-40 inline-block">{d.agent}</b>
                {d.reasoning}
              </summary>
              <div className="grid md:grid-cols-2 gap-2 mt-1">
                <pre className="text-xs bg-neutral-50 p-2 rounded overflow-auto max-h-64">inputs {JSON.stringify(d.inputs, null, 2)}</pre>
                <pre className="text-xs bg-neutral-50 p-2 rounded overflow-auto max-h-64">output {JSON.stringify(d.output, null, 2)}</pre>
              </div>
            </details>
          ))}
        </div>
      </section>
    </main>
  );
}

function ApprovalQueue({ items, onDone }: { items: any[]; onDone: () => void }) {
  const queue = items.filter((c) => c.status === "pending_approval" || c.status === "failed_compliance");
  const [sel, setSel] = useState<Set<number>>(new Set());
  useEffect(() => {
    setSel(new Set(queue.filter((c) => c.status === "pending_approval").map((c) => c.id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.length]);
  const pending = queue.filter((c) => c.status === "pending_approval");

  async function submit() {
    await post("/admin/approvals", { approve: [...sel], reject: pending.filter((c) => !sel.has(c.id)).map((c) => c.id) });
    onDone();
  }

  return (
    <section className="card border-amber-300">
      <div className="flex items-center mb-2">
        <div className="h !mb-0 mr-auto">Approval queue · {pending.length} ads passed compliance</div>
        <button className="btn btn-primary" onClick={submit}>Approve {sel.size} &amp; launch</button>
      </div>
      <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-2">
        {queue.map((c) => (
          <label key={c.id} className={`border rounded p-2 text-sm block ${c.status === "failed_compliance" ? "bg-red-50" : ""}`}>
            <div className="flex gap-2 items-start">
              <input type="checkbox" disabled={c.status !== "pending_approval"} checked={sel.has(c.id)}
                onChange={(e) => { const n = new Set(sel); e.target.checked ? n.add(c.id) : n.delete(c.id); setSel(n); }} />
              <div>
                <div className="text-xs text-neutral-500">{c.product} · {c.channel}</div>
                <div className="font-semibold">{c.headline}</div>
                <div>{c.body}</div>
                <div className="text-[11px] text-neutral-500 mt-1">{c.disclosure}</div>
                {c.findings.map((f: any, i: number) => (
                  <div key={i} className={`text-xs mt-1 ${f.severity === "error" ? "text-red-700" : "text-amber-700"}`}>
                    {f.severity === "error" ? "✖" : "⚠"} {f.rule}: {f.msg}
                  </div>
                ))}
                {!c.findings.length && <div className="text-xs mt-1 text-green-800">✔ Reg DD + claims checks passed</div>}
              </div>
            </div>
          </label>
        ))}
      </div>
    </section>
  );
}

function BudgetChart({ split }: { split: any[] }) {
  if (!split.length) return <p className="text-sm text-neutral-500">No allocations yet: submit a brief, approve, then run days.</p>;
  const last = split[split.length - 1];
  const total = Object.keys(PRODUCT_COLORS).reduce((a, k) => a + (last[k] ?? 0), 0);
  return (
    <>
      <p className="text-sm text-neutral-600 mb-2">
        Exploration today: <b>{total ? Math.round((last.explore / total) * 100) : 0}%</b> of {usd(total)}/day
      </p>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={split} margin={{ left: 8, right: 8 }}>
          <CartesianGrid stroke="#ecebe7" vertical={false} />
          <XAxis dataKey="day" tick={{ fontSize: 11 }} stroke="#a3a29d" />
          <YAxis tickFormatter={(v) => `$${v}`} tick={{ fontSize: 11 }} stroke="#a3a29d" width={52} />
          <Tooltip formatter={(v) => usd(Number(v))} labelFormatter={(d) => `Day ${d}`} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {Object.entries(PRODUCT_COLORS).map(([k, c]) => (
            <Area key={k} type="monotone" dataKey={k} stackId="1" stroke="#fcfcfb" strokeWidth={2} fill={c} fillOpacity={0.9} isAnimationActive={false} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </>
  );
}

function Posteriors({ rows }: { rows: any[] }) {
  if (!rows.length) return <p className="text-sm text-neutral-500">No posteriors yet.</p>;
  const max = Math.max(...rows.map((r) => r.mean + r.sd), 1);
  return (
    <div className="max-h-[360px] overflow-auto">
      <table>
        <thead><tr><th>Arm (product | channel | audience | geo)</th><th style={{ width: "40%" }}>Value per $</th><th className="num">Budget today</th><th className="num">Spend to date</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.arm} title={`${r.arm}: ${r.mean.toFixed(2)} ± ${r.sd.toFixed(2)} value per $`}>
              <td className="whitespace-nowrap">
                <span className="inline-block w-2 h-2 rounded-full mr-1.5" style={{ background: PRODUCT_COLORS[r.arm.split("|")[0]] }} />
                {r.arm}{r.explore && <span className="ml-1 text-[10px] px-1 rounded bg-neutral-200">explore</span>}
              </td>
              <td>
                <div className="relative h-3">
                  <div className="absolute top-1 h-1 bg-neutral-300 rounded"
                    style={{ left: `${(Math.max(r.mean - r.sd, 0) / max) * 100}%`, width: `${((r.mean + r.sd - Math.max(r.mean - r.sd, 0)) / max) * 100}%` }} />
                  <div className="absolute top-0 h-3 w-1 rounded" style={{ left: `${(r.mean / max) * 100}%`, background: PRODUCT_COLORS[r.arm.split("|")[0]] }} />
                </div>
                <span className="text-xs text-neutral-600">{r.mean.toFixed(2)} ± {r.sd.toFixed(2)}</span>
              </td>
              <td className="num">{usd(r.budget)}</td>
              <td className="num">{usd(r.spend)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Guardrails({ policy, onSaved }: { policy: any; onSaved: () => void }) {
  const fields = ["daily_budget", "explore_share", "max_shift", "arm_floor", "geo_floor"];
  const [p, setP] = useState<any>(policy);
  useEffect(() => setP(policy), [policy]);
  return (
    <div>
      <div className="h">Guardrails (policy.yaml)</div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        {fields.map((f) => (
          <label key={f} className="flex flex-col">
            <span className="text-xs text-neutral-500">{f}</span>
            <input className="border rounded px-2 py-0.5" type="number" step="any" value={p[f]}
              onChange={(e) => setP({ ...p, [f]: Number(e.target.value) })} />
          </label>
        ))}
      </div>
      <button className="btn mt-2" onClick={async () => { await api("/admin/policy", { method: "PUT", body: JSON.stringify(p) }); onSaved(); }}>
        Save guardrails
      </button>
    </div>
  );
}
