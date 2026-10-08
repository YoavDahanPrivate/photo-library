import { useEffect, useState, useRef, useMemo } from "react";

type Person = { id: number; name: string | null };
type Place = { id: string; label: string; country: string };
const quote = (s: string) => JSON.stringify(s);

export default function SearchBuilder({
  people,
  expression,
  onApply,
  openRequest,
  draft,
  onDraftChange: setDraft,
  onEdit,
  editVersion,
}: {
  openRequest: number;
  draft: string;
  onDraftChange: (value:string)=>void;
  onEdit: ()=>void;
  editVersion:number;
  people: Person[];
  expression: string;
  onApply: (s: string) => void;
}) {
  const panel = useRef<HTMLDetailsElement>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (openRequest && panel.current) {
      panel.current.open = true;
      setExpanded(true);
      panel.current
        .querySelector<HTMLInputElement>("input")
        ?.focus({ preventScroll: true });
    }
  }, [openRequest]);
  const [selected, setSelected] = useState<number[]>([]),
    [excluded, setExcluded] = useState<number[]>([]);
  const [mode, setMode] = useState("Includes"),
    [locations, setLocations] = useState<string[]>([]),
    [join, setJoin] = useState("or");
  const [places, setPlaces] = useState<Place[]>([]),
    [personQuery, setPersonQuery] = useState("");
  const [manual, setManual] = useState(!!expression),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {if (editVersion) setManual(true);}, [editVersion]);
  const [from, setFrom] = useState(""),
    [until, setUntil] = useState("");
  const labels = useMemo(() => {
    const counts = new Map<string, number>();
    for (const person of people) if (person.name) {
      const key = person.name.toLocaleLowerCase();
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return new Map(people.map((person) => {
      const label = person.name || `Group ${person.id}`;
      return [person.id, (counts.get(label.toLocaleLowerCase()) || 0) > 1 ? `${label} [#${person.id}]` : label];
    }));
  }, [people]);
  const name = (id:number) => labels.get(id) || `Group ${id}`;
  const names = selected.map((id) => quote(name(id))).join(" and ");
  const terms: string[] = [];
  if (names) terms.push(`${mode} (${names})`);
  excluded.forEach((id) => terms.push(`not Includes (${quote(name(id))})`));
  if (locations.length)
    terms.push(
      "(" +
        locations
          .map(
            (id) =>
              `Place(${quote(places.filter((p) => p.label === places.find((x) => x.id === id)?.label).length === 1 ? places.find((p) => p.id === id)!.label : id)})`,
          )
          .join(` ${join} `) +
        ")",
    );
  if (from) terms.push(`date >= ${from}`);
  if (until) terms.push(`date <= ${until}`);
  const generated = terms.join(" and ");
  useEffect(() => {
    let active = true;
    fetch("/api/place-options")
      .then((r) => r.json())
      .then((r) => {
        if (active) setPlaces(r.options);
      })
      .catch(() => {
        if (active) setError("Could not load places. Reopen search to retry.");
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (!manual) setDraft(generated);
  }, [generated, manual]);
  useEffect(() => {
    if (expression === "") {
      setSelected([]);
      setExcluded([]);
      setLocations([]);
      setFrom("");
      setUntil("");
      setDraft("");
      setManual(false);
    }
  }, [expression]);
  async function apply() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch(
        "/api/search/validate?" + new URLSearchParams({ expression: draft }),
      );
      const data = await r.json();
      if (!r.ok)
        throw Error(
          typeof data.detail === "string" ? data.detail : "Invalid search",
        );
      onApply(draft);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="search-builder" ref={panel} onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary>
        Build or edit a search {expression && <span>· Search active</span>}
      </summary>
      {expanded && <div className="builder-body">
        <div className="builder-actions builder-pinned-actions">
          <button onClick={() => {if (manual) setManual(false); else {setManual(true);onEdit();}}}>
            {manual ? "Start a new builder draft" : "Edit expression"}
          </button>
          <button className="primary" disabled={busy} onClick={apply}>
            {busy ? "Checking…" : "Apply search"}
          </button>
          <button
            onClick={() => {
              setError("");
              setSelected([]);
              setExcluded([]);
              setLocations([]);
              setFrom("");
              setUntil("");
              setDraft("");
              setManual(false);
              onApply("");
            }}
          >
            Clear expression
          </button>
        </div>
        <div className="builder-scroll-fields">
        <div onChangeCapture={(event) => {
          const target = event.target as HTMLInputElement;
          if (target.placeholder !== "Name or group number") setManual(false);
        }} onClickCapture={(event) => {
          if ((event.target as HTMLElement).closest("button")) setManual(false);
        }}>
            <h3>Who would you like to find?</h3>
            <div
              className="mode-options"
              role="group"
              aria-label="People matching mode"
            >
              {["Includes", "Just", "Only"].map((v) => (
                <button
                  key={v}
                  aria-pressed={mode === v}
                  onClick={() => setMode(v)}
                >
                  {v}
                </button>
              ))}
            </div>
            <p className="small-note">
              {mode === "Includes"
                ? "All selected people, with anyone else allowed."
                : mode === "Just"
                  ? "All selected people, with no other named people. Unnamed people are allowed."
                  : "All selected people, with no other detected faces. Missed faces can affect accuracy."}
            </p>
            <fieldset className="builder-fields">
              <label>
                Find people
                <input
                  value={personQuery}
                  onChange={(e) => setPersonQuery(e.target.value)}
                  placeholder="Name or group number"
                />
              </label>
              <div className="builder-people">
                {people
                  .filter(
                    (p) =>
                      p.id > 0 &&
                      (p.name || `Group ${p.id}`)
                        .toLowerCase()
                        .includes(personQuery.toLowerCase()),
                  )
                  .map((p) => (
                    <label key={p.id}>
                      <input
                        type="checkbox"
                        checked={selected.includes(p.id)}
                        onChange={() =>
                          setSelected((old) =>
                            old.includes(p.id)
                              ? old.filter((x) => x !== p.id)
                              : [...old, p.id],
                          )
                        }
                      />
                      {name(p.id)}
                    </label>
                  ))}
              </div>
              <div className="builder-columns">
                <label>
                  Exclude someone
                  <select
                    value=""
                    onChange={(e) =>
                      setExcluded((old) =>
                        Array.from(new Set([...old, Number(e.target.value)])),
                      )
                    }
                  >
                    <option value="">Choose a person…</option>
                    {people
                      .filter((p) => p.id > 0)
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {name(p.id)}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Add a location
                  <select
                    value=""
                    onChange={(e) =>
                      setLocations((old) =>
                        Array.from(new Set([...old, e.target.value])),
                      )
                    }
                  >
                    <option value="">Choose a place…</option>
                    {places.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label} · {p.country}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Location matching
                  <select
                    value={join}
                    onChange={(e) => setJoin(e.target.value)}
                  >
                    <option value="or">Any selected location (OR)</option>
                    <option value="and">Every selected location (AND)</option>
                  </select>
                </label>
              </div>
              <div className="builder-chips">
                {selected.map((id) => (
                  <button
                    type="button"
                    key={"p" + id}
                    onClick={() =>
                      setSelected((old) => old.filter((x) => x !== id))
                    }
                  >
                    {name(id)} ×
                  </button>
                ))}
                {excluded.map((id) => (
                  <button
                    type="button"
                    key={"x" + id}
                    onClick={() =>
                      setExcluded((old) => old.filter((x) => x !== id))
                    }
                  >
                    Not {name(id)} ×
                  </button>
                ))}
                {locations.map((id) => (
                  <button
                    type="button"
                    key={id}
                    onClick={() =>
                      setLocations((old) => old.filter((x) => x !== id))
                    }
                  >
                    {places.find((p) => p.id === id)?.label} ×
                  </button>
                ))}
              </div>
              <div className="date-inputs">
                <label>
                  From date
                  <input
                    type="date"
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                  />
                </label>
                <label>
                  Through date
                  <input
                    type="date"
                    value={until}
                    onChange={(e) => setUntil(e.target.value)}
                  />
                </label>
              </div>
            </fieldset>
        </div>
        {manual && (
          <p className="small-note">
            Edit the expression in the main search bar above, then press Enter or Apply search. To choose people
            with the controls above, select the people, places and dates for a new expression.
          </p>
        )}
        {error && (
          <p id="search-expression-error" role="alert" className="error">
            {error}
          </p>
        )}
        {draft !== expression && (
          <p className="small-note">
            Unapplied changes. Apply search to update results.
          </p>
        )}
        <p className="small-note">
          AND requires both; OR allows either. Rome AND Italy can match, Italy
          AND France cannot. Year comparisons compare the year: date &gt; 2025
          starts in 2026. Use date &gt;= 2025 and date &lt; 2026 for 2025.
          Videos use sampled frames; people may appear at different times.
          Phone, map and other filters also apply.
        </p>
        </div>
      </div>}
    </details>
  );
}
