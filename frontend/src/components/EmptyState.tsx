import type { ReactNode } from "react";

interface Props {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: Props) {
  return (
    <div className="card flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="grid h-10 w-10 place-items-center rounded-full bg-white/[0.05] text-neutral-400">
        {icon ?? (
          <svg
            viewBox="0 0 24 24"
            className="h-5 w-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M21 21l-4.35-4.35" />
            <circle cx="11" cy="11" r="7" />
          </svg>
        )}
      </div>
      <div>
        <h3 className="text-sm font-semibold text-neutral-100">{title}</h3>
        {description && (
          <p className="mt-1 max-w-md text-sm text-neutral-400">{description}</p>
        )}
      </div>
      {action && <div className="pt-2">{action}</div>}
    </div>
  );
}
