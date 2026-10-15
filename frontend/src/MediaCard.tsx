import {captureLabel,type MetadataInfo} from "./MetadataTools";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
const visibilityCallbacks = new Map<Element, (visible:boolean) => void>();
let tileObserver: IntersectionObserver | null = null;
function observeTile(node: Element, callback:(visible:boolean)=>void) {
  if (!tileObserver) tileObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => visibilityCallbacks.get(entry.target)?.(entry.isIntersecting));
  }, {root:node.closest(".unified-gallery-scroll"),rootMargin:"900px 0px"});
  visibilityCallbacks.set(node, callback);
  tileObserver.observe(node);
  return () => {tileObserver?.unobserve(node);visibilityCallbacks.delete(node);if(!visibilityCallbacks.size){tileObserver?.disconnect();tileObserver=null;}};
}
type Item = MetadataInfo & {
  id: string;
  name: string;
  phone: string;
  album: string;
  kind: string;
  taken: string | null;
  width: number;
  height: number;
  duration: number | null;
  city?: string | null;
  country?: string | null;
  people_names?: string[];
};
export default function MediaCard({
  item: m,
  onOpen,
  selecting=false, selected=false, onSelect,
}: {
  item: Item;
  onOpen: () => void;
  selecting?:boolean; selected?:boolean; onSelect?:()=>void;
}) {
  const tile = useRef<HTMLDivElement>(null);
  const [nearby, setNearby] = useState(false);
  useEffect(() => {
    if (!tile.current) return;
    return observeTile(tile.current, setNearby);
  }, []);
  useEffect(() => {if (!nearby) stop();}, [nearby]);
  const [showInfo,setShowInfo]=useState(false);
  const [active, setActive] = useState(false),
    [url, setUrl] = useState(""),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null),
    alive = useRef(true),
    request = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);
  async function start() {
    setActive(true);
    if (url || request.current) return;
    request.current = true;
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`/api/media/${m.id}/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!r.ok) throw Error("Preview unavailable. Open the item to retry.");
      const data = await r.json();
      if (alive.current) setUrl(data.url);
    } catch (e) {
      if (alive.current) setError(String(e));
    } finally {
      request.current = false;
      if (alive.current) setLoading(false);
    }
  }
  function stop() {
    if (timer.current) clearTimeout(timer.current);
    setActive(false);
  }
  return (
    <div
      ref={tile}
      className="media-tile"
      onPointerEnter={(e) => {
        if (m.kind === "video" && e.pointerType === "mouse")
          timer.current = setTimeout(start, 650);
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === "mouse") stop();
      }}
    >
      {selecting&&<label className="media-selection"><input type="checkbox" aria-label={'Select '+m.name} checked={selected} onChange={onSelect}/><span>Select</span></label>}
      <button
        className="photo-card"
        style={{aspectRatio: `${m.width || 4} / ${m.height || 3}`}}
        onClick={onOpen}
        aria-label={`Open ${m.name} from ${m.phone}`}
      >
        {nearby && <picture>
          <source media="(max-width: 700px)" srcSet={`/api/media/${m.id}/thumbnail?size=small`} />
          <img
            src={`/api/media/${m.id}/thumbnail?size=medium`}
            loading="lazy"
            decoding="async"
            alt={m.name}
            width={m.width}
            height={m.height}
          />
        </picture>}
        {nearby && active && url && (
          <video
            className="hover-video"
            src={url}
            autoPlay
            muted
            playsInline
            loop
            onError={() =>
              setError("Playback unavailable; open the item to retry.")
            }
          />
        )}{" "}
        {m.kind === "video" && (
          <span className="video-badge">
            ▶ {Math.floor((m.duration || 0) / 60)}:
            {String(Math.floor((m.duration || 0) % 60)).padStart(2, "0")}
          </span>
        )}
        <span className="photo-caption">
          {m.phone}
          <small>{captureLabel(m)}</small>
          <small>
            {m.location_label || [m.city && `Near ${m.city}`, m.country]
              .filter(Boolean)
              .join(", ") || "Location name unavailable"}
          </small>
          {m.people_names?.length ? (
            <small>{m.people_names.join(", ")}</small>
          ) : null}
        </span>
      </button>
      <div className="mobile-tile-info"><button className="tile-info-toggle" aria-label={"Photo information for "+m.name} aria-expanded={showInfo} onClick={()=>setShowInfo(v=>!v)}>ⓘ <span>{m.phone}</span>{!!m.people_names?.length&&<small> · {m.people_names.length} people</small>}</button>{showInfo&&<div className="tile-info-details"><strong>{m.name}</strong><span>{captureLabel(m)}</span><span>{m.location_label||[m.city,m.country].filter(Boolean).join(", ")||"Location unknown"}</span><span>{m.people_names?.join(", ")||"No named faces"}</span><button onClick={onOpen}>Open details</button></div>}</div>
      {m.kind === "video" && (
        <div className="video-preview-action">
          <button
            aria-label={`${active ? "Stop" : "Preview"} video ${m.name}`}
            onClick={() => (active ? stop() : start())}
          >
            {active ? "Stop preview" : "▶ Preview video"}
          </button>
          {active && loading && <small role="status">Preparing locally…</small>}
          {active && error && <small role="alert">{error}</small>}
        </div>
      )}
    </div>
  );
}


export function BufferedGallery({items, onOpen,selecting=false,selected=[],onSelect}: {items:Item[];onOpen:(id:string)=>void;selecting?:boolean;selected?:string[];onSelect?:(id:string)=>void}) {
  const container = useRef<HTMLDivElement>(null);
  const [count,setCount] = useState(2);
  useLayoutEffect(() => {
    if (!container.current) return;
    const node = container.current;
    const update = () => setCount(Math.max(1, Math.floor(node.clientWidth / (window.innerWidth <= 700 ? 140 : 240))));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const columns: Item[][] = Array.from({length:count}, () => []);
  const heights = Array(count).fill(0);
  for (const item of items) {
    const column = heights.indexOf(Math.min(...heights));
    columns[column].push(item);
    heights[column] += (item.height || 3) / (item.width || 4) + (item.kind === "video" ? 0.18 : 0.05);
  }
  return <div className="buffered-gallery" ref={container}>{columns.map((column,index) => <div className="buffered-column" key={index}>{column.map((item) => <MediaCard key={item.id} item={item} onOpen={() => onOpen(item.id)} selecting={selecting} selected={selected.includes(item.id)} onSelect={()=>onSelect?.(item.id)} />)}</div>)}</div>;
}
