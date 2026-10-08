import Link from "next/link";

interface EmptyStateProps {
  /** Trains running anywhere; `null` while unknown. */
  networkTotal: number | null;
  onShowGermany: () => void;
}

/**
 * No trains in view. That is usually just where the map is pointed, or the
 * night: long-distance traffic thins to a few dozen trains. If nothing runs
 * anywhere, the timetable is the likelier cause.
 */
export function EmptyState({ networkTotal, onShowGermany }: EmptyStateProps) {
  const nothingRuns = networkTotal === 0;

  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
      <section className="pointer-events-auto max-w-sm rounded-lg border border-border bg-surface/90 px-5 py-4 text-center shadow-lg backdrop-blur">
        <h2 className="font-mono text-xs uppercase tracking-widest text-muted">
          {nothingRuns ? "No trains running" : "No trains in this view"}
        </h2>
        <p className="mt-2 text-sm">
          {nothingRuns ? (
            <>
              Nothing is running on the long-distance network. If that seems wrong, the
              timetable may have expired: check the{" "}
              <Link href="/status" className="text-accent hover:underline">
                stack status
              </Link>
              .
            </>
          ) : networkTotal !== null ? (
            <>
              {networkTotal} {networkTotal === 1 ? "train is" : "trains are"} running elsewhere
              on the network.
            </>
          ) : (
            "Long-distance trains run elsewhere on the network."
          )}
        </p>
        {!nothingRuns && (
          <button
            type="button"
            onClick={onShowGermany}
            className="mt-3 rounded border border-border px-3 py-1 font-mono text-xs uppercase tracking-widest text-muted hover:border-accent hover:text-foreground"
          >
            Show Germany
          </button>
        )}
      </section>
    </div>
  );
}
