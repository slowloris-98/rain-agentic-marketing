"use client";
/**
 * The orchestration as a constellation, after NexusGTM's RunGraph: orchestrator at the centre,
 * the four stages as hubs, their agents on the outer ring. Handoff lines come only from the
 * decision log (what actually ran, in order); agents this run has not used yet are dimmed;
 * the agent executing right now pulses. A relay dot replays the latest hops in order.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { STAGES, STAGE_OF, agentLabel } from "./stages";

const SIZE = 1000;
const C = SIZE / 2;
const R_DEPT = 200;
const R_AGENT = 310;
const R_DEPT_LABEL = 465;
const NODE = { core: 18, coreRing: 28, coreHalo: 120, hub: 18, hubRing: 28, agent: 12, pulse: 27 };
const FAN = (2 * Math.PI / STAGES.length) * 0.35;
const START = -Math.PI / 4; // stages sit on the diagonals so agent labels never stack on one row

type Pt = { x: number; y: number };
type AgentNode = Pt & { agent: string; hue: number; theta: number; stage: string };

const hueVar = (h: number): CSSProperties => ({ "--hue": h }) as CSSProperties;
const pct = (n: number) => `${(n / SIZE) * 100}%`;

function layout() {
  const hubs: (Pt & { id: string; label: string; hue: number; theta: number; lx: number; ly: number })[] = [];
  const agents: AgentNode[] = [];
  STAGES.forEach((s, i) => {
    const theta = START + (2 * Math.PI * i) / STAGES.length;
    hubs.push({
      id: s.id, label: s.label, hue: s.hue, theta,
      x: C + R_DEPT * Math.cos(theta), y: C + R_DEPT * Math.sin(theta),
      lx: C + R_DEPT_LABEL * Math.cos(theta), ly: C + R_DEPT_LABEL * Math.sin(theta),
    });
    const M = s.agents.length;
    s.agents.forEach((a, j) => {
      const at = theta + (M <= 1 ? 0 : -FAN + (2 * FAN * j) / (M - 1));
      agents.push({ agent: a, hue: s.hue, theta: at, stage: s.id, x: C + R_AGENT * Math.cos(at), y: C + R_AGENT * Math.sin(at) });
    });
  });
  return { hubs, agents, byAgent: new Map(agents.map((a) => [a.agent, a])) };
}

function starfield(count: number, seed = 9) {
  let s = seed;
  const rand = () => ((s = (s * 1664525 + 1013904223) % 4294967296), s / 4294967296);
  return Array.from({ length: count }, () => ({ x: rand() * 100, y: rand() * 100, r: 0.4 + rand() * 0.75, o: 0.15 + rand() * 0.5 }));
}

const DOT_SPEED = 260;
const hopSeconds = (len: number) => Math.min(2.6, Math.max(0.9, len / DOT_SPEED));

export function AgentMap({ decisions, runningAgent, phase }:
  { decisions: { id: number; agent: string }[]; runningAgent: string | null; phase?: string }) {
  const g = useMemo(layout, []);
  const stars = useMemo(() => starfield(360), []);

  // Route = the decision log oldest-first, restricted to agents on the map, consecutive repeats folded.
  const path = useMemo(() => {
    const out: string[] = [];
    for (const d of [...decisions].sort((a, b) => a.id - b.id)) {
      if (!STAGE_OF[d.agent]) continue;
      if (out[out.length - 1] !== d.agent) out.push(d.agent);
    }
    if (runningAgent && STAGE_OF[runningAgent] && out[out.length - 1] !== runningAgent) out.push(runningAgent);
    return out;
  }, [decisions, runningAgent]);

  const touched = useMemo(() => new Set(path), [path]);
  const touchedStages = useMemo(() => new Set(path.map((a) => STAGE_OF[a].id)), [path]);

  const hops = useMemo(() => {
    const list: { id: string; a: AgentNode; b: AgentNode; hue: number; len: number }[] = [];
    for (let i = 1; i < path.length; i++) {
      const a = g.byAgent.get(path[i - 1])!, b = g.byAgent.get(path[i])!;
      list.push({ id: `${a.agent}->${b.agent}`, a, b, hue: b.hue, len: Math.hypot(b.x - a.x, b.y - a.y) });
    }
    return list;
  }, [path, g]);
  const uniqueHops = useMemo(() => [...new Map(hops.map((h) => [h.id, h])).values()], [hops]);

  // Relay: walk the last few hops in order, then loop. A cursor (setTimeout), as in NexusGTM.
  const replay = useMemo(() => hops.slice(-8), [hops]);
  const [head, setHead] = useState(0);
  const reduced = useReducedMotion();
  const sig = replay.map((h) => h.id).join("|");
  useEffect(() => setHead(0), [sig]);
  useEffect(() => {
    if (!replay.length || reduced) return;
    const cur = replay[head % replay.length];
    const t = setTimeout(() => setHead((h) => (h + 1) % replay.length), hopSeconds(cur.len) * 1000 + 160);
    return () => clearTimeout(t);
  }, [head, sig, reduced, replay]);
  const current = replay.length ? replay[head % replay.length] : null;

  const planning = phase === "planning" && !runningAgent;
  const liveStage = runningAgent ? STAGE_OF[runningAgent]?.id : undefined;

  const readout = runningAgent
    ? <><b>1 agent working</b> · {agentLabel(runningAgent)} in {STAGE_OF[runningAgent]?.label ?? "the orchestrator"}</>
    : planning
      ? <><b>Planner</b> · choosing the first step</>
      : <><b>No agent working</b> · {hops.length ? `${hops.length} handoffs recorded. Lines are handoffs that actually happened.` : "Nothing has run yet."}</>;

  return (
    <div className="map-stage">
      <svg className="map-starfield" aria-hidden="true">
        <g className="map-stars">
          {stars.slice(0, 240).map((s, i) => <circle key={i} cx={`${s.x.toFixed(2)}%`} cy={`${s.y.toFixed(2)}%`} r={s.r.toFixed(2)} opacity={s.o.toFixed(2)} />)}
        </g>
        <g className="map-stars map-stars-b">
          {stars.slice(240).map((s, i) => <circle key={i} cx={`${s.x.toFixed(2)}%`} cy={`${s.y.toFixed(2)}%`} r={(s.r * 0.8).toFixed(2)} opacity={(s.o * 0.7).toFixed(2)} />)}
        </g>
      </svg>

      <div className="map-canvas">
        <svg className="map-svg" viewBox={`0 0 ${SIZE} ${SIZE}`} preserveAspectRatio="xMidYMid meet" role="img"
          aria-label={`Agent map. ${path.length ? `Route so far: ${path.map(agentLabel).join(", then ")}.` : "No agent has run yet."}`}>
          <defs>
            <radialGradient id="rain-core-halo" className="map-halo">
              <stop className="halo-in" offset="0%" />
              <stop className="halo-mid" offset="45%" />
              <stop className="halo-out" offset="100%" />
            </radialGradient>
            <filter id="rain-node-glow" x="-120%" y="-120%" width="340%" height="340%">
              <feGaussianBlur stdDeviation="9" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          <g className="map-structural">
            {g.hubs.map((h) => <line key={h.id} className="trunk" style={hueVar(h.hue)} x1={C} y1={C} x2={h.x} y2={h.y} />)}
            {g.agents.map((a) => {
              const h = g.hubs.find((x) => x.id === a.stage)!;
              return <line key={a.agent} className="branch" style={hueVar(a.hue)} x1={h.x} y1={h.y} x2={a.x} y2={a.y} />;
            })}
          </g>

          <g className="map-flow">
            {uniqueHops.map((h) => (
              <path key={h.id} className={current?.id === h.id ? "hot" : ""} style={hueVar(h.hue)}
                d={`M ${h.a.x.toFixed(1)} ${h.a.y.toFixed(1)} L ${h.b.x.toFixed(1)} ${h.b.y.toFixed(1)}`} />
            ))}
          </g>

          <g className="map-flow-dots">
            {!reduced && current && (
              <circle key={`${sig}:${head}`} cx={0} cy={0} r={4}
                style={{
                  "--hue": current.hue,
                  "--x1": `${current.a.x.toFixed(1)}px`, "--y1": `${current.a.y.toFixed(1)}px`,
                  "--x2": `${current.b.x.toFixed(1)}px`, "--y2": `${current.b.y.toFixed(1)}px`,
                  animationDuration: `${hopSeconds(current.len).toFixed(2)}s`,
                } as CSSProperties} />
            )}
          </g>

          <g className={planning ? "map-core live" : "map-core"}>
            <circle className="halo" cx={C} cy={C} r={NODE.coreHalo} />
            <circle className="core" cx={C} cy={C} r={NODE.core} />
            <circle className="ring" cx={C} cy={C} r={NODE.coreRing} />
          </g>

          {g.hubs.map((h) => (
            <g key={h.id} style={hueVar(h.hue)}
              className={`map-hub${touchedStages.has(h.id) ? "" : " dimmed"}${liveStage === h.id ? " live" : ""}`}>
              <circle className="ring" cx={h.x} cy={h.y} r={NODE.hubRing} />
              <circle className="hub" cx={h.x} cy={h.y} r={NODE.hub} />
            </g>
          ))}

          {g.agents.map((a) => {
            const live = a.agent === runningAgent;
            return (
              <g key={a.agent} style={hueVar(a.hue)}
                className={`map-node${live ? " live" : ""}${touched.has(a.agent) ? "" : " dimmed"}`}>
                {live && <circle className="pulse" cx={a.x} cy={a.y} r={NODE.pulse} />}
                <circle className="node" cx={a.x} cy={a.y} r={NODE.agent} filter={live ? "url(#rain-node-glow)" : undefined} />
              </g>
            );
          })}
        </svg>

        <div className="map-labels" aria-hidden="true">
          <div className="map-dept-label" style={{ left: "50%", top: pct(C + 46), transform: "translate(-50%, 0)", letterSpacing: "0.12em", opacity: 0.75 }}>
            Orchestrator
          </div>
          {g.hubs.map((h) => (
            <div key={h.id} className={`map-dept-label${touchedStages.has(h.id) ? "" : " dimmed"}`}
              style={{ left: pct(h.lx), top: pct(h.ly), transform: "translate(-50%, -50%)" }}>
              {h.label}
            </div>
          ))}
          {g.agents.map((a) => {
            // Labels sit just outside each node along its ray, anchored away from the centre.
            const r = R_AGENT + 24, cos = Math.cos(a.theta);
            const x = C + r * cos, y = C + r * Math.sin(a.theta);
            const tx = Math.abs(cos) < 0.25 ? "-50%" : cos > 0 ? "0" : "-100%";
            return (
              <div key={a.agent} style={{ ...hueVar(a.hue), left: pct(x), top: pct(y), transform: `translate(${tx}, -50%)` }}
                className={`map-agent-label${touched.has(a.agent) ? " shown" : ""}${a.agent === runningAgent ? " live" : ""}`}>
                {agentLabel(a.agent)}
              </div>
            );
          })}
        </div>
      </div>
      <div className="map-readout" aria-live="polite">{readout}</div>
    </div>
  );
}

function useReducedMotion() {
  const [r, setR] = useState(false);
  const mq = useRef<MediaQueryList | null>(null);
  useEffect(() => {
    mq.current = window.matchMedia("(prefers-reduced-motion: reduce)");
    setR(mq.current.matches);
    const on = (e: MediaQueryListEvent) => setR(e.matches);
    mq.current.addEventListener("change", on);
    return () => mq.current?.removeEventListener("change", on);
  }, []);
  return r;
}
