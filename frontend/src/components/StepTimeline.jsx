import { useState } from "react";
import { Check, ChevronDown, Spinner, X } from "./icons.jsx";

function isNumberList(v) {
  return Array.isArray(v) && v.length > 0 && v.every((x) => typeof x === "number");
}

function Value({ value }) {
  if (value === null || value === undefined) return <span className="text-muted">—</span>;
  if (typeof value === "boolean") return <span>{value ? "yes" : "no"}</span>;
  if (isNumberList(value)) {
    return <code className="block overflow-x-auto rounded-lg bg-surface-2 px-2.5 py-1.5 text-xs">[{value.join(", ")}, …]</code>;
  }
  if (Array.isArray(value) && value.every((x) => typeof x === "string")) {
    return (
      <span className="flex flex-wrap gap-1.5">
        {value.map((s, i) => (
          <span className="badge bg-surface-2 text-fg" key={i}>
            {s}
          </span>
        ))}
      </span>
    );
  }
  if (Array.isArray(value)) {
    return (
      <div className="space-y-2">
        {value.map((item, i) =>
          item && typeof item === "object" && "text" in item ? (
            <div className="rounded-xl border border-border bg-surface-2/60 p-3" key={i}>
              <div className="mb-1.5 text-xs text-muted">
                chunk {item.index} · {item.section}
                {item.page ? ` · p.${item.page}` : ""} · {item.chars} chars
              </div>
              <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed">{item.text}</pre>
            </div>
          ) : (
            <code key={i}>{JSON.stringify(item)}</code>
          )
        )}
      </div>
    );
  }
  if (typeof value === "object") {
    return <pre className="overflow-x-auto rounded-lg bg-surface-2 px-2.5 py-1.5 text-xs">{JSON.stringify(value, null, 2)}</pre>;
  }
  return <span className="break-words">{String(value)}</span>;
}

function Details({ details }) {
  return (
    <dl className="mt-3 space-y-2.5 rounded-xl border border-border bg-surface-2/40 p-3.5 text-sm">
      {Object.entries(details).map(([k, v]) => (
        <div className="grid gap-1 sm:grid-cols-[11rem_1fr] sm:gap-3" key={k}>
          <dt className="text-xs font-medium capitalize text-muted sm:pt-0.5">{k.replace(/_/g, " ")}</dt>
          <dd className="min-w-0">
            <Value value={v} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

const dot = {
  pending: "border-border text-muted",
  running: "border-ring text-accent-text bg-accent-soft",
  done: "border-transparent bg-success-soft text-success",
  error: "border-transparent bg-danger-soft text-danger",
};

function StatusDot({ status, index }) {
  return (
    <span className={`relative z-10 grid size-8 shrink-0 place-items-center rounded-full border-2 text-xs font-semibold ${dot[status]}`}>
      {status === "done" ? <Check className="size-4" /> : status === "error" ? <X className="size-4" /> : status === "running" ? <Spinner className="size-4" /> : index + 1}
    </span>
  );
}

export default function StepTimeline({ steps }) {
  const [open, setOpen] = useState({});
  return (
    <ol>
      {steps.map((s, i) => {
        const expandable = s.details || s.error;
        const isOpen = open[s.id] ?? s.status === "error";
        const last = i === steps.length - 1;
        return (
          <li key={s.id} className={`relative flex gap-3.5 ${last ? "" : "pb-5"} ${s.status === "pending" ? "opacity-60" : ""}`}>
            {!last && <span className="absolute left-4 top-8 -ml-px h-[calc(100%-1.5rem)] w-0.5 bg-border" aria-hidden="true" />}
            <StatusDot status={s.status} index={i} />
            <div className="min-w-0 flex-1">
              <div className="flex min-h-8 flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-medium">{s.label}</span>
                {s.duration_ms !== undefined && <span className="text-xs tabular-nums text-muted">{s.duration_ms} ms</span>}
                {expandable && (
                  <button
                    type="button"
                    onClick={() => setOpen({ ...open, [s.id]: !isOpen })}
                    aria-expanded={isOpen}
                    className="ml-auto inline-flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-accent-text transition-colors hover:bg-accent-soft"
                  >
                    {isOpen ? "Hide details" : "Show details"}
                    <ChevronDown className={`size-3.5 transition-transform ${isOpen ? "rotate-180" : ""}`} />
                  </button>
                )}
              </div>
              {s.error && <p className="mt-1 text-sm text-danger">{s.error}</p>}
              {isOpen && s.details && <Details details={s.details} />}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
