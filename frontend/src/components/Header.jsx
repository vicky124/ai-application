import { Cloud, LogOut, ShieldCheck } from "./icons.jsx";
import ThemeToggle from "./ThemeToggle.jsx";

export function Logo({ className = "size-9" }) {
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-sm ${className}`}
    >
      <ShieldCheck className="size-[55%]" />
    </span>
  );
}

const initials = (name) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");

export default function Header({
  user,
  view,
  onView,
  canIngest,
  models,
  modelId,
  onModel,
  selectedModel,
  theme,
  onToggleTheme,
  onSignOut,
}) {
  const groups = [
    ["Local (open source, stays on this machine)", models.filter((m) => m.local)],
    ["Cloud (retrieved text is sent to the provider)", models.filter((m) => !m.local)],
  ].filter(([, group]) => group.length > 0);

  const tab = (id, label) => (
    <button
      type="button"
      onClick={() => onView(id)}
      aria-current={view === id ? "page" : undefined}
      className={`cursor-pointer rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
        view === id ? "bg-surface text-fg shadow-card ring-1 ring-border" : "text-muted hover:text-fg"
      }`}
    >
      {label}
    </button>
  );

  // Small screens: row 1 = brand + theme/sign-out, row 2 = tabs, row 3 = model and user. Wide screens: a single row.
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-surface/85 backdrop-blur">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-3 px-4 py-3">
        <div className="order-1 flex items-center gap-2.5">
          <Logo />
          <div className="leading-tight">
            <h1 className="text-sm font-semibold">Policy &amp; HR Copilot</h1>
            <p className="hidden text-xs text-muted sm:block">Grounded answers from approved documents</p>
          </div>
        </div>

        <div className="order-2 ml-auto flex items-center gap-2 md:order-4 md:ml-0">
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          <button type="button" onClick={onSignOut} className="btn-ghost !p-2" aria-label="Sign out" title="Sign out">
            <LogOut />
          </button>
        </div>

        {canIngest && (
          <nav className="order-3 flex gap-1 rounded-full bg-surface-2 p-1 md:order-2" aria-label="Sections">
            {tab("chat", "Chat")}
            {tab("ingest", "Ingestion")}
          </nav>
        )}

        <div className="order-4 flex w-full flex-wrap items-center gap-2 md:order-3 md:ml-auto md:w-auto">
          {view === "chat" && (
            <>
              <label className="flex min-w-0 items-center gap-2 text-xs text-muted">
                <span className="hidden lg:inline">Model</span>
                <select
                  value={modelId}
                  onChange={(e) => onModel(e.target.value)}
                  className="field !w-auto max-w-[14rem] cursor-pointer !py-1.5 text-xs"
                  aria-label="Model"
                >
                  {groups.map(([title, group]) => (
                    <optgroup key={title} label={title}>
                      {group.map((m) => (
                        <option key={m.id} value={m.id} disabled={!m.available}>
                          {m.label}
                          {!m.available ? ` — unavailable: ${m.unavailable_reason}` : ""}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </label>
              {selectedModel && !selectedModel.local && (
                <span
                  className="badge bg-warn-soft text-warn"
                  title="Your question and the retrieved policy passages are sent to the model provider"
                >
                  <Cloud className="size-3" /> cloud model
                </span>
              )}
            </>
          )}

          <div className="ml-auto flex items-center gap-2 rounded-full border border-border bg-surface-2 py-1 pl-1 pr-3 md:ml-0">
            <span className="grid size-7 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent-text">
              {initials(user.name)}
            </span>
            <span className="hidden text-sm font-medium sm:inline">{user.name}</span>
            <span className="badge bg-accent-soft capitalize text-accent-text">{user.role === "hr" ? "HR" : user.role}</span>
          </div>
        </div>
      </div>
    </header>
  );
}
