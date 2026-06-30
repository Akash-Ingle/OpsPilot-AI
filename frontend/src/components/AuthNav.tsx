"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getMe, logout, PUBLIC_BACKEND_URL } from "@/lib/api";
import type { User } from "@/lib/types";

const DOCS_URL = PUBLIC_BACKEND_URL.replace(/\/api\/v1$/, "") + "/docs";

export function AuthNav() {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    // Re-check whenever the route changes (e.g. after login/logout navigation).
  }, [pathname]);

  async function onLogout() {
    setLoggingOut(true);
    try {
      await logout();
    } catch {
      /* ignore */
    }
    setUser(null);
    router.push("/login");
    router.refresh();
  }

  return (
    <nav className="flex items-center gap-1 text-sm text-neutral-400">
      <Link
        href="/"
        className="rounded-md px-3 py-1.5 font-medium text-neutral-200 transition-colors hover:bg-white/5"
      >
        Incidents
      </Link>
      {user && (
        <Link
          href="/connect"
          className="rounded-md px-3 py-1.5 font-medium text-neutral-200 transition-colors hover:bg-white/5"
        >
          Connect your app
        </Link>
      )}
      <a
        href={DOCS_URL}
        target="_blank"
        rel="noreferrer"
        className="rounded-md px-3 py-1.5 font-medium transition-colors hover:bg-white/5 hover:text-neutral-200"
      >
        API docs ↗
      </a>

      {ready &&
        (user ? (
          <div className="ml-1 flex items-center gap-2 border-l border-white/10 pl-2">
            <span className="hidden max-w-[160px] truncate text-xs text-neutral-400 sm:inline">
              {user.email}
            </span>
            <button
              onClick={onLogout}
              disabled={loggingOut}
              className="rounded-md border border-white/10 px-3 py-1.5 text-xs font-medium text-neutral-300 transition-colors hover:bg-white/5 disabled:opacity-50"
            >
              {loggingOut ? "…" : "Log out"}
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="ml-1 rounded-md bg-gradient-to-br from-sky-500 to-indigo-500 px-3.5 py-1.5 text-xs font-semibold text-white shadow-lg shadow-indigo-500/20"
          >
            Log in
          </Link>
        ))}
    </nav>
  );
}
