import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import DocumentsTable from "./DocumentsTable.jsx";
import { Alert, Check, Spinner, Upload } from "./icons.jsx";
import StepTimeline from "./StepTimeline.jsx";

const ROLE_PRESETS = [
  { label: "Everyone", value: "all" },
  { label: "Managers and above", value: "manager,hr,compliance,admin" },
  { label: "HR, compliance, admin", value: "hr,compliance,admin" },
  { label: "Custom…", value: "custom" },
];

const slug = (s) =>
  s
    .toLowerCase()
    .replace(/\.[^.]+$/, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

const kb = (bytes) => (bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`);

function Field({ label, children, className = "" }) {
  return (
    <label className={`block space-y-1.5 ${className}`}>
      <span className="text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

export default function IngestPage() {
  const [file, setFile] = useState(null);
  const [form, setForm] = useState({ title: "", doc_id: "", department: "General", version: "1.0", status: "active" });
  const [preset, setPreset] = useState("all");
  const [custom, setCustom] = useState("employee");
  const [steps, setSteps] = useState([]);
  const [outcome, setOutcome] = useState(null);
  const [running, setRunning] = useState(false);
  const [formError, setFormError] = useState("");
  const [docs, setDocs] = useState(null);
  const [dragging, setDragging] = useState(false);

  const loadDocs = useCallback(() => api.documents().then(setDocs).catch(() => setDocs([])), []);
  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  function pickFile(f) {
    setFile(f);
    if (f) {
      const id = slug(f.name);
      setForm((prev) => ({
        ...prev,
        doc_id: prev.doc_id || id,
        title: prev.title || id.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      }));
    }
  }

  const update = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  function applyEvent(ev) {
    if (ev.type === "plan") {
      setSteps(ev.steps.map((s) => ({ ...s, status: "pending" })));
    } else if (ev.type === "step") {
      setSteps((prev) => prev.map((s) => (s.id === ev.id ? { ...s, ...ev } : s)));
    } else if (ev.type === "complete") {
      setOutcome({ ok: true, text: `Indexed ${ev.chunks} chunks for "${ev.doc_id}".` });
    } else if (ev.type === "failed") {
      setOutcome({ ok: false, text: `Ingestion failed: ${ev.error}` });
    }
  }

  async function run(e) {
    e.preventDefault();
    setFormError("");
    if (!file) return setFormError("Choose a file first (.md, .txt or .pdf).");
    const fd = new FormData();
    fd.append("file", file);
    Object.entries(form).forEach(([k, v]) => fd.append(k, v));
    fd.append("allowed_roles", preset === "custom" ? custom : preset);

    setSteps([]);
    setOutcome(null);
    setRunning(true);
    try {
      await api.ingest(fd, applyEvent);
      loadDocs();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setRunning(false);
    }
  }

  async function remove(d) {
    if (!window.confirm(`Delete "${d.title}" and its ${d.chunks} chunks from the index?`)) return;
    await api.deleteDocument(d.doc_id);
    loadDocs();
  }

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 px-4 py-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Document ingestion</h2>
        <p className="mt-1 text-sm text-muted">
          Upload a policy document and watch it move through parsing, chunking, embedding and indexing.
        </p>
      </div>

      <section className="card p-5 sm:p-6">
        <form onSubmit={run} className="grid gap-4 sm:grid-cols-2">
          <label
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              pickFile(e.dataTransfer.files[0] || null);
            }}
            className={`flex cursor-pointer flex-col items-center gap-1.5 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors focus-within:border-ring sm:col-span-2 ${
              dragging ? "border-ring bg-accent-soft" : "border-border hover:border-ring/60 hover:bg-surface-2"
            }`}
          >
            <Upload className="size-6 text-accent-text" />
            {file ? (
              <>
                <span className="text-sm font-medium">{file.name}</span>
                <span className="text-xs text-muted">{kb(file.size)} · click or drop to replace</span>
              </>
            ) : (
              <>
                <span className="text-sm font-medium">Drop a file here or click to browse</span>
                <span className="text-xs text-muted">.md, .txt or .pdf</span>
              </>
            )}
            <input type="file" accept=".md,.txt,.pdf" className="sr-only" onChange={(e) => pickFile(e.target.files[0] || null)} />
          </label>

          <Field label="Title">
            <input className="field" value={form.title} onChange={update("title")} required />
          </Field>
          <Field label="Document ID">
            <input
              className="field font-mono"
              value={form.doc_id}
              onChange={update("doc_id")}
              required
              pattern="[a-z0-9][a-z0-9_\-]{1,60}"
              title="lowercase letters, digits, - or _"
            />
          </Field>
          <Field label="Department">
            <input className="field" value={form.department} onChange={update("department")} />
          </Field>
          <Field label="Version">
            <input className="field" value={form.version} onChange={update("version")} />
          </Field>
          <Field label="Who can read it">
            <select className="field cursor-pointer" value={preset} onChange={(e) => setPreset(e.target.value)}>
              {ROLE_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          {preset === "custom" ? (
            <Field label="Roles (comma separated)">
              <input className="field" value={custom} onChange={(e) => setCustom(e.target.value)} />
            </Field>
          ) : null}
          <Field label="Status">
            <select className="field cursor-pointer" value={form.status} onChange={update("status")}>
              <option value="active">active (searchable)</option>
              <option value="draft">draft</option>
              <option value="inactive">inactive</option>
            </select>
          </Field>

          <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
            <button className="btn-primary" disabled={running}>
              {running ? <Spinner /> : null}
              {running ? "Running pipeline…" : "Run ingestion pipeline"}
            </button>
            {formError && (
              <span role="alert" className="inline-flex items-center gap-1.5 text-sm text-danger">
                <Alert className="size-4" /> {formError}
              </span>
            )}
          </div>
        </form>
      </section>

      {steps.length > 0 && (
        <section className="card p-5 sm:p-6">
          <h3 className="mb-4 text-base font-semibold">Pipeline steps</h3>
          <StepTimeline steps={steps} />
          {outcome && (
            <p
              role="status"
              className={`mt-5 flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-sm font-medium ${
                outcome.ok ? "bg-success-soft text-success" : "bg-danger-soft text-danger"
              }`}
            >
              {outcome.ok ? <Check className="size-4" /> : <Alert className="size-4" />}
              {outcome.text}
            </p>
          )}
        </section>
      )}

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between px-5 pb-3 pt-5 sm:px-6">
          <h3 className="text-base font-semibold">Indexed documents</h3>
          {docs && <span className="badge bg-surface-2 text-muted">{docs.length}</span>}
        </div>
        <DocumentsTable docs={docs} onDelete={remove} />
      </section>
    </main>
  );
}
