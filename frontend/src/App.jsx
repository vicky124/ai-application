import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import IngestPage from "./components/IngestPage.jsx";
import Login from "./components/Login.jsx";
import Message from "./components/Message.jsx";

export default function App() {
  const [user, setUser] = useState(null);
  const [models, setModels] = useState([]);
  const [modelId, setModelId] = useState("");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState("chat");
  const endRef = useRef(null);
  const canIngest = Boolean(user?.permissions?.includes("documents:manage"));

  useEffect(() => {
    if (api.hasToken()) loadSession().catch(() => api.logout());
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function loadSession() {
    const [me, m] = await Promise.all([api.me(), api.models()]);
    setUser(me);
    setModels(m.models);
    setModelId(m.default);
  }

  async function send(e) {
    e.preventDefault();
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: question }]);
    setBusy(true);
    try {
      const r = await api.chat(question, modelId);
      setMessages((prev) => [...prev, { role: "assistant", ...r }]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "error", text: err.message }]);
    } finally {
      setBusy(false);
    }
  }

  function signOut() {
    api.logout();
    setUser(null);
    setMessages([]);
    setView("chat");
  }

  if (!user) {
    return (
      <Login
        onLogin={async (u, p) => {
          await api.login(u, p);
          await loadSession();
        }}
      />
    );
  }

  return (
    <div className="app">
      <header>
        <h1>Policy &amp; HR Copilot</h1>
        {canIngest && (
          <nav className="tabs">
            <button className={view === "chat" ? "tab active" : "tab"} onClick={() => setView("chat")}>Chat</button>
            <button className={view === "ingest" ? "tab active" : "tab"} onClick={() => setView("ingest")}>Ingestion</button>
          </nav>
        )}
        <div className="controls">
          {view === "chat" && (
            <label>
              Model{" "}
              <select value={modelId} onChange={(e) => setModelId(e.target.value)}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <span className="user">
            {user.name} · {user.role}
          </span>
          <button className="link" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      {view === "ingest" && canIngest && <IngestPage />}

      {view === "chat" && (<>
      <main>
        {messages.length === 0 && (
          <p className="hint">
            Ask about leave, code of conduct, IT policy or onboarding. Answers cite approved documents only.
          </p>
        )}
        {messages.map((m, i) => (
          <Message key={i} m={m} />
        ))}
        {busy && (
          <div className="msg assistant">
            <em>Searching policies…</em>
          </div>
        )}
        <div ref={endRef} />
      </main>

      <form onSubmit={send} className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a policy question…"
          autoFocus
        />
        <button disabled={busy || !input.trim()}>Send</button>
      </form>
      </>)}
    </div>
  );
}
