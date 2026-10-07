import { describe, expect, it } from "vitest";

import { roundZoom, viewportBbox } from "./bbox";

const parse = (bbox: string) => bbox.split(",").map(Number);

describe("viewportBbox", () => {
  it("pads each side by a fraction of the viewport", () => {
    expect(viewportBbox({ west: 10, south: 50, east: 12, north: 52 }, 0.25)).toBe(
      "9.5,49.5,12.5,52.5",
    );
  });

  it("is unpadded when asked", () => {
    expect(viewportBbox({ west: 10, south: 50, east: 12, north: 52 }, 0)).toBe("10,50,12,52");
  });

  it("rounds outwards to three decimals", () => {
    expect(viewportBbox({ west: 5.87654, south: 47.27111, east: 15.04001, north: 55.0612 }, 0)).toBe(
      "5.876,47.271,15.041,55.062",
    );
  });

  it("clamps to the ranges the API accepts", () => {
    expect(viewportBbox({ west: -200, south: -95, east: 210, north: 89 }, 0.25)).toBe(
      "-180,-90,180,90",
    );
  });

  it("asks for every longitude when the view crosses the antimeridian", () => {
    const [west, , east] = parse(viewportBbox({ west: 170, south: 0, east: -170, north: 10 }));
    expect([west, east]).toEqual([-180, 180]);
  });

  it("always yields west <= east and south <= north", () => {
    for (const bounds of [
      { west: 179.9999, south: 89.9999, east: 179.99995, north: 89.99999 },
      { west: -180, south: -90, east: -180, north: -90 },
      { west: 5.87, south: 47.27, east: 15.04, north: 55.06 },
    ]) {
      const [west, south, east, north] = parse(viewportBbox(bounds));
      expect(west).toBeLessThanOrEqual(east);
      expect(south).toBeLessThanOrEqual(north);
    }
  });
});

describe("roundZoom", () => {
  it("rounds to one decimal within [0, 24]", () => {
    expect(roundZoom(5.4321)).toBe(5.4);
    expect(roundZoom(-1)).toBe(0);
    expect(roundZoom(30)).toBe(24);
  });
});
