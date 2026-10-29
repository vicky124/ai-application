import { useState } from "react";
import { Alert, Spinner } from "./icons.jsx";
import { Logo } from "./Header.jsx";
import ThemeToggle from "./ThemeToggle.jsx";

const DEMO = [
  ["alice", "alice123", "Employee"],
  ["mark", "mark123", "Manager"],
  ["hannah", "hannah123", "HR"],
  ["root", "root123", "Admin"],
];

export default function Login({ onLogin, theme, onToggleTheme }) {
  const [u, setU] = useState("alice");
  const [p, setP] = useState("alice123");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await onLogin(u, p);
    } catch (ex) {
      setErr(ex.message);
      setBusy(false);
    }
  }

  return (
    <div className="relative grid min-h-dvh place-items-center px-4 py-10">
      <div className="absolute right-4 top-4">
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </div>
      <div
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-72 bg-gradient-to-b from-accent-soft to-transparent"
        aria-hidden="true"
      />

      <form onSubmit={submit} className="card w-full max-w-sm space-y-5 p-8">
        <div className="flex flex-col items-center gap-3 text-center">
          <Logo className="size-12" />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Policy &amp; HR Copilot</h1>
            <p className="mt-1 text-sm text-muted">Sign in to ask questions about company policy.</p>
          </div>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="username" className="text-sm font-medium">
            Username
          </label>
          <input
            id="username"
            className="field"
            value={u}
            onChange={(e) => setU(e.target.value)}
            autoComplete="username"
            autoFocus
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="password" className="text-sm font-medium">
            Password
          </label>
          <input
            id="password"
            type="password"
            className="field"
            value={p}
            onChange={(e) => setP(e.target.value)}
            autoComplete="current-password"
          />
        </div>

        {err && (
          <p role="alert" className="flex items-start gap-2 rounded-xl bg-danger-soft px-3 py-2 text-sm text-danger">
            <Alert className="mt-0.5 size-4 shrink-0" />
            {err}
          </p>
        )}

        <button className="btn-primary w-full" disabled={busy}>
          {busy ? <Spinner /> : null}
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <div className="border-t border-border pt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Demo accounts</p>
          <div className="flex flex-wrap gap-2">
            {DEMO.map(([name, pw, role]) => (
              <button
                type="button"
                key={name}
                onClick={() => {
                  setU(name);
                  setP(pw);
                }}
                className={`badge cursor-pointer px-3 py-1 transition-colors ${
                  u === name
                    ? "bg-accent text-accent-fg"
                    : "bg-surface-2 text-muted hover:bg-accent-soft hover:text-accent-text"
                }`}
              >
                {role}
              </button>
            ))}
          </div>
        </div>
      </form>
    </div>
  );
}
