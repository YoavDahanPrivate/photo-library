import MatchingQuality from "./MatchingQuality";
import PeopleProgress,{type PeopleOperation} from "./PeopleProgress";
import ReviewPager from "./ReviewPager";
import {readApiResponse} from "./ApiResponse";
import AppUpdates from "./AppUpdates";
import {albumLocation} from "./albumHierarchy";
import {isIOSStandalone} from "./iosExport";
import MetadataTools, {MetadataEditor,captureLabel,type MetadataInfo} from './MetadataTools';
type ViewerNeighbor={id:string;previous:string|null;next:string|null;position:number|null;total:number};
type ViewerNeighbors={previous:string|null;next:string|null;position:number|null;total:number;window?:ViewerNeighbor[]};
import MediaViewerStage from "./MediaViewerStage";
import SyncSettings from "./SyncSettings";
import UnifiedSearch from "./UnifiedSearch";
import React, { useEffect, useLayoutEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  Images,
  Search,
  Users,
  Smartphone,
  Layers,
  X,
  Play,
  ArrowLeft,
  Undo2,
  Check,
  Repeat2,
  Info,
  CalendarDays,
  HardDrive,
  LoaderCircle,
  Maximize2,
} from "lucide-react";
import "./style.css";
import SearchBuilder from "./SearchBuilder";
import { BufferedGallery } from "./MediaCard";
import LocationMap from "./LocationMap";
import FaceEditor from "./FaceEditor";
import SearchWorkspace, {
  GeoSelection,
  emptyGeo,
  hasGeo,
} from "./SearchWorkspace";
type Media = MetadataInfo & {
  id: string;
  name: string;
  phone: string;
  album: string;
  kind: "photo" | "video";
  taken: string | null;
  width: number;
  height: number;
  duration: number | null;
  latitude: number | null;
  longitude: number | null;
  city?: string | null;
  country?: string | null;
  people_names?: string[];
};
type Detail = Media & {
  relative_path?:string;
  source_relative_path?:string;
  album_relative_path?:string;
  metadata: Record<string, string>;
  faces: {
    id: string;
    person_id: number | null;
    timestamp: number;
    bbox?: string;
    bbox_width?: number | null;
    bbox_height?: number | null;
    name: string | null;
  }[];
};
type Source = { phone: string; album: string; count: number;database_id?:string|null;source_id?:string|null;album_id?:string|null;database_alias?:string|null };
type Person = { id: number; name: string | null; count: number; cover: string };
type Face = {
  id: string;
  media_id: string;
  person_id: number | null;
  timestamp: number;
  status: string;
};
type Status = {
  revision: number;
  total: number;
  counts: Record<string, number>;
  faces: number;
  scan?: {
    state: string;
    phase: string;
    processed?: number;
    to_process?: number;
    remaining_seconds?: number;
    run_errors?: number;
    changed_sources?: number;
    discovery_errors?: number;
    stale?: boolean;
    error?: string;
  } | null;
};
const thumb = (id: string, size = "medium") =>
  "/api/media/" + id + "/thumbnail?size=" + size;
