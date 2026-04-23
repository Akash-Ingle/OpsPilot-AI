export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="h-3 w-28 animate-pulse rounded bg-white/[0.06]" />
      <div className="space-y-3">
        <div className="flex gap-2">
          <div className="h-5 w-16 animate-pulse rounded-full bg-white/[0.06]" />
          <div className="h-5 w-16 animate-pulse rounded-full bg-white/[0.06]" />
        </div>
        <div className="h-7 w-2/3 animate-pulse rounded bg-white/[0.06]" />
        <div className="h-3 w-1/3 animate-pulse rounded bg-white/[0.06]" />
      </div>
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <div className="h-64 animate-pulse rounded-xl bg-white/[0.04]" />
          <div className="h-48 animate-pulse rounded-xl bg-white/[0.04]" />
          <div className="h-48 animate-pulse rounded-xl bg-white/[0.04]" />
        </div>
        <div className="space-y-5">
          <div className="h-56 animate-pulse rounded-xl bg-white/[0.04]" />
          <div className="h-48 animate-pulse rounded-xl bg-white/[0.04]" />
        </div>
      </div>
    </div>
  );
}
