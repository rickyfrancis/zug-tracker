/**
 * Train icons, drawn on a canvas at runtime: one arrow and one dot per
 * category group. No asset files, and the colours stay in `categories.ts`.
 *
 * The arrow points north; the layer rotates it by the train's bearing. The
 * dot is for a train without one.
 */

import type { Map as MapLibreMap } from "maplibre-gl";

import { GROUP_STYLES } from "@/lib/trains/categories";

import { COLORS, ICON_GROUPS, iconId } from "./style";

/** CSS pixels at `icon-size: 1`. */
const ICON_SIZE = 20;
const PIXEL_RATIO = 2;

type Shape = "arrow" | "dot";

export function addTrainIcons(map: MapLibreMap): void {
  for (const group of ICON_GROUPS) {
    for (const shape of ["arrow", "dot"] as const) {
      const id = iconId(group, shape);
      if (!map.hasImage(id)) {
        map.addImage(id, drawIcon(shape, GROUP_STYLES[group].color), {
          pixelRatio: PIXEL_RATIO,
        });
      }
    }
  }
}

function drawIcon(shape: Shape, color: string): ImageData {
  const size = ICON_SIZE * PIXEL_RATIO;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  if (context === null) {
    throw new Error("2D canvas unavailable");
  }

  context.scale(size, size);
  context.beginPath();
  if (shape === "arrow") {
    context.moveTo(0.5, 0.1);
    context.lineTo(0.82, 0.86);
    context.lineTo(0.5, 0.68);
    context.lineTo(0.18, 0.86);
    context.closePath();
  } else {
    context.arc(0.5, 0.5, 0.26, 0, Math.PI * 2);
  }
  context.fillStyle = color;
  context.fill();
  // A dark outline keeps light icons legible over light basemap features.
  context.lineJoin = "round";
  context.lineWidth = 0.07;
  context.strokeStyle = COLORS.background;
  context.stroke();

  return context.getImageData(0, 0, size, size);
}
