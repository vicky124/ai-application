import { useState } from "react";

const ICON = { pending: "○", running: "◔", done: "✓", error: "✕" };

function isNumberList(v) {
  return Array.isArray(v) && v.length > 0 && v.every((x) => typeof x === "number");
}

function Value({ value }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  if (typeof value === "boolean") return <span>{value ? "yes" : "no"}</span>;
  if (isNumberList(value)) return <code className="vector">[{value.join(", ")}, …]</code>;
  if (Array.isArray(value) && value.every((x) => typeof x === "string")) {
    return (
      <span className="chips">
        {value.map((s, i) => (
          <span className="chip" key={i}>{s}</span>
        ))}
      </span>
    );
  }
  if (Array.isArray(value)) {
    return (
      <div className="cards">
        {value.map((item, i) =>
          item && typeof item === "object" && "text" in item ? (
            <div className="card" key={i}>
              <div className="card-head">
                chunk {item.index} · {item.section}
                {item.page ? ` · p.${item.page}` : ""} · {item.chars} chars
              </div>
              <pre>{item.text}</pre>
            </div>
          ) : (
            <code key={i}>{JSON.stringify(item)}</code>
          )
        )}
      </div>
    );
  }
  if (typeof value === "object") return <pre className="obj">{JSON.stringify(value, null, 2)}</pre>;
  return <span>{String(value)}</span>;
}

function Details({ details }) {
  return (
    <dl className="details">
      {Object.entries(details).map(([k, v]) => (
        <div className="row" key={k}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd><Value value={v} /></dd>
        </div>
      ))}
    </dl>
  );
}

export default function StepTimeline({ steps }) {
  const [open, setOpen] = useState({});
  return (
    <ol className="timeline">
      {steps.map((s, i) => {
        const expandable = s.details || s.error;
        const isOpen = open[s.id] ?? s.status === "error";
        return (
          <li key={s.id} className={`step ${s.status}`}>
            <div className="step-head">
              <span className={`icon ${s.status === "running" ? "spin" : ""}`}>{ICON[s.status]}</span>
              <span className="step-name">{i + 1}. {s.label}</span>
              {s.duration_ms !== undefined && <span className="muted">{s.duration_ms} ms</span>}
              {expandable && (
                <button className="link" onClick={() => setOpen({ ...open, [s.id]: !isOpen })}>
                  {isOpen ? "hide details" : "show details"}
                </button>
              )}
            </div>
            {s.error && <p className="error">{s.error}</p>}
            {isOpen && s.details && <Details details={s.details} />}
          </li>
        );
      })}
    </ol>
  );
}
