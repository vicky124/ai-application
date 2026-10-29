import { useState } from "react";

function renderWithCitations(text, sources, onPick) {
  return text.split(/(\[\d+\])/g).map((part, i) => {
    const m = part.match(/^\[(\d+)\]$/);
    if (m && sources[+m[1] - 1]) {
      return (
        <button key={i} className="cite" onClick={() => onPick(+m[1] - 1)}>
          {m[1]}
        </button>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

export default function Message({ m }) {
  const [active, setActive] = useState(null);
  const [showTrace, setShowTrace] = useState(false);

  if (m.role === "user") return <div className="msg user">{m.text}</div>;
  if (m.role === "error") return <div className="msg error">{m.text}</div>;

  const sources = m.sources || [];
  return (
    <div className={`msg assistant ${m.abstained ? "abstained" : ""}`}>
      <p>{renderWithCitations(m.answer, sources, setActive)}</p>
      {m.abstained && m.abstain_reason && <p className="meta">Reason: {m.abstain_reason}</p>}

      {sources.length > 0 && (
        <ol className="sources">
          {sources.map((s, i) => (
            <li key={i} className={active === i ? "active" : ""}>
              <button className="link" onClick={() => setActive(active === i ? null : i)}>
                {s.title} — {s.section} (v{s.version}
                {s.page ? `, p.${s.page}` : ""}) · {(s.score * 100).toFixed(0)}%
              </button>
              {active === i && <blockquote>{s.text}</blockquote>}
            </li>
          ))}
        </ol>
      )}

      <div className="meta">
        model: {m.model_id}
        {m.verification && (
          <>
            {" "}
            · verified: {m.verification.passed ? "yes" : "no"} ({m.verification.reason})
          </>
        )}{" "}
        ·{" "}
        <button className="link" onClick={() => setShowTrace(!showTrace)}>
          {showTrace ? "hide" : "show"} steps
        </button>
      </div>
      {showTrace && (
        <ul className="trace">
          {m.trace.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
