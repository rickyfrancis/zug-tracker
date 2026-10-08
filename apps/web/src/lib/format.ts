const BERLIN_TIME = new Intl.DateTimeFormat("de-DE", {
  timeZone: "Europe/Berlin",
  hour: "2-digit",
  minute: "2-digit",
});

/** `14:32`, in the timetable's time zone whatever the viewer's. */
export function formatBerlinTime(iso: string): string {
  return BERLIN_TIME.format(new Date(iso));
}

/** `ICE 10 → München Hbf`: the feed has no train numbers. */
export function trainTitle(train: { label: string; destination: string }): string {
  return `${train.label} → ${train.destination}`;
}
