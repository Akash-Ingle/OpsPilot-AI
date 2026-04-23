export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="h-4 w-24 animate-pulse rounded bg-white/[0.06]" />
        <div className="h-8 w-48 animate-pulse rounded bg-white/[0.06]" />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-[82px] animate-pulse rounded-xl bg-white/[0.04]"
          />
        ))}
      </div>
      <div className="space-y-2.5">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-[96px] animate-pulse rounded-xl bg-white/[0.04]"
          />
        ))}
      </div>
    </div>
  );
}
