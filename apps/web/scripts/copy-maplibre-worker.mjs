// Copies MapLibre's web worker into public/, where the map loads it from.
//
// maplibre-gl 6 locates its worker relative to its own module URL, which a
// bundler rewrites into a chunk URL, so the worker would 404. The worker file
// is self-contained, so serving it as a static file is enough; the controller
// points `setWorkerUrl` at it. Runs before `next dev` and `next build`.

import { copyFileSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const source = require.resolve("maplibre-gl/dist/maplibre-gl-worker.mjs");
const target = join(dirname(fileURLToPath(import.meta.url)), "../public/vendor/maplibre-gl-worker.mjs");

function unchanged() {
  try {
    return readFileSync(source).equals(readFileSync(target));
  } catch {
    return false;
  }
}

// The dev container writes this file as root through the bind mount, so a host
// build must not try to overwrite an identical copy it does not own.
if (!unchanged()) {
  mkdirSync(dirname(target), { recursive: true });
  rmSync(target, { force: true });
  copyFileSync(source, target);
}
