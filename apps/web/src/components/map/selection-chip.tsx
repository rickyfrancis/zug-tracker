import { trainTitle } from "@/lib/format";
import type { SelectedTrain } from "@/lib/map/train-map-controller";

interface SelectionChipProps {
  selection: SelectedTrain | null;
  notice: string | null;
  onClose: () => void;
}

/** Which train is selected. Phase 10's detail panel replaces this. */
export function SelectionChip({ selection, notice, onClose }: SelectionChipProps) {
  if (selection === null && notice === null) {
    return null;
  }

  return (
    <div className="pointer-events-auto flex flex-col items-start gap-2 sm:items-end">
      {selection !== null && (
        <div className="flex items-center gap-3 rounded-lg border border-accent/40 bg-surface/90 py-2 pl-4 pr-2 shadow-lg backdrop-blur">
          <span className="text-sm">{trainTitle(selection)}</span>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 py-0.5 font-mono text-xs text-muted hover:bg-surface-raised hover:text-foreground"
            aria-label="Clear selection"
            title="Clear selection (Esc)"
          >
            ✕
          </button>
        </div>
      )}
      {notice !== null && (
        <p className="rounded-lg border border-warn/40 bg-surface/90 px-4 py-2 text-xs text-warn shadow-lg backdrop-blur">
          {notice}
        </p>
      )}
    </div>
  );
}
