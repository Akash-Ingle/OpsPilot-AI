import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center text-center">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-neutral-500">
        404
      </p>
      <h1 className="mt-2 text-2xl font-semibold text-neutral-100">
        Incident not found
      </h1>
      <p className="mt-1.5 max-w-md text-sm text-neutral-400">
        The incident you’re looking for doesn’t exist, or has been deleted.
      </p>
      <Link
        href="/"
        className="mt-6 inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm font-medium text-neutral-200 transition-colors hover:border-white/20 hover:bg-white/10"
      >
        Back to incidents
      </Link>
    </div>
  );
}
