import { describe, expect, it } from "vitest";

import { dataAgeSeconds, liveness, STALE_AFTER_SECONDS } from "./liveness";

const NOW = 1_800_000_000_000;

describe("liveness", () => {
  it("is connecting before anything has arrived", () => {
    expect(liveness(null, NOW)).toBe("connecting");
  });

  it("is live for a fresh snapshot that just arrived", () => {
    expect(liveness({ snapshotAgeSeconds: 0, receivedAt: NOW }, NOW)).toBe("live");
  });

  it("goes stale when the server's snapshot is old (a stopped worker)", () => {
    const received = { snapshotAgeSeconds: STALE_AFTER_SECONDS, receivedAt: NOW };
    expect(liveness(received, NOW)).toBe("stale");
  });

  it("goes stale when nothing has arrived for a while (an unreachable API)", () => {
    const received = { snapshotAgeSeconds: 0, receivedAt: NOW - STALE_AFTER_SECONDS * 1000 };
    expect(liveness(received, NOW)).toBe("stale");
  });

  it("adds the two ages together", () => {
    const received = { snapshotAgeSeconds: 70, receivedAt: NOW - 50_000 };
    expect(dataAgeSeconds(received, NOW)).toBe(120);
    expect(liveness(received, NOW)).toBe("stale");
    expect(liveness(received, NOW - 1)).toBe("live");
  });

  it("does not let a receipt from the future make data younger", () => {
    expect(dataAgeSeconds({ snapshotAgeSeconds: 5, receivedAt: NOW + 10_000 }, NOW)).toBe(5);
  });
});
