import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import DocumentsTable from "./DocumentsTable.jsx";
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
    <div className="ingest">
      <section>
        <h2>Ingest a document</h2>
        <form onSubmit={run} className="ingest-form">
          <label className="wide">
            File
            <input type="file" accept=".md,.txt,.pdf" onChange={(e) => pickFile(e.target.files[0] || null)} />
          </label>
          <label>
            Title
            <input value={form.title} onChange={update("title")} required />
          </label>
          <label>
            Document ID
            <input value={form.doc_id} onChange={update("doc_id")} required pattern="[a-z0-9][a-z0-9_\-]{1,60}" title="lowercase letters, digits, - or _" />
          </label>
          <label>
            Department
            <input value={form.department} onChange={update("department")} />
          </label>
          <label>
            Version
            <input value={form.version} onChange={update("version")} />
          </label>
          <label>
            Who can read it
            <select value={preset} onChange={(e) => setPreset(e.target.value)}>
              {ROLE_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </label>
          {preset === "custom" && (
            <label>
              Roles (comma separated)
              <input value={custom} onChange={(e) => setCustom(e.target.value)} />
            </label>
          )}
          <label>
            Status
            <select value={form.status} onChange={update("status")}>
              <option value="active">active (searchable)</option>
              <option value="draft">draft</option>
              <option value="inactive">inactive</option>
            </select>
          </label>
          <div className="wide">
            <button disabled={running}>{running ? "Running pipeline…" : "Run ingestion pipeline"}</button>
            {formError && <span className="error"> {formError}</span>}
          </div>
        </form>
      </section>

      {steps.length > 0 && (
        <section>
          <h2>Pipeline steps</h2>
          <StepTimeline steps={steps} />
          {outcome && <p className={outcome.ok ? "ok" : "error"}>{outcome.text}</p>}
        </section>
      )}

      <section>
        <h2>Indexed documents</h2>
        <DocumentsTable docs={docs} onDelete={remove} />
      </section>
    </div>
  );
}
