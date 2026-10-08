import {withMediaFilter,selectedMediaFilter} from "./mediaFilter";
import {searchSuggestions,acceptSuggestion,normalizeSearch,deviceKey,type SearchItem,type Suggestion} from "./searchSuggestions";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { GeoMap, preloadMapBoundaries, emptyGeo, type GeoSelection } from "./SearchWorkspace";
type Person = { id: number; name: string | null };
type Source = { phone: string; album: string; count: number };
type Place = { id: string; label: string; kind: string; country: string; search_aliases?: string[] };
const quote = (value: string) => JSON.stringify(value);
const toggle = (items: string[], value: string) =>
  items.includes(value) ? items.filter((x) => x !== value) : [...items, value];
const joinOr = (terms: string[]) =>
  terms.length ? `(${terms.join(" or ")})` : "";
const emptyParts: Record<string, string> = {};
export default function UnifiedSearch({
  people,
  sources,
  sourceSelection,
  onSourceChange,
  expression,
  onApply,
  query,
  resultsLoading,
  children,
}: {
  people: Person[];
  sources: Source[];
  sourceSelection: string[];
  onSourceChange: (sources:string[])=>void;
  expression: string;
  onApply: (value: string) => void;
  query: string;
  resultsLoading: boolean;
  children: (mediaControl: ReactNode) => ReactNode;
}) {
  const [panel, setPanel] = useState("");
  const [base, setBase] = useState(expression);
  const [parts, setParts] = useState<Record<string, string>>(emptyParts);
  const [draft, setDraft] = useState(expression);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const version = useRef(0);
  const lastCommitted = useRef<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const [personQuery, setPersonQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [mode, setMode] = useState("Includes");
  const [placeQuery, setPlaceQuery] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [geo, setGeo] = useState<GeoSelection>(emptyGeo);
  const [year, setYear] = useState("");
  const [dates, setDates] = useState({ from: "", until: "" });
  const [albumQuery, setAlbumQuery] = useState("");
  const [albums, setAlbums] = useState<string[]>([]);
  const [kind, setKind] = useState("");
  const [orientation, setOrientation] = useState("");
  const [mapResults, setMapResults] = useState({
    points: [],
    total: 0,
    known: 0,
    unknown: 0,
  });
  const [mapContext, setMapContext] = useState(mapResults);
  const mapCache = useRef(new Map<string, Promise<any>>());
  const [resetMapPreview, setResetMapPreview] = useState(false);
  const [mapGeneration,setMapGeneration] = useState(0);
  const [mapLoadedQuery,setMapLoadedQuery] = useState<string | null>(null);
  const mapDialog = useRef<HTMLElement>(null);
  const [mapPending, setMapPending] = useState(false);
  const [mapError, setMapError] = useState("");
  const [cursor,setCursor]=useState(0);
  const [suggestionsOpen,setSuggestionsOpen]=useState(false);
  const [activeSuggestion,setActiveSuggestion]=useState(-1);
  const placeRequest=useRef<Promise<Place[]> | null>(null);
  function loadPlaces(){
    if(!placeRequest.current)placeRequest.current=fetch("/api/place-options").then(r=>{if(!r.ok)throw Error("Could not load place suggestions");return r.json();}).then(r=>{setPlaces(r.options);return r.options;}).catch(e=>{placeRequest.current=null;throw e;});
    return placeRequest.current;
  }
  const phoneNames = [...new Set(sources.map((s) => s.phone))];
  const labels = useMemo(() => {
    const counts = new Map<string, number>();
    people.forEach((p) => {
      if (p.name)
        counts.set(
          p.name.toLowerCase(),
          (counts.get(p.name.toLowerCase()) || 0) + 1,
        );
    });
    return people
      .filter((p) => p.id > 0 && p.name?.trim())
      .map((p) => ({
        id: p.id,
        name: p.name!,
        label:
          (counts.get(p.name!.toLowerCase()) || 0) > 1
            ? `${p.name} [#${p.id}]`
            : p.name!,
      }));
  }, [people]);
  const suggestionItems=useMemo<SearchItem[]>(()=>[
    {label:"Photos only",value:"photo",kind:"Media",aliases:["photos","images","only photos","only images"]},
    {label:"Videos only",value:"video",kind:"Media",aliases:["videos","only videos"]},
    {label:"All phones",value:"__all_phones__",kind:"Device",aliases:["All Phone","All devices"]},
    ...labels.map(p=>({label:p.label,value:p.label,kind:"Person"})),
    ...places.map(p=>({label:p.kind==="city"?p.label+" · "+p.country:p.label,value:p.id,kind:p.kind==="country"?"Country":"City",aliases:[p.label,...p.search_aliases||[]]})),
    ...[...new Set(sources.map(s=>s.phone))].map(p=>({label:p,value:p,kind:"Device"})),
    ...sources.map(s=>({label:s.album+" · "+s.phone,value:s.phone+"\x1f"+s.album,kind:"Album",aliases:[s.album]}))
  ],[labels,places,sources]);
  const suggestions=useMemo(()=>searchSuggestions(draft,cursor,suggestionItems),[draft,cursor,suggestionItems]);
  function editDraft(value:string,position:number){
    version.current++;setBusy(false);setError("");setDraft(value);setBase(value);setParts({});clearWidgets();setCursor(position);setActiveSuggestion(-1);setSuggestionsOpen(!!value);
    if(!value.trim()){lastCommitted.current="";setDraft("");setBase("");onApply("");}
  }
  function complete(s:Suggestion){
    const next=acceptSuggestion(draft,s);editDraft(next.value,next.cursor);setSuggestionsOpen(s.kind==="Command" || s.kind==="Date phrase" || next.value.slice(0,next.cursor).endsWith(" and "));
    requestAnimationFrame(()=>{input.current?.focus();input.current?.setSelectionRange(next.cursor,next.cursor);});
  }
  function clearWidgets() {
    setYear("");
    setExcluded([]);
    setSelected([]);
    setGeo(emptyGeo);
    setResetMapPreview(true);
    setMapGeneration(n=>n+1);
    setDates({ from: "", until: "" });
    setAlbums([]);
    setKind("");
    setOrientation("");
  }
  useEffect(() => {
    if (lastCommitted.current === expression) return;
    version.current++;
    setBusy(false);
    setBase(expression);
    setParts({});
    setDraft(expression);
    setError("");
    clearWidgets();
  }, [expression]);
  function update(key: string, value: string) {
    version.current++;
    setBusy(false);
    setError("");
    const next = { ...parts, [key]: value };
    setParts(next);
    setDraft(
      [base ? `(${base})` : "", ...Object.values(next)]
        .filter(Boolean)
        .join(" and "),
    );
  }
  function changeGeo(next: GeoSelection) {
    setGeo(next);
    setResetMapPreview(!next.includes.length && !next.excludes.length);
    const positive = [
      ...next.places.map((id) => `Place(${quote(id)})`),
      ...(next.unknown ? ['Location("unknown")'] : []),
      ...next.includes.map(
        (a) => `Area(${quote([a.south, a.north, a.west, a.east].join(","))})`,
      ),
    ];
    const negative = next.excludes.map(
      (a) => `not Area(${quote([a.south, a.north, a.west, a.east].join(","))})`,
    );
    update(
      "geography",
      [joinOr(positive), ...negative].filter(Boolean).join(" and "),
    );
  }
  function peoplePart(names: string[], nextMode = mode) {
    setSelected(names);
    setMode(nextMode);
    update(
      "people",
      names.length ? `${nextMode} (${names.map(quote).join(" and ")})` : "",
    );
  }
  function changeDates(next: typeof dates) {
    setYear("");
    setDates(next);
    update(
      "dates",
      [
        next.from ? `date >= ${next.from}` : "",
        next.until ? `date <= ${next.until}` : "",
      ]
        .filter(Boolean)
        .join(" and "),
    );
  }
  async function apply(closeMap = false, mediaOverride?: string) {
    if (busy) return;
    if (dates.from && dates.until && dates.from > dates.until) {
      setError("From date must not be later than Through date.");
      return;
    }
    const attempt = ++version.current;
    setBusy(true);
    setError("");
    let value = mediaOverride === undefined ? draft.trim() : withMediaFilter(draft,mediaOverride);
    let bare = value;
    try {
      if (value.startsWith('"')) bare = JSON.parse(value);
    } catch {}
    setSuggestionsOpen(false);
    try {
      if(value && !/^(includes|only|just|person|place|not|date|phone|allphones|album|mediatype|orientation|text|area|location|after|before|between|since|until|through|on|in|during)\b|[()<>=!]|&&|\|\|/i.test(value) && !/\b(and|or)\b/i.test(bare)){
        const knownPlaces=await loadPlaces();
        const person=labels.some(p=>normalizeSearch(p.name)===normalizeSearch(bare)||normalizeSearch(p.label)===normalizeSearch(bare));
        const place=knownPlaces.some(p=>[p.label,p.id,...p.search_aliases||[]].some(a=>normalizeSearch(a)===normalizeSearch(bare)));
        const phone=phoneNames.some(p=>deviceKey(p)===deviceKey(bare)) || ["allphone","allphones","alldevices"].includes(deviceKey(bare));
        const media=["photo","photos","image","images","video","videos","photos only","images only","videos only"].includes(bare.toLowerCase());
        value=person||place||phone||media?quote(bare):'Text('+quote(bare)+')';
      }
      const response = await fetch(
        "/api/search/validate?" + new URLSearchParams({ expression: value }),
      );
      const result = await response.json();
      if (!response.ok)
        throw Error(
          typeof result.detail === "string"
            ? result.detail
            : "Invalid search expression",
        );
      if (attempt === version.current) {
        value = result.expression ?? value;
        lastCommitted.current = value;
        setDraft(value);
        if(mediaOverride!==undefined){setBase(value);setParts({});clearWidgets();}
        setResetMapPreview(false);
        mapCache.current.delete(query);
        onApply(value);
        if (closeMap) setPanel("");
      }
    } catch (e) {
      if (attempt === version.current)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (attempt === version.current) setBusy(false);
    }
  }
  useEffect(() => {void loadPlaces().catch(()=>{});}, []);
  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      void preloadMapBoundaries().catch(() => {});
      setMapPending(true); setMapError("");
      let task = mapCache.current.get(query);
      if (!task) {
        task = Promise.all(["/api/map-results?", "/api/map-context?"].map(path => fetch(path + query).then(r => {
          if (!r.ok) throw Error("Could not load map");
          return r.json();
        })));
        mapCache.current.set(query, task);
        task.catch(() => mapCache.current.delete(query));
        while (mapCache.current.size > 3) mapCache.current.delete(mapCache.current.keys().next().value!);
      }
      task.then(([results, context]) => {
        if (active) { setMapResults(results); setMapContext(context); setMapLoadedQuery(query); }
      }).catch(e => { if (active) setMapError(e.message); })
        .finally(() => { if (active) setMapPending(false); });
    }, panel === "Map" ? 0 : 250);
    return () => { active = false; window.clearTimeout(timer); };
  }, [panel, query]);
  useEffect(() => {
    if (panel !== "Map") return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = mapDialog.current;
    dialog?.querySelector<HTMLButtonElement>("button")?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); setPanel(""); }
      if (e.key !== "Tab" || !dialog) return;
      const items = [...dialog.querySelectorAll<HTMLElement>("button:not(:disabled), input, summary, a[href]")].filter(el => el.getClientRects().length);
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); previous?.focus({preventScroll:true}); };
  }, [panel]);
  return (
    <div className="unified-search-shell">
      <header className="master-search-header">
        <div className="page-heading">
          <div>
            <span className="eyebrow">ALL THE LITTLE MOMENTS</span>
            <h1>Your library</h1>
            <p>Find your people, places and shared memories.</p>
          </div>
        </div>
        <section className="device-strip" aria-label="Search sources">
          <strong>Search sources</strong>
          <div className="device-buttons">
            <button aria-pressed={phoneNames.length>0&&phoneNames.every(name=>sourceSelection.includes(name))} disabled={!phoneNames.length} onClick={()=>onSourceChange(phoneNames.every(name=>sourceSelection.includes(name))?[]:phoneNames)}>All</button>
            {phoneNames.map(name=><button key={name} aria-pressed={sourceSelection.includes(name)} onClick={()=>onSourceChange(toggle(sourceSelection,name))}>{name}</button>)}
          </div>
        </section>
        <p className="small-note master-help">
          Source selections apply immediately. Apply search text and helper changes
          with Enter or Search.
        </p>
        <div className="master-search-row">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void apply();
            }}
          >
            <div className="search-input-wrap">
            <input
              ref={input}
              type="search"
              aria-label="Search photos"
              aria-invalid={!!error}
              aria-describedby="master-search-error"
              value={draft}
              placeholder='Person name, filename, or Includes ("Name") and Place("Italy")'
              autoComplete="off"
              role="combobox"
              aria-autocomplete="list"
              aria-controls="search-suggestions"
              aria-expanded={suggestionsOpen && suggestions.length>0}
              aria-activedescendant={suggestionsOpen && activeSuggestion>=0 ? "search-suggestion-"+activeSuggestion : undefined}
              onFocus={()=>{setSuggestionsOpen(!!draft);setCursor(input.current?.selectionStart??draft.length);}}
              onBlur={()=>setSuggestionsOpen(false)}
              onSelect={(e)=>{setCursor(e.currentTarget.selectionStart??0);setActiveSuggestion(-1);}}
              onClick={()=>setSuggestionsOpen(!!draft)}
              onKeyDown={(e)=>{
                if(e.nativeEvent.isComposing)return;
                if(e.key==="Escape"){setSuggestionsOpen(false);setActiveSuggestion(-1);e.stopPropagation();}
                else if((e.key==="ArrowDown"||e.key==="ArrowUp") && suggestions.length){e.preventDefault();setSuggestionsOpen(true);setActiveSuggestion(i=>(i+(e.key==="ArrowDown"?1:-1)+suggestions.length)%suggestions.length);}
                else if(e.key==="Enter" && suggestionsOpen && activeSuggestion>=0 && suggestions[activeSuggestion]){e.preventDefault();complete(suggestions[activeSuggestion]);}
              }}
              onChange={(e)=>editDraft(e.target.value,e.target.selectionStart??e.target.value.length)}
            />
            {draft && <button type="button" className="search-clear" aria-label="Clear search" onClick={()=>{editDraft("",0);input.current?.focus();setSuggestionsOpen(false);}}>×</button>}
            </div>
            {suggestionsOpen && suggestions.length>0 && <div id="search-suggestions" className="search-suggestions" role="listbox" aria-label="Search suggestions">
              {suggestions.map((s,i)=><button type="button" role="option" id={"search-suggestion-"+i} aria-selected={i===activeSuggestion} key={s.kind+":"+s.label+":"+i} onPointerDown={e=>e.preventDefault()} onClick={()=>complete(s)}><span>{s.label}</span><small>{s.kind}</small></button>)}
            </div>}
            <button className="primary" disabled={busy}>
              {busy ? "Checking…" : "Search"}
            </button>
          </form>
          <nav aria-label="Search helpers">
            {["People", "Places", "Dates", "Media", "Albums & more", "Map"].map(
              (name) => (
                <button
                  key={name}
                  aria-expanded={panel === name}
                  aria-controls="search-helper-panel"
                  onClick={() => setPanel(panel === name ? "" : name)}
                >
                  {name}
                </button>
              ),
            )}
          </nav>
        </div>
        <span className="search-status-announcement" role="status">{draft !== expression ? "Search changed. Press Search or Enter to apply." : "Search applied"}</span>
        {error && (
          <p id="master-search-error" role="alert" className="error">
            {error}
          </p>
        )}
      </header>
      {panel && (
        <section
          id="search-helper-panel"
          ref={mapDialog}
          role={panel === "Map" ? "dialog" : undefined}
          aria-modal={panel === "Map" ? true : undefined}
          className={`search-helper-panel ${panel === "Map" ? "map-search-dialog" : ""}`}
          aria-label={`${panel} search controls`}
        >
          <div className="helper-title">
            <strong>{panel === "Map" ? "Choose locations" : panel}</strong>
            {panel === "Map" && <button className="primary" disabled={busy} onClick={() => void apply(true)}>Apply search</button>}
            <button
              aria-label="Close search helper"
              onClick={() => setPanel("")}
            >
              Close
            </button>
          </div>
          <div className="helper-scroll">
            {base && panel !== "Map" && (
              <p className="small-note">
                Selections here are added to the expression already in the
                search bar. Edit the bar to change existing clauses, or clear it
                to start a new search.
              </p>
            )}
            {panel === "People" && (
              <>
                <div className="builder-actions">
                  {["Includes", "Just", "Only"].map((value) => (
                    <button
                      key={value}
                      aria-pressed={mode === value}
                      onClick={() => peoplePart(selected, value)}
                    >
                      {value}
                    </button>
                  ))}
                </div>
                <input
                  aria-label="Find named people"
                  placeholder="Find a saved person"
                  value={personQuery}
                  onChange={(e) => setPersonQuery(e.target.value)}
                />
                <div className="helper-options">
                  {labels
                    .filter((p) =>
                      p.name.toLowerCase().includes(personQuery.toLowerCase()),
                    )
                    .map((p) => (
                      <label key={p.id}>
                        <input
                          type="checkbox"
                          checked={selected.includes(p.label)}
                          onChange={() => peoplePart(toggle(selected, p.label))}
                        />
                        {p.label}
                      </label>
                    ))}
                </div>
                <label>
                  Exclude a person
                  <select
                    aria-label="Exclude a person"
                    value=""
                    onChange={(e) => {
                      const next = [...new Set([...excluded, e.target.value])];
                      setExcluded(next);
                      update(
                        "excluded",
                        next
                          .map((name) => `not Includes (${quote(name)})`)
                          .join(" and "),
                      );
                    }}
                  >
                    <option value="">Choose a named person…</option>
                    {labels.map((p) => (
                      <option key={p.id} value={p.label}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="builder-actions">
                  {excluded.map((name) => (
                    <button
                      key={name}
                      onClick={() => {
                        const next = excluded.filter((n) => n !== name);
                        setExcluded(next);
                        update(
                          "excluded",
                          next
                            .map((n) => `not Includes (${quote(n)})`)
                            .join(" and "),
                        );
                      }}
                    >
                      Remove exclusion: {name}
                    </button>
                  ))}
                </div>
                <p className="small-note">
                  Includes allows other people. Just allows unnamed extras. Only
                  excludes all other detected faces.
                </p>
              </>
            )}
            {panel === "Places" && (
              <>
                <input
                  aria-label="Find countries and cities"
                  placeholder="Country or city"
                  value={placeQuery}
                  onChange={(e) => setPlaceQuery(e.target.value)}
                />
                <label>
                  <input
                    type="checkbox"
                    checked={geo.unknown}
                    onChange={() =>
                      changeGeo({ ...geo, unknown: !geo.unknown })
                    }
                  />
                  Location unknown
                </label>
                <div className="helper-options">
                  {places
                    .filter((p) =>
                      (p.label + " " + p.country)
                        .toLowerCase()
                        .includes(placeQuery.toLowerCase()),
                    )
                    .map((p) => (
                      <label key={p.id}>
                        <input
                          type="checkbox"
                          checked={geo.places.includes(p.id)}
                          onChange={() =>
                            changeGeo({
                              ...geo,
                              places: toggle(geo.places, p.id),
                            })
                          }
                        />
                        {p.label}
                        {p.kind === "city" ? ` · ${p.country}` : " (country)"}
                      </label>
                    ))}
                </div>
                <button
                  onClick={() =>
                    changeGeo({ ...geo, places: [], unknown: false })
                  }
                >
                  Clear places
                </button>
              </>
            )}
            {panel === "Media" && <div className="builder-actions">{[["","Photos & videos"],["photo","Photos only"],["video","Videos only"]].map(([value,label])=><button key={label} aria-pressed={kind===value} onClick={()=>{setKind(value);update("kind",value?'MediaType('+quote(value)+')':'');}}>{label}</button>)}</div>}
            {panel === "Dates" && (
              <>
                <p>Choose an inclusive date range, or type a date phrase in search.</p>
                <p className="small-note">Try “after May 2025”, “between May 2025 and April 2026”, or “&gt; May 21. 2024”. After/before exclude the named day or month; between includes both endpoints.</p>
                <div className="date-inputs">
                  <label>
                    From
                    <input
                      aria-label="From date"
                      type="date"
                      value={dates.from}
                      onChange={(e) =>
                        changeDates({ ...dates, from: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Through
                    <input
                      aria-label="Through date"
                      type="date"
                      min={dates.from || undefined}
                      value={dates.until}
                      onChange={(e) =>
                        changeDates({ ...dates, until: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Year
                    <input
                      aria-label="Search year"
                      type="number"
                      min="1"
                      max="9999"
                      placeholder="2025"
                      value={year}
                      onChange={(e) => {
                        setYear(e.target.value);
                        const n = Number(e.target.value);
                        if (n >= 1 && n <= 9999) {
                          setDates({ from: "", until: "" });
                          update("dates", `date = ${n}`);
                        } else if (!e.target.value) update("dates", "");
                      }}
                    />
                  </label>
                </div>
                <button onClick={() => changeDates({ from: "", until: "" })}>
                  Clear dates
                </button>
              </>
            )}
            {panel === "Albums & more" && (
              <>
                <div className="builder-actions">
                  <label>
                    Media type
                    <select
                      aria-label="Media type"
                      value={kind}
                      onChange={(e) => {
                        setKind(e.target.value);
                        update(
                          "kind",
                          e.target.value
                            ? `MediaType(${quote(e.target.value)})`
                            : "",
                        );
                      }}
                    >
                      <option value="">All media</option>
                      <option value="photo">Photos</option>
                      <option value="video">Videos</option>
                    </select>
                  </label>
                  <label>
                    Orientation
                    <select
                      aria-label="Image orientation"
                      value={orientation}
                      onChange={(e) => {
                        setOrientation(e.target.value);
                        update(
                          "orientation",
                          e.target.value
                            ? `Orientation(${quote(e.target.value)})`
                            : "",
                        );
                      }}
                    >
                      <option value="">Any orientation</option>
                      <option value="portrait">Portrait</option>
                      <option value="landscape">Landscape</option>
                      <option value="square">Square</option>
                    </select>
                  </label>
                </div>
                <input
                  aria-label="Find albums"
                  placeholder="Find an album"
                  value={albumQuery}
                  onChange={(e) => setAlbumQuery(e.target.value)}
                />
                <div className="helper-options">
                  {sources
                    .filter((s) =>
                      (s.phone + " " + s.album)
                        .toLowerCase()
                        .includes(albumQuery.toLowerCase()),
                    )
                    .map((s) => {
                      const id = s.phone + "\x1f" + s.album;
                      return (
                        <label key={id}>
                          <input
                            type="checkbox"
                            checked={albums.includes(id)}
                            onChange={() => {
                              const next = toggle(albums, id);
                              setAlbums(next);
                              update(
                                "albums",
                                joinOr(
                                  next.map((value) => `Album(${quote(value)})`),
                                ),
                              );
                            }}
                          />
                          {s.album || "Main folder"} · {s.phone}
                        </label>
                      );
                    })}
                </div>
              </>
            )}
            {panel === "Map" && (
              <>
                <p className="small-note">
                  Locations stay visible across area searches. Dashed markers are outside the applied results. Clear areas resets the map preview; Apply search updates the gallery.
                </p>
                {mapError && <p role="alert">{mapError}</p>}
                <GeoMap
                  key={mapGeneration}
                  geo={geo}
                  onGeo={changeGeo}
                  results={mapLoadedQuery === query ? mapContext : {points:[],total:0,known:0,unknown:0}}
                  matching={mapLoadedQuery === query ? (resetMapPreview ? mapContext : mapResults) : {points:[],total:0,known:0,unknown:0}}
                  pending={mapPending || mapLoadedQuery !== query}
                />
                <div className="map-draft-status" role="status">{mapPending || mapLoadedQuery !== query ? "Updating map…" : draft !== expression ? "Selection changed — press Apply search" : `${mapResults.total.toLocaleString()} matching moments`}</div>
                {error && <p role="alert">{error}</p>}
              </>
            )}
          </div>
        </section>
      )}
      <div className={"unified-gallery-scroll"+((resultsLoading||busy)?" results-pending":"")} aria-label="Search results" aria-busy={resultsLoading||busy}>
        {(resultsLoading||busy) && <div className="results-loading-anchor"><div className="results-loading-banner" role="status" aria-live="polite"><span className="results-loading-spinner" aria-hidden="true"/><div><strong>{busy?"Preparing your search…":"Results loading…"}</strong><span>{busy?"Checking your search criteria":"Updating photos and videos for your search"}</span></div><div className="results-loading-progress" aria-hidden="true"/></div></div>}
        {children(<select className="gallery-media-filter" aria-label="Show photos or videos" value={selectedMediaFilter(expression)} disabled={busy} onChange={e=>void apply(false,e.target.value)}><option value="">Photos &amp; Videos</option><option value="photo">Photos</option><option value="video">Videos</option>{selectedMediaFilter(expression)==="custom"&&<option value="custom" disabled>Custom media filter</option>}</select>)}
      </div>
    </div>
  );
}
