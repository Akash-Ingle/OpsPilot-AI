import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "OpsPilot-AI",
  description:
    "Autonomous DevOps agent dashboard — incidents, AI reasoning, and tool telemetry.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen font-sans antialiased">
        <div className="flex min-h-screen flex-col">
          <TopBar />
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
            {children}
          </main>
          <Footer />
        </div>
      </body>
    </html>
  );
}

function TopBar() {
  return (
    <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-[var(--bg-base)]/85 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="group flex items-center gap-2.5 text-sm font-semibold tracking-tight text-neutral-100"
        >
          <span className="grid h-7 w-7 place-items-center rounded-md bg-gradient-to-br from-sky-500 to-indigo-500 shadow-lg shadow-indigo-500/20 transition-transform group-hover:scale-105">
            <svg
              viewBox="0 0 24 24"
              className="h-4 w-4 text-white"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M12 3l8 4.5v9L12 21 4 16.5v-9L12 3z" />
              <path d="M12 12l8-4.5" />
              <path d="M12 12v9" />
              <path d="M12 12L4 7.5" />
            </svg>
          </span>
          <span>OpsPilot-AI</span>
          <span className="rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-neutral-400">
            Agent
          </span>
        </Link>

        <nav className="flex items-center gap-1 text-sm text-neutral-400">
          <Link
            href="/"
            className="rounded-md px-3 py-1.5 font-medium text-neutral-200 transition-colors hover:bg-white/5"
          >
            Incidents
          </Link>
          <a
            href={
              (
                process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
                "http://localhost:8000/api/v1"
              ).replace(/\/api\/v1$/, "") + "/docs"
            }
            target="_blank"
            rel="noreferrer"
            className="rounded-md px-3 py-1.5 font-medium transition-colors hover:bg-white/5 hover:text-neutral-200"
          >
            API docs ↗
          </a>
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="border-t border-white/[0.06] py-6 text-center text-xs text-neutral-500">
      OpsPilot-AI · autonomous DevOps reasoning
    </footer>
  );
}
