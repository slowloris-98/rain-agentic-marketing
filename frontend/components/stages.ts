/** The orchestrator's stages (backend/app/orchestrator.py SETUP / LAUNCH / DAILY / WEEKLY), drawn as
 *  the "departments" of the agent map. human_approval is the one human step, logged in Launch. */
export type Stage = { id: string; label: string; hue: number; agents: string[] };

export const STAGES: Stage[] = [
  { id: "setup", label: "Setup", hue: 230, agents: ["strategist", "creative", "compliance"] },
  { id: "launch", label: "Launch", hue: 310, agents: ["human_approval", "media_launch"] },
  { id: "daily", label: "Daily loop", hue: 40, agents: ["allocator", "media_update", "simulate_day", "core_feed", "upload_conversions"] },
  { id: "weekly", label: "Weekly", hue: 150, agents: ["rollup", "reflection", "reporter"] },
];

export const STAGE_OF: Record<string, Stage> = Object.fromEntries(
  STAGES.flatMap((s) => s.agents.map((a) => [a, s] as const)),
);

export const agentLabel = (a: string) => a.replace(/_/g, " ");

/** CSS colour for a stage, matching the map's node recipe but readable on a light surface. */
export const stageColor = (agent: string) =>
  STAGE_OF[agent] ? `oklch(60% 0.15 ${STAGE_OF[agent].hue})` : "var(--text-primary)";
