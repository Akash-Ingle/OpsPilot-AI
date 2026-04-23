"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("OpsPilot UI error:", error);
  }, [error]);

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center text-center">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-red-400">
        Something went wrong
      </p>
      <h1 className="mt-2 text-2xl font-semibold text-neutral-100">
        Unexpected error
      </h1>
      <p className="mt-1.5 max-w-md text-sm text-neutral-400">
        {error.message || "The dashboard hit an unexpected error."}
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-6 inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm font-medium text-neutral-200 transition-colors hover:border-white/20 hover:bg-white/10"
      >
        Try again
      </button>
    </div>
  );
}
