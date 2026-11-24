"use client";
/** The flow: every agent step in the order it happened, with its reasoning (NexusGTM's Trail). */
import type { CSSProperties } from "react";
import { STAGE_OF, agentColor, agentLabel, kindOf } from "./stages";

export type Decision = { id: number; ts: string; day: number; agent: string; reasoning: string; inputs: unknown; output: unknown };

const CAP = 40;

export function Trail({ decisions, runningAgent }: { decisions: Decision[]; runningAgent: string | null }) {
  const ordered = [...decisions].sort((a, b) => a.id - b.id);
  const shown = ordered.slice(-CAP);
  if (!shown.length && !runningAgent) return <p className="empty">No steps yet. The flow fills in as each agent finishes.</p>;

  return (
    <>
      {ordered.length > CAP && (
        <p className="empty" style={{ marginBottom: 12 }}>Showing the latest {CAP} of {ordered.length} steps.</p>
      )}
      <ol className="trail">
        {shown.map((d, i) => {
          const human = d.agent.startsWith("human_");  // human_control is not on the map; kindOf calls it an agent
          const failed = d.agent === "orchestrator" || /failed/i.test(d.reasoning);
          const stage = STAGE_OF[d.agent]?.label ?? (human ? "Human" : "Orchestrator");
          const prevDay = i > 0 ? shown[i - 1].day : -1;
          return (
            <li key={d.id} className={`kind-${kindOf(d.agent)}${failed ? " terminal" : ""}`}
              style={{ "--dot": agentColor(d.agent) } as CSSProperties}>
              {d.day !== prevDay && d.day > 0 && (
                <div className="step-candidates" style={{ marginTop: 0, marginBottom: 2, textTransform: "uppercase", letterSpacing: ".05em" }}>
                  Day {d.day}
                </div>
              )}
              <div className="step-agent">
                <span>{agentLabel(d.agent)}</span>{" "}
                <span className="dept">· {stage}</span>
              </div>
              <div className="step-rationale">{d.reasoning?.replace(/^\[(llm|template)\]\s*/, "") || "No reasoning recorded."}</div>
              <details>
                <summary>
                  {new Date(d.ts + (d.ts.endsWith("Z") ? "" : "Z")).toLocaleTimeString()} · show input and output
                </summary>
                <pre className="payload">{JSON.stringify({ inputs: d.inputs, output: d.output }, null, 2)}</pre>
              </details>
            </li>
          );
        })}
        {runningAgent && (
          <li className={`running kind-${kindOf(runningAgent)}`} style={{ "--dot": agentColor(runningAgent) } as CSSProperties}>
            <div className="step-agent">
              <span>{agentLabel(runningAgent)}</span>{" "}
              <span className="dept">· {STAGE_OF[runningAgent]?.label ?? "Orchestrator"}</span>
            </div>
            <div className="step-rationale">Working now…</div>
          </li>
        )}
      </ol>
    </>
  );
}
