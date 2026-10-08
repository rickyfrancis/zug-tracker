import { formatBerlinTime } from "@/lib/format";
import type { Liveness } from "@/lib/trains/liveness";

import type { TrainMapState } from "./use-train-map";

const LIVENESS_STYLES: Record<Liveness, { label: string; dot: string; text: string }> = {
  connecting: { label: "Connecting", dot: "bg-muted", text: "text-muted" },
  live: { label: "Live", dot: "bg-ok animate-live", text: "text-ok" },
  stale: { label: "Stale", dot: "bg-warn", text: "text-warn" },
};

type MapHudProps = Pick<TrainMapState, "liveness" | "snapshot" | "failing">;

export function MapHud({ liveness, snapshot, failing }: MapHudProps) {
  const styles = LIVENESS_STYLES[liveness];

  return (
    <section className="pointer-events-auto rounded-lg border border-border bg-surface/90 px-4 py-3 shadow-lg backdrop-blur">
      <div className="flex items-center gap-4">
        <h1 className="font-mono text-sm tracking-[0.2em] uppercase">zug-tracker</h1>
        <span
          className={`flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest ${styles.text}`}
          title="Whether the positions shown are current"
        >
          <span className={`h-1.5 w-1.5 rounded-full ${styles.dot}`} />
          {styles.label}
        </span>
      </div>
      <p className="mt-1 font-mono text-xs text-muted">
        {snapshot === null ? (
          "waiting for trains…"
        ) : (
          <>
            <span className="text-foreground">{snapshot.trainCount}</span>{" "}
            {snapshot.trainCount === 1 ? "train" : "trains"} in view · updated{" "}
            <time dateTime={snapshot.timestamp}>{formatBerlinTime(snapshot.timestamp)}</time>
          </>
        )}
        {failing && <span className="text-error"> · retrying…</span>}
      </p>
    </section>
  );
}
