import type { ReactNode } from "react";

interface Props {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}

/** A titled card section — used throughout the incident detail page. */
export function Section({ title, description, icon, action, children }: Props) {
  return (
    <section className="card">
      <header className="flex items-start justify-between gap-3 border-b border-white/[0.06] px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          {icon && (
            <span className="grid h-7 w-7 place-items-center rounded-md bg-white/[0.04] text-neutral-300">
              {icon}
            </span>
          )}
          <div>
            <h2 className="text-sm font-semibold text-neutral-100">{title}</h2>
            {description && (
              <p className="mt-0.5 text-xs text-neutral-500">{description}</p>
            )}
          </div>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </header>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}
