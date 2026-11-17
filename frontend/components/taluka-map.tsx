"use client";

/**
 * Where the cases are coming from, as a heat map.
 *
 * OpenStreetMap tiles through Leaflet, with leaflet.heat for the intensity
 * field. Every coordinate is a real Nominatim result cached in
 * lib/taluka-coords.json — nothing is placed by guesswork, and a taluka that
 * failed to geocode is named below the map rather than dropped silently.
 *
 * An honest caveat, stated on the page too: a heat map interpolates between
 * points, and these are 16 taluka centroids, not a continuous survey. The
 * warm areas show where the recorded cases cluster, not a measured density
 * at every spot in between. The markers on top carry the exact figures,
 * which is what an officer should act on.
 */
import { useEffect, useMemo } from "react";
import {
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import { HeatLayer } from "leaflet.heat";

import { useLang } from "@/components/lang";
import coords from "@/lib/taluka-coords.json";

import "leaflet/dist/leaflet.css";

export type MapRow = {
  taluka: string;
  value: number;
  recorded: number;
  open: number;
  overdue: number;
  breachRate: number | null;
};

type Coord = { lat: number; lon: number } | null;

const COORDS = coords.talukas as Record<string, Coord>;

/**
 * The heat layer.
 *
 * The gradient runs through the app's own palette rather than the plugin's
 * default blue-to-red: chartreuse where it is light, red where it is worst,
 * so the map says the same thing as every chip in the interface.
 */
function HeatField({
  points,
}: {
  points: [number, number, number][];
}) {
  const map = useMap();

  useEffect(() => {
    if (points.length === 0) return;

    // leaflet.heat 1.x is an ES module exporting a HeatLayer class. It does
    // NOT patch L.heatLayer the way the old 0.2 release did, which is why a
    // global-assignment approach silently renders nothing.
    const layer = new HeatLayer(points, {
      radius: 42,
      blur: 32,
      maxZoom: 11,
      minOpacity: 0.4,
      // The app's own palette, not the plugin's blue-to-red default, so the
      // map says the same thing as every chip in the interface.
      gradient: {
        0.0: "#dfff00",
        0.45: "#c9e600",
        0.7: "#e8a200",
        1.0: "#7a4a00",
      },
    });

    // The package ships types that do not declare HeatLayer as extending
    // L.Layer, although at runtime it does (`class extends e.Layer`). One
    // narrow cast beats loosening the whole file to any.
    const asLayer = layer as unknown as L.Layer;
    map.addLayer(asLayer);
    return () => {
      // In development React mounts effects twice, so the map may already be
      // tearing down by the time this runs.
      if (map.hasLayer(asLayer)) map.removeLayer(asLayer);
    };
  }, [map, points]);

  return null;
}

/** Frames the map on the talukas that actually have coordinates. */
function FitToMarkers({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    map.fitBounds(points, { padding: [36, 36], maxZoom: 10 });
  }, [map, points]);
  return null;
}

export default function TalukaMap({
  rows,
  measure,
}: {
  rows: MapRow[];
  measure: "volume" | "breach";
}) {
  const { t } = useLang();

  const placed = useMemo(
    () =>
      rows
        .map((row) => ({ row, coord: COORDS[row.taluka] }))
        .filter((entry): entry is { row: MapRow; coord: NonNullable<Coord> } =>
          Boolean(entry.coord),
        ),
    [rows],
  );

  const missing = rows.filter((row) => !COORDS[row.taluka]).map((r) => r.taluka);
  const max = Math.max(1, ...placed.map((p) => p.row.value));

  const points = placed.map(
    (p) => [p.coord.lat, p.coord.lon] as [number, number],
  );
  // Intensity is normalised, so the hottest taluka anchors the scale and the
  // map re-reads correctly when the measure changes.
  const heatPoints = placed.map(
    (p) =>
      [p.coord.lat, p.coord.lon, Math.max(0.15, p.row.value / max)] as [
        number,
        number,
        number,
      ],
  );

  return (
    <div>
      <div className="card overflow-hidden">
        <MapContainer
          center={[19.15, 77.5]}
          zoom={8}
          scrollWheelZoom={false}
          style={{ height: 440, width: "100%", background: "#efede7" }}
          aria-label={t("hot.map.title")}
        >
          <TileLayer
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            maxZoom={18}
          />
          <FitToMarkers points={points} />
          <HeatField points={heatPoints} />

          {/* Small markers sit on top of the field: the heat shows the
              pattern, these carry the exact numbers. */}
          {placed.map(({ row, coord }) => (
            <CircleMarker
              key={row.taluka}
              center={[coord.lat, coord.lon]}
              radius={7}
              pathOptions={{
                color: "#111010",
                weight: 2,
                fillColor: row.overdue > 0 ? "#111010" : "#faf9f6",
                fillOpacity: 1,
              }}
            >
              <Popup>
                <div className="font-sans">
                  <div className="text-[15px] font-700 mb-1.5">
                    {row.taluka}
                  </div>
                  <dl className="text-[13px] space-y-0.5">
                    <Row label={t("hot.recorded")} value={row.recorded} />
                    <Row label={t("hot.openNow")} value={row.open} />
                    <Row label={t("hot.overdue")} value={row.overdue} />
                    <Row
                      label={t("hot.pastSla")}
                      value={
                        row.breachRate !== null
                          ? `${Math.round(row.breachRate * 100)}%`
                          : "—"
                      }
                    />
                  </dl>
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>

      {/* A gradient legend: a heat map is unreadable without one. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 mt-3 text-[13px] text-ink-2">
        <span className="flex items-center gap-2">
          <span className="text-ink-3">
            {measure === "volume" ? t("hot.recorded") : t("hot.pastSla")}
          </span>
          <span
            className="inline-block h-3 w-28 rounded-chip border-2 border-ink"
            style={{
              background:
                "linear-gradient(90deg,#dfff00 0%,#c9e600 45%,#e8a200 70%,#7a4a00 100%)",
            }}
            aria-hidden
          />
          <span className="text-ink-3">{t("hot.map.scale")}</span>
        </span>
        <span className="flex items-center gap-2">
          <span
            className="inline-block w-3.5 h-3.5 rounded-chip border-2 border-ink bg-ink"
            aria-hidden
          />
          {t("hot.overdue")}
        </span>
      </div>

      <p className="text-[13px] text-ink-2 mt-2">{t("hot.map.caveat")}</p>

      {missing.length > 0 && (
        <p className="text-[13px] text-rose mt-2 font-600">
          {t("hot.map.missing")}: {missing.join(", ")}
        </p>
      )}

      <p className="text-[12px] text-ink-3 mt-2">
        {coords.licence} · {coords.note}
      </p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between gap-4">
      <dt>{label}</dt>
      <dd className="font-600 tabular">{value}</dd>
    </div>
  );
}
