import { describe, expect, it } from "vitest";

import { makeTrain } from "@/test/trains";

import { categoryGroup } from "./categories";
import { DELAYED_AT_SECONDS, trainToFeature, trainsToFeatureCollection } from "./features";

describe("categoryGroup", () => {
  it.each([
    ["ICE", "ice"],
    ["IC", "ic"],
    ["EC", "ic"],
    ["ECE", "ic"],
    ["RJ", "rj"],
    ["EN", "en"],
    ["ice", "ice"],
  ])("puts %s in %s", (category, group) => {
    expect(categoryGroup(category)).toBe(group);
  });

  it("keeps unknown categories as other rather than dropping them", () => {
    expect(categoryGroup("RE")).toBe("other");
  });
});

describe("trainToFeature", () => {
  it("places the train at [lon, lat]", () => {
    const feature = trainToFeature(makeTrain({ lat: 51.2, lon: 11.9 }));
    expect(feature.geometry.coordinates).toEqual([11.9, 51.2]);
  });

  it("styles a scheduled train with no delay plainly", () => {
    const { properties } = trainToFeature(makeTrain());
    expect(properties).toMatchObject({ realtime: false, delayed: false, delay_label: "" });
  });

  it("marks realtime-backed trains", () => {
    expect(trainToFeature(makeTrain({ position_source: "realtime" })).properties.realtime).toBe(
      true,
    );
  });

  it("falls back to an undirected icon without a bearing", () => {
    const { properties } = trainToFeature(makeTrain({ bearing: null }));
    expect(properties).toMatchObject({ has_bearing: false, bearing: 0 });
  });

  it("keeps the bearing when there is one", () => {
    expect(trainToFeature(makeTrain({ bearing: 231.5 })).properties).toMatchObject({
      has_bearing: true,
      bearing: 231.5,
    });
  });

  it("counts a train as delayed from the threshold, not before", () => {
    const late = (seconds: number) =>
      trainToFeature(makeTrain({ position_source: "realtime", delay_seconds: seconds })).properties;

    expect(late(DELAYED_AT_SECONDS - 1)).toMatchObject({ delayed: false, delay_label: "" });
    expect(late(DELAYED_AT_SECONDS)).toMatchObject({ delayed: true, delay_label: "+6′" });
  });

  it("draws ICE above other categories", () => {
    const ice = trainToFeature(makeTrain({ category: "ICE" })).properties.sort_key;
    const ic = trainToFeature(makeTrain({ category: "IC" })).properties.sort_key;
    expect(ice).toBeGreaterThan(ic);
  });
});

describe("trainsToFeatureCollection", () => {
  it("is empty, not missing, when nothing runs", () => {
    expect(trainsToFeatureCollection([])).toEqual({ type: "FeatureCollection", features: [] });
  });
});
