"use client";
/**
 * The run as one straight line of steps, in the order the orchestrator runs them. Shape says what
 * kind of step it is (circle = AI agent, diamond = human, square = ad platform / bank system), and
 * every step has its own colour. Two return arcs close the loops: conversions flow back from the
 * platforms to the allocator every day, and the weekly review feeds the next week.
 * Lit = has run, dimmed = not yet, pulsing = running now. A dot replays the latest handoffs.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { KIND_LABEL, ORDER, agentHue, agentLabel, kindOf, type Kind } from "./stages";

const SIZE = 1000;
const X = 520;           // the line
const TOP = 110;
const BOTTOM = 880;
const R = 13;            // circle radius; squares/diamonds are drawn to the same visual weight
const STEP = (BOTTOM - TOP) / (ORDER.length - 1);

const at = (a: string) => ({ x: X, y: TOP + (ORDER as readonly string[]).indexOf(a) * STEP });
const idx = (a: string) => (ORDER as readonly string[]).indexOf(a);

/** Return arcs that close the loops, drawn on the left of the line. */
const LOOPS = [
  { id: "daily", from: "upload_conversions", to: "allocator", cx: 330, label: "conversions feed back · every day" },
  { id: "weekly", from: "reporter", to: "allocator", cx: 190, label: "lessons feed the next week" },
] as const;
const loopPath = (l: (typeof LOOPS)[number]) => {
  const a = at(l.from), b = at(l.to);
  return `M ${X - R - 4} ${a.y} C ${l.cx} ${a.y}, ${l.cx} ${b.y}, ${X - R - 6} ${b.y}`;
};
const loopApexX = (cx: number) => 0.25 * (X - R - 5) + 0.75 * cx;

const hueVar = (h: number): CSSProperties => ({ "--hue": h }) as CSSProperties;
const pct = (n: number) => `${(n / SIZE) * 100}%`;

function starfield(count: number, seed = 9) {
  let s = seed;
  const rand = () => ((s = (s * 1664525 + 1013904223) % 4294967296), s / 4294967296);
  return Array.from({ length: count }, () => ({ x: rand() * 100, y: rand() * 100, r: 0.4 + rand() * 0.75, o: 0.15 + rand() * 0.5 }));
}

/** One node in its kind's shape. */
function Shape({ kind, x, y, live }: { kind: Kind; x: number; y: number; live: boolean }) {
  const filter = live ? "url(#rain-node-glow)" : undefined;
  if (kind === "platform") {
    const s = R * 1.75;
    return <rect className="node" x={x - s / 2} y={y - s / 2} width={s} height={s} rx={3} filter={filter} />;
  }
  if (kind === "human") {
    const s = R * 1.6;
    return <rect className="node" x={x - s / 2} y={y - s / 2} width={s} height={s} rx={2}
      transform={`rotate(45 ${x} ${y})`} filter={filter} />;
  }
  return <circle className="node" cx={x} cy={y} r={R} filter={filter} />;
}

/** Small legend glyph, same shapes as the nodes. */
function Glyph({ kind }: { kind: Kind }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      {kind === "agent" && <circle cx="6" cy="6" r="5" />}
      {kind === "platform" && <rect x="1.5" y="1.5" width="9" height="9" rx="1.5" />}
      {kind === "human" && <rect x="2.5" y="2.5" width="7" height="7" rx="1" transform="rotate(45 6 6)" />}
    </svg>
  );
}

const DOT_SPEED = 220;
const hopSeconds = (len: number) => Math.min(1.8, Math.max(0.6, len / DOT_SPEED));

