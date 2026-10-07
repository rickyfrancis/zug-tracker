/**
 * The viewport as `GET /trains?bbox=` takes it.
 *
 * The API rejects longitudes outside [-180, 180] and latitudes outside
 * [-90, 90], and a box that crosses the antimeridian. MapLibre's bounds can do
 * all three at low zoom, so they are clamped here rather than trusted.
 */

export interface Bounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

/**
 * Extra margin on each side, as a fraction of the viewport. The list is only
 * refetched once a pan ends, so this keeps the edges populated while it is
 * under way.
 */
export const BBOX_PADDING = 0.25;

const DECIMALS = 1000;

/** `west,south,east,north`, padded, clamped and rounded outwards. */
export function viewportBbox(bounds: Bounds, padding: number = BBOX_PADDING): string {
  if (bounds.west > bounds.east) {
    // Crosses the antimeridian: the API cannot express that, so ask for every
    // longitude. Never happens over Europe with world copies turned off.
    return formatBbox({ ...pad(bounds, padding, false), west: -180, east: 180 });
  }
  return formatBbox(pad(bounds, padding, true));
}

function pad(bounds: Bounds, padding: number, padLongitude: boolean): Bounds {
  const dx = padLongitude ? (bounds.east - bounds.west) * padding : 0;
  const dy = (bounds.north - bounds.south) * padding;
  return {
    west: clamp(bounds.west - dx, -180, 180),
    south: clamp(bounds.south - dy, -90, 90),
    east: clamp(bounds.east + dx, -180, 180),
    north: clamp(bounds.north + dy, -90, 90),
  };
}

function formatBbox(bounds: Bounds): string {
  // Outwards, so rounding never shrinks the box.
  const down = (value: number) => Math.floor(value * DECIMALS) / DECIMALS;
  const up = (value: number) => Math.ceil(value * DECIMALS) / DECIMALS;
  return [
    Math.max(down(bounds.west), -180),
    Math.max(down(bounds.south), -90),
    Math.min(up(bounds.east), 180),
    Math.min(up(bounds.north), 90),
  ].join(",");
}

/** Zoom to one decimal, within the [0, 24] the API accepts. */
export function roundZoom(zoom: number): number {
  return clamp(Math.round(zoom * 10) / 10, 0, 24);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}
