import { useRef, useState, type PointerEvent } from "react";
type Box = { x: number; y: number; width: number; height: number };
type Face = {
  id: string;
  person_id: number | null;
  name: string | null;
  bbox?: string;
  bbox_width?: number | null;
  bbox_height?: number | null;
};
export default function FaceEditor({
  id,
  faces,
  people,
  onSaved,
  onClose,
}: {
  id: string;
  faces: Face[];
  people: { id: number; name: string | null }[];
  onSaved: () => Promise<void>;
  onClose: () => void;
}) {
  const [box, setBox] = useState<Box | null>(null),
    [chosen, setChosen] = useState(""),
    [person, setPerson] = useState(""),
    [name, setName] = useState(""),
    [size, setSize] = useState({ width: 1, height: 1 }),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const start = useRef<{ x: number; y: number } | null>(null);
  function point(e: PointerEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
      y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
    };
  }
  async function request(path: string, body: unknown) {
    const r = await fetch("/api" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok)
      throw Error(
        typeof data.detail === "string"
          ? data.detail
          : "Check the face box and person selection",
      );
    return data;
  }
  async function save(redraw: boolean) {
    if (!box) return;
    setBusy(true);
    setMessage("");
    try {
      if (chosen && !redraw) {
        if (!person || person === "new")
          throw Error(
            "Choose an existing person to reassign this face, or save a new box for a new person.",
          );
        await request("/faces/correct", {
          face_ids: [chosen],
          action: "move",
          target: Number(person),
        });
        setMessage("Assignment updated. You can undo it.");
      } else {
        const result = await request(`/media/${id}/manual-face`, {
          ...box,
          person_id: person && person !== "new" ? Number(person) : null,
          name: person === "new" ? name : null,
          replaces: chosen || null,
        });
        setMessage(
          result.recognition_ready
            ? "Saved with a recognition signature. Reevaluate can use this example."
            : "Saved for person search. No reliable recognition signature was found for this region.",
        );
      }
      setBox(null);
      setChosen("");
      await onSaved();
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="face-editor" aria-label="Mark and assign faces">
      <div className="face-editor-heading">
        <strong>Mark a face</strong>
        <button disabled={busy} onClick={onClose}>
          Done
        </button>
      </div>
      <p>
        Drag around the face, or tap an existing box. On a phone, drag with one
        finger and fine-tune the box below.
      </p>
      <div
        className="face-drawing"
        onPointerDown={(e) => {
          if (busy || (e.target as HTMLElement).closest("button")) return;
          e.preventDefault();
          e.currentTarget.setPointerCapture(e.pointerId);
          const p = point(e);
          start.current = p;
          setChosen("");
          setMessage("");
          setBox({ ...p, width: 0, height: 0 });
        }}
        onPointerMove={(e) => {
          if (!start.current) return;
          const p = point(e),
            a = start.current;
          setBox({
            x: Math.min(a.x, p.x),
            y: Math.min(a.y, p.y),
            width: Math.abs(p.x - a.x),
            height: Math.abs(p.y - a.y),
          });
        }}
        onPointerUp={() => {
          start.current = null;
        }}
        onPointerCancel={() => {
          start.current = null;
        }}
      >
        <img
          src={`/api/media/${id}/thumbnail?size=large`}
          alt="Photo for marking a face"
          draggable={false}
          onLoad={(e) =>
            setSize({
              width: e.currentTarget.naturalWidth,
              height: e.currentTarget.naturalHeight,
            })
          }
        />
        {faces.map((f) => {
          let r: number[];
          try {
            r = JSON.parse(f.bbox || "[]");
          } catch {
            return null;
          }
          if (r.length !== 4) return null;
          r = [
            (r[0] * size.width) / (f.bbox_width || size.width),
            (r[1] * size.height) / (f.bbox_height || size.height),
            (r[2] * size.width) / (f.bbox_width || size.width),
            (r[3] * size.height) / (f.bbox_height || size.height),
          ];
          return (
            <button
              key={f.id}
              disabled={busy}
              className="existing-face-box"
              aria-label={`Select face: ${f.name || "Unnamed person"}`}
              title={f.name || "Unnamed person"}
              style={{
                left: (r[0] / size.width) * 100 + "%",
                top: (r[1] / size.height) * 100 + "%",
                width: (r[2] / size.width) * 100 + "%",
                height: (r[3] / size.height) * 100 + "%",
              }}
              onClick={() => {
                setChosen(f.id);
                setBox({
                  x: r[0] / size.width,
                  y: r[1] / size.height,
                  width: r[2] / size.width,
                  height: r[3] / size.height,
                });
                setPerson(f.person_id ? String(f.person_id) : "");
                setMessage(
                  "Existing face selected. Reassign it, adjust its box, or remove it.",
                );
              }}
            />
          );
        })}
        {box && (
          <div
            className="new-face-box"
            style={{
              left: box.x * 100 + "%",
              top: box.y * 100 + "%",
              width: box.width * 100 + "%",
              height: box.height * 100 + "%",
            }}
          />
        )}
      </div>
      <div className="face-editor-controls">
        <button
          disabled={busy}
          onClick={() => {
            setChosen("");
            setMessage("");
            setBox({ x: 0.35, y: 0.3, width: 0.3, height: 0.3 });
          }}
        >
          Start a box without dragging
        </button>
        {box && (
          <>
            <div className="face-box-fields">
              {(["x", "y", "width", "height"] as const).map((key) => (
                <label key={key}>
                  {
                    { x: "Left", y: "Top", width: "Width", height: "Height" }[
                      key
                    ]
                  }{" "}
                  %
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    disabled={busy}
                    value={Math.round(box[key] * 1000) / 10}
                    onChange={(e) => {
                      const v = Math.max(
                        0,
                        Math.min(1, Number(e.target.value) / 100),
                      );
                      setBox((old) => {
                        if (!old) return old;
                        const next = { ...old, [key]: v };
                        next.width = Math.min(next.width, 1 - next.x);
                        next.height = Math.min(next.height, 1 - next.y);
                        return next;
                      });
                    }}
                  />
                </label>
              ))}
            </div>
            <label>
              Who is this?
              <select
                aria-label="Assign marked face to person"
                disabled={busy}
                value={person}
                onChange={(e) => setPerson(e.target.value)}
              >
                <option value="">Choose a person…</option>
                {people
                  .filter((p) => p.id > 0 && !!p.name?.trim())
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name || `Unnamed group ${p.id}`} · #{p.id}
                    </option>
                  ))}
                <option value="new">Create a new person…</option>
              </select>
            </label>
            {person === "new" && (
              <label>
                New person name
                <input
                  aria-label="New person name"
                  disabled={busy}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
            )}
            <div className="builder-actions">
              {chosen && (
                <button
                  disabled={busy || !person || person === "new"}
                  onClick={() => save(false)}
                >
                  Update assignment
                </button>
              )}
              <button
                disabled={
                  busy ||
                  !person ||
                  (person === "new" && !name.trim()) ||
                  !box.width ||
                  !box.height
                }
                onClick={() => save(true)}
              >
                {busy
                  ? "Saving…"
                  : chosen
                    ? "Save adjusted face box"
                    : "Save face"}
              </button>
              {chosen && (
                <button
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await request("/faces/correct", {
                        face_ids: [chosen],
                        action: "dismiss",
                      });
                      setBox(null);
                      setChosen("");
                      await onSaved();
                      setMessage("Face removed. You can undo it.");
                    } catch (e) {
                      setMessage(String(e));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Remove face
                </button>
              )}
              <button
                disabled={busy}
                onClick={() => {
                  setBox(null);
                  setChosen("");
                }}
              >
                Cancel box
              </button>
            </div>
          </>
        )}
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const r = await request("/undo", {});
              await onSaved();
              setChosen("");
              setBox(null);
              setMessage(`Undone: ${r.description}`);
            } catch (e) {
              setMessage(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Undo last library change
        </button>
        {message && <p role="status">{message}</p>}
      </div>
    </section>
  );
}
