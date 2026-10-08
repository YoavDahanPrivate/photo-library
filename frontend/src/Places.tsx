import { useEffect, useState } from "react";
import {
  MapPin,
  Search,
  X,
  Plus,
  Minus,
  SlidersHorizontal,
  ArrowRight,
  Compass,
} from "lucide-react";

export type GeoFilter = Record<string, string>;
type Area = {
  id: string;
  latitude: number;
  longitude: number;
  south: number;
  north: number;
  west: number;
  east: number;
  count: number;
  cover: string;
};
type Summary = {
  groups: Area[];
  known: number;
  unknown: number;
  total: number;
};
type Moment = {
  id: string;
  name: string;
  kind: string;
  width: number;
  height: number;
};
export const locationLabel = (f: GeoFilter) =>
  f.location === "unknown"
    ? "Location unknown"
    : f.location === "known"
      ? "With location"
      : f.location === "radius"
        ? `Within ${f.radius_km} km of ${f.latitude}, ${f.longitude}`
        : f.location === "bounds"
          ? `Area ${f.south}…${f.north}, ${f.west}…${f.east}`
          : "Any location";

export default function Places({
  query,
  filter,
  onFilter,
  items,
  total,
  loading,
  onOpen,
  onLibrary,
  onRefine,
}: {
  query: string;
  filter: GeoFilter;
  onFilter: (f: GeoFilter) => void;
  items: Moment[];
  total: number;
  loading: boolean;
  onOpen: (id: string) => void;
  onLibrary: () => void;
  onRefine: () => void;
}) {
  const [summary, setSummary] = useState<Summary>({
    groups: [],
    known: 0,
    unknown: 0,
    total: 0,
  });
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(true);
  const [land, setLand] = useState<number[][][]>([]);
  const [mapError, setMapError] = useState(false);
  const initialCenter =
    filter.location === "radius"
      ? { lat: filter.latitude, lon: filter.longitude }
      : filter.location === "bounds"
        ? {
            lat: String((+filter.south + +filter.north) / 2),
            lon: String((+filter.west + +filter.east) / 2),
          }
        : { lat: "", lon: "" };
  const [view, setView] = useState(
    initialCenter.lat
      ? {
          lat: +initialCenter.lat,
          lon: +initialCenter.lon,
          span:
            filter.location === "radius"
              ? Math.min(360, Math.max(0.1, (+filter.radius_km / 111) * 6))
              : Math.max(0.4, +filter.east - +filter.west),
        }
      : { lat: 20, lon: 0, span: 360 },
  );
  const [center, setCenter] = useState(initialCenter);
  const [radius, setRadius] = useState(filter.radius_km || "10");
  const [tab, setTab] = useState("map");
  useEffect(() => {
    if (
      !filter.location ||
      filter.location === "unknown" ||
      filter.location === "known"
    )
      setCenter({ lat: "", lon: "" });
  }, [filter]);
  useEffect(() => {
    const controller = new AbortController();
    setPending(true);
    setError("");
    fetch("/api/places?" + query, { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw Error("Unable to load captured areas");
        return r.json();
      })
      .then(setSummary)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setPending(false);
      });
    return () => controller.abort();
  }, [query]);
  useEffect(() => {
    fetch("/api/map/land")
      .then((r) => {
        if (!r.ok) throw Error();
        return r.json();
      })
      .then((data) => {
        const rings: number[][][] = [];
        for (const feature of data.features) {
          const g = feature.geometry;
          if (g.type === "Polygon") rings.push(...g.coordinates);
          if (g.type === "MultiPolygon")
            for (const p of g.coordinates) rings.push(...p);
        }
        setLand(rings);
      })
      .catch(() => setMapError(true));
  }, []);
  const project = (lon: number, lat: number) => [
    ((lon - view.lon) / view.span) * 1000 + 500,
    ((view.lat - lat) / view.span) * 1000 + 325,
  ];
  const shift = (x: number, y: number, zoom = 1) =>
    setView((v) => ({
      lat: Math.max(-85, Math.min(85, v.lat + y * v.span)),
      lon: Math.max(-180, Math.min(180, v.lon + x * v.span)),
      span: Math.max(0.05, Math.min(360, v.span * zoom)),
    }));
  const choose = (a: Area) => {
    onFilter({
      location: "bounds",
      south: String(a.south),
      north: String(a.north),
      west: String(a.west),
      east: String(a.east),
    });
    setCenter({ lat: a.latitude.toFixed(2), lon: a.longitude.toFixed(2) });
    setView({ lat: a.latitude, lon: a.longitude, span: 0.4 });
  };
  const matching = summary.groups.filter((a) =>
    search
      .trim()
      .toLowerCase()
      .split(/[ ,]+/)
      .every((term) =>
        `${a.latitude.toFixed(2)} ${a.longitude.toFixed(2)} ${a.south} ${a.west}`.includes(
          term,
        ),
      ),
  );
  const clusters = new Map<string, Area[]>();
  for (const area of summary.groups) {
    const [x, y] = project(area.longitude, area.latitude);
    if (x < -25 || x > 1025 || y < -25 || y > 675) continue;
    const key = `${Math.floor(x / 48)}:${Math.floor(y / 48)}`;
    clusters.set(key, [...(clusters.get(key) || []), area]);
  }
  const validCenter =
    center.lat.trim() !== "" &&
    center.lon.trim() !== "" &&
    Number.isFinite(+center.lat) &&
    Number.isFinite(+center.lon) &&
    Math.abs(+center.lat) <= 90 &&
    Math.abs(+center.lon) <= 180 &&
    +radius > 0 &&
    +radius <= 20020;
  const circle: number[][] = [];
  if (validCenter) {
    const r = +radius / 6371.0088,
      a = (+center.lat * Math.PI) / 180,
      o = (+center.lon * Math.PI) / 180;
    for (let i = 0; i <= 72; i++) {
      const bearing = (i / 72) * 2 * Math.PI;
      const lat = Math.asin(
        Math.sin(a) * Math.cos(r) +
          Math.cos(a) * Math.sin(r) * Math.cos(bearing),
      );
      const lon =
        o +
        Math.atan2(
          Math.sin(bearing) * Math.sin(r) * Math.cos(a),
          Math.cos(r) - Math.sin(a) * Math.sin(lat),
        );
      circle.push(project((lon * 180) / Math.PI, (lat * 180) / Math.PI));
    }
  }
  return (
    <section className="places">
      <div className="place-metrics">
        <span>
          <MapPin size={16} />
          {pending
            ? "Loading areas…"
            : `${summary.known} located moments · ${summary.groups.length} captured areas`}
        </span>
        <span>From your current filters</span>
      </div>
      <div
        className="place-pills"
        role="group"
        aria-label="Location availability"
      >
        <button
          className={!filter.location ? "chosen" : ""}
          onClick={() => onFilter({})}
        >
          Any location
        </button>
        <button
          className={filter.location === "known" ? "chosen" : ""}
          onClick={() => onFilter({ location: "known" })}
        >
          With location · {summary.known}
        </button>
        <button
          className={filter.location === "unknown" ? "chosen" : ""}
          onClick={() => onFilter({ location: "unknown" })}
        >
          Location unknown · {summary.unknown}
        </button>
      </div>
      <div className="place-mobile-tabs segmented">
        <button
          className={tab === "map" ? "chosen" : ""}
          onClick={() => setTab("map")}
        >
          Map & areas
        </button>
        <button
          className={tab === "photos" ? "chosen" : ""}
          onClick={() => setTab("photos")}
        >
          Photos · {total}
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className={"places-layout tab-" + tab}>
        <div className="places-map-column">
          <div className="map-frame">
            <svg
              className="offline-map"
              viewBox="0 0 1000 650"
              role="img"
              aria-label="Offline map of captured areas. Select an area marker, or click the map to set a radius center. Equivalent controls follow below."
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const lon =
                  view.lon +
                  ((e.clientX - rect.left) / rect.width - 0.5) * view.span;
                const lat =
                  view.lat -
                  ((e.clientY - rect.top) / rect.height - 0.5) *
                    view.span *
                    0.65;
                setCenter({
                  lat: Math.max(-90, Math.min(90, lat)).toFixed(5),
                  lon: Math.max(-180, Math.min(180, lon)).toFixed(5),
                });
              }}
            >
              <rect width="1000" height="650" fill="#e4eeed" />
              {land.map((ring, i) => (
                <path
                  key={i}
                  d={
                    ring
                      .map(
                        ([lon, lat], j) =>
                          (j ? "L" : "M") + project(lon, lat).join(","),
                      )
                      .join(" ") + "Z"
                  }
                  fill="#f3f3e5"
                  stroke="#b6c9b3"
                  strokeWidth="1"
                />
              ))}
              {Array.from({ length: 13 }, (_, i) => -180 + i * 30).map(
                (lon) => (
                  <line
                    key={lon}
                    x1={project(lon, 0)[0]}
                    x2={project(lon, 0)[0]}
                    y1="0"
                    y2="650"
                    stroke="#aabeba"
                    opacity=".25"
                  />
                ),
              )}
              {Array.from({ length: 7 }, (_, i) => -90 + i * 30).map((lat) => (
                <line
                  key={lat}
                  x1="0"
                  x2="1000"
                  y1={project(0, lat)[1]}
                  y2={project(0, lat)[1]}
                  stroke="#aabeba"
                  opacity=".25"
                />
              ))}
              {filter.location === "bounds" && (
                <rect
                  x={project(+filter.west, +filter.north)[0]}
                  y={project(+filter.west, +filter.north)[1]}
                  width={((+filter.east - +filter.west) / view.span) * 1000}
                  height={((+filter.north - +filter.south) / view.span) * 1000}
                  fill="#406647"
                  fillOpacity=".15"
                  stroke="#294f3a"
                  strokeDasharray="8 5"
                  strokeWidth="2"
                />
              )}
              {circle.length > 0 && (
                <path
                  d={
                    circle
                      .map((p, i) => (i ? "L" : "M") + p.join(","))
                      .join(" ") + "Z"
                  }
                  fill="#406647"
                  fillOpacity=".08"
                  stroke="#527757"
                  strokeWidth="2"
                  strokeDasharray="6 5"
                />
              )}
              {Array.from(clusters.entries()).map(([key, areas]) => {
                const a = {
                  ...areas[0],
                  latitude:
                    areas.reduce((sum, a) => sum + a.latitude, 0) /
                    areas.length,
                  longitude:
                    areas.reduce((sum, a) => sum + a.longitude, 0) /
                    areas.length,
                  count: areas.reduce((sum, a) => sum + a.count, 0),
                };
                const [x, y] = project(a.longitude, a.latitude);
                if (x < -25 || x > 1025 || y < -25 || y > 675) return null;
                return (
                  <g
                    key={key}
                    transform={`translate(${x},${y})`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (areas.length === 1) choose(a);
                      else
                        setView({
                          lat: a.latitude,
                          lon: a.longitude,
                          span: Math.max(0.05, view.span / 4),
                        });
                    }}
                    className="map-marker"
                  >
                    <title>
                      {a.count} moments in {areas.length} captured areas
                    </title>
                    <circle
                      r="22"
                      fill="#294f3a"
                      stroke="white"
                      strokeWidth="3"
                    />
                    <text
                      textAnchor="middle"
                      dy="5"
                      fill="white"
                      fontSize="16"
                      fontWeight="600"
                    >
                      {a.count}
                    </text>
                  </g>
                );
              })}
              {validCenter && (
                <g
                  transform={`translate(${project(+center.lon, +center.lat).join(",")})`}
                  pointerEvents="none"
                >
                  <circle r="7" fill="#e09b3b" stroke="white" strokeWidth="2" />
                </g>
              )}
            </svg>
            <span className="map-badge">
              <Compass size={14} />
              Offline · North up
            </span>
            <button
              className="map-search-area"
              onClick={() =>
                onFilter({
                  location: "bounds",
                  south: String(Math.max(-90, view.lat - view.span * 0.325)),
                  north: String(Math.min(90, view.lat + view.span * 0.325)),
                  west: String(Math.max(-180, view.lon - view.span / 2)),
                  east: String(Math.min(180, view.lon + view.span / 2)),
                })
              }
            >
              Search visible area
            </button>
            <div className="map-tools">
              <button aria-label="Zoom in" onClick={() => shift(0, 0, 0.5)}>
                <Plus size={18} />
              </button>
              <button aria-label="Zoom out" onClick={() => shift(0, 0, 2)}>
                <Minus size={18} />
              </button>
              <button onClick={() => setView({ lat: 20, lon: 0, span: 360 })}>
                World
              </button>
            </div>
            <div className="map-pan">
              <button aria-label="Pan west" onClick={() => shift(-0.3, 0)}>
                ←
              </button>
              <button aria-label="Pan north" onClick={() => shift(0, 0.3)}>
                ↑
              </button>
              <button aria-label="Pan south" onClick={() => shift(0, -0.3)}>
                ↓
              </button>
              <button aria-label="Pan east" onClick={() => shift(0.3, 0)}>
                →
              </button>
            </div>
          </div>
          <p className="map-caption">
            {mapError
              ? "Coastline unavailable. Markers and geographic search still work."
              : "Natural Earth overview coastline · no street detail"}{" "}
            · Map clicks set the amber radius center. The dashed circle previews
            your radius; apply it below.
          </p>
          <form
            className="radius-panel"
            onSubmit={(e) => {
              e.preventDefault();
              if (validCenter) {
                onFilter({
                  location: "radius",
                  latitude: String(+center.lat),
                  longitude: String(+center.lon),
                  radius_km: String(+radius),
                });
                setView({
                  lat: +center.lat,
                  lon: +center.lon,
                  span: Math.min(
                    360,
                    Math.max(
                      0.1,
                      ((+radius / 111) * 6) /
                        Math.max(0.15, Math.cos((+center.lat * Math.PI) / 180)),
                    ),
                  ),
                });
              }
            }}
          >
            <div>
              <h3>Find moments nearby</h3>
              <p>Choose an area or tap the map, then set a distance.</p>
            </div>
            <div className="radius-fields">
              <label>
                Latitude
                <input
                  type="number"
                  step="any"
                  min="-90"
                  max="90"
                  required
                  value={center.lat}
                  onChange={(e) =>
                    setCenter({ ...center, lat: e.target.value })
                  }
                />
              </label>
              <label>
                Longitude
                <input
                  type="number"
                  step="any"
                  min="-180"
                  max="180"
                  required
                  value={center.lon}
                  onChange={(e) =>
                    setCenter({ ...center, lon: e.target.value })
                  }
                />
              </label>
              <label>
                Radius (km)
                <input
                  type="number"
                  min="0.01"
                  max="20020"
                  step="any"
                  required
                  value={radius}
                  onChange={(e) => setRadius(e.target.value)}
                />
              </label>
            </div>
            <button className="primary" disabled={!validCenter}>
              Search this radius
            </button>
          </form>
          <div className="areas-heading">
            <h3>Captured areas</h3>
            <span>{matching.length} areas</span>
          </div>
          <div className="search-row">
            <Search size={18} />
            <input
              aria-label="Search captured coordinates"
              placeholder="Search coordinates, e.g. 32.05, 34.85"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button
                aria-label="Clear area search"
                onClick={() => setSearch("")}
              >
                <X size={16} />
              </button>
            )}
          </div>
          <p className="small-note">
            Areas are 0.1° coordinate cells, not named cities. Search their
            center coordinates; place names come later. Counts include your
            other filters.
          </p>
          <div className="area-list">
            {matching.map((a) => (
              <button
                key={a.id}
                className="area-card"
                onClick={() => choose(a)}
                aria-label={`Select area ${a.latitude.toFixed(2)}, ${a.longitude.toFixed(2)}, ${a.count} moments`}
              >
                <img
                  src={`/api/media/${a.cover}/thumbnail?size=small`}
                  alt=""
                  loading="lazy"
                />
                <span>
                  <strong>
                    {a.latitude.toFixed(2)}, {a.longitude.toFixed(2)}
                  </strong>
                  <small>
                    {a.count} {a.count === 1 ? "moment" : "moments"} · captured
                    area
                  </small>
                </span>
                <ArrowRight size={17} />
              </button>
            ))}
          </div>
          {!pending && !matching.length && (
            <p className="empty">
              {search
                ? "No captured areas match these coordinates."
                : "No located moments match your current filters."}
            </p>
          )}
        </div>
        <section className="place-results" aria-label="Location results">
          <div className="place-results-heading">
            <div>
              <span className="eyebrow">YOUR SELECTION</span>
              <h2>
                {filter.location
                  ? "Moments in this view"
                  : "Everywhere together"}
              </h2>
              <p aria-live="polite">
                {loading ? "Updating…" : `${total} moments`}
              </p>
            </div>
            <button className="outline" onClick={onRefine}>
              <SlidersHorizontal size={17} />
              Filters
            </button>
          </div>
          <p className="place-selection">{locationLabel(filter)}</p>
          <div className="place-photo-grid">
            {items.slice(0, 18).map((m) => (
              <button
                key={m.id}
                onClick={() => onOpen(m.id)}
                aria-label={"Open " + m.name}
              >
                <img
                  src={`/api/media/${m.id}/thumbnail`}
                  width={m.width}
                  height={m.height}
                  alt={m.name}
                  loading="lazy"
                />
                {m.kind === "video" && <span>Video</span>}
              </button>
            ))}
          </div>
          {!loading && !total && (
            <p className="empty">
              No moments match this location and your other filters. Try a wider
              radius or clear a filter.
            </p>
          )}
          <button className="primary view-timeline" onClick={onLibrary}>
            View {total} moments by date <ArrowRight size={16} />
          </button>
        </section>
      </div>
    </section>
  );
}
