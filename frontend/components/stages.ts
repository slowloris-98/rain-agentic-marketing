/** Every step the orchestrator runs (backend/app/orchestrator.py SETUP / LAUNCH / DAILY / WEEKLY),
 *  in run order. The agent map draws them as one straight line; the stage is kept as text context. */
export const ORDER = [
  "strategist", "creative", "compliance", "human_approval", "media_launch",
  "allocator", "media_update", "simulate_day", "core_feed", "upload_conversions",
  "rollup", "reflection", "reporter",
] as const;

export type Kind = "agent" | "human" | "platform";

/** Shape on the map: AI agents are circles, human steps diamonds, external systems squares. */
const KIND: Record<string, Kind> = {
  human_approval: "human",
  media_launch: "platform",       // creates the campaigns on Google / Meta
  media_update: "platform",       // pushes today's budgets to the platforms
  simulate_day: "platform",       // the platforms' delivery results (simulated in sandbox)
  core_feed: "platform",          // new accounts from the bank's core system
  upload_conversions: "platform", // value-weighted conversions back to the platforms
};
export const kindOf = (a: string): Kind => KIND[a] ?? "agent";
export const KIND_LABEL: Record<Kind, string> = { agent: "AI agent", human: "Human step", platform: "Ad platform / bank system" };

export type Stage = { id: string; label: string; agents: string[] };
export const STAGES: Stage[] = [
  { id: "setup", label: "Setup", agents: ["strategist", "creative", "compliance"] },
  { id: "launch", label: "Launch", agents: ["human_approval", "media_launch"] },
  { id: "daily", label: "Daily loop", agents: ["allocator", "media_update", "simulate_day", "core_feed", "upload_conversions"] },
  { id: "weekly", label: "Weekly", agents: ["rollup", "reflection", "reporter"] },
];
export const STAGE_OF: Record<string, Stage> = Object.fromEntries(
  STAGES.flatMap((s) => s.agents.map((a) => [a, s] as const)),
);

/** Display name: Title Case, with "Agent" after every AI agent on the map
 *  (strategist -> "Strategist Agent", upload_conversions -> "Upload Conversions"). */
export const agentLabel = (a: string) => {
  const title = a.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  return (ORDER as readonly string[]).includes(a) && kindOf(a) === "agent" ? `${title} Agent` : title;
};

/** One evenly spaced hue per step, so every node has its own colour. */
export const agentHue = (a: string) => {
  const i = (ORDER as readonly string[]).indexOf(a);
  return i < 0 ? 250 : (210 + (i * 360) / ORDER.length) % 360;
};

/** The step's colour on a light surface (the Trail), matching its node on the map. */
export const agentColor = (a: string) =>
  (ORDER as readonly string[]).includes(a) ? `oklch(60% 0.15 ${agentHue(a)})` : "var(--text-primary)";
