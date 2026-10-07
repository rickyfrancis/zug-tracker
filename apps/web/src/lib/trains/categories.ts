/**
 * How train categories are told apart on the map.
 *
 * Categories come from the feed (`ICE`, `IC`, `EC`, `ECE`, `RJ`, `EN` today),
 * so anything unlisted - regional trains, once they exist - falls into
 * `other` instead of disappearing. The map style and the legend both read the
 * colours from here.
 */

export type CategoryGroup = "ice" | "ic" | "rj" | "en" | "other";

const GROUP_BY_CATEGORY: Record<string, CategoryGroup> = {
  ICE: "ice",
  IC: "ic",
  EC: "ic",
  ECE: "ic",
  RJ: "rj",
  EN: "en",
};

export function categoryGroup(category: string): CategoryGroup {
  return GROUP_BY_CATEGORY[category.toUpperCase()] ?? "other";
}

export interface GroupStyle {
  label: string;
  color: string;
  /** Higher draws on top where trains overlap. */
  order: number;
}

export const GROUP_STYLES: Record<CategoryGroup, GroupStyle> = {
  ice: { label: "ICE", color: "#e6edf3", order: 4 },
  ic: { label: "IC / EC / ECE", color: "#38bdf8", order: 3 },
  rj: { label: "Railjet", color: "#f87171", order: 2 },
  en: { label: "EuroNight", color: "#a78bfa", order: 1 },
  other: { label: "Other", color: "#7d8896", order: 0 },
};

/** Legend order: most prominent first. */
export const GROUPS: readonly CategoryGroup[] = ["ice", "ic", "rj", "en"];
