"use client";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AGENTIC, BASELINE, api, num, usd, useLive } from "@/lib/api";

type Data = { kpis: any; campaigns: any[]; trends: any[]; reports: any[] };

const money = (v: number) => (v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${Math.round(v / 1000)}k`);

export default function Client() {
  const { data } = useLive<Data>({
    kpis: "/client/kpis", campaigns: "/client/campaigns", trends: "/client/trends", reports: "/client/reports",
  });
  const [detail, setDetail] = useState<any>(null);
  const k = data.kpis;

  return (
    <main className="max-w-[1200px] mx-auto p-6 space-y-4">
      <header className="flex items-center">
        <h1 className="text-xl font-semibold mr-auto">{k?.tenant ?? "Client"} · deposit growth</h1>
        <span className="text-sm text-neutral-600 mr-3">Day {k?.day ?? 0} · powered by RAIN</span>
        <button className="btn" onClick={() => { localStorage.clear(); location.href = "/login"; }}>Sign out</button>
      </header>

      <section className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Kpi label="New accounts" value={num(k?.new_accounts)} />
        <Kpi label="New deposits" value={usd(k?.new_deposits)} />
        <Kpi label="Average balance" value={usd(k?.avg_balance)} />
        <Kpi label="Cost per $1K deposits" value={usd(k?.cost_per_1k_deposits, 2)} />
        <Kpi label="Members / non-members" value={`${num(k?.members)} / ${num(k?.non_members)}`} />
      </section>

      <section className="card">
        <div className="h">Cumulative deposit value · agentic allocation vs fixed split (same spend)</div>
        {k?.lift_vs_baseline != null && (
          <p className="text-sm mb-2">
            Agentic allocation: <b>{(k.lift_vs_baseline * 100).toFixed(1)}%</b> {k.lift_vs_baseline >= 0 ? "more" : "less"} long-term
            deposit value than a fixed even split ({usd(k.value)} vs {usd(k.baseline.value)}).
          </p>
        )}
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={data.trends ?? []} margin={{ left: 8, right: 16 }}>
            <CartesianGrid stroke="#ecebe7" vertical={false} />
            <XAxis dataKey="day" tick={{ fontSize: 11 }} stroke="#a3a29d" />
            <YAxis tickFormatter={money} tick={{ fontSize: 11 }} stroke="#a3a29d" width={56} />
            <Tooltip formatter={(v) => usd(Number(v))} labelFormatter={(d) => `Day ${d}`} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line name="Agentic" dataKey="agentic_value_cum" stroke={AGENTIC} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line name="Fixed split" dataKey="baseline_value_cum" stroke={BASELINE} strokeWidth={2} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>

      <div className="grid md:grid-cols-5 gap-4">
        <section className="card md:col-span-3">
          <div className="h">Campaigns</div>
          <table>
            <thead><tr><th>Campaign</th><th>Status</th><th className="num">Spend</th><th className="num">Accounts</th><th className="num">Deposits</th></tr></thead>
            <tbody>
              {(data.campaigns ?? []).map((c) => (
                <tr key={c.id} className="cursor-pointer hover:bg-neutral-50" onClick={async () => setDetail(await api(`/client/campaigns/${c.id}`))}>
                  <td className="underline decoration-dotted">{c.name}</td>
                  <td>{c.status}</td>
                  <td className="num">{usd(c.spend)}</td>
                  <td className="num">{num(c.accounts)}</td>
                  <td className="num">{usd(c.deposits)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {detail && (
            <div className="mt-4 border-t pt-3">
              <div className="flex items-center"><b className="mr-auto">{detail.name}</b><button className="btn !py-0" onClick={() => setDetail(null)}>Close</button></div>
              <p className="text-sm text-neutral-600">{num(detail.accounts)} accounts · {usd(detail.deposits)} deposits · {usd(detail.spend)} spend · envelope {usd(detail.envelope)}/day</p>
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={detail.daily}>
                  <CartesianGrid stroke="#ecebe7" vertical={false} />
                  <XAxis dataKey="day" tick={{ fontSize: 11 }} stroke="#a3a29d" />
                  <YAxis tickFormatter={money} tick={{ fontSize: 11 }} stroke="#a3a29d" width={56} />
                  <Tooltip formatter={(v) => usd(Number(v))} labelFormatter={(d) => `Day ${d}`} />
                  <Line name="Deposits" dataKey="deposits" stroke={AGENTIC} strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
              {detail.creatives.map((c: any, i: number) => (
                <div key={i} className="text-sm border rounded p-2 mt-2">
                  <b>{c.headline}</b> · {c.body}<div className="text-[11px] text-neutral-500">{c.disclosure}</div>
                </div>
              ))}
            </div>
          )}
        </section>
        <section className="card md:col-span-2">
          <div className="h">Weekly report</div>
          <div className="space-y-3 max-h-[520px] overflow-auto">
            {(data.reports ?? []).map((r) => (
              <article key={r.week} className="text-sm"><div className="text-xs text-neutral-500">Week {r.week}</div>{r.text}</article>
            ))}
            {!data.reports?.length && <p className="text-sm text-neutral-500">The first report arrives after week 1.</p>}
          </div>
        </section>
      </div>
    </main>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
