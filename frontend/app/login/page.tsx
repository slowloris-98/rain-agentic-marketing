"use client";
import { useState } from "react";
import { API } from "@/lib/api";

export default function Login() {
  const [email, setEmail] = useState("admin@rain");
  const [password, setPassword] = useState("admin");
  const [err, setErr] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const r = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) return setErr("Invalid credentials");
    const j = await r.json();
    localStorage.setItem("token", j.token);
    window.location.href = j.role === "admin" ? "/admin" : "/client";
  }

  return (
    <main className="min-h-screen flex items-center justify-center">
      <form onSubmit={submit} className="card w-80 space-y-3">
        <h1 className="text-lg font-semibold">RAIN · Agentic Marketing</h1>
        <input className="w-full border rounded px-2 py-1" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="w-full border rounded px-2 py-1" type="password" value={password}
          onChange={(e) => setPassword(e.target.value)} />
        {err && <p className="text-sm text-red-700">{err}</p>}
        <button className="btn btn-primary w-full">Sign in</button>
        <p className="text-xs text-neutral-500">
          Demo: admin@rain / admin (RAIN staff) · client@lacap / client (La Cap, read-only)
        </p>
      </form>
    </main>
  );
}
