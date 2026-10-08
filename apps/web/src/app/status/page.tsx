import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";

import { StatusPanel } from "@/components/status-panel";
import { fetchHealth } from "@/lib/api";

export const metadata: Metadata = {
  title: "Stack status · zug-tracker",
};

export default async function StatusPage() {
  // The stack status is request-time information; never prerender it at build
  // time, when the API is not running.
  await connection();
  const result = await fetchHealth();

  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <div className="w-full max-w-xl space-y-6">
        <header className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="h-2 w-2 rounded-full bg-accent animate-live" />
              <h1 className="font-mono text-xl tracking-[0.2em] uppercase">zug-tracker</h1>
            </div>
            <Link
              href="/"
              className="font-mono text-xs uppercase tracking-widest text-muted hover:text-foreground"
            >
              ← map
            </Link>
          </div>
          <p className="text-sm text-muted">
            Whether every service behind the map is up. A green page means the stack is
            wired up correctly.
          </p>
        </header>

        <StatusPanel result={result} />
      </div>
    </main>
  );
}
