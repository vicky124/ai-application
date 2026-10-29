import { useState } from "react";
import { Logo } from "./Header.jsx";
import { Alert, Check, ChevronDown, Cloud, Cpu, FileText, X } from "./icons.jsx";

function Cited({ text, sources, onPick }) {
  return text.split(/(\[\d+\])/g).map((part, i) => {
    const m = part.match(/^\[(\d+)\]$/);
    if (m && sources[+m[1] - 1]) {
      return (
        <button
          key={i}
          type="button"
          onClick={() => onPick(+m[1] - 1)}
          title={`${sources[+m[1] - 1].title}: ${sources[+m[1] - 1].section}`}
          className="mx-0.5 inline-flex size-5 -translate-y-0.5 cursor-pointer items-center justify-center rounded-md bg-accent-soft text-[11px] font-semibold text-accent-text transition-colors hover:bg-accent hover:text-accent-fg"
        >
          {m[1]}
        </button>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

function ScoreBar({ score }) {
  // `score` is the calibrated relevance (0..1). Cross-encoder probabilities can be tiny, so show "<1%" instead of 0%.
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const label = pct === 0 && score > 0 ? "<1%" : `${pct}%`;
  return (
    <span className="flex items-center gap-2" title={`Relevance ${(score * 100).toFixed(2)}%`}>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-2">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${Math.max(pct, score > 0 ? 3 : 0)}%` }} />
      </span>
      <span className="w-8 text-right text-xs tabular-nums text-muted">{label}</span>
    </span>
  );
}

export default function Message({ m }) {
  const [active, setActive] = useState(null);
  const [showTrace, setShowTrace] = useState(false);

  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-sm leading-relaxed text-accent-fg shadow-sm">
          {m.text}
        </p>
      </div>
    );
  }

  if (m.role === "error") {
    return (
      <div role="alert" className="flex items-start gap-2.5 rounded-2xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
        <Alert className="mt-0.5 size-4 shrink-0" />
        <p className="leading-relaxed">{m.text}</p>
      </div>
    );
  }

  const sources = m.sources || [];
  const v = m.verification;
  return (
    <div className="flex items-start gap-3">
      <Logo className="size-8" />
      <div
        className={`card min-w-0 flex-1 space-y-3 rounded-tl-md px-4 py-3.5 ${
          m.abstained ? "border-l-4 !border-l-warn" : ""
        }`}
      >
        {m.abstained && (
          <span className="badge bg-warn-soft text-warn">
            <Alert className="size-3" /> Couldn't answer from the documents
          </span>
        )}
        <p className="text-sm leading-relaxed">
          <Cited text={m.answer} sources={sources} onPick={(i) => setActive(active === i ? null : i)} />
        </p>
        {m.abstained && m.abstain_reason && <p className="text-xs text-muted">Reason: {m.abstain_reason}</p>}

        {sources.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Sources</p>
            <ol className="space-y-1.5">
              {sources.map((s, i) => (
                <li key={i} className={`rounded-xl border transition-colors ${active === i ? "border-ring/60 bg-accent-soft/50" : "border-border bg-surface-2/50"}`}>
                  <button
                    type="button"
                    onClick={() => setActive(active === i ? null : i)}
                    aria-expanded={active === i}
                    className="flex w-full cursor-pointer items-center gap-2.5 px-3 py-2 text-left"
                  >
                    <span className="grid size-5 shrink-0 place-items-center rounded-md bg-accent-soft text-[11px] font-semibold text-accent-text">
                      {i + 1}
                    </span>
                    <FileText className="size-4 shrink-0 text-muted" />
                    <span className="min-w-0 flex-1 truncate text-sm">
                      <span className="font-medium">{s.title}</span>
                      <span className="text-muted"> · {s.section.split(" > ").slice(-1)[0]}</span>
                    </span>
                    <span className="hidden text-xs text-muted sm:inline">
                      v{s.version}
                      {s.page ? ` · p.${s.page}` : ""}
                    </span>
                    <ScoreBar score={s.relevance ?? s.score} />
                    <ChevronDown className={`size-4 shrink-0 text-muted transition-transform ${active === i ? "rotate-180" : ""}`} />
                  </button>
                  {active === i && (
                    <blockquote className="mx-3 mb-3 whitespace-pre-wrap rounded-lg border-l-2 border-accent bg-surface px-3 py-2 text-xs leading-relaxed text-muted">
                      {s.text}
                    </blockquote>
                  )}
                </li>
              ))}
            </ol>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs">
          <span className="badge bg-surface-2 text-muted">
            {m.model_local === false ? <Cloud className="size-3" /> : <Cpu className="size-3" />}
            {m.model_id}
          </span>
          {v && (
            <span className={`badge ${v.passed ? "bg-success-soft text-success" : "bg-danger-soft text-danger"}`} title={`Citation coverage ${Math.round(v.coverage * 100)}%`}>
              {v.passed ? <Check className="size-3" /> : <X className="size-3" />}
              {v.passed ? "Verified" : "Not verified"} · {v.reason}
            </span>
          )}
          <button
            type="button"
            onClick={() => setShowTrace(!showTrace)}
            aria-expanded={showTrace}
            className="ml-auto inline-flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-0.5 text-muted transition-colors hover:text-fg"
          >
            Steps ({m.trace.length})
            <ChevronDown className={`size-3.5 transition-transform ${showTrace ? "rotate-180" : ""}`} />
          </button>
        </div>

        {showTrace && (
          <ol className="space-y-1.5 border-l border-border pl-4 text-xs text-muted">
            {m.trace.map((t, i) => (
              <li key={i} className="relative before:absolute before:-left-[1.28rem] before:top-1.5 before:size-1.5 before:rounded-full before:bg-ring">
                {t}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