export function AgentMap({ decisions, runningAgent, phase }:
  { decisions: { id: number; agent: string }[]; runningAgent: string | null; phase?: string }) {
  const stars = useMemo(() => starfield(360), []);

  // Route = the decision log oldest-first, restricted to steps on the line, repeats folded.
  const path = useMemo(() => {
    const out: string[] = [];
    for (const d of [...decisions].sort((a, b) => a.id - b.id)) {
      if (idx(d.agent) < 0) continue;
      if (out[out.length - 1] !== d.agent) out.push(d.agent);
    }
    if (runningAgent && idx(runningAgent) >= 0 && out[out.length - 1] !== runningAgent) out.push(runningAgent);
    return out;
  }, [decisions, runningAgent]);

  const touched = useMemo(() => new Set(path), [path]);
  const hops = useMemo(() => path.slice(1).map((b, i) => ({ id: `${path[i]}->${b}`, a: path[i], b })), [path]);
  const used = useMemo(() => new Set(hops.map((h) => h.id)), [hops]);
  const loopOf = (h: { a: string; b: string }) => LOOPS.find((l) => l.from === h.a && l.to === h.b);

  // Relay: walk the latest hops in order, then loop. Forward hops get a travelling dot; a
  // loop-back hop lights its return arc instead.
  const replay = useMemo(() => hops.slice(-8), [hops]);
  const sig = replay.map((h) => h.id).join("|");
  const [head, setHead] = useState(0);
  const reduced = useReducedMotion();
  useEffect(() => setHead(0), [sig]);
  useEffect(() => {
    if (!replay.length || reduced) return;
    const cur = replay[head % replay.length];
    const len = loopOf(cur) ? 400 : Math.abs(at(cur.b).y - at(cur.a).y);
    const t = setTimeout(() => setHead((h) => (h + 1) % replay.length), hopSeconds(len) * 1000 + 160);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [head, sig, reduced]);
  const current = replay.length ? replay[head % replay.length] : null;
  const currentLoop = current ? loopOf(current) : undefined;
  const forward = current && !currentLoop && idx(current.b) > idx(current.a) ? current : null;

  const readout = runningAgent
    ? <><b>1 step working</b> · {agentLabel(runningAgent)}{kindOf(runningAgent) === "agent" ? "" : ` (${KIND_LABEL[kindOf(runningAgent)].toLowerCase()})`}</>
    : phase === "planning"
      ? <><b>Starting</b> · the Strategist Agent is about to read the goal</>
      : <><b>Nothing working</b> · {hops.length ? `${hops.length} handoffs so far. Lit steps have run; dim ones have not yet.` : "Nothing has run yet."}</>;

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
          aria-label={`Run flow. ${path.length ? `So far: ${path.map(agentLabel).join(", then ")}.` : "Nothing has run yet."}`}>
          <defs>
            <filter id="rain-node-glow" x="-120%" y="-120%" width="340%" height="340%">
              <feGaussianBlur stdDeviation="9" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <marker id="rain-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className="map-arrow" />
            </marker>
          </defs>

          {/* The straight line, one segment per consecutive pair, in the receiving step's hue. */}
          <g className="map-line">
            {ORDER.slice(1).map((b, i) => {
              const a = ORDER[i], id = `${a}->${b}`;
              return (
                <line key={id} className={`${used.has(id) ? "used" : ""}${forward?.id === id ? " hot" : ""}`}
                  style={hueVar(agentHue(b))} x1={X} y1={at(a).y + R} x2={X} y2={at(b).y - R} />
              );
            })}
          </g>

          {/* Return arcs that close the loops. */}
          <g className="map-loop">
            {LOOPS.map((l) => {
              const id = `${l.from}->${l.to}`;
              const midY = (at(l.from).y + at(l.to).y) / 2, tx = loopApexX(l.cx) - 12;
              return (
                <g key={l.id} className={`${used.has(id) ? "used" : ""}${currentLoop?.id === l.id ? " hot" : ""}`}
                  style={hueVar(agentHue(l.to))}>
                  <path d={loopPath(l)} markerEnd="url(#rain-arrow)" />
                  <text x={tx} y={midY} transform={`rotate(-90 ${tx} ${midY})`} textAnchor="middle">{l.label}</text>
                </g>
              );
            })}
          </g>

          <g className="map-flow-dots">
            {!reduced && forward && (() => {
              const a = at(forward.a), b = at(forward.b);
              return (
                <circle key={`${sig}:${head}`} cx={0} cy={0} r={5}
                  style={{
                    "--hue": agentHue(forward.b),
                    "--x1": `${a.x}px`, "--y1": `${a.y.toFixed(1)}px`, "--x2": `${b.x}px`, "--y2": `${b.y.toFixed(1)}px`,
                    animationDuration: `${hopSeconds(b.y - a.y).toFixed(2)}s`,
                  } as CSSProperties} />
              );
            })()}
          </g>

          {ORDER.map((a) => {
            const p = at(a), live = a === runningAgent;
            return (
              <g key={a} style={hueVar(agentHue(a))}
                className={`map-node${live ? " live" : ""}${touched.has(a) ? "" : " dimmed"}`}>
                {live && <circle className="pulse" cx={p.x} cy={p.y} r={30} />}
                <Shape kind={kindOf(a)} x={p.x} y={p.y} live={live} />
              </g>
            );
          })}
        </svg>

        <div className="map-labels" aria-hidden="true">
          <div className="map-legend" style={{ left: "3%", top: "3%" }}>
            {(["agent", "human", "platform"] as Kind[]).map((k) => (
              <span key={k}><Glyph kind={k} />{KIND_LABEL[k]}</span>
            ))}
          </div>
          {ORDER.map((a) => {
            const p = at(a);
            return (
              <div key={a} style={{ ...hueVar(agentHue(a)), left: pct(p.x + 30), top: pct(p.y), transform: "translate(0, -50%)" }}
                className={`map-agent-label${touched.has(a) ? " shown" : ""}${a === runningAgent ? " live" : ""}`}>
                {agentLabel(a)}
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
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setR(mq.matches);
    const on = (e: MediaQueryListEvent) => setR(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return r;
}
