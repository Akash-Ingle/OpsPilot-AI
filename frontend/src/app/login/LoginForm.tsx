"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ApiError, login, register } from "@/lib/api";

type Mode = "login" | "signup";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") {
        await register(email.trim(), password);
      } else {
        await login(email.trim(), password);
      }
      router.push(next);
      router.refresh();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : (err as Error).message || "Something went wrong",
      );
      setBusy(false);
    }
  }

  return (
    <div className="card p-7">
      <h1 className="text-xl font-semibold tracking-tight text-neutral-50">
        {mode === "signup" ? "Create your account" : "Welcome back"}
      </h1>
      <p className="mt-1 text-sm text-neutral-400">
        {mode === "signup"
          ? "Sign up to connect your apps and get private, AI-analyzed incidents."
          : "Log in to view your projects and incidents."}
      </p>

      <form onSubmit={submit} className="mt-6 space-y-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-neutral-400">
            Email
          </label>
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-sky-500/50"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-neutral-400">
            Password
          </label>
          <input
            type="password"
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === "signup" ? "At least 8 characters" : "••••••••"}
            className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-sky-500/50"
          />
        </div>

        {error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/[0.06] px-3 py-2 text-sm text-red-200">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy || !email.trim() || password.length < 8}
          className="w-full rounded-lg bg-gradient-to-br from-sky-500 to-indigo-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition-opacity disabled:opacity-50"
        >
          {busy
            ? "Please wait…"
            : mode === "signup"
              ? "Create account"
              : "Log in"}
        </button>
      </form>

      <p className="mt-5 text-center text-sm text-neutral-400">
        {mode === "signup" ? "Already have an account?" : "New to OpsPilot?"}{" "}
        <button
          type="button"
          onClick={() => {
            setMode(mode === "signup" ? "login" : "signup");
            setError(null);
          }}
          className="font-medium text-sky-400 hover:text-sky-300"
        >
          {mode === "signup" ? "Log in" : "Create an account"}
        </button>
      </p>
    </div>
  );
}
