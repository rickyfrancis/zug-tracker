import type { DependencyHealth, DependencyStatus, HealthResult } from "@/lib/api";

const STATUS_STYLES: Record<DependencyStatus, { dot: string; label: string }> = {
  ok: { dot: "bg-ok", label: "text-ok" },
  error: { dot: "bg-error", label: "text-error" },
  unknown: { dot: "bg-warn", label: "text-warn" },
};

const DEPENDENCY_LABELS: Record<string, string> = {
  postgres: "PostgreSQL + PostGIS",
  redis: "Redis",
  worker: "Worker",
};

function DependencyRow({ dependency }: { dependency: DependencyHealth }) {
  const styles = STATUS_STYLES[dependency.status];

  return (
    <li className="flex items-center justify-between gap-4 px-4 py-3">
      <div className="flex items-center gap-3 min-w-0">
        <span className={`h-2 w-2 shrink-0 rounded-full ${styles.dot}`} />
        <span className="truncate">
          {DEPENDENCY_LABELS[dependency.name] ?? dependency.name}
        </span>
      </div>
      <div className="flex items-center gap-3 shrink-0 font-mono text-xs">
        {dependency.latency_ms != null && (
          <span className="text-muted">{dependency.latency_ms} ms</span>
        )}
        <span className={`uppercase ${styles.label}`}>{dependency.status}</span>
      </div>
    </li>
  );
}

export function StatusPanel({ result }: { result: HealthResult }) {
  if (!result.ok) {
    return (
      <section className="rounded-lg border border-error/40 bg-surface p-4 text-sm">
        <h2 className="font-mono uppercase tracking-widest text-error">API unreachable</h2>
        <p className="mt-2 text-muted">
          {result.error}. Is the stack running? Try <code>make dev</code>.
        </p>
      </section>
    );
  }

  const { health } = result;
  const degraded = health.status !== "ok";

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="flex items-center justify-between border-b border-border bg-surface-raised px-4 py-3">
        <h2 className="font-mono text-xs uppercase tracking-widest text-muted">
          Stack status
        </h2>
        <span
          className={`font-mono text-xs uppercase tracking-widest ${
            degraded ? "text-error" : "text-ok"
          }`}
        >
          {health.status}
        </span>
      </header>

      <ul className="divide-y divide-border text-sm">
        {health.dependencies.map((dependency) => (
          <DependencyRow key={dependency.name} dependency={dependency} />
        ))}
      </ul>

      <footer className="flex items-center justify-between border-t border-border px-4 py-2 font-mono text-[11px] text-muted">
        <span>env: {health.environment}</span>
        <time dateTime={health.checked_at}>
          checked {new Date(health.checked_at).toLocaleTimeString("de-DE")}
        </time>
      </footer>
    </section>
  );
}
