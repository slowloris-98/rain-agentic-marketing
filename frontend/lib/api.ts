"use client";
import { useCallback, useEffect, useState } from "react";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function token(): string | null {
  return typeof window === "undefined" ? null : localStorage.getItem("token");
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(API + path, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token()}`, ...(init.headers ?? {}) },
  });
  if (r.status === 401) {
    localStorage.removeItem("token");
    window.location.href = "/login";
  }
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const post = (path: string, body: unknown) => api(path, { method: "POST", body: JSON.stringify(body) });

/** Fetch a set of endpoints and refetch them whenever the backend pushes an SSE event. */
export function useLive<T extends Record<string, any>>(paths: Record<keyof T, string>, streamQuery = "") {
  const [data, setData] = useState<Partial<T>>({});
  const [tick, setTick] = useState(0);
  const load = useCallback(async () => {
    const entries = await Promise.all(
      Object.entries(paths).map(async ([k, p]) => [k, await api(p as string).catch(() => undefined)] as const),
    );
    setData(Object.fromEntries(entries) as Partial<T>);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(paths)]);

  useEffect(() => {
    load();
  }, [load, tick]);

  useEffect(() => {
    const t = token();
    if (!t) return;
    const es = new EventSource(`${API}/stream?token=${encodeURIComponent(t)}${streamQuery}`);
    let timer: ReturnType<typeof setTimeout> | null = null;
    es.onmessage = () => {
      // coalesce bursts (a simulated day emits ~5 events) into one refresh
      if (!timer) timer = setTimeout(() => { timer = null; setTick((x) => x + 1); }, 400);
    };
    return () => { es.close(); if (timer) clearTimeout(timer); };
  }, [streamQuery]);

  return { data, reload: load };
}

export const usd = (n: number | undefined, d = 0) =>
  n === undefined || n === null ? "–" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: d });
export const num = (n: number | undefined) => (n === undefined || n === null ? "–" : n.toLocaleString("en-US"));

/** Reference categorical palette (validated, fixed order). Products always map to the same slot. */
export const PRODUCT_COLORS: Record<string, string> = {
  checking: "#2a78d6",
  savings: "#eb6834",
  cd: "#1baf7a",
  money_market: "#eda100",
};
export const AGENTIC = "#2a78d6";
export const BASELINE = "#8a8984";