const faceThumb = (id: string) => "/api/faces/" + id + "/thumbnail";
async function api<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(
    "/api" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  return readApiResponse<T>(r);
}
function App() {
  const [settingsOpen, setSettingsOpen] = useState(()=>window.location.hash.startsWith("#tools/"));
  useEffect(()=>{const changed=()=>setSettingsOpen(window.location.hash.startsWith("#tools/"));window.addEventListener("hashchange",changed);return()=>window.removeEventListener("hashchange",changed);},[]);
  useEffect(()=>{if(!settingsOpen&&window.location.hash.startsWith("#tools/"))window.history.replaceState(null,"",window.location.pathname+window.location.search);},[settingsOpen]);
  const [liveSync,setLiveSync]=useState<{running:boolean;runs:{state:string;progress:{phase?:string;database_id?:string;live_added?:number;previews_published?:number}}[]}|null>(null);
  const [editingFace, setEditingFace] = useState(false);
  const [selectedGroups, setSelectedGroups] = useState<number[]>([]);
  const [builderOpen, setBuilderOpen] = useState(0);
  const [expression, setExpression] = useState("");
  const [hideFormatDuplicates,setHideFormatDuplicates]=useState(()=>{try{return localStorage.getItem("dahan.hideFormatDuplicates")!=="false";}catch{return true;}});
  useEffect(()=>{try{localStorage.setItem("dahan.hideFormatDuplicates",String(hideFormatDuplicates));}catch{}},[hideFormatDuplicates]);
  const viewerSequence=useRef(0);
  const viewerImages=useRef(new Map<string,HTMLImageElement>());
  const viewerNeighbors=useRef(new Map<string,ViewerNeighbors>());
  const viewerCache=useRef(new Map<string,Promise<{media:Detail;near:ViewerNeighbors}>>());
  const [slideDirection,setSlideDirection]=useState<"next"|"previous"|"none">("none");
  const [departingImage,setDepartingImage]=useState("");
  const [backToSearch,setBackToSearch]=useState(false);
  const viewerElement=useRef<HTMLElement>(null);
  const [expanded,setExpanded]=useState(false);
  const [fullscreenHint,setFullscreenHint]=useState("");
  const fullscreenRequest=useRef(0),ownedFullscreen=useRef<Element|null>(null);
  const fullscreenElement=()=>document.fullscreenElement || (document as Document & {webkitFullscreenElement?:Element}).webkitFullscreenElement;
  const exitViewerFullscreen=()=>{
    const element=fullscreenElement();
    if(!element || element!==ownedFullscreen.current)return;
    const doc=document as Document & {webkitExitFullscreen?:()=>void};
    try {if(doc.exitFullscreen)void doc.exitFullscreen().catch(()=>{});else doc.webkitExitFullscreen?.();}catch{}
  };
  const collapseViewer=()=>{fullscreenRequest.current++;setExpanded(false);setFullscreenHint("");exitViewerFullscreen();};
  const toggleExpanded=async()=>{
    if(expanded){collapseViewer();return;}
    const attempt=++fullscreenRequest.current;
    setExpanded(true);setFullscreenHint("");
    if(window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & {standalone?:boolean}).standalone)return;
    const element=viewerElement.current as (HTMLElement & {webkitRequestFullscreen?:()=>void})|null;
    const fallback=()=>{if(attempt===fullscreenRequest.current)setFullscreenHint(/iPhone|iPad|iPod/.test(navigator.userAgent)?"For viewing without Safari bars: Share → Add to Home Screen → Open as Web App, then launch Dahan from its icon.":"Browser fullscreen is unavailable here. The image is expanded; use your browser’s fullscreen command to hide its toolbar.");};
    if(!element)return;
    const hintTimer=window.setTimeout(()=>{if(fullscreenElement()!==element)fallback();},1800);
    try{
      if(element.requestFullscreen)await element.requestFullscreen({navigationUI:"hide"});
      else if(element.webkitRequestFullscreen)element.webkitRequestFullscreen();
      else {fallback();return;}
      if(fullscreenElement()===element){ownedFullscreen.current=element;setFullscreenHint("");}
      else fallback();
      if(attempt!==fullscreenRequest.current)exitViewerFullscreen();
    }catch{fallback();}finally{window.clearTimeout(hintTimer);}
  };
  useEffect(()=>{
    const changed=()=>{
      const current=fullscreenElement();
      if(current===viewerElement.current && current){ownedFullscreen.current=current;setFullscreenHint("");}
      else if(ownedFullscreen.current){ownedFullscreen.current=null;fullscreenRequest.current++;setExpanded(false);setFullscreenHint("");}
    };
    document.addEventListener("fullscreenchange",changed);document.addEventListener("webkitfullscreenchange",changed);
    return()=>{document.removeEventListener("fullscreenchange",changed);document.removeEventListener("webkitfullscreenchange",changed);};
  },[]);
  const [viewerBusy,setViewerBusy]=useState(false);
  const [neighbors,setNeighbors]=useState<ViewerNeighbors>({previous:null,next:null,position:null,total:0});
  const closeViewer=()=>{collapseViewer();viewerSequence.current++;setDetail(null);setViewerBusy(false);};
  const [order, setOrder] = useState("desc");
  const [suggestions, setSuggestions] = useState<
    {
      face_id: string;
      person_id: number;
      name: string;
      score: number;
      margin?:number;media_id?:string;taken?:string|null;support?:number|null;score_cutoff?:number|null;margin_cutoff?:number|null;
      source_person_id: number | null;
      confidence: "high" | "lower";
    }[]
  >([]);
  const pendingReviews = useRef(new Set<string>());
  const completedReviews = useRef(new Set<string>());
  const [savingReviews, setSavingReviews] = useState<string[]>([]);
  const [reviewErrors, setReviewErrors] = useState<Record<string, string>>({});
  const [groupMatch, setGroupMatch] = useState<{group:number;person_id:number;name:string;count:number} | null>(null);
  const [checkingMatch, setCheckingMatch] = useState(false);
  const [matchError, setMatchError] = useState("");
  const [approvedOpen, setApprovedOpen] = useState(false);
  const [approvedLimit, setApprovedLimit] = useState(40);
  const [peopleLimit, setPeopleLimit] = useState(120);
  const peopleSentinel = useRef<HTMLDivElement>(null);
  const [approvedReviews, setApprovedReviews] = useState<{face_id:string;person_id:number;name:string}[]>([]);
  const [correctionTargets, setCorrectionTargets] = useState<Record<string,string>>({});
  const [approvingAll, setApprovingAll] = useState(false);
  const [reviewMessage, setReviewMessage] = useState("");
  const [peopleOperation,setPeopleOperation]=useState<PeopleOperation|null>(null);
  const [peopleProgressError,setPeopleProgressError]=useState("");
  const completedPeopleOperations=useRef(new Set<string>());
  const observedPeopleOperations=useRef(new Set<string>());
  const peopleReviewVersions=useRef(new Map<string,number>());
  const peopleWorking=peopleOperation?.state==="queued"||peopleOperation?.state==="running";
  const [approvalCount,setApprovalCount]=useState(0);
  const [reviewPages,setReviewPages]=useState({high:0,lower:0});
  const reviewPageSize=48;
  const [reviewPerson,setReviewPerson]=useState('');
  const [reviewOrder,setReviewOrder]=useState('strongest');
  const [selectedReviews,setSelectedReviews]=useState<string[]>([]);
  const selectedReviewSet=new Set(selectedReviews);
  const selectedMatchCount=suggestions.reduce((count,row)=>count+Number(selectedReviewSet.has(row.face_id)),0);
  const [reviewChanges,setReviewChanges]=useState(0);
  const refreshedReviewChanges=useRef(0);
  const [refreshAfterReviews,setRefreshAfterReviews]=useState(()=>{try{return localStorage.getItem('dahan.refreshMatchesAfterReview')!=='false';}catch{return true;}});
  useEffect(()=>{try{localStorage.setItem('dahan.refreshMatchesAfterReview',String(refreshAfterReviews));}catch{}},[refreshAfterReviews]);
  useEffect(()=>{setReviewPages({high:0,lower:0});setSelectedReviews([]);},[reviewPerson,reviewOrder]);
  const reviewPeople=Array.from(new Map(suggestions.map(row=>[row.person_id,row.name])).entries()).sort((a,b)=>a[1].localeCompare(b[1]));
  const reviewMatches=(level:'high'|'lower')=>{
    const rows=suggestions.filter(row=>row.confidence===level&&(!reviewPerson||String(row.person_id)===reviewPerson));
    if(reviewOrder==='strongest')return rows;
    const dates=new Map<string,typeof suggestions>();
    for(const row of rows){const key=row.person_id+':'+(row.taken?.slice(0,10)||row.media_id||row.face_id);const bucket=dates.get(key)||[];bucket.push(row);dates.set(key,bucket);}
    const result:typeof suggestions=[];let active=Array.from(dates.values()),index=0;
    while(active.length){const next:typeof active=[];for(const bucket of active){result.push(bucket[index]);if(index+1<bucket.length)next.push(bucket);}active=next;index++;}
    return result;
  };
  const matchingReason=(row:(typeof suggestions)[number])=>row.confidence==='high'?'Strong match with supporting photographs':[
    row.score<(row.score_cutoff??.70)?'Needs a stronger similarity':null,
    (row.margin??1)<(row.margin_cutoff??.12)?'Another person is also similar':null,
    row.support!=null&&row.support<2?'Needs another supporting photograph':null,
  ].filter(Boolean).join(' · ')||'Review this match before assigning';
  const [page, setPage] = useState<"library" | "people">("library");
  const [peopleQuery, setPeopleQuery] = useState("");
  const [geo, setGeo] = useState<GeoSelection>(emptyGeo);
  const [view, setView] = useState("months");
  const generation = useRef(0);
  const [sources, setSources] = useState<Source[]>([]),
    [scope, setScope] = useState<string[]>([]),
    [albums, setAlbums] = useState<string[]>([]);
  const [sourcesReady,setSourcesReady]=useState(false);
  const [databaseScope,setDatabaseScope]=useState("");
  const [sourceScope,setSourceScope]=useState("");
  const [albumScope,setAlbumScope]=useState("");
  const sourceSnapshot=useRef<Source[]>([]);
  const [includeChildren,setIncludeChildren]=useState(false);
  const [hierarchy,setHierarchy]=useState<{databases:{id:string;alias:string;parent_id:string|null;visible:number}[];sources:{id:string;alias:string;database_id:string;database_alias:string;active:number;visible:number;database_visible:number}[];linked_sources:{id:string;alias:string;visible:boolean;members:{database_id:string}[]}[]}>({databases:[],sources:[],linked_sources:[]});

  const databaseFamily=new Set([databaseScope]);
  if(includeChildren){let changed=true;while(changed){changed=false;for(const d of hierarchy.databases)if(d.parent_id&&databaseFamily.has(d.parent_id)&&!databaseFamily.has(d.id)){databaseFamily.add(d.id);changed=true;}}}
  const databaseChoices=hierarchy.databases.length?hierarchy.databases.filter(d=>d.visible).map(d=>[d.id,d.alias]):Array.from(new Map(sources.filter(s=>s.database_id).map(s=>[s.database_id!,s.database_alias||s.database_id!])).entries());
  const sourceChoices=hierarchy.sources.length?hierarchy.sources.filter(s=>s.active&&s.visible&&s.database_visible&&(!databaseScope||databaseFamily.has(s.database_id))).map(s=>[s.id,s.alias+" · "+s.database_alias]):Array.from(new Map(sources.filter(s=>s.source_id&&(!databaseScope||s.database_id===databaseScope)).map(s=>[s.source_id!,s.phone+" · "+(s.database_alias||"Database")])).entries());
  const [sheet, setSheet] = useState(false),
    [kind, setKind] = useState(""),
    [orientation, setOrientation] = useState(""),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [q, setQ] = useState(""),
    [peopleFilter, setPeopleFilter] = useState<number[]>([]);
  const [items, setItems] = useState<Media[]>([]),
    [total, setTotal] = useState(0),
    [loading, setLoading] = useState(true),
    [resultsLoading, setResultsLoading] = useState(true),
    [status, setStatus] = useState<Status | null>(null);
  const [people, setPeople] = useState<Person[]>([]),
    [group, setGroup] = useState<number | null>(null),
    [faces, setFaces] = useState<Face[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [personName, setPersonName] = useState(""),
    [target, setTarget] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null),
    [preview, setPreview] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [revision, setRevision] = useState(0);
  const [selectingMedia,setSelectingMedia]=useState(false),[selectedMedia,setSelectedMedia]=useState<string[]>([]),[editingMetadata,setEditingMetadata]=useState(false);
  const [sortBy,setSortBy]=useState('capture');
  const [connectionError,setConnectionError]=useState("");
  useEffect(()=>{let active=true;api<typeof hierarchy>("/library/hierarchy").then(value=>{if(active)setHierarchy(value);}).catch(()=>{});return()=>{active=false;};},[status?.revision]);
  useEffect(()=>{
    if((sourcesReady&&status&&!loading)||connectionError||error){
      document.getElementById("dahan-startup")?.remove();
      window.dispatchEvent(new Event("dahan:ready"));
    }
  },[sourcesReady,status,loading,connectionError,error]);
  const metadataSaved=()=>{setRevision(v=>v+1);setSelectedMedia([]);void api<Status>('/status').then(setStatus);if(detail)void api<Detail>('/media/'+detail.id).then(d=>setDetail(old=>old?.id===d.id?d:old));};
  const unnamedGroups = people.filter((p) => p.id > 0 && !p.name?.trim());
  const eligibleGroups = selectedGroups.filter((id) =>
    unnamedGroups.some((p) => p.id === id),
  );
  useEffect(() => {
    setSelectedGroups((old) =>
      old.filter((id) => people.some((p) => p.id === id && !p.name?.trim())),
    );
  }, [people]);
  useEffect(() => {
    if (editingFace)
      document
        .querySelector(".face-editor")
        ?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [editingFace]);
  const phoneNames = Array.from(new Set(sources.map((s) => s.phone)));
  useEffect(() => {
    api<Source[]>("/sources")
      .then((s) => {
        setSources(s);
        sourceSnapshot.current=s;
        const available = Array.from(new Set(s.map((x) => x.phone)));
        let saved: string[] | null = null;
        try {
          const value = JSON.parse(
            localStorage.getItem("dahan.sources.v1") ?? localStorage.getItem("dahan.phones.v1") ?? "null",
          );
          if (Array.isArray(value) && value.every((v) => typeof v === "string"))
            saved = value;
        } catch {}
        let stable:string[]|null=null;
        try {const v=JSON.parse(localStorage.getItem("dahan.sourceIds.v2")||"null");if(Array.isArray(v)&&v.every(x=>typeof x==="string"))stable=v;}catch{}
        const matched=stable?s.filter(x=>stable!.includes(x.source_id||"legacy:"+x.phone)).map(x=>x.phone):null;
        setScope(matched?Array.from(new Set(matched)):saved?saved.filter(v=>available.includes(v)):available);
        setSourcesReady(true);
      })
      .catch((e) => setError(e.message));
    const update = () =>
      api<Status>("/status")
        .then(s=>{setStatus(s);setConnectionError("");void api<typeof liveSync>("/sync/status").then(setLiveSync).catch(()=>{});})
        .catch((e) => setConnectionError(e.message));
    update();
    const timer = setInterval(update, 5000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    let active = true;
    if (page !== "people") return;
    api<typeof suggestions>("/people/suggestions")
      .then((rows) => {
        if (active)
          setSuggestions(
            rows.filter((row) => !completedReviews.current.has(row.face_id)),
          );
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [page]);
  useEffect(() => {
    api<Person[]>("/people")
      .then(setPeople)
      .catch((e) => setError(e.message));
  }, [revision, page]);
  useEffect(() => {
    if (!status) return;
    api<Source[]>("/sources")
      .then(next=>{
        const previous=sourceSnapshot.current;
        setScope(selected=>{
          const all=Array.from(new Set(previous.map(s=>s.phone))).every(name=>selected.includes(name));
          const ids=new Set(previous.filter(s=>selected.includes(s.phone)).map(s=>s.source_id||"legacy:"+s.phone));
          const names=Array.from(new Set(next.filter(s=>all||ids.has(s.source_id||"legacy:"+s.phone)).map(s=>s.phone)));
          return names.length===selected.length&&names.every(name=>selected.includes(name))?selected:names;
        });
        sourceSnapshot.current=next;setSources(next);
        setAlbums(selected=>{const available=selected.filter(a=>next.some(s=>s.phone+"\x1f"+s.album===a));return available.length===selected.length?selected:available;});
      })
      .catch((e) => setError(e.message));
    if (page === "people" && group === null) setRevision((v) => v + 1);
  }, [status?.revision]);
  useEffect(() => {
    if (sourcesReady) {
      try {
        localStorage.setItem("dahan.sources.v1", JSON.stringify(scope));
        localStorage.setItem("dahan.sourceIds.v2",JSON.stringify(Array.from(new Set(sources.filter(s=>scope.includes(s.phone)).map(s=>s.source_id||"legacy:"+s.phone)))));
      } catch {}
    }
  }, [scope, sourcesReady, sources]);
  useEffect(() => {
    if (group !== null)
      setPersonName(
        group === 0 ? "" : people.find((p) => p.id === group)?.name || "",
      );
  }, [people, group]);
  useEffect(() => {
    if (!sheet && !detail) return;
    const oldFocus = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const dialog = document.querySelector<HTMLElement>("[role=dialog]");
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),input,select,a[href],video[controls]",
        ) || [],
      ).filter((e) => e.offsetParent !== null);
    focusable()[0]?.focus();
    const trap = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const list = focusable();
      const first = list[0],
        last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", trap);
      oldFocus?.focus();
    };
  }, [sheet, detail?.id]);

  const query = (includeGeo = true) => {
    const p = new URLSearchParams();
    if(databaseScope){p.append("database_ids",databaseScope);if(includeChildren)p.set("include_child_databases","true");}
    if(sourceScope){if(sourceScope.startsWith("linked:"))p.append("linked_source_ids",sourceScope.slice(7));else p.append("source_ids",sourceScope);}
    if(albumScope)p.append("album_ids",albumScope);
    if(!databaseScope&&!sourceScope)scope.forEach((v) => p.append("phones", v));
    albums.forEach((v) => p.append("albums", v));
    peopleFilter.forEach((v) => p.append("people", String(v)));
    if (kind) p.set("kind", kind);
    if (orientation) p.set("orientation", orientation);
    if (start) p.set("start", start);
    if (end) p.set("end", end);
    if (q) p.set("q", q);
    if (expression) p.set("expression", expression);
    p.set("order", order);
    p.set("sort_by",sortBy);
    if(hideFormatDuplicates)p.set("hide_format_duplicates","true");
    p.set("catalogue_revision", String(status?.revision || 0));
    if (!scope.length&&!databaseScope&&!sourceScope) p.append("phones", "__no_phone_selected__");
    if (includeGeo && hasGeo(geo)) p.set("geo", JSON.stringify(geo));
    return p;
  };
  useEffect(() => {
    generation.current++;
    if (!scope.length&&!databaseScope&&!sourceScope) {
      setItems([]);
      setTotal(0);
      setLoading(false);
      setResultsLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setResultsLoading(true);
    const timer = setTimeout(() => {
      api<{ items: Media[]; total: number }>("/media?" + query())
        .then((r) => {
          if (active) {
            setItems(r.items);
            setTotal(r.total);
          }
        })
        .catch((e) => {
          if (active) {
            setError(e.message);
            setItems([]);
            setTotal(0);
          }
        })
        .finally(() => {if(active){setLoading(false);setResultsLoading(false);}});
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [
    scope,
    albums,
    databaseScope,
    includeChildren,
    sourceScope,
    albumScope,
    kind,
    orientation,
    start,
    end,
    q,
    peopleFilter,
    revision,
    geo,
    expression,
    order,
    sortBy,
    hideFormatDuplicates,
  ]);
  useEffect(() => {
    if (group === null) {
      setFaces([]);
      return;
    }
    let active = true;
    setFaces([]);
    api<Face[]>(group === 0 ? "/faces?unknown=true" : "/faces?person=" + group)
      .then((rows) => {
        if (active) setFaces(rows);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    setSelected([]);
    setPersonName(
      group === 0 ? "" : people.find((p) => p.id === group)?.name || "",
    );
    return () => {
      active = false;
    };
  }, [group, revision]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if(expanded){collapseViewer();return;}
        closeViewer();
        setSheet(false);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [expanded]);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(t);
  }, [notice]);
  const reset = () => {
    setExpression("");
    setGeo(emptyGeo);
    setScope(phoneNames);
    setAlbums([]);setAlbumScope("");
    setKind("");
    setOrientation("");
    setStart("");
    setEnd("");
    setPeopleFilter([]);
    setQ("");
  };
  const togglePhone = (phone: string) => {
    setScope((old) =>
      old.includes(phone) ? old.filter((p) => p !== phone) : [...old, phone],
    );
    setAlbums((old) => old.filter((a) => !a.startsWith(phone + "\x1f")));
  };
  const viewerKey=(id:string)=>query().toString()+":"+revision+":"+id;
  const loadNeighborhood=async(id:string)=>{
    const search=query().toString(),prefix=search+":"+revision+":";
    const near=await api<ViewerNeighbors>("/media/"+id+"/neighbors?"+search);
    for(const row of near.window||[])viewerNeighbors.current.set(prefix+row.id,{...row,window:near.window});
    while(viewerNeighbors.current.size>24)viewerNeighbors.current.delete(viewerNeighbors.current.keys().next().value!);
    return near;
  };
  const loadViewer=(id:string)=>{
    const key=viewerKey(id),cached=viewerCache.current.get(key);if(cached)return cached;
    // Start decoding immediately, independently of metadata and navigation queries.
    const image=new Image();image.src=thumb(id,"large");viewerImages.current.set(key,image);
    const pending=Promise.all([api<Detail>("/media/"+id),viewerNeighbors.current.get(key)||loadNeighborhood(id),image.decode().catch(()=>{})]).then(([media,near])=>({media,near})).catch(error=>{viewerCache.current.delete(key);viewerImages.current.delete(key);throw error;});
    viewerCache.current.set(key,pending);
    while(viewerCache.current.size>9){const oldest=viewerCache.current.keys().next().value!;viewerCache.current.delete(oldest);viewerImages.current.delete(oldest);}
    return pending;
  };
  useEffect(()=>{
    if(!detail)return;let active=true;
    const buffer=async()=>{
      let near=viewerNeighbors.current.get(viewerKey(detail.id))||neighbors;
      const rows=near.window||[],position=near.position||0;
      if(!rows.length||((rows[0].position||1)>Math.max(1,position-2))||((rows[rows.length-1].position||0)<Math.min(near.total,position+2))){
        near=await loadNeighborhood(detail.id);if(!active)return;
      }
      const candidates=(near.window||[]).filter(row=>row.id!==detail.id).sort((a,b)=>Math.abs((a.position||0)-position)-Math.abs((b.position||0)-position));
      // Two downloads at a time, nearest frames first, keep browsing responsive.
      for(let i=0;i<candidates.length&&active;i+=2)await Promise.all(candidates.slice(i,i+2).map(row=>loadViewer(row.id).catch(()=>{})));
    };
    void buffer().catch(()=>{});return()=>{active=false;};
  },[detail?.id,revision,status?.revision]);
  const open = async (id: string, swiped = false) => {
    const sequence=++viewerSequence.current;setViewerBusy(true);
    const direction=detail?(id===neighbors.previous?"previous":"next"):"none";
    try {
      const {media,near}=await loadViewer(id);
      if(sequence!==viewerSequence.current)return false;
      if(!detail)setExpanded(false);
      setSlideDirection(swiped?"none":direction);setDepartingImage(detail&&!swiped?(expanded&&detail.kind==="photo"?"/api/media/"+detail.id+"/display-original":thumb(detail.id,"large")):"");
      setEditingFace(false);setPreview("");setDetail(media);setNeighbors(near);return true;
    } catch(e){if(sequence===viewerSequence.current)setError(String(e));return false;}
    finally{if(sequence===viewerSequence.current)setViewerBusy(false);}
  };
  const reviewSuggestion = async (
    s: (typeof suggestions)[number],
    accept: boolean,
  ) => {
    if (pendingReviews.current.has(s.face_id)) return;
    pendingReviews.current.add(s.face_id);
    setSavingReviews([...pendingReviews.current]);
    setReviewErrors((errors) => ({ ...errors, [s.face_id]: "" }));
    try {
      await api(
        accept ? "/faces/correct" : "/people/reject-suggestion",
        accept
          ? {
              face_ids: [s.face_id],
              action: "move",
              target: s.person_id,
              from_suggestion: true,
            }
          : { face_id: s.face_id, person_id: s.person_id },
      );
      completedReviews.current.add(s.face_id);
      setReviewChanges(value=>value+1);
      setSuggestions((rows) => rows.filter((row) => row.face_id !== s.face_id));
      setReviewMessage(
        refreshAfterReviews?"Saved. Matches will refresh in the background after you pause reviewing.":"Saved. Reevaluate when ready to use your latest confirmations and corrections.",
      );
      setRevision((v) => v + 1);
    } catch (e) {
      setReviewErrors((errors) => ({ ...errors, [s.face_id]: String(e) }));
    } finally {
      pendingReviews.current.delete(s.face_id);
      setSavingReviews([...pendingReviews.current]);
    }
  };
  const approveSuggestions = async (matches: typeof suggestions) => {
    if (approvingAll || peopleWorking || pendingReviews.current.size || !matches.length) return;
    setApprovingAll(true);
    setApprovalCount(matches.length);
    setReviewMessage(`Saving ${matches.length.toLocaleString()} assignments…`);
    try {
      const result = await api<{approved:number}>("/people/approve-suggestions", {
        matches: matches.map(({face_id,person_id,source_person_id}) => ({face_id,person_id,source_person_id})),
      });
      const ids = new Set(matches.map(row => row.face_id));
      ids.forEach(id => completedReviews.current.add(id));
      setSelectedReviews([]);setReviewChanges(value=>value+1);
      setSuggestions(rows => rows.filter(row => !ids.has(row.face_id)));
      setReviewMessage(`Saved ${result.approved.toLocaleString()} assignments. You can undo this batch. ${refreshAfterReviews?"Matches will refresh in the background after you pause reviewing.":"Reevaluate when ready to find more matches."}`);
      setRevision(v => v + 1);
    } catch (e) {
      setReviewMessage("");
      setError(String(e));
      // A lost response may follow a successful commit. Reload the queue so
      // retrying never silently includes newly suggested faces.
      try {
        const rows = await api<typeof suggestions>("/people/suggestions");
        setSuggestions(rows.filter(row => !completedReviews.current.has(row.face_id)));
        setRevision(v => v + 1);
      } catch { /* Keep the error and current selection visible for retry. */ }
    } finally { setApprovingAll(false); }
  };
  useEffect(()=>{
    let active=true,timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      let running=false;
      try {
        const operation=await api<PeopleOperation|null>("/people/operations/current");
        if(!active)return;
        setPeopleProgressError("");
        setPeopleOperation(previous=>previous?.id===operation?.id&&previous?.state===operation?.state&&previous?.updated_at===operation?.updated_at&&previous?.stop_requested===operation?.stop_requested?previous:operation);
        running=operation?.state==="queued"||operation?.state==="running";
        if(operation&&running)observedPeopleOperations.current.add(operation.id);
        if(operation&&!running&&!observedPeopleOperations.current.has(operation.id))completedPeopleOperations.current.add(operation.id);
        const reviewChanged=operation&&running&&(operation.review_revision||0)>(peopleReviewVersions.current.get(operation.id)||0);
        if(operation&&(reviewChanged||(!running&&!completedPeopleOperations.current.has(operation.id)))){
          const rows=await api<typeof suggestions>("/people/suggestions");
          if(!active)return;
          if(!running)completedPeopleOperations.current.add(operation.id);
          peopleReviewVersions.current.set(operation.id,operation.review_revision||0);
          completedReviews.current.clear();
          setSuggestions(rows);setReviewPages({high:0,lower:0});setRevision(v=>v+1);
          if(operation.result?.profile_warning)setReviewMessage(operation.result.profile_warning);
        }
      } catch(e){if(active)setPeopleProgressError(String(e));}
      if(active)timer=setTimeout(poll,running?1000:5000);
    };
    void poll();return()=>{active=false;clearTimeout(timer);};
  },[]);
  useEffect(()=>{
    if(peopleWorking||approvingAll)document.querySelector(".people-operation")?.scrollIntoView({block:"nearest",behavior:"smooth"});
  },[peopleWorking,approvingAll]);
  const reevaluatePeople=async(kind:"reevaluate"|"auto-approve"|"calibrate"="reevaluate")=>{
    if(pendingReviews.current.size||peopleWorking)return;
    setBusy(true);
    try {
      const operation=await api<PeopleOperation>("/people/operations/"+kind,{});
      if(kind!=="calibrate")refreshedReviewChanges.current=reviewChanges;
      observedPeopleOperations.current.add(operation.id);
      setPeopleOperation(operation);setReviewMessage("");setPeopleProgressError("");
    }catch(e){setError(String(e));}finally{setBusy(false);}
  };
  useEffect(()=>{
    if(!refreshAfterReviews||reviewChanges<=refreshedReviewChanges.current||peopleWorking||approvingAll||savingReviews.length)return;
    const timer=setTimeout(()=>{void reevaluatePeople();},8000);
    return()=>clearTimeout(timer);
  },[refreshAfterReviews,reviewChanges,peopleWorking,approvingAll,savingReviews.length]);
  const perform = async (path: string, body: unknown) => {
    setBusy(true);
    try {
      await api(path, body);
      if(path==="/faces/correct"||/^\/people\/\d+\/name$/.test(path))setReviewChanges(value=>value+1);
      if (/^\/people\/\d+\/name$/.test(path)) returnToPeople();
      if (path === "/faces/correct" && group !== null) {
        const remaining = await api<Face[]>(
          group === 0 ? "/faces?unknown=true" : "/faces?person=" + group,
        );
        if (!remaining.length) {
          restorePeoplePosition.current = true;
          if (!peoplePosition.current) peoplePosition.current = {y:0,anchors:[]};
          setGroup((current) => current === group ? null : current);
          setSelected([]);
        }
      }
      completedReviews.current.clear();
      setSuggestions(await api<typeof suggestions>("/people/suggestions"));
      setRevision((r) => r + 1);
      setNotice("Saved locally. You can undo this change.");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const correct = (action: string) => {
    if (!selected.length) return;
    perform("/faces/correct", {
      face_ids: selected,
      action,
      target: target ? Number(target) : null,
      name: action === "split" ? null : personName || null,
    });
  };
  // Finish one refresh before requesting another. Scan revisions can arrive
  // faster than a large loaded window; discarding each response starves updates.
  const galleryRefreshState=useRef({query:"",revision:0,count:0,total:0,allowed:false});
  galleryRefreshState.current={query:query().toString(),revision:status?.revision||0,count:items.length,total,allowed:!!(scope.length||databaseScope||sourceScope)};
  useEffect(() => {
    if(loading||settingsOpen||page!=="library")return;
    let active=true,busy=false,appliedRevision=-1;
    const refresh=async()=>{
      const snapshot=galleryRefreshState.current;
      if(busy||!snapshot.allowed||snapshot.revision===appliedRevision||loadingMore.current)return;
      busy=true;
      const expected=generation.current;
      try {
        const result:Media[]=[];let count=snapshot.total;
        for(let offset=0;offset<Math.max(80,snapshot.count);offset+=200){
          if(!active||generation.current!==expected)return;
          const p=new URLSearchParams(snapshot.query);p.set("offset",String(offset));p.set("limit",String(Math.min(200,Math.max(80,snapshot.count)-offset)));
          const batch=await api<{items:Media[];total:number}>("/media?"+p);
          result.push(...batch.items);count=batch.total;
          if(offset+batch.items.length>=count)break;
        }
        if(active&&generation.current===expected&&!loadingMore.current&&galleryRefreshState.current.count===snapshot.count){
          setItems(result);setTotal(count);appliedRevision=snapshot.revision;
        }
      } finally {busy=false;}
    };
    const request=()=>void refresh().catch(()=>{});
    request();const timer=setInterval(request,5000);
    return()=>{active=false;clearInterval(timer);};
  },[loading,settingsOpen,page]);
  const loadSentinel = useRef<HTMLDivElement>(null);
  const loadingMore = useRef(false);
  const [moreError, setMoreError] = useState("");
  const [theme, setTheme] = useState(() => {try {return localStorage.getItem("dahan.theme") || "sage";} catch {return "sage";}});
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    const favicon=document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if(favicon)favicon.href="/brand/dahan-"+(["sage","ocean","plum","black","dark"].includes(theme)?theme:"sage")+"-v2.svg";
    try {localStorage.setItem("dahan.theme", theme);} catch {}
  }, [theme]);
  const loadMore = async () => {
    if (loadingMore.current || loading || items.length >= total) return;
    loadingMore.current = true;
    setMoreError("");
    const expected = generation.current;
    setLoading(true);
    try {
      const p = query();
      p.set("offset", String(items.length));
      const r = await api<{ items: Media[] }>("/media?" + p);
      if (expected === generation.current)
        setItems((old) => [...old, ...r.items]);
    } catch (e) {
      if (expected === generation.current) setMoreError("Could not load more photos. Please retry.");
    } finally {
      loadingMore.current = false;
      if (expected === generation.current) setLoading(false);
    }
  };
  useEffect(() => {
    const gallery=document.querySelector<HTMLElement>(".unified-gallery-scroll");
    const mobile=document.querySelector<HTMLElement>("main.library-workspace-page");
    if(!gallery||!mobile||page!=="library"||settingsOpen)return;
    const onScroll=(event:Event)=>{
      const pane=event.currentTarget as HTMLElement;
      const small=window.matchMedia("(max-width:760px)").matches;
      if(pane!==(small?mobile:gallery))return;
      if(small)setBackToSearch(pane.scrollTop>240);
      if(!loading&&!moreError&&pane.scrollHeight-pane.scrollTop-pane.clientHeight<700)void loadMore();
    };
    gallery.addEventListener("scroll",onScroll,{passive:true});mobile.addEventListener("scroll",onScroll,{passive:true});
    return()=>{gallery.removeEventListener("scroll",onScroll);mobile.removeEventListener("scroll",onScroll);};
  },[items.length,total,loading,moreError,page,settingsOpen]);
  useEffect(()=>{
    setMoreError("");setBackToSearch(false);
    for(const selector of [".unified-gallery-scroll","main.library-workspace-page"]){const pane=document.querySelector<HTMLElement>(selector);if(pane)pane.scrollTop=0;}
  },[scope,albums,databaseScope,includeChildren,sourceScope,albumScope,kind,start,end,q,expression,order,geo,hideFormatDuplicates]);
  useEffect(()=>{setSelectedMedia([]);},[scope,albums,databaseScope,includeChildren,sourceScope,albumScope,kind,start,end,q,expression,geo]);
  useEffect(()=>{setEditingMetadata(false);},[detail?.id]);
  const groups: Record<string, Media[]> = {};
  items.forEach((m) => {
    const day =
      view === "all"
        ? "All moments"
        : m.taken
          ? m.taken.slice(0, view === "years" ? 4 : view === "months" ? 7 : 10)
          : "Unknown date";
    (groups[day] ||= []).push(m);
  });
  useEffect(() => {
    let active = true;
    setGroupMatch(null);
    setMatchError("");
    if (group === null || group <= 0) { setCheckingMatch(false); return; }
    setCheckingMatch(true);
    api<{match: {person_id:number;name:string;count:number} | null}>(`/people/${group}/match`)
      .then((result) => { if (active) setGroupMatch(result.match ? {...result.match, group} : null); })
      .catch(() => { if (active) setMatchError("Could not check for a named match. Reopen this group to retry."); })
      .finally(() => { if (active) setCheckingMatch(false); });
    return () => { active = false; };
  }, [group, revision]);
  const peoplePosition = useRef<{y:number; anchors:{id:string;top:number}[]} | null>(null);
  const restorePeoplePosition = useRef(false);
  const returnToPeople = () => {
    if (!peoplePosition.current) peoplePosition.current = {y:0,anchors:[]};
    restorePeoplePosition.current = true;
    setGroup(null);
    setSettingsOpen(false); setPage("people");
    setSelected([]);
    setTarget("");
  };
  useEffect(() => {
    if (page !== "people" || group !== null) return;
    const remember = () => {
      if (restorePeoplePosition.current) return;
      const card = document.elementFromPoint(window.innerWidth * 0.6, window.innerHeight * 0.4)?.closest<HTMLElement>("[data-person-card]");
      peoplePosition.current = {y:window.scrollY,anchors:card ? [{id:card.dataset.personCard!,top:card.getBoundingClientRect().top}] : []};
    };
    window.addEventListener("scroll", remember, {passive:true});
    return () => window.removeEventListener("scroll", remember);
  }, [page, group]);
  const openPeopleGroup = (id: number) => {
    const cards = Array.from(document.querySelectorAll<HTMLElement>("[data-person-card]"));
    const index = cards.findIndex((card) => card.dataset.personCard === String(id));
    const nearby = index >= 0 ? [...cards.slice(index, index + 12), ...cards.slice(Math.max(0, index - 12), index).reverse()] : [];
    if (page === "people" && group === null) peoplePosition.current = {y: window.scrollY, anchors: nearby.map((card) => ({id: card.dataset.personCard!, top: card.getBoundingClientRect().top}))};
    restorePeoplePosition.current = true;
    setGroup(id);
  };
  useLayoutEffect(() => {
    if (page !== "people" || group !== null || !restorePeoplePosition.current || !peoplePosition.current) return;
    const saved = peoplePosition.current;
    let y = saved.y;
    for (const anchor of saved.anchors) {
      const card = document.querySelector<HTMLElement>(`[data-person-card="${anchor.id}"]`);
      if (card) { y = window.scrollY + card.getBoundingClientRect().top - anchor.top; break; }
    }
    window.scrollTo({top: Math.max(0, y), behavior: "instant"});
    // Retain the anchor through the asynchronous people-count refresh, until
    // the user starts interacting with the restored list.
    const release = () => { restorePeoplePosition.current = false; };
    const events = ["wheel", "touchstart", "pointerdown", "keydown"] as const;
    events.forEach((event) => window.addEventListener(event, release, {passive:true}));
    return () => events.forEach((event) => window.removeEventListener(event, release));
  }, [page, group, people]);
  useEffect(() => {
    let active = true;
    if (page !== "people") return;
    api<typeof approvedReviews>("/people/review/approved").then((rows) => {if(active) setApprovedReviews(rows);}).catch((e) => setError(String(e)));
    return () => {active=false;};
  }, [revision, page]);
  useEffect(() => {
    if (page !== "people" || group !== null || !peopleSentinel.current) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setPeopleLimit((n) => Math.min(n + 120, people.length));
    }, {rootMargin:"800px 0px"});
    observer.observe(peopleSentinel.current);
    return () => observer.disconnect();
  }, [page, group, people.length, peopleLimit]);
  const namedCorrectionPeople = people.filter((person) => person.id > 0 && person.name?.trim());
  const activeGroup = people.find((p) => p.id === group);
  const groupSuggestions = new Map<number, {name:string;count:number}>();
  if (groupMatch && groupMatch.group === group && !activeGroup?.name) groupSuggestions.set(groupMatch.person_id, groupMatch);
  return (
    <div className="app-shell">
      <aside className="sidebar" inert={sheet || !!detail}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setSettingsOpen(false); setPage("library");
          }}
        >
          <span className="brand-logo photo-brand-mark" aria-hidden="true" />
          <span>
            Dahan<span className="brand-sub">FAMILY LIBRARY</span>
          </span>
        </a>
        <div className="nav-label">YOUR COLLECTION</div>
        <nav>
          <button
            className={!settingsOpen && page === "library" ? "active" : ""}
            onClick={() => {setSettingsOpen(false);setPage("library");}}
          >
            <Images size={20} />
            Library
          </button>
          <button
            className={!settingsOpen && page === "people" ? "active" : ""}
            onClick={() => {
              setSettingsOpen(false); setPage("people");
              returnToPeople();
            }}
          >
            <Users size={20} />
            People<span className="nav-count">{people.length}</span>
          </button>
          <button
            onClick={() => {
              setSettingsOpen(false); setPage("library");
              setSheet(true);
            }}
          >
            <Layers size={20} />
            Sources & albums
          </button>
          <button className={settingsOpen ? "active" : ""} onClick={()=>{window.location.hash="tools/databases";setSettingsOpen(true);}}><HardDrive size={20}/>Library tools</button>
        </nav>
        <div className="sidebar-bottom">
          <HardDrive size={18} />
          <div>
            Stored on your SSD<small>Local family library</small>
          </div>
        </div>
      </aside>
      <main className={!settingsOpen && page === "library" ? "library-workspace-page" : ""} inert={sheet || !!detail}>
        <header className="topbar">
          <span className="mobile-brand-logo photo-brand-mark" role="img" aria-label="Dahan" />
          <label className="theme-picker">Theme <select aria-label="Color theme" value={theme} onChange={(e) => setTheme(e.target.value)}><option value="sage">Sage</option><option value="ocean">Ocean</option><option value="plum">Plum</option><option value="black">Black</option><option value="dark">Dark</option></select></label>
          <span className="breadcrumb">
            Your family / {settingsOpen ? "Library tools" : page === "library" ? "Library" : "People"}
          </span>
          <span className="sample-badge">
            <span />
            {(status?.total || 0).toLocaleString()} files
          </span>
        </header>
        {liveSync && (liveSync.running || ["paused","cancelled","interrupted"].includes(liveSync.runs[0]?.state)) && <section className="live-sync" aria-label="Library sync"><strong>Sync · {liveSync.runs[0]?.state}</strong><span>{liveSync.runs[0]?.progress.phase} · {(status?.counts.ready||0).toLocaleString()} viewable</span><button onClick={()=>{window.location.hash="tools/sync";setSettingsOpen(true);}}>Sync controls</button>{liveSync.runs[0]?.progress.live_added!==undefined&&<span>{liveSync.runs[0].progress.live_added!.toLocaleString()} new items · {(liveSync.runs[0].progress.previews_published||0).toLocaleString()} previews processed</span>}{liveSync.runs[0]?.progress.database_id&&databaseChoices.some(([id])=>id===liveSync.runs[0].progress.database_id)&&<button onClick={()=>{reset();setDatabaseScope(liveSync.runs[0].progress.database_id!);setSourceScope("");setAlbumScope("");setPage("library");setSettingsOpen(false);}}>View importing Database</button>}<small>{liveSync.running?"New previews appear while scanning. Face recognition follows preview publishing.":"Progress is saved. Resume from Library tools when ready."}</small></section>}
        {!liveSync?.runs.length && status?.scan && (
          <section className="scan-progress" aria-label="Full library scan">
            <strong>
              {status.scan.stale
                ? "Scan heartbeat stopped"
                : status.scan.state === "running"
                  ? "Full library scan running"
                  : status.scan.state === "completed"
                    ? "Full library scan complete"
                    : status.scan.state === "completed_with_issues"
                      ? "Full scan finished with issues"
                      : `Full scan ${status.scan.state}`}
            </strong>
            <p>
              {(status.counts.ready || 0).toLocaleString()} of{" "}
              {status.total.toLocaleString()} files browsable ·{" "}
              {status.scan.phase}
              {status.scan.run_errors
                ? ` · ${status.scan.run_errors} processing errors`
                : ""}
              {status.scan.changed_sources
                ? ` · ${status.scan.changed_sources} changed sources need review`
                : ""}
              {status.scan.discovery_errors
                ? ` · ${status.scan.discovery_errors} folders/files could not be read`
                : ""}
            </p>
            {status.scan.state === "running" && (
              <>
                <progress
                  aria-label="Files processed in this scan"
                  max={status.scan.to_process || 1}
                  value={status.scan.processed || 0}
                />
                <p className="small-note">
                  {status.scan.remaining_seconds
                    ? `Estimated time remaining: ${Math.ceil(status.scan.remaining_seconds / 3600)} hours. `
                    : ""}
                  New results appear as files finish. Existing names and
                  corrections are preserved.
                </p>
                <button
                  onClick={async () => {
                    try {
                      await api("/scan/pause", {});
                      setNotice(
                        "Pause requested. Current files will finish first.",
                      );
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  Pause scan
                </button>
              </>
            )}
            {status.scan.error && <p role="alert">{status.scan.error}</p>}
          </section>
        )}
        <PeopleProgress operation={peopleOperation} approving={approvingAll} approvalCount={approvalCount} connection={peopleProgressError} onCancel={async()=>{if(peopleOperation)try{await api("/people/operations/"+peopleOperation.id+"/cancel",{});}catch(e){setError(String(e));throw e;}}}/>
        {connectionError && <div role="alert" className="error">{connectionError} Retrying automatically…</div>}
        {error && (
          <div role="alert" className="error">
            {error}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={18} />
            </button>
          </div>
        )}
        {settingsOpen ? <SyncSettings onBrowseAlbum={(databaseId,sourceId,albumId)=>{setDatabaseScope(databaseId);setIncludeChildren(false);setSourceScope(sourceId);setAlbums([]);setAlbumScope(albumId);setSettingsOpen(false);setPage("library");setResultsLoading(true);}} onPeopleChanged={()=>setRevision(v=>v+1)} onClose={() => setSettingsOpen(false)} hideFormatDuplicates={hideFormatDuplicates} onHideFormatDuplicates={setHideFormatDuplicates} /> : page === "library" ? (
          <>
            {backToSearch&&<button className="back-to-search" onClick={()=>{const pane=document.querySelector<HTMLElement>("main.library-workspace-page");pane?.scrollTo({top:0,behavior:window.matchMedia("(prefers-reduced-motion:reduce)").matches?"auto":"smooth"});}}>↑ Back to search</button>}
            <div className="sync-fields" aria-label="Database and Source filters">
              <label>Database<select aria-label="Database" value={databaseScope} onChange={e=>{setDatabaseScope(e.target.value);setIncludeChildren(false);setSourceScope("");setAlbums([]);setAlbumScope("");setResultsLoading(true);}}><option value="">All visible Databases</option>{databaseChoices.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>{databaseScope&&hierarchy.databases.some(d=>d.parent_id===databaseScope)&&<label className="library-children-toggle"><input type="checkbox" checked={includeChildren} onChange={e=>{setIncludeChildren(e.target.checked);setSourceScope("");setAlbumScope("");setResultsLoading(true);}}/>Include child Databases</label>}
              <label>Source<select aria-label="Source" value={sourceScope} onChange={e=>{setSourceScope(e.target.value);setAlbums([]);setAlbumScope("");setResultsLoading(true);}}><option value="">All Sources in scope</option><optgroup label="Folder Sources">{sourceChoices.map(([id,name])=><option key={id} value={id}>{name}</option>)}</optgroup>{hierarchy.linked_sources.some(g=>g.visible)&&<optgroup label="Linked Sources">{hierarchy.linked_sources.filter(g=>g.visible&&(!databaseScope||g.members.some(m=>databaseFamily.has(m.database_id)))).map(g=><option key={g.id} value={"linked:"+g.id}>{g.alias}</option>)}</optgroup>}</select></label>
            </div>
            {albumScope&&<p className="library-album-scope">Album: <strong>{sources.find(s=>s.album_id===albumScope)?.album||"Selected Album"}</strong> <button onClick={()=>setAlbumScope("")}>Show all Albums</button></p>}
            <UnifiedSearch sourceSelection={scope} onSourceChange={(selected)=>{setResultsLoading(true);setScope(selected);}} resultsLoading={resultsLoading} people={people} sources={sources} expression={expression} query={query().toString()} onApply={(value) => {
              setResultsLoading(true);
              if(!value.trim())setScope(phoneNames);setAlbums([]);setAlbumScope("");setGeo(emptyGeo);setQ("");setPeopleFilter([]);setStart("");setEnd("");setKind("");setOrientation("");setExpression(value);
            }}>
              {(mediaControl)=><>
              <div className="gallery-controls" aria-label="Gallery display controls">
              <div
                className="date-scale"
                role="group"
                aria-label="Timeline grouping"
              >
                {["years", "months", "days", "all"].map((v) => (
                  <button
                    key={v}
                    className={view === v ? "chosen" : ""}
                    onClick={() => setView(v)}
                  >
                    {v === "all" ? "All" : v[0].toUpperCase() + v.slice(1)}
                  </button>
                ))}
              </div>
              {mediaControl}
              <select className="gallery-media-filter gallery-sort-basis" aria-label="Gallery sort basis" title="Sort by" value={sortBy} onChange={e=>setSortBy(e.target.value)}><option value="capture">Sort by: Capture date</option><option value="file">Sort by: File date</option></select>
              <label className="sort-control">
                <span className="sort-label">Date order</span>
                <select
                  aria-label="Result date order"
                  value={order}
                  onChange={(e) => setOrder(e.target.value)}
                >
                  <option value="desc">Newest first</option>
                  <option value="asc">Oldest first</option>
                </select>
              </label>
                <span className="result-count" aria-live="polite">
                  {total.toLocaleString()} moments
                </span>
              </div>
              <MetadataTools query={query().toString()} selected={selectedMedia} selecting={selectingMedia} onSelecting={setSelectingMedia} onSelectLoaded={()=>setSelectedMedia(items.map(m=>m.id))} onClear={()=>setSelectedMedia([])} count={total} revision={revision} onSaved={metadataSaved}/>
              {sortBy==='file'&&<p className="metadata-note">Sorting by filesystem timestamp. Timeline groups still describe capture dates; missing capture dates stay unknown.</p>}
              {loading && !items.length ? (
                <div className="empty">
                  <LoaderCircle className="spin" />
                  Loading your moments…
                </div>
              ) : !items.length ? (
                <div className="empty">
                  <Images size={36} />
                  <h2>No moments in this view</h2>
                  <p>
                    {scope.length
                      ? "Try another source, album, or date."
                      : "Choose at least one source to browse."}
                  </p>
                  <button className="primary" onClick={reset}>
                    Show all files
                  </button>
                </div>
              ) : (
                Object.entries(groups)
                  .sort(([a], [b]) =>
                    a === "Unknown date"
                      ? 1
                      : b === "Unknown date"
                        ? -1
                        : order === "asc"
                          ? a.localeCompare(b)
                          : b.localeCompare(a),
                  )
                  .map(([day, photos]) => (
                    <section className="day-group" key={day}>
                      <div className="day-heading">
                        <h2>
                          {day === "Unknown date" ||
                          day === "All moments" ||
                          view === "years" || day.length<10
                            ? day
                            : new Date(
                                day +
                                  (view === "months" ? "-01" : "") +
                                  "T12:00:00",
                              ).toLocaleDateString(
                                undefined,
                                view === "months"
                                  ? { month: "long", year: "numeric" }
                                  : {
                                      weekday: "long",
                                      day: "numeric",
                                      month: "long",
                                      year: "numeric",
                                    },
                              )}
                        </h2>
                        <span>{photos.length} shown</span>
                      </div>
                      <BufferedGallery items={photos} onOpen={resultsLoading ? ()=>{} : open} selecting={selectingMedia} selected={selectedMedia} onSelect={id=>setSelectedMedia(old=>old.includes(id)?old.filter(i=>i!==id):[...old,id])} />
                    </section>
                  ))
              )}
              {items.length < total && (
                <div className="load-more" ref={loadSentinel} role="status">
                  {moreError ? <><span>{moreError}</span><button onClick={() => void loadMore()}>Retry loading</button></> : <span>{loading ? "Loading more photos…" : "Scroll to explore more"} · {items.length.toLocaleString()} of {total.toLocaleString()}</span>}
                </div>
              )}
              <footer className="library-footer">
                <Info size={15} />
                <span>
                  Face groups need review. Scene, dog and portrait-type search
                  are the next milestone.
                </span>
                <span>{status?.counts.ready || 0} indexed</span>
              </footer>
              </>}
            </UnifiedSearch>
          </>
        ) : (
          <>
            <div className="page-heading">
              <div>
                <span className="eyebrow">FAMILIAR FACES</span>
                <h1>
                  {group === -1
                    ? "Unknown People"
                    : group === null
                      ? "People"
                      : activeGroup?.name || "An unnamed person"}
                </h1>
                <p>Help your library put a name to a face.</p>
              </div>
              <button
                className="outline"
                disabled={busy || peopleWorking || approvingAll || savingReviews.length > 0}
                onClick={() => perform("/undo", {})}
              >
                <Undo2 size={17} />
                Undo last change
              </button>
            </div>
            {group === null ? (
              <>
                <div className="review-note">
                  <Info size={18} />
                  <div>
                    <strong>Suggestions, ready for your review</strong>
                    <p>
                      Open a group to name it, move incorrect faces, or split it
                      into different people. This review covers all Sources.
                    </p>
                  </div>
                </div>
                <section
                  className="people-review-tools"
                  aria-label="People review tools"
                >
                  <h2>Keep your people up to date</h2>
                  <p>
                    Open a person to rename them or correct their faces.
                    Reevaluate uses current saved examples and respects faces
                    you removed.
                  </p>
                  <div className="builder-actions">
                    <button
                      className="primary"
                      disabled={busy || peopleWorking || approvingAll || savingReviews.length > 0}
                      onClick={()=>reevaluatePeople()}
                    >
                      {peopleWorking ? peopleOperation?.kind==="calibrate"?"Calibration running…":peopleOperation?.kind==="auto-approve"?"Auto approval running…":"Reevaluation running…" : busy ? "Working…" : "Reevaluate unassigned faces"}
                    </button>
                  </div>
                  <p className="small-note">
                    Confidence is based on similarity, separation from other people, and supporting photos—not an accuracy percentage. Choose individual approvals, Approve all, or the high-confidence approval loop.
                  </p>
                  <MatchingQuality revision={revision} working={!!peopleWorking||busy||approvingAll||!!savingReviews.length} calibrating={!!peopleWorking&&peopleOperation?.kind==='calibrate'} analyze={()=>void reevaluatePeople('calibrate')} changed={()=>{setSuggestions(rows=>rows.map(row=>({...row,confidence:'lower'})));setReviewMessage('Matching rules updated. Reevaluate unassigned faces to refresh the matches.');setRevision(value=>value+1);}}/>
                  <div className="review-batch-toolbar">
                    <label>Suggested person<select aria-label="Filter suggested person" value={reviewPerson} onChange={event=>setReviewPerson(event.target.value)}><option value="">All people</option>{reviewPeople.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
                    <label>Review order<select aria-label="Match review order" value={reviewOrder} onChange={event=>setReviewOrder(event.target.value)}><option value="strongest">Strongest first</option><option value="dates">Spread across dates</option></select></label>
                    <label className="review-refresh"><input type="checkbox" checked={refreshAfterReviews} onChange={event=>setRefreshAfterReviews(event.target.checked)}/>Refresh matches after reviewing</label>
                    <button className="outline approve-all-button" disabled={busy||!!peopleWorking||approvingAll||!!savingReviews.length||!selectedMatchCount} onClick={()=>void approveSuggestions(suggestions.filter(row=>selectedReviewSet.has(row.face_id)))}>Approve selected {selectedMatchCount}</button>
                    {!!selectedReviews.length&&<button className="outline" onClick={()=>setSelectedReviews([])}>Clear selection</button>}
                  </div>
                  {reviewMessage && <p role="status">{reviewMessage}</p>}
                  <div className="confidence-sections">
                    {(["high", "lower"] as const).map((level) => {
                      const sectionMatches = reviewMatches(level);
                      const sectionPage=Math.min(reviewPages[level],Math.max(0,Math.ceil(sectionMatches.length/reviewPageSize)-1));
                      return <section key={level} aria-label={level === "high" ? "High-confidence matches" : "Lower-confidence matches"}>
                        <h3>{level === "high" ? "High-confidence matches" : "Lower-confidence matches"} ({sectionMatches.length})</h3>
                        <div className="approval-actions">
                        <button className="outline approve-all-button" disabled={busy || peopleWorking || approvingAll || !!savingReviews.length || !sectionMatches.length} onClick={() => approveSuggestions(sectionMatches)}><Check size={16} aria-hidden="true"/>{approvingAll ? "Saving assignments…" : `Approve all ${sectionMatches.length}`}</button>
                        {level==="high"&&<button className="outline approve-all-button auto-approve-button" disabled={busy||peopleWorking||approvingAll||!!savingReviews.length||!sectionMatches.length} onClick={()=>reevaluatePeople("auto-approve")}><Repeat2 size={16} aria-hidden="true"/>Auto approve high-confidence</button>}
                        </div>
                        {level==="high"&&<p className="small-note auto-approve-help">Auto approve covers all people in the visible library, including those outside this review filter. It repeats approval and reevaluation until no high-confidence matches remain, or you press Stop. Completed approvals stay saved; each batch can be undone.</p>}
                        {!!sectionMatches.length&&<button className="outline review-select-page" disabled={busy||!!peopleWorking||approvingAll||!!savingReviews.length} onClick={()=>setSelectedReviews(previous=>Array.from(new Set([...previous,...sectionMatches.slice(sectionPage*reviewPageSize,(sectionPage+1)*reviewPageSize).map(row=>row.face_id)])))}>Select this page ({Math.min(reviewPageSize,sectionMatches.length-sectionPage*reviewPageSize)})</button>}
                        <ReviewPager page={sectionPage} total={sectionMatches.length} size={reviewPageSize} onPage={value=>setReviewPages(previous=>({...previous,[level]:value}))}/>
                        <div className="suggestion-grid">
                        {sectionMatches.slice(sectionPage*reviewPageSize,(sectionPage+1)*reviewPageSize).map((s) => (
                          <div
                            key={s.face_id}
                            aria-busy={savingReviews.includes(s.face_id)}
                          >
                            <img
                              src={faceThumb(s.face_id)}
                              loading="lazy" decoding="async"
                              alt="Face suggested for assignment"
                            />
                            <label className="review-card-selection"><input type="checkbox" aria-label={'Select match '+s.face_id} disabled={busy||!!peopleWorking||approvingAll||!!savingReviews.length} checked={selectedReviews.includes(s.face_id)} onChange={event=>setSelectedReviews(previous=>event.target.checked?[...previous,s.face_id]:previous.filter(id=>id!==s.face_id))}/>Select</label>
                            <span>Possibly {s.name}</span>
                            <small className="match-evidence">{matchingReason(s)}</small>
                            {s.taken&&<small>{s.taken.slice(0,10)}</small>}
                            {s.source_person_id !== null &&
                              s.source_person_id > 0 && (
                                <button
                                  disabled={
                                    busy || peopleWorking || approvingAll || savingReviews.includes(s.face_id)
                                  }
                                  onClick={() => openPeopleGroup(s.source_person_id!)}
                                >
                                  Review face group
                                </button>
                              )}
                            <button
                              disabled={
                                busy || peopleWorking || approvingAll || savingReviews.includes(s.face_id)
                              }
                              onClick={() => reviewSuggestion(s, true)}
                            >
                              {savingReviews.includes(s.face_id)
                                ? "Saving…"
                                : `Assign to ${s.name}`}
                            </button>
                            <button
                              disabled={
                                busy || peopleWorking || approvingAll || savingReviews.includes(s.face_id)
                              }
                              onClick={() => reviewSuggestion(s, false)}
                            >
                              Not {s.name}
                            </button>
                            {reviewErrors[s.face_id] && (
                              <p role="alert">{reviewErrors[s.face_id]}</p>
                            )}
                          </div>
                        ))}
                        </div>
                      </section>;
                    })}
                  </div>
                  {!!approvedReviews.length && <details onToggle={(event) => setApprovedOpen(event.currentTarget.open)}>
                    <summary>Recently approved — correct a wrong person ({approvedReviews.length})</summary>
                    <p>Choose the correct person or leave unassigned, then click Wrong person. The rejected identity will be excluded from future suggestions. Showing up to 2,000 recent approvals.</p>
                    <div className="suggestion-grid">
                      {approvedOpen && approvedReviews.slice(0, approvedLimit).map((s) => <div key={s.face_id}>
                        <img src={faceThumb(s.face_id)} loading="lazy" decoding="async" alt={`Assigned to ${s.name}`} />
                        <span>{s.name}</span>
                        <select aria-label={`Correct person for ${s.face_id}`} value={correctionTargets[s.face_id] || ""} onChange={(event) => setCorrectionTargets((old) => ({...old,[s.face_id]:event.target.value}))}>
                          <option value="">Leave unassigned</option>
                          {namedCorrectionPeople.filter((p) => p.id !== s.person_id).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                        <button disabled={busy || peopleWorking || approvingAll || !!savingReviews.length} onClick={() => perform("/faces/correct", {face_ids:[s.face_id], action:correctionTargets[s.face_id] ? "move" : "unknown", target:correctionTargets[s.face_id] ? Number(correctionTargets[s.face_id]) : null, expected_person:s.person_id})}>Wrong person</button>
                      </div>)}
                    </div>
                    {approvedOpen && approvedLimit < approvedReviews.length && <button onClick={() => setApprovedLimit((n) => n + 40)}>Show next 40 approvals</button>}
                  </details>}
                </section>
                <section
                  className="group-selection-bar"
                  aria-label="Select unnamed groups"
                >
                  <strong aria-live="polite">
                    {eligibleGroups.length} of {unnamedGroups.length} unnamed
                    groups selected
                  </strong>
                  <div className="builder-actions">
                    <button
                      disabled={
                        busy ||
                        !unnamedGroups.length ||
                        eligibleGroups.length === unnamedGroups.length
                      }
                      onClick={() =>
                        setSelectedGroups(unnamedGroups.map((p) => p.id))
                      }
                    >
                      Select all
                    </button>
                    <button
                      disabled={busy || !eligibleGroups.length}
                      onClick={() => setSelectedGroups([])}
                    >
                      Deselect all
                    </button>
                    <button
                      className="primary"
                      disabled={busy || !eligibleGroups.length}
                      onClick={async () => {
                        setBusy(true);
                        try {
                          const r = await api<{ moved: number }>(
                            "/people/archive-unnamed",
                            { person_ids: eligibleGroups },
                          );
                          setSelectedGroups([]);
                          setReviewMessage(
                            `${r.moved} faces moved to Unknown People. Original groups preserved; use Undo to restore them.`,
                          );
                          setRevision((v) => v + 1);
                        } catch (e) {
                          setError(String(e));
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      Move selected to Unknown People
                    </button>
                  </div>
                  <p className="small-note">
                    Select the checkboxes on unnamed groups below. Named people
                    stay in place. You can still open any card to review its
                    faces.
                  </p>
                </section>
                <div className="people-grid">
                  {people.slice(0, peopleLimit).map((p) => (
                    <div
                      className={
                        "selectable-person " +
                        (eligibleGroups.includes(p.id) ? "group-selected" : "")
                      }
                      key={p.id}
                      data-person-card={p.id}
                    >
                      {p.id > 0 && !p.name?.trim() && (
                        <label className="group-checkbox">
                          <input
                            type="checkbox"
                            aria-label={`Select unnamed person ${p.id}`}
                            disabled={busy}
                            checked={eligibleGroups.includes(p.id)}
                            onChange={() =>
                              setSelectedGroups((old) =>
                                old.includes(p.id)
                                  ? old.filter((id) => id !== p.id)
                                  : [...old, p.id],
                              )
                            }
                          />
                          <span>Select group</span>
                        </label>
                      )}
                      <button
                        className="person-card"
                        key={p.id}
                        onClick={() => openPeopleGroup(p.id)}
                      >
                        <img
                          src={faceThumb(p.cover)}
                          loading="lazy"
                          alt="Suggested face group"
                        />
                        <strong>{p.name || "Unnamed person " + p.id}</strong>
                        <small>
                          {p.count} {p.count === 1 ? "face" : "faces"} ·{" "}
                          {p.id === 0
                            ? "Needs assignment"
                            : p.name
                              ? "Named"
                              : "Needs review"}
                        </small>
                      </button>
                    </div>
                  ))}
                </div>
                {peopleLimit < people.length && <div ref={peopleSentinel} role="status" className="load-more">Scroll for more people · {peopleLimit} of {people.length}</div>}
                {!people.length && (
                  <div className="empty">
                    Face processing is not ready yet. Refresh after indexing
                    completes.
                  </div>
                )}
              </>
            ) : (
              <>
                <button
                  className="text-button back"
                  onClick={returnToPeople}
                >
                  <ArrowLeft size={17} />
                  All people
                </button>
                <div className="identity-form">
                  <input
                    aria-label="Person name"
                    placeholder="Give this person a name"
                    value={personName}
                    onChange={(e) => setPersonName(e.target.value)}
                  />
                  <button
                    className="primary"
                    disabled={
                      busy ||
                      (group !== null && group <= 0) ||
                      !personName.trim()
                    }
                    onClick={() =>
                      perform("/people/" + group + "/name", {
                        name: personName,
                      })
                    }
                  >
                    {activeGroup?.name ? "Rename person" : "Save name"}
                  </button>
                  <button
                    className="outline"
                    disabled={group !== null && group <= 0}
                    onClick={() => {
                      setPeopleFilter([group]);
                      setSettingsOpen(false); setPage("library");
                    }}
                  >
                    View photos
                  </button>
                </div>
                {!activeGroup?.name && group !== null && group > 0 && (
                  <p role="status">{checkingMatch ? "Checking for a match among named people…" : matchError || (!groupMatch ? "No confident named match found." : "")}</p>
                )}
                {!!groupSuggestions.size && (
                  <section
                    className="review-note"
                    aria-label="Suggested group assignments"
                  >
                    <div>
                      <strong>Suggested people for this group</strong>
                      <p>
                        Assign all {faces.length} displayed faces to a suggested
                        person, including faces without an individual
                        suggestion. Check the group first; you can undo the
                        assignment.
                      </p>
                      <div className="builder-actions">
                        {[...groupSuggestions]
                          .sort((a, b) => b[1].count - a[1].count)
                          .map(([personId, suggestion]) => (
                            <div key={personId}>
                              <p className="small-note">
                                {suggestion.count} of {faces.length} faces
                                suggested as {suggestion.name}
                              </p>
                              <button
                                className="primary"
                                disabled={
                                  busy ||
                                  savingReviews.length > 0 ||
                                  !faces.length
                                }
                                onClick={() => {
                                  const ids = faces.map((face) => face.id);
                                  setSelected(ids);
                                  perform("/faces/correct", {
                                    face_ids: ids,
                                    action: "move",
                                    target: personId,
                                  });
                                }}
                              >
                                Mark all as {suggestion.name}
                              </button>
                            </div>
                          ))}
                      </div>
                    </div>
                  </section>
                )}
                <div className="face-toolbar">
                  <span aria-live="polite">
                    {selected.length} of {faces.length} selected
                  </span>
                  {!!activeGroup?.name && group !== null && group > 0 && (
                    <button
                      disabled={!selected.length || busy}
                      onClick={() =>
                        perform("/faces/correct", {
                          face_ids: selected,
                          action: "move",
                          target: group,
                        })
                      }
                    >
                      Confirm selected faces
                    </button>
                  )}
                  <button
                    className="outline"
                    disabled={
                      !faces.length || selected.length === faces.length || busy
                    }
                    onClick={() => setSelected(faces.map((f) => f.id))}
                  >
                    Select all
                  </button>
                  <button
                    className="outline"
                    disabled={!selected.length || busy}
                    onClick={() => setSelected([])}
                  >
                    Deselect all
                  </button>
                  <select
                    aria-label="Move to person"
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                  >
                    <option value="">Move / merge into…</option>
                    {people
                      .filter((p) => p.id !== group && p.id > 0 && !!p.name?.trim())
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name || "Unnamed " + p.id}
                        </option>
                      ))}
                  </select>
                  <button
                    disabled={!selected.length || !target || busy}
                    onClick={() => correct("move")}
                  >
                    Move
                  </button>
                  <button
                    disabled={!selected.length || busy}
                    onClick={() => correct("split")}
                  >
                    Split group
                  </button>
                  <button
                    disabled={!selected.length || busy}
                    onClick={() => correct("unknown")}
                  >
                    Unassign
                  </button>
                  <button
                    disabled={!selected.length || busy}
                    onClick={() => correct("dismiss")}
                  >
                    Not a face
                  </button>
                </div>
                <p className="small-note">
                  Select face crops to correct them. Select all and move to
                  merge groups. You can undo every correction.
                </p>
                <div className="face-grid">
                  {faces.map((f) => (
                    <div
                      key={f.id}
                      className={
                        "face-card " +
                        (selected.includes(f.id) ? "selected" : "")
                      }
                    >
                      <button
                        aria-label="Select face"
                        onClick={() =>
                          setSelected((old) =>
                            old.includes(f.id)
                              ? old.filter((id) => id !== f.id)
                              : [...old, f.id],
                          )
                        }
                      >
                        <img src={faceThumb(f.id)} alt="Detected face" />
                        <span className="face-check">
                          {selected.includes(f.id) && <Check size={16} />}
                        </span>
                      </button>
                      <button
                        className="face-source"
                        onClick={() => open(f.media_id)}
                      >
                        Open source
                        {f.timestamp > 0
                          ? " · " + f.timestamp.toFixed(1) + "s"
                          : ""}
                      </button>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </main>
      <nav className="mobile-nav" inert={sheet || !!detail}>
        <button
          className={!settingsOpen && page === "library" ? "active" : ""}
          onClick={() => {setSettingsOpen(false);setPage("library");}}
        >
          <Images />
          Library
        </button>
        <button
          onClick={() => {
            setSettingsOpen(false); setPage("library");
            setSheet(true);
          }}
        >
          <Search />
          Search
        </button>
        <button
          className={!settingsOpen && page === "people" ? "active" : ""}
          onClick={() => {
            setSettingsOpen(false); setPage("people");
            returnToPeople();
          }}
        >
          <Users />
          People
        </button>
        <button onClick={() => setSheet(true)}>
          <Layers />
          Albums
        </button>
        <button className={settingsOpen ? "active" : ""} aria-label="Library tools" onClick={()=>{window.location.hash="tools/databases";setSettingsOpen(true);}}><HardDrive/>Tools</button>
      </nav>
      {sheet && (
        <div className="overlay" onClick={() => setSheet(false)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-label="Sources, albums and filters"
            className="filter-sheet"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sheet-heading">
              <div>
                <span className="eyebrow">MAKE IT YOUR VIEW</span>
                <h2>Sources & filters</h2>
              </div>
              <button
                aria-label="Close filters"
                onClick={() => setSheet(false)}
              >
                <X />
              </button>
            </div>
            <div className="sheet-scroll">
              <div className="filter-section">
                <h3>
                  <Smartphone size={17} />
                  Sources
                </h3>
                <p>Select Sources here, or choose a Database and Source above the search.</p>
                {phoneNames.map((phone) => (
                  <label className="check-row" key={phone}>
                    <input
                      type="checkbox"
                      checked={scope.includes(phone)}
                      onChange={() => togglePhone(phone)}
                    />
                    <span>{phone}</span>
                    <small>
                      {sources
                        .filter((s) => s.phone === phone)
                        .reduce((a, s) => a + s.count, 0)}
                    </small>
                  </label>
                ))}
              </div>
              <div className="filter-section">
                <h3>
                  <Layers size={17} />
                  Source albums
                </h3>
                <button className="text-button" onClick={() => setAlbums([])}>
                  All albums in selected Sources
                </button>
                {scope.map((phone) => (
                  <details key={phone}>
                    <summary>{phone}</summary>
                    {sources
                      .filter((s) => s.phone === phone)
                      .map((s) => {
                        const value = s.phone + "\x1f" + s.album;
                        return (
                          <label className="check-row" key={value}>
                            <input
                              type="checkbox"
                              checked={albums.includes(value)}
                              onChange={() =>
                                setAlbums((old) =>
                                  old.includes(value)
                                    ? old.filter((a) => a !== value)
                                    : [...old, value],
                                )
                              }
                            />
                            <span>{s.album}</span>
                            <small>{s.count}</small>
                          </label>
                        );
                      })}
                  </details>
                ))}
              </div>
              <div className="filter-section">
                <h3>
                  <CalendarDays size={17} />
                  Date taken
                </h3>
                <div className="date-inputs">
                  <label>
                    From
                    <input
                      type="date"
                      value={start}
                      onChange={(e) => setStart(e.target.value)}
                    />
                  </label>
                  <label>
                    Until
                    <input
                      type="date"
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                  </label>
                </div>
              </div>
              <div className="filter-section">
                <h3>Image orientation</h3>
                <select
                  value={orientation}
                  onChange={(e) => setOrientation(e.target.value)}
                >
                  <option value="">Any orientation</option>
                  <option value="landscape">Landscape</option>
                  <option value="portrait">Portrait</option>
                  <option value="square">Square</option>
                </select>
                <p>Orientation is the image shape, not portrait photography.</p>
              </div>
              <div className="filter-section">
                <h3>
                  <Users size={17} />
                  People · match all selected
                </h3>
                <input
                  aria-label="Find a person or face group"
                  placeholder="Search name or group number"
                  value={peopleQuery}
                  onChange={(e) => setPeopleQuery(e.target.value)}
                />
                <p>
                  Choose named people or suggested groups. Every selected person
                  must appear; suggested identities need review.
                </p>
                <div className="people-filter-list">
                  {people
                    .filter(
                      (p) =>
                        p.id > 0 &&
                        (p.name || "Group " + p.id)
                          .toLowerCase()
                          .includes(peopleQuery.toLowerCase()),
                    )
                    .map((p) => (
                      <label key={p.id} className="check-row">
                        <input
                          type="checkbox"
                          checked={peopleFilter.includes(p.id)}
                          onChange={() =>
                            setPeopleFilter((old) =>
                              old.includes(p.id)
                                ? old.filter((id) => id !== p.id)
                                : [...old, p.id],
                            )
                          }
                        />
                        <img
                          src={faceThumb(p.cover)}
                          loading="lazy"
                          alt=""
                          width="32"
                          height="32"
                          style={{ borderRadius: "50%", objectFit: "cover" }}
                        />
                        {p.name || "Group " + p.id + " · suggested"}
                      </label>
                    ))}
                </div>
              </div>
            </div>
            <div className="sheet-actions">
              <button className="text-button" onClick={reset}>
                Reset all
              </button>
              <button className="primary" onClick={() => setSheet(false)}>
                Show {total} moments
              </button>
            </div>
          </section>
        </div>
      )}
      {detail && (
        <div className={"overlay viewer-overlay"+(expanded?" viewer-expanded-overlay":"")} onClick={closeViewer}>
          <section
            role="dialog"
            aria-modal="true"
            aria-label="Media details"
            ref={viewerElement}
            className={"viewer"+(expanded?" viewer-expanded":"")}
            onClick={(e) => e.stopPropagation()}
          >
            {expanded && fullscreenHint && <div className="fullscreen-tip" role="status"><span>{fullscreenHint}</span><button aria-label="Dismiss fullscreen help" onClick={()=>setFullscreenHint("")}>×</button></div>}
            {editingFace&&<button
              className="viewer-close"
              aria-label="Close viewer"
              onClick={closeViewer}
            >
              <X />
            </button>}
            <div className="viewer-media">
              {editingFace && detail.kind === "photo" ? (
                <FaceEditor
                  key={detail.id}
                  id={detail.id}
                  faces={detail.faces}
                  people={people}
                  onClose={() => setEditingFace(false)}
                  onSaved={async () => {
                    const fresh = await api<Detail>("/media/" + detail.id);
                    setDetail((current) =>
                      current?.id === fresh.id ? fresh : current,
                    );
                    setRevision((v) => v + 1);
                  }}
                />
              ) : <MediaViewerStage key={detail.id} id={detail.id} name={detail.name} width={detail.width||1} height={detail.height||1} imageUrl={thumb(detail.id,"large")} direction={slideDirection} departingImage={departingImage} onClose={closeViewer} onEditFaces={()=>{collapseViewer();setEditingFace(true);}} videoUrl={preview} kind={detail.kind} expanded={expanded} onToggleExpanded={toggleExpanded} {...neighbors} busy={viewerBusy} onNavigate={open}/>}
            </div>
            <aside className="viewer-info">
              <span className="eyebrow">
                {detail.kind === "video" ? "VIDEO" : "PHOTOGRAPH"}
              </span>
              <h2>{detail.name}</h2>
              {detail.kind==="photo"&&<div className="viewer-face-entry"><button className="primary" onClick={()=>{collapseViewer();setEditingFace(v=>!v);}}>{editingFace?"Close face editor":"Add a missed face / edit faces"}</button>{!detail.faces.length&&<p>No faces detected. You can mark a face manually.</p>}</div>}
              <button className="primary" onClick={()=>{collapseViewer();setEditingMetadata(v=>!v);}}>{editingMetadata?'Close date/location editor':'Edit date & location'}</button>
              {editingMetadata&&<MetadataEditor ids={[detail.id]} count={1} onSaved={metadataSaved} onClose={()=>setEditingMetadata(false)}/>}
              <dl>
                <dt>Phone</dt>
                <dd>{detail.phone}</dd>
                {(()=>{const location=albumLocation({album:detail.album,albumKey:detail.album_relative_path,relative:detail.relative_path,sourceKey:detail.source_relative_path});return <><dt>Album</dt><dd>{location.album}</dd>{location.subAlbum&&<><dt>Sub Album</dt><dd className="viewer-sub-album">{location.subAlbum}</dd></>}</>;})()}
                <dt>Date taken</dt>
                <dd>
                  {captureLabel(detail)}
                </dd>
                <dt>Location</dt>
                <dd>
                  {detail.location_label || [detail.city && `Near ${detail.city}`, detail.country]
                    .filter(Boolean)
                    .join(", ") ||
                    (detail.latitude !== null
                      ? "GPS available; name unresolved"
                      : "Unknown — no GPS found")}
                </dd>
                <dt>Location provenance</dt><dd>{detail.location_source==='manual'?`Entered by user · ${detail.location_precision==='place'?'place only, no GPS coordinates':'manual point'}`:detail.location_source==='embedded'?'Embedded GPS':'Unknown'}</dd>
                <dt>Embedded capture date</dt><dd>{detail.embedded_taken||'Absent'}{detail.embedded_date_field?' · '+detail.embedded_date_field:''}</dd>
                <dt>File created</dt><dd>{detail.file_created?new Date(detail.file_created*1000).toLocaleString():'Unavailable in the existing catalogue'}</dd>
                <dt>File modified</dt><dd>{detail.file_modified?new Date(detail.file_modified*1000).toLocaleString():'Unknown'}</dd>
                <dt>First recorded index</dt><dd>{detail.imported_at?new Date(detail.imported_at).toLocaleString():'Not recorded for this earlier import'}</dd>
                <dt>People tags</dt>
                <dd>
                  {detail.people_names?.join(", ") ||
                    "No named people detected"}
                </dd>
                <dt>Dimensions</dt>
                <dd>
                  {detail.width} × {detail.height}
                </dd>
              </dl>
              {detail.latitude !== null &&
                detail.longitude !== null &&
                Number.isFinite(detail.latitude) &&
                Number.isFinite(detail.longitude) &&
                Math.abs(detail.latitude) <= 90 &&
                Math.abs(detail.longitude) <= 180 && (
                  <LocationMap
                    key={detail.id}
                    latitude={detail.latitude}
                    longitude={detail.longitude}
                    city={detail.city}
                    country={detail.country}
                  />
                )}
              {detail.kind === "video" && (
                <>
                  <button
                    disabled={busy}
                    className="primary"
                    onClick={async () => {
                      const sequence=viewerSequence.current;
                      setBusy(true);
                      try {
                        const result = await api<{ url: string }>(
                          "/media/" + detail.id + "/preview",
                          {},
                        );
                        if(sequence===viewerSequence.current)setPreview(result.url);
                      } catch (e) {
                        setError(String(e));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    <Play size={17} />
                    {busy ? "Preparing…" : "Play 60-second preview"}
                  </button>
                  <p className="small-note">
                    Generated locally. The original stays untouched.
                  </p>
                </>
              )}
              <a
                className="outline"
                href={"/api/media/" + detail.id + "/original"}
                onClick={event=>{if(isIOSStandalone()){event.preventDefault();window.dispatchEvent(new CustomEvent("dahan:save-original",{detail:{id:detail.id}}));}}}
                target="_blank"
                rel="noreferrer"
              >
                Open original
              </a>
              <p className="small-note">
                Object and scenery tags are not available yet.
              </p>

              <h3>Faces in this moment</h3>
              <div className="detail-faces">
                {detail.faces.map((f) => (
                  <button
                    key={f.id}
                    onClick={() => {
                      if (f.person_id) {
                        openPeopleGroup(f.person_id);
                        setSettingsOpen(false); setPage("people");
                        closeViewer();
                      }
                    }}
                  >
                    <img src={faceThumb(f.id)} alt="Detected face" />
                    <small>
                      {f.name || "Unnamed"}
                      {f.timestamp > 0
                        ? " · " + f.timestamp.toFixed(1) + "s"
                        : ""}
                    </small>
                  </button>
                ))}
              </div>
              <details>
                <summary>Embedded metadata</summary>
                <pre>{JSON.stringify(detail.metadata, null, 2)}</pre>
              </details>
            </aside>
          </section>
        </div>
      )}
      <AppUpdates canReload={!detail && !settingsOpen && !busy && !peopleWorking && !approvingAll && page === "library"} />
      {notice && (
        <div role="status" className="toast">
          <Check size={17} />
          {notice}
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
