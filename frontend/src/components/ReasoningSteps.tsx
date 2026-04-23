interface Props {
  steps: string[];
}

export function ReasoningSteps({ steps }: Props) {
  if (!steps || steps.length === 0) {
    return (
      <p className="text-sm italic text-neutral-500">
        The model did not emit explicit reasoning steps for this run.
      </p>
    );
  }

  return (
    <ol className="relative space-y-3">
      {steps.map((step, idx) => (
        <li key={idx} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full border border-white/10 bg-white/[0.04] font-mono text-[11px] font-semibold text-neutral-300">
              {idx + 1}
            </span>
            {idx < steps.length - 1 && (
              <span
                className="mt-1 w-px flex-1 bg-gradient-to-b from-white/10 to-transparent"
                aria-hidden
              />
            )}
          </div>
          <p className="pb-2 pt-0.5 text-sm leading-relaxed text-neutral-200">
            {step}
          </p>
        </li>
      ))}
    </ol>
  );
}
