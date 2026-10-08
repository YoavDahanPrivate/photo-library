import {clusterLevel, geographicClusters, zoomAt, zoomToRectangle, countryAnchor} from "./mapGeometry";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type PointerEvent,
} from "react";
import {
  ZoomIn,
  Smartphone,
  MapPin,
  Search,
  Users,
  CalendarDays,
  Layers,
  X,
  Check,
  Plus,
  Minus,
  Map as MapIcon,
} from "lucide-react";
export type Rectangle = {
  id: string;
  south: number;
  north: number;
  west: number;
  east: number;
};
export type GeoSelection = {
  places: string[];
  unknown: boolean;
  includes: Rectangle[];
  excludes: Rectangle[];
};
export const emptyGeo: GeoSelection = {
  places: [],
  unknown: false,
  includes: [],
  excludes: [],
};
export const hasGeo = (g: GeoSelection) =>
  !!(g.places.length || g.unknown || g.includes.length || g.excludes.length);
export const locationLabel = (g: GeoSelection) =>
  hasGeo(g)
    ? `${g.places.length + g.includes.length + +g.unknown} included · ${g.excludes.length} excluded`
    : "Any location";
type Point = {
  latitude: number;
  longitude: number;
  count: number;
  city: string | null;
  country: string | null;
  cover: string;
};
type MapResults = {
  points: Point[];
  total: number;
  known: number;
  unknown: number;
};
type Place = {
  id: string;
  label: string;
  kind: string;
  country: string;
  aliases: string;
  count: number;
};
type View = { lat: number; lon: number; span: number };
const areaId = () =>
  `area-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const normalize = (s: string) =>
  s
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
async function read<T>(url: string, signal: AbortSignal): Promise<T> {
  const r = await fetch(url, { signal });
  if (!r.ok) throw Error("Search could not be loaded. Please retry.");
  return r.json();
}

export default function SearchWorkspace({
  phones,
  scope,
  onPhone,
  onAll,
  query,
  baseQuery,
  geo,
  onGeo,
  q,
  onQ,
  expression,
  onExpression,
  savedPeople,
  onRefine,
  onPeople,
  onReset,
  chips,
  total,
  children,
  builder,
}: {
  phones: string[];
  scope: string[];
  onPhone: (p: string) => void;
  onAll: () => void;
  query: string;
  baseQuery: string;
  geo: GeoSelection;
  onGeo: (g: GeoSelection) => void;
  q: string;
  onQ: (q: string) => void;
  expression: string;
  onExpression: (expression:string) => void;
  savedPeople: {id:number;name:string|null}[];
  onRefine: () => void;
  onPeople: () => void;
  onReset: () => void;
  chips: ReactNode;
  total: number;
  children: ReactNode;
  builder: (controls: {draft:string;onDraftChange:(value:string)=>void;onEdit:()=>void;editVersion:number}) => ReactNode;
}) {
  const searchInput = useRef<HTMLInputElement>(null);
  const [editVersion,setEditVersion] = useState(0);
  const [searchDraft, setSearchDraft] = useState(expression || q);
  const [searchError, setSearchError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submission = useRef(0);
  useEffect(() => {submission.current++; setSubmitting(false); setSearchDraft(expression || q); setSearchError("");}, [q, expression]);
  async function submitSearch() {
    if (submitting) return;
    const version = ++submission.current;
    let value = searchDraft.trim();
    let bareName = value;
    if (/^"(?:[^"\\]|\\.)*"$/.test(value)) {
      try {bareName = JSON.parse(value);} catch {}
    }
    if (bareName && savedPeople.some((person) => person.name?.trim().toLocaleLowerCase() === bareName.toLocaleLowerCase())) {
      value = `Includes (${JSON.stringify(bareName)})`;
    }
    const structured = /^(?:includes|only|just|person|place|not|date)\b|[()"<>]|&&|\|\|/i.test(value);
    setSubmitting(true);
    setSearchError("");
    try {
      if (structured) {
        const response = await fetch("/api/search/validate?" + new URLSearchParams({expression:value}));
        const result = await response.json();
        if (!response.ok) throw Error(typeof result.detail === "string" ? result.detail : "Invalid search expression.");
      }
      if (version !== submission.current) return;
      onQ(structured ? "" : value);
      onExpression(structured ? value : "");
    } catch (error) {
      if (version === submission.current) setSearchError(error instanceof Error ? error.message : String(error));
    } finally {if (version === submission.current) setSubmitting(false);}
  }
  const [picker, setPicker] = useState(false),
    [placeQuery, setPlaceQuery] = useState("");
  const [options, setOptions] = useState<Place[]>([]),
    [coverage, setCoverage] = useState({ total: 0, countries: 0, cities: 0 });
  const [expandedMap, setExpandedMap] = useState(false);
  const [map, setMap] = useState(true),
    [mobileTab, setMobileTab] = useState("results");
  const [mobileViewport, setMobileViewport] = useState(() => window.matchMedia("(max-width:760px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width:760px)");
    const update = () => setMobileViewport(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const showMap = map && (!mobileViewport || mobileTab === "map");
  const [results, setResults] = useState<MapResults>({
    points: [],
    total: 0,
    known: 0,
    unknown: 0,
  });
  const [pending, setPending] = useState(true),
    [error, setError] = useState("");
  const pickerRef = useRef<HTMLDivElement>(null),
    pickerButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const c = new AbortController();
    setPending(true);
    setError("");
    setResults({ points: [], total: 0, known: 0, unknown: 0 });
    if (!showMap) {setPending(false); return () => c.abort();}
    read<MapResults>("/api/map-results?" + query, c.signal)
      .then(setResults)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!c.signal.aborted) setPending(false);
      });
    return () => c.abort();
  }, [query, showMap]);
  useEffect(() => {
    const c = new AbortController();
    read<{ options: Place[]; coverage: typeof coverage }>(
      "/api/place-options?" + baseQuery,
      c.signal,
    )
      .then((r) => {
        setOptions(r.options);
        setCoverage(r.coverage);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, [baseQuery]);
  useEffect(() => {
    if (!picker) return;
    pickerRef.current?.querySelector("input")?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPicker(false);
        pickerButton.current?.focus();
      }
    };
    const click = (e: globalThis.PointerEvent) => {
      if (
        !pickerRef.current?.contains(e.target as Node) &&
        !pickerButton.current?.contains(e.target as Node)
      )
        setPicker(false);
    };
    document.addEventListener("keydown", key);
    document.addEventListener("pointerdown", click);
    return () => {
      document.removeEventListener("keydown", key);
      document.removeEventListener("pointerdown", click);
    };
  }, [picker]);
  const toggle = (id: string) =>
    onGeo({
      ...geo,
      places: geo.places.includes(id)
        ? geo.places.filter((p) => p !== id)
        : [...geo.places, id].slice(0, 40),
    });
  const chosenName = (id: string) => {
    const p = options.find((p) => p.id === id);
    return p ? (p.kind === "city" ? "Near " : "") + p.label : id;
  };
  const filtered = options.filter((p) =>
    normalize(`${p.label} ${p.country} ${p.aliases}`).includes(
      normalize(placeQuery),
    ),
  );
  return (
    <>
      <section className="device-strip" aria-label="Search devices">
        <div>
          <strong>Search devices</strong>
          <small>
            {scope.length
              ? `${scope.length} of ${phones.length} phones selected`
              : "No phones selected · no results"}
          </small>
        </div>
        <div className="device-buttons">
          <button
            aria-pressed={scope.length === phones.length && !!phones.length}
            onClick={onAll}
          >
            All phones
          </button>
          {phones.map((p) => (
            <button
              key={p}
              aria-pressed={scope.includes(p)}
              onClick={() => onPhone(p)}
            >
              <Smartphone size={18} />
              <span>{p}</span>
              {scope.includes(p) && <Check size={15} />}
            </button>
          ))}
        </div>
      </section>
      <p id="main-search-help" className="small-note">Press Enter or Search to apply. A saved person’s name searches for that person (quotes optional). Other plain text searches filenames and albums; use Includes("Name"), Only("Name"), Just("Name"), or Place("Country or city") for expressions.</p>
        <p id="main-search-error" role="alert" className={searchError ? "error" : ""}>{searchError}</p>
        <div className="unified-filters" aria-label="Library search filters">
        <form className="unified-text-search" onSubmit={(event) => {event.preventDefault(); void submitSearch();}}>
            <Search size={18} />
            <input ref={searchInput} type="search" aria-label="Search photos" placeholder='Filename, album, or Only ("Person name")…'
              aria-invalid={!!searchError} aria-describedby="main-search-help main-search-error"
              value={searchDraft}
              onChange={(event) => {submission.current++;setSubmitting(false);setSearchDraft(event.target.value);setEditVersion((v)=>v+1);setSearchError("");}}
              onKeyDown={(event) => {if (event.nativeEvent.isComposing && event.key === "Enter") event.preventDefault();}} />
            <button type="submit" disabled={submitting}>{submitting ? "Checking…" : "Search"}</button>
          </form>
        <button onClick={onPeople}>
          <Users size={17} />
          People
        </button>
        <button
          ref={pickerButton}
          aria-expanded={picker}
          aria-controls="places-picker"
          onClick={() => setPicker(!picker)}
        >
          <MapPin size={17} />
          Places{hasGeo(geo) && <span className="filter-dot" />}
        </button>
        <button onClick={onPeople}>
          <CalendarDays size={17} />
          Dates
        </button>
        <button onClick={onRefine}>
          <Layers size={17} />
          Albums & more
        </button>
        <button
          className="desktop-map-toggle"
          aria-pressed={map}
          onClick={() => setMap(!map)}
        >
          <MapIcon size={17} />
          Map
        </button>
      </div>
      {picker && (
        <div
          id="places-picker"
          className="places-popover"
          ref={pickerRef}
          role="region"
          aria-label="Choose countries and cities"
        >
          <div className="picker-title">
            <strong>Choose places</strong>
            <button
              aria-label="Close places"
              onClick={() => {
                setPicker(false);
                pickerButton.current?.focus();
              }}
            >
              <X size={18} />
            </button>
          </div>
          <input
            type="search"
            aria-label="Search countries or cities"
            placeholder="Search countries or cities…"
            value={placeQuery}
            onChange={(e) => setPlaceQuery(e.target.value)}
          />
          <p>
            Choose several places. Matches include <strong>any</strong> selected
            place or area; exclusions win.
          </p>
          <button
            className="unknown-place"
            aria-pressed={geo.unknown}
            onClick={() => onGeo({ ...geo, unknown: !geo.unknown })}
          >
            {geo.unknown && <Check size={15} />}Location unknown
          </button>
          <div className="place-option-list">
            {filtered.map((p) => (
              <button
                key={p.id}
                aria-pressed={geo.places.includes(p.id)}
                onClick={() => toggle(p.id)}
              >
                <span>
                  <strong>
                    {p.kind === "city" ? "Near " : ""}
                    {p.label}
                  </strong>
                  <small>
                    {p.kind === "city"
                      ? p.country + " · nearest mapped settlement, ≤25 km"
                      : "Country · offline boundary lookup"}
                  </small>
                </span>
                <span>{p.count}</span>
                {geo.places.includes(p.id) && <Check size={16} />}
              </button>
            ))}
          </div>
          {!filtered.length && (
            <p>
              No matching names in this sample. Try another spelling, or use the
              map.
            </p>
          )}
          <p className="coverage-note">
            This sample: {coverage.countries}/{coverage.total} GPS files have a
            country match; {coverage.cities} have a nearby settlement.
            Unresolved GPS stays searchable on the map. Counts here follow
            people, dates and sources, before geographic selection.
          </p>
          <p className="attribution">
            Names:{" "}
            <a
              href="https://www.geonames.org/"
              target="_blank"
              rel="noreferrer"
            >
              GeoNames (CC BY 4.0)
            </a>{" "}
            · Boundaries:{" "}
            <a
              href="https://www.naturalearthdata.com/"
              target="_blank"
              rel="noreferrer"
            >
              Natural Earth
            </a>{" "}
            · All lookups offline
          </p>
          <button className="outline" onClick={() => onGeo(emptyGeo)}>
            Clear geographic selection
          </button>
        </div>
      )}
      <div className="search-chips" aria-label="Active search filters">
        {chips}
        {geo.places.map((id) => (
          <button
            key={id}
            onClick={() => toggle(id)}
            aria-label={"Remove " + chosenName(id)}
          >
            {chosenName(id)}
            <X size={13} />
          </button>
        ))}
        {geo.unknown && (
          <button onClick={() => onGeo({ ...geo, unknown: false })}>
            Location unknown
            <X size={13} />
          </button>
        )}
        {geo.includes.map((a, i) => (
          <button
            key={a.id}
            onClick={() =>
              onGeo({
                ...geo,
                includes: geo.includes.filter((x) => x.id !== a.id),
              })
            }
            title={`${a.south}, ${a.west} → ${a.north}, ${a.east}`}
          >
            Area {i + 1}
            <X size={13} />
          </button>
        ))}
        {geo.excludes.map((a, i) => (
          <button
            className="exclude-chip"
            key={a.id}
            onClick={() =>
              onGeo({
                ...geo,
                excludes: geo.excludes.filter((x) => x.id !== a.id),
              })
            }
            title={`${a.south}, ${a.west} → ${a.north}, ${a.east}`}
          >
            Excluded area {i + 1}
            <X size={13} />
          </button>
        ))}
        {!!(geo.includes.length || geo.excludes.length) && (
          <button onClick={() => onGeo({ ...geo, includes: [], excludes: [] })}>
            Clear map areas
          </button>
        )}
        {hasGeo(geo) && (
          <button className="clear-geo" onClick={() => onGeo(emptyGeo)}>
            Clear geography
          </button>
        )}
        <button className="reset-search" onClick={onReset}>
          Reset all filters
        </button>
      </div>
      {builder({draft:searchDraft,onDraftChange:(value) => {submission.current++;setSubmitting(false);setSearchDraft(value);setSearchError("");},onEdit:() => {searchInput.current?.focus({preventScroll:true});},editVersion})}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="search-results-heading">
        <strong aria-live="polite">
          {pending
            ? "Updating map…"
            : `${results.total} moments · ${results.known} located · ${results.unknown} unknown`}
        </strong>
        <span>Map and gallery share every filter</span>
      </div>
      <div className="search-mobile-tabs segmented">
        <button
          aria-pressed={mobileTab === "results"}
          onClick={() => setMobileTab("results")}
        >
          Results · {total}
        </button>
        <button
          aria-pressed={mobileTab === "map"}
          onClick={() => {
            setMap(true);
            setMobileTab("map");
          }}
        >
          Map & areas
        </button>
      </div>
      <div
        className={`search-workspace ${expandedMap ? "expanded-map" : "compact-map"} ${map ? "with-map" : "no-map"} mobile-${mobileTab}`}
      >
        <section className="search-gallery" aria-label="Filtered gallery">
          {children}
        </section>
        {showMap && (
          <div className="map-container">
            <button className="outline map-size-toggle" aria-expanded={expandedMap} onClick={() => setExpandedMap(!expandedMap)}>{expandedMap ? "Minimize map" : "Enlarge map"}</button>
            <GeoMap geo={geo} onGeo={onGeo} results={results} pending={pending} />
          </div>
        )}
      </div>
    </>
  );
}

type MapFeature = {properties?: {NAME_EN?: string; NAME?: string; LABEL_X?: number; LABEL_Y?: number; MIN_LABEL?: number; LABELRANK?: number}; geometry: {type: string; coordinates: number[][][] | number[][][][]}};
let boundaries: Promise<MapFeature[]> | undefined;
export function preloadMapBoundaries() {
  if (!boundaries) boundaries = fetch("/api/map/countries").then(r => {
    if (!r.ok) throw Error("Offline boundaries unavailable");
    return r.json();
  }).then(data => data.features as MapFeature[]).catch(e => { boundaries = undefined; throw e; });
  return boundaries;
}

export function GeoMap({
  geo,
  onGeo,
  results,
  pending,
  matching,
}: {
  geo: GeoSelection;
  onGeo: (g: GeoSelection) => void;
  results: MapResults;
  pending: boolean;
  matching?: MapResults;
}) {
  const [features, setFeatures] = useState<MapFeature[]>([]);
  const [mapError, setMapError] = useState(false),
    [mode, setMode] = useState("pan"),
    [view, setView] = useState<View>({ lat: 25, lon: 20, span: 240 });
  const [draft, setDraft] = useState<Rectangle | null>(null),
    [message, setMessage] = useState("");
  const drag = useRef<{
    x: number;
    y: number;
    view: View;
    pointer: number;
    boxZoom: boolean;
  } | null>(null);
  const pointers = useRef(new Map<number,{x:number;y:number}>());
  const pinch = useRef<{view:View;mid:{x:number;y:number};distance:number}|null>(null);
  const [pinchLevel,setPinchLevel] = useState<number|null>(null);
  const blockTap = useRef(false);
  const suppressClickUntil = useRef(0);
  const tap = useRef<{timer:number;at:number;x:number;y:number}|null>(null);
  const [altZoom,setAltZoom] = useState(false);
  useEffect(()=>{const key=(e:KeyboardEvent)=>setAltZoom(e.altKey || e.ctrlKey);const blur=()=>setAltZoom(false);window.addEventListener("keydown",key);window.addEventListener("keyup",key);window.addEventListener("blur",blur);return()=>{window.removeEventListener("keydown",key);window.removeEventListener("keyup",key);window.removeEventListener("blur",blur);if(tap.current)window.clearTimeout(tap.current.timer);};},[]);
  const [fields, setFields] = useState({
    south: "",
    north: "",
    west: "",
    east: "",
  });
  useEffect(() => {
    let active = true;
    preloadMapBoundaries().then(data => {if (active) setFeatures(data);})
      .catch(() => {if (active) setMapError(true);});
    return () => {active = false;};
  }, []);
  const paths = useMemo(
    () =>
      features.map((f) => {
        const polys =
          f.geometry.type === "Polygon"
            ? [f.geometry.coordinates as number[][][]]
            : (f.geometry.coordinates as number[][][][]);
        return polys
          .map((poly) =>
            poly
              .map(
                (ring) =>
                  ring
                    .map(([x, y], i) => `${i ? "L" : "M"}${x},${-y}`)
                    .join(" ") + "Z",
              )
              .join(" "),
          )
          .join(" ");
      }),
    [features],
  );
  const surface = useRef<HTMLDivElement>(null);
  const [mapHeight, setMapHeight] = useState(650);
  const [mapWidth, setMapWidth] = useState(1000);
  const [cityLabels, setCityLabels] = useState<{id:string;name:string;lat:number;lon:number;feature_code:string}[]>([]);
  useEffect(() => {
    const el = surface.current; if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) {setMapWidth(entry.contentRect.width);setMapHeight(1000 * entry.contentRect.height / entry.contentRect.width);}
    });
    observer.observe(el); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (view.span > 80) {setCityLabels([]);return;}
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({
        south:String(Math.max(-90,view.lat-view.span*mapHeight/2000)),north:String(Math.min(90,view.lat+view.span*mapHeight/2000)),
        west:String(Math.max(-180,view.lon-view.span/2)),east:String(Math.min(180,view.lon+view.span/2)),span:String(view.span)
      });
      fetch("/api/map/labels?"+params,{signal:controller.signal}).then(r=>{if(!r.ok) throw Error("Labels unavailable");return r.json();})
        .then(data=>setCityLabels(data.cities)).catch(e=>{if(e.name!=="AbortError")setCityLabels([]);});
    },150);
    return () => {window.clearTimeout(timer);controller.abort();};
  }, [view.lat,view.lon,view.span,mapHeight]);
  const centerY = mapHeight / 2;
  const scale = 1000 / view.span;
  const project = (lon: number, lat: number) => [
    (lon - view.lon) * scale + 500,
    (view.lat - lat) * scale + centerY,
  ];
  const unproject = (x: number, y: number, v: View) => ({
    lon: Math.max(-180, Math.min(180, v.lon + ((x - 500) / 1000) * v.span)),
    lat: Math.max(-90, Math.min(90, v.lat - ((y - centerY) / 1000) * v.span)),
  });
  const cursor = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return {
      x: ((e.clientX - r.left) / r.width) * 1000,
      y: ((e.clientY - r.top) / r.height) * mapHeight,
    };
  };
  const rectangle = (
    x: number,
    y: number,
    start: NonNullable<typeof drag.current>,
  ): Rectangle => {
    const a = unproject(start.x, start.y, start.view),
      b = unproject(x, y, start.view);
    return {
      id: areaId(),
      south: Math.min(a.lat, b.lat),
      north: Math.max(a.lat, b.lat),
      west: Math.min(a.lon, b.lon),
      east: Math.max(a.lon, b.lon),
    };
  };
  const add = (r: Rectangle, exclude = mode === "exclude") => {
    if (r.south >= r.north || r.west === r.east) {
      setMessage("Choose an area with nonzero width and height.");
      return;
    }
    const key = exclude ? "excludes" : "includes";
    if (geo[key].length >= 20) {
      setMessage("Up to 20 areas of each type; remove one to add another.");
      return;
    }
    onGeo({ ...geo, [key]: [...geo[key], r] });
    setMessage(
      exclude
        ? "Excluded area added. Other filters are unchanged."
        : "Area added. Included places and areas combine with OR.",
    );
  };
  const visible = (): Rectangle => ({
    id: areaId(),
    south: Math.max(-90, view.lat - view.span * centerY / 1000),
    north: Math.min(90, view.lat + view.span * centerY / 1000),
    west: Math.max(-180, view.lon - view.span / 2),
    east: Math.min(180, view.lon + view.span / 2),
  });
  const shift = (x: number, y: number, zoom = 1) =>
    setView((v) => ({
      lat: Math.max(-85, Math.min(85, v.lat + y * v.span)),
      lon: Math.max(-180, Math.min(180, v.lon + x * v.span)),
      span: Math.max(0.005, Math.min(360, v.span * zoom)),
    }));
  const matchingPoints = new Set((matching ?? results).points.map(p => `${p.latitude}:${p.longitude}`));
  const level = pinchLevel ?? clusterLevel(view.span,mapWidth);
  const allClusters = useMemo(()=>geographicClusters(results.points,level),[results.points,level]);
  const clusters = new Map([...allClusters].filter(([,points])=>{
    const [x,y]=project(points.reduce((s,p)=>s+p.longitude,0)/points.length,points.reduce((s,p)=>s+p.latitude,0)/points.length);
    return x>=-40 && x<=1040 && y>=-40 && y<=mapHeight+40;
  }));
  const labelZoom = Math.log2(360 / view.span) + 2;
  const labelCandidates = [
    ...features.flatMap((f,i) => {
      const p=f.properties;
      if (!p || (p.MIN_LABEL ?? 0) > labelZoom) return [];
      const polygons=f.geometry.type === "Polygon" ? [f.geometry.coordinates as number[][][]] : f.geometry.coordinates as number[][][][];
      const anchor=countryAnchor(polygons,view,mapHeight,{lon:p.LABEL_X ?? NaN,lat:p.LABEL_Y ?? NaN});
      return anchor ? [{id:"country-"+i,name:p.NAME_EN || p.NAME || "",lat:anchor.lat,lon:anchor.lon,kind:"country",rank:p.LABELRANK ?? 9}] : [];
    }).sort((a,b)=>a.rank-b.rank),
    ...cityLabels.map(p=>({id:"city-"+p.id,name:p.name,lat:p.lat,lon:p.lon,kind:"city",rank:10}))
  ];
  const occupied = [...clusters.values()].map(points=>{
    const [x,y]=project(points.reduce((s,p)=>s+p.longitude,0)/points.length,points.reduce((s,p)=>s+p.latitude,0)/points.length);
    return {x:x*mapWidth/1000,y:y*mapWidth/1000,w:64,h:42};
  });
  const labels: {id:string;name:string;kind:string;x:number;y:number}[] = [];
  const countryBoxes:{x:number;y:number;w:number;h:number}[]=[];
  for (const p of labelCandidates) {
    const [x,y]=project(p.lon,p.lat); let px=x*mapWidth/1000, py=y*mapWidth/1000;
    const w=p.name.length*(p.kind==="country"?7.5:6.3)+18,h=p.kind==="country"?36:20;
    if (!p.name || x<0 || x>1000 || y<0 || y>mapHeight) continue;
    if(p.kind!=="country" && (px<w/2 || px>mapWidth-w/2 || py<h/2 || py>mapHeight*mapWidth/1000-h/2))continue;
    if(p.kind==="country"){
      px=Math.max(w/2+4,Math.min(mapWidth-w/2-4,px));py=Math.max(h/2+4,Math.min(mapHeight*mapWidth/1000-h/2-4,py));
      const free=[[0,0],[0,-44],[0,44],[-64,0],[64,0],[-64,-44],[64,-44]].map(([dx,dy])=>({x:px+dx,y:py+dy})).find(pos=>pos.x>=w/2+4 && pos.x<=mapWidth-w/2-4 && pos.y>=h/2+4 && pos.y<=mapHeight*mapWidth/1000-h/2-4 && !occupied.some(b=>Math.abs(pos.x-b.x)<(w+b.w)/2+5 && Math.abs(pos.y-b.y)<(h+b.h)/2+5));
      if(free){px=free.x;py=free.y;}
      else if(view.span>8 || countryBoxes.some(b=>Math.abs(px-b.x)<(w+b.w)/2+8 && Math.abs(py-b.y)<(h+b.h)/2+8))continue;
      countryBoxes.push({x:px,y:py,w,h});
    }
    if (p.kind!=="country" && occupied.some(b=>Math.abs(px-b.x)<(w+b.w)/2 && Math.abs(py-b.y)<(h+b.h)/2)) continue;
    occupied.push({x:px,y:py,w,h});
    labels.push({id:p.id,name:p.name,kind:p.kind,x:p.kind==="country"?Math.max(w/2+4,Math.min(mapWidth-w/2-4,px))*1000/mapWidth:x,y:p.kind==="country"?Math.max(h/2+4,Math.min(mapHeight*mapWidth/1000-h/2-4,py))*1000/mapWidth:y});
  }
  const markerClick = (points: Point[]) => {
    const lat = points.reduce((s, p) => s + p.latitude, 0) / points.length,
      lon = points.reduce((s, p) => s + p.longitude, 0) / points.length;
    if (points.length > 1 || mode === "pan") {
      setView({ lat, lon, span: Math.max(0.005, view.span / 4) });
      return;
    }
    const id = `pin:${lat}:${lon}`;
    const selectedKey = mode === "exclude" ? "excludes" : "includes";
    if (geo[selectedKey].some((r) => r.id === id))
      onGeo({ ...geo, [selectedKey]: geo[selectedKey].filter((r) => r.id !== id) });
    else
      add(
        {
          id,
          south: Math.max(-90, lat - 0.000001),
          north: Math.min(90, lat + 0.000001),
          west: Math.max(-180, lon - 0.000001),
          east: Math.min(180, lon + 0.000001),
        },
        mode === "exclude",
      );
  };
  const drawRect = (r: Rectangle, excluded: boolean, key: string) =>
    (r.west < r.east
      ? [[r.west, r.east]]
      : [
          [r.west, 180],
          [-180, r.east],
        ]
    ).map(([w, e], i) => (
      <rect
        key={key + i}
        x={w}
        y={-r.north}
        width={e - w}
        height={r.north - r.south}
        className={excluded ? "map-exclusion" : "map-inclusion"}
        vectorEffect="non-scaling-stroke"
      />
    ));
  const fit = () => {
    if (!results.points.length) return;
    const lats = results.points.map((p) => p.latitude),
      lons = results.points.map((p) => p.longitude);
    setView({
      lat: (Math.max(...lats) + Math.min(...lats)) / 2,
      lon: (Math.max(...lons) + Math.min(...lons)) / 2,
      span: Math.min(
        360,
        Math.max(
          0.05,
          (Math.max(...lons) - Math.min(...lons)) * 1.4,
          (Math.max(...lats) - Math.min(...lats)) * 1400 / mapHeight,
        ),
      ),
    });
  };
  const fittedInitially = useRef(false);
  useEffect(() => {
    if (!pending && results.points.length && !fittedInitially.current) {
      fittedInitially.current = true;
      fit();
    }
  }, [pending, results]);
  return (
    <section className="geo-map-panel" aria-label="Matching locations">
      <div
        className="geo-map-tools"
        role="group"
        aria-label="Map interaction tools"
      >
        {[
          ["zoom", "Zoom"],
          ["pan", "Pan"],
          ["select", "Select locations"],
          ["add", "Add area"],
          ["exclude", "Exclude area"],
        ].map(([m, label]) => (
          <button
            key={m}
            aria-pressed={mode === m}
            onClick={() => {
              if(tap.current){window.clearTimeout(tap.current.timer);tap.current=null;}
              setMode(m);
              setDraft(null);
              drag.current = null;
            }}
          >
            {m === "zoom" && <ZoomIn size={16} aria-hidden="true" />} {label}
          </button>
        ))}
        <button onClick={() => { if(tap.current){window.clearTimeout(tap.current.timer);tap.current=null;} pointers.current.clear();pinch.current=null;setPinchLevel(null);blockTap.current=false; drag.current = null; setDraft(null); setMode("pan"); setFields({south:"",north:"",west:"",east:""}); onGeo({ ...geo, includes: [], excludes: [] }); fit(); setMessage("Map reset. Press Apply search to update the gallery."); }}>Clear areas</button>
      </div>
      <div className="map-area-chips" aria-label="Selected map areas">
        {(["includes", "excludes"] as const).flatMap(key => geo[key].map((area, i) => <button key={key + area.id} onClick={() => onGeo({...geo, [key]:geo[key].filter(a => a.id !== area.id)})} aria-label={`Remove ${key === "includes" ? "included" : "excluded"} area ${i+1}`}>{key === "includes" ? "Include" : "Exclude"} {i+1} ×</button>))}
      </div>
      <p className="map-mode-help">
        {mode === "zoom"
          ? "Click to zoom in, or drag a box with your mouse. Ctrl/Alt-click or double-click/tap zooms out. Pinch with two fingers to zoom."
          : mode === "pan"
          ? "Drag to move. Zooming or panning never changes your search."
          : mode === "select"
            ? "Select a marker to include its location. Remove selections using the chips above."
            : `Drag a rectangle to ${mode === "add" ? "include" : "exclude"} an area, or use the coordinate controls below.`}
      </p>
      <div className={"interactive-map " + (mode === "zoom" ? "zoom-tool-active" : "")} ref={surface}
        style={{cursor:mode === "zoom" ? (altZoom ? "zoom-out" : "zoom-in") : mode === "pan" ? "grab" : "crosshair"}}
        onClickCapture={e=>{if(Date.now()<suppressClickUntil.current){e.preventDefault();e.stopPropagation();}}}
        onPointerDown={e=>{
          if((e.target as Element).closest(".geo-zoom") || (e.pointerType === "mouse" && e.button !== 0))return;
          e.preventDefault();
          const pos=cursor(e);pointers.current.set(e.pointerId,pos);
          if(!(e.target as Element).closest(".geo-marker"))e.currentTarget.setPointerCapture(e.pointerId);
          if(pointers.current.size===2){
            if(tap.current){window.clearTimeout(tap.current.timer);tap.current=null;}
            const [a,b]=[...pointers.current.values()];
            pinch.current={view,mid:{x:(a.x+b.x)/2,y:(a.y+b.y)/2},distance:Math.max(1,Math.hypot(a.x-b.x,a.y-b.y))};
            blockTap.current=true;setPinchLevel(level);drag.current=null;setDraft(null);return;
          }
          if(pointers.current.size===1){blockTap.current=false;drag.current={...pos,view,pointer:e.pointerId,boxZoom:mode==="zoom" && e.pointerType==="mouse" && !e.altKey && !e.ctrlKey};}
        }}
        onPointerMove={e=>{
          if(!pointers.current.has(e.pointerId))return;
          const p=cursor(e);pointers.current.set(e.pointerId,p);
          if(pinch.current && pointers.current.size>=2){
            const [a,b]=[...pointers.current.values()],start=pinch.current;
            const mid={x:(a.x+b.x)/2,y:(a.y+b.y)/2};
            setView(zoomAt(start.view,start.mid,mid,start.distance/Math.max(1,Math.hypot(a.x-b.x,a.y-b.y)),mapHeight));
            suppressClickUntil.current=Date.now()+500;return;
          }
          const start=drag.current;if(!start || blockTap.current || start.pointer!==e.pointerId)return;
          if(Math.hypot(p.x-start.x,p.y-start.y)*mapWidth/1000>5)suppressClickUntil.current=Date.now()+500;
          if(mode==="pan")setView(zoomAt(start.view,start,p,1,mapHeight));
          else if(mode==="add" || mode==="exclude" || start.boxZoom)setDraft(rectangle(p.x,p.y,start));
        }}
        onPointerUp={e=>{
          if(!pointers.current.has(e.pointerId))return;
          pointers.current.delete(e.pointerId);
          const start=drag.current,p=cursor(e);
          if(!blockTap.current && start?.pointer===e.pointerId){
            const moved=Math.hypot(p.x-start.x,p.y-start.y)*mapWidth/1000;
            if(start.boxZoom && moved>5 && Math.abs(p.x-start.x)>5 && Math.abs(p.y-start.y)>5){
              if(tap.current){window.clearTimeout(tap.current.timer);tap.current=null;}
              setView(zoomToRectangle(rectangle(p.x,p.y,start),mapHeight));
            }else if(mode==="zoom" && moved<=5){
              suppressClickUntil.current=Date.now()+500;
              const previous=tap.current;
              if(previous)window.clearTimeout(previous.timer);
              if(e.altKey || e.ctrlKey || (previous && Date.now()-previous.at<320 && Math.hypot(p.x-previous.x,p.y-previous.y)*mapWidth/1000<30)){
                tap.current=null;setView(v=>zoomAt(v,p,p,2,mapHeight));
              }else{
                if(previous)setView(v=>zoomAt(v,previous,previous,.5,mapHeight));
                tap.current={...p,at:Date.now(),timer:window.setTimeout(()=>{tap.current=null;setView(v=>zoomAt(v,p,p,.5,mapHeight));},320)};
              }
            }else if((mode==="add" || mode==="exclude") && Math.abs(p.x-start.x)>5 && Math.abs(p.y-start.y)>5)add(rectangle(p.x,p.y,start));
          }
          drag.current=null;setDraft(null);
          if(!pointers.current.size){pinch.current=null;setPinchLevel(null);if(blockTap.current)suppressClickUntil.current=Date.now()+500;blockTap.current=false;}
          if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);
        }}
        onPointerCancel={()=>{pointers.current.clear();pinch.current=null;setPinchLevel(null);blockTap.current=false;drag.current=null;setDraft(null);if(tap.current){window.clearTimeout(tap.current.timer);tap.current=null;}}}
      >
        <svg viewBox={"0 0 1000 " + mapHeight} role="img" aria-label="Offline map of matching photographs. Use map tools or the coordinate form to select areas.">
          <rect width="1000" height={mapHeight} fill="#e5eeef" />
          <g
            transform={`translate(500,${centerY}) scale(${scale}) translate(${-view.lon},${view.lat})`}
          >
            {paths.map((d, i) => (
              <path
                key={i}
                d={d}
                fill="#eff2e5"
                stroke="#afc6b7"
                strokeWidth=".7"
                vectorEffect="non-scaling-stroke"
                fillRule="evenodd"
              />
            ))}
            {geo.includes.flatMap((r) => drawRect(r, false, r.id))}
            {geo.excludes.flatMap((r) => drawRect(r, true, r.id))}
            {draft && drawRect(draft, mode === "exclude", "draft")}
          </g>
        </svg>
        {Array.from(clusters.entries()).map(([key, points]) => {
          const count = points.reduce((s, p) => s + p.count, 0),
            [x, y] = project(
              points.reduce((s, p) => s + p.longitude, 0) / points.length,
              points.reduce((s, p) => s + p.latitude, 0) / points.length,
            );
          return (
            <button
              className={`geo-marker ${points.some(p => matchingPoints.has(`${p.latitude}:${p.longitude}`)) ? "" : "map-context-marker"}`}
              key={key}
              data-cluster={key}
              style={{ left: `${x / 10}%`, top: `${y / mapHeight * 100}%` }}
              onClick={() => markerClick(points)}
              aria-label={`${points.length > 1 || mode === "pan" ? "Zoom to" : "Select"} ${count} moments${points.length === 1 && points[0].city ? " near " + points[0].city : ""}`}
            >
              {count}
            </button>
          );
        })}
        <div className="map-place-labels" aria-label="Map place names">{labels.map(label=><span key={label.id} className={`map-place-label ${label.kind}`} style={{left:`${label.x/10}%`,top:`${label.y/mapHeight*100}%`}}>{label.kind === "country" && <small>Country</small>}{label.name}</span>)}</div>
        <span className="geo-map-badge">Offline · North up</span>
        <div className="geo-zoom">
          <button aria-label="Zoom in" onClick={() => shift(0, 0, 0.5)}>
            <Plus size={18} />
          </button>
          <button aria-label="Zoom out" onClick={() => shift(0, 0, 2)}>
            <Minus size={18} />
          </button>
        </div>
      </div>
      <div className="geo-map-footer">
        <span aria-live="polite">
          {pending
            ? "Updating…"
            : `${(matching ?? results).known} located matches · ${results.known} before location filters`}
        </span>
        <button onClick={fit} disabled={!results.points.length}>
          All locations
        </button>
        <button onClick={() => setView({ lat: 0, lon: 0, span: 360 })}>
          World
        </button>
      </div>
      <details className="map-more-controls"><summary>More map controls</summary>
      <div className="geo-pan-controls">
        <button aria-label="Pan west" onClick={() => shift(-0.25, 0)}>
          ←
        </button>
        <button aria-label="Pan north" onClick={() => shift(0, 0.25)}>
          ↑
        </button>
        <button aria-label="Pan south" onClick={() => shift(0, -0.25)}>
          ↓
        </button>
        <button aria-label="Pan east" onClick={() => shift(0.25, 0)}>
          →
        </button>
        <button onClick={() => add(visible(), mode === "exclude")}>
          {mode === "exclude" ? "Exclude" : "Add"} visible area
        </button>
      </div>

      {mapError && (
        <p role="alert">
          Offline boundaries unavailable. Coordinates and filters still work.
        </p>
      )}
      <details className="coordinate-area">
        <summary>
          Enter area coordinates · keyboard / mobile alternative
        </summary>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (Object.values(fields).some((v) => !v.trim())) return;
            add({
              id: areaId(),
              ...Object.fromEntries(
                Object.entries(fields).map(([k, v]) => [k, +v]),
              ),
            } as Rectangle);
          }}
        >
          <div className="area-coordinate-fields">
            {(["south", "north", "west", "east"] as const).map((k) => (
              <label key={k}>
                {k[0].toUpperCase() + k.slice(1)}
                <input
                  type="number"
                  required
                  step="any"
                  min={k === "south" || k === "north" ? -90 : -180}
                  max={k === "south" || k === "north" ? 90 : 180}
                  value={fields[k]}
                  onChange={(e) =>
                    setFields({ ...fields, [k]: e.target.value })
                  }
                />
              </label>
            ))}
          </div>
          <p>
            South must be below north. West greater than east crosses the date
            line.
          </p>
          <button className="primary">
            {mode === "exclude"
              ? "Exclude coordinate area"
              : "Add coordinate area"}
          </button>
        </form>
      </details>
      </details>
      {message && <p className="map-feedback" role="status">{message}</p>}
      <p className="geo-map-note">
        Country overview, not street detail. All {results.unknown} unlocated
        results remain in the gallery unless geography excludes them.{" "}
        <a
          href="https://www.naturalearthdata.com/"
          target="_blank"
          rel="noreferrer"
        >
          Natural Earth
        </a>{" "}
        ·{" "}
        <a href="https://www.geonames.org/" target="_blank" rel="noreferrer">
          GeoNames
        </a>
      </p>
    </section>
  );
}
