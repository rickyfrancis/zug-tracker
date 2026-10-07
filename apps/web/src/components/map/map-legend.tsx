import Link from "next/link";

import { COLORS } from "@/lib/map/style";
import { GROUP_STYLES, GROUPS } from "@/lib/trains/categories";

function Arrow({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 shrink-0" aria-hidden>
      <polygon points="10,2 16.4,17.2 10,13.6 3.6,17.2" fill={color} />
    </svg>
  );
}

function Ring({ color }: { color: string | null }) {
  return (
    <span
      className="h-3.5 w-3.5 shrink-0 rounded-full border-[1.5px]"
      style={{ borderColor: color ?? "transparent" }}
      aria-hidden
    />
  );
}

export function MapLegend() {
  return (
    <section className="pointer-events-auto absolute bottom-3 left-3 hidden w-56 rounded-lg border border-border bg-surface/90 px-4 py-3 text-xs shadow-lg backdrop-blur sm:block">
      <ul className="space-y-1.5">
        {GROUPS.map((group) => (
          <li key={group} className="flex items-center gap-2">
            <Arrow color={GROUP_STYLES[group].color} />
            {GROUP_STYLES[group].label}
          </li>
        ))}
      </ul>
      <ul className="mt-3 space-y-1.5 border-t border-border pt-3 text-muted">
        <li className="flex items-center gap-2">
          <Ring color={COLORS.ok} /> Realtime-backed
        </li>
        <li className="flex items-center gap-2">
          <Ring color={COLORS.warn} /> Delayed 6+ min
        </li>
        <li className="flex items-center gap-2">
          <Ring color={null} /> Estimated from the timetable
        </li>
      </ul>
      <p className="mt-3 border-t border-border pt-3 text-[11px] leading-snug text-muted">
        Long-distance trains only. Few of them run overnight.
      </p>
      <Link
        href="/status"
        className="mt-2 inline-block font-mono text-[11px] uppercase tracking-widest text-muted hover:text-foreground"
      >
        Stack status →
      </Link>
    </section>
  );
}
