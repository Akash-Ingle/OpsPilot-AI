/**
 * Server-only auth helpers. Importing `next/headers` makes these usable only in
 * server components / route handlers (never in "use client" files).
 */

import { cookies } from "next/headers";

import { getMe } from "./api";
import type { User } from "./types";

/** The full Cookie header to forward to the backend during SSR (or undefined). */
export function sessionCookie(): string | undefined {
  const jar = cookies().toString();
  return jar || undefined;
}

/** Resolve the logged-in user from the session cookie, or null if anonymous. */
export async function currentUser(): Promise<User | null> {
  const cookie = sessionCookie();
  if (!cookie) return null;
  try {
    return await getMe(cookie);
  } catch {
    return null;
  }
}
