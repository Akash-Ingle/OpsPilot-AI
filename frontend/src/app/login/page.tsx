import { Suspense } from "react";

import { LoginForm } from "./LoginForm";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <div className="mx-auto mt-10 max-w-md">
      <Suspense fallback={<div className="card p-7 text-sm text-neutral-400">Loading…</div>}>
        <LoginForm />
      </Suspense>
    </div>
  );
}
