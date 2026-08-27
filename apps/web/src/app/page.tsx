import { StatusPanel } from "@/components/status-panel";
import { fetchHealth } from "@/lib/api";

// The stack status is request-time information; never prerender it at build
// time, when the API is not running.
export const dynamic = "force-dynamic";

export default async function Home() {
  const result = await fetchHealth();

  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <div className="w-full max-w-xl space-y-6">
        <header className="space-y-2">
          <div className="flex items-center gap-3">
            <span className="h-2 w-2 rounded-full bg-accent animate-live" />
            <h1 className="font-mono text-xl tracking-[0.2em] uppercase">zug-tracker</h1>
          </div>
          <p className="text-sm text-muted">
            Live map of German long-distance trains. The map lands in Phase 5 - for now
            this page reports whether the stack is wired up correctly.
          </p>
        </header>

        <StatusPanel result={result} />
      </div>
    </main>
  );
}
