"use client";
import { useState, type ReactNode } from "react";

export type Tone = "good" | "attention" | "fault" | "neutral" | "live";

export function Chip({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return <span className={`chip ${tone}`} title={title}>{children}</span>;
}

export function Block({ title, aside, children, className = "", id }:
  { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section id={id} className={`block ${className}`}>
      <h2>{title}{aside}</h2>
      {children}
    </section>
  );
}

export function Spread({ children }: { children: ReactNode }) {
  return <div className="spread">{children}</div>;
}

/** Run phase -> label, explanation and tone. One place, so the rail and the header agree. */
export function readPhase(phase: string | undefined, killed = false): { label: string; tone: Tone; gloss: string } {
  if (killed) return { label: "Killed", tone: "fault", gloss: "The kill switch is on: every live campaign is paused until you resume." };
  switch (phase) {
    case "planning":
      return { label: "Planning", tone: "live", gloss: "The strategist, creative and compliance agents are working out the plan and writing ads." };
    case "awaiting_approval":
      return { label: "Needs approval", tone: "attention", gloss: "Ads passed compliance and are waiting for a human to approve them before anything launches." };
    case "running":
      return { label: "Running", tone: "live", gloss: "Campaigns are live. Each day the allocator moves budget toward what is working." };
    case "idle":
      return { label: "Idle", tone: "neutral", gloss: "Nothing was approved, so no campaigns launched." };
    case "error":
      return { label: "Failed", tone: "fault", gloss: "Planning failed. The flow below shows where it stopped." };
    default:
      return { label: phase ?? "Unknown", tone: "neutral", gloss: "" };
  }
}

/** Dropdown of preset day counts with a "Custom…" option that reveals a number input. */
export function DaysPicker({ value, onChange, presets, max, label }:
  { value: number; onChange: (n: number) => void; presets: number[]; max: number; label?: string }) {
  // Explicit mode, not derived from the value: typing "10" passes through "1", which is a preset.
  const [customMode, setCustomMode] = useState(!presets.includes(value));
  const custom = customMode || !presets.includes(value);
  return (
    <span className="inline-flex items-center gap-2">
      <select className="input" aria-label={label ?? "Days"} value={custom ? "custom" : String(value)}
        onChange={(e) => {
          if (e.target.value === "custom") setCustomMode(true);
          else { setCustomMode(false); onChange(Number(e.target.value)); }
        }}>
        {presets.map((n) => <option key={n} value={n}>{n} day{n === 1 ? "" : "s"}</option>)}
        <option value="custom">Custom…</option>
      </select>
      {custom && (
        <input className="input w-24" type="number" min={1} max={max} value={value} aria-label="Custom days"
          onChange={(e) => onChange(Math.max(1, Math.min(max, Math.round(Number(e.target.value) || 1))))} />
      )}
    </span>
  );
}
