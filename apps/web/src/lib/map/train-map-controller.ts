/**
 * The MapLibre map, outside React.
 *
 * React creates one controller per mount and destroys it on unmount, which
 * is all StrictMode's double mount and Fast Refresh need. Trains reach the map
 * through `setTrains`, never through React state: a poll replaces one GeoJSON
 * source and re-renders nothing.
 *
 * Calls made before the style has loaded are kept and applied on load, so the
 * caller never has to wait for it.
 */

import {
  type GeoJSONSource,
  getVersion,
  Map as MapLibreMap,
  type MapMouseEvent,
  NavigationControl,
  setWorkerUrl,
} from "maplibre-gl";
import type { FeatureCollection, Geometry } from "geojson";

import type { TrainDetail, TrainQuery } from "@/lib/api";
import { roundZoom, viewportBbox } from "@/lib/trains/bbox";
import type { TrainFeatureCollection, TrainProperties } from "@/lib/trains/features";

import { addTrainIcons } from "./icons";
import {
  BASEMAP_STYLE_URL,
  GERMANY_BOUNDS,
  LAYER_TRAIN_SELECTED,
  LAYER_TRAINS,
  LAYER_TRAINS_REALTIME,
  MAX_ZOOM,
  MIN_ZOOM,
  ringOpacity,
  routeLayers,
  selectedFilter,
  SOURCE_ROUTE,
  SOURCE_TRAINS,
  trainLayers,
  trainOpacity,
} from "./style";

/** Served from public/ by scripts/copy-maplibre-worker.mjs. */
const WORKER_URL = "/vendor/maplibre-gl-worker.mjs";

/** How far from a train a click or tap still selects it, in CSS pixels. */
const HIT_TOLERANCE = 8;

const FIT_PADDING = 24;

/** Enough of a train to select it and to say which one it is. */
export interface SelectedTrain {
  tripId: string;
  serviceDate: string;
  label: string;
  destination: string;
}

export interface TrainMapCallbacks {
  /** After the map settles on a new view; also once on load. */
  onViewportChange: (query: TrainQuery) => void;
  /** A train was clicked, or empty map (`null`). */
  onSelect: (train: SelectedTrain | null) => void;
}

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

export class TrainMapController {
  private readonly map: MapLibreMap;
  private loaded = false;

  private trains: TrainFeatureCollection | null = null;
  private route: FeatureCollection | null = null;
  private selectedTripId: string | null = null;
  private stale = false;

  constructor(
    container: HTMLElement,
    private callbacks: TrainMapCallbacks | null,
  ) {
    setWorkerUrl(`${WORKER_URL}?v=${getVersion()}`);

    this.map = new MapLibreMap({
      container,
      style: BASEMAP_STYLE_URL,
      bounds: GERMANY_BOUNDS,
      fitBoundsOptions: { padding: FIT_PADDING },
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      // One world: the API's bbox cannot cross the antimeridian.
      renderWorldCopies: false,
      // A north-up map keeps bearings readable; rotation adds nothing here.
      dragRotate: false,
      touchPitch: false,
      pitchWithRotate: false,
      attributionControl: { compact: true },
    });
    this.map.touchZoomRotate.disableRotation();
    this.map.keyboard.disableRotation();
    this.map.addControl(new NavigationControl({ showCompass: false }), "bottom-right");

    this.map.on("load", this.handleLoad);
    this.map.on("moveend", this.handleMoveEnd);
    this.map.on("click", this.handleClick);
    this.map.on("mouseenter", LAYER_TRAINS, this.showPointer);
    this.map.on("mouseleave", LAYER_TRAINS, this.hidePointer);
  }

  setTrains(trains: TrainFeatureCollection): void {
    this.trains = trains;
    if (this.loaded) {
      this.map.getSource<GeoJSONSource>(SOURCE_TRAINS)?.setData(trains);
    }
  }

  setSelected(tripId: string | null): void {
    this.selectedTripId = tripId;
    if (this.loaded) {
      this.map.setFilter(LAYER_TRAIN_SELECTED, selectedFilter(tripId));
    }
  }

  /** Draws a train's route and stops; `null` clears it. */
  setRoute(detail: TrainDetail | null): void {
    this.route = detail === null ? null : routeFeatures(detail);
    if (this.loaded) {
      this.map.getSource<GeoJSONSource>(SOURCE_ROUTE)?.setData(this.route ?? EMPTY);
    }
  }

  setStale(stale: boolean): void {
    this.stale = stale;
    if (this.loaded) {
      this.map.setPaintProperty(LAYER_TRAINS, "icon-opacity", trainOpacity(stale));
      this.map.setPaintProperty(LAYER_TRAINS_REALTIME, "circle-stroke-opacity", ringOpacity(stale));
    }
  }

  resetView(): void {
    this.map.fitBounds(GERMANY_BOUNDS, { padding: FIT_PADDING });
  }

  destroy(): void {
    this.callbacks = null;
    this.map.remove();
  }

  private handleLoad = (): void => {
    addTrainIcons(this.map);

    this.map.addSource(SOURCE_ROUTE, { type: "geojson", data: this.route ?? EMPTY });
    this.map.addSource(SOURCE_TRAINS, { type: "geojson", data: this.trains ?? EMPTY });

    // The route goes under the basemap's labels; trains go on top of everything.
    const firstLabel = this.map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;
    for (const layer of routeLayers()) {
      this.map.addLayer(layer, firstLabel);
    }
    for (const layer of trainLayers(this.stale)) {
      this.map.addLayer(layer);
    }

    this.loaded = true;
    this.setSelected(this.selectedTripId);
    this.emitViewport();
  };

  private handleMoveEnd = (): void => {
    // The initial fit can settle before the style loads; load reports it.
    if (this.loaded) {
      this.emitViewport();
    }
  };

  private emitViewport(): void {
    const bounds = this.map.getBounds();
    this.callbacks?.onViewportChange({
      bbox: viewportBbox({
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth(),
      }),
      zoom: roundZoom(this.map.getZoom()),
    });
  }

  private handleClick = (event: MapMouseEvent): void => {
    if (!this.loaded) {
      return;
    }
    const { x, y } = event.point;
    const [hit] = this.map.queryRenderedFeatures(
      [
        [x - HIT_TOLERANCE, y - HIT_TOLERANCE],
        [x + HIT_TOLERANCE, y + HIT_TOLERANCE],
      ],
      { layers: [LAYER_TRAINS] },
    );
    const properties = hit?.properties as TrainProperties | undefined;
    this.callbacks?.onSelect(
      properties === undefined
        ? null
        : {
            tripId: properties.trip_id,
            serviceDate: properties.service_date,
            label: properties.label,
            destination: properties.destination,
          },
    );
  };

  private showPointer = (): void => {
    this.map.getCanvas().style.cursor = "pointer";
  };

  private hidePointer = (): void => {
    this.map.getCanvas().style.cursor = "";
  };
}

/** The route line plus a point per stop, for the `selected-route` source. */
function routeFeatures(detail: TrainDetail): FeatureCollection<Geometry> {
  return {
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: detail.route, properties: {} },
      ...detail.stops.map((stop) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [stop.station.lon, stop.station.lat] },
        properties: { name: stop.station.name },
      })),
    ],
  };
}
