import { useEffect, useState } from "react";
import { api } from "./api.js";
import { useTheme } from "./theme.js";
import ChatView from "./components/ChatView.jsx";
import Header from "./components/Header.jsx";
import IngestPage from "./components/IngestPage.jsx";
import Login from "./components/Login.jsx";

export default function App() {
  const { theme, toggle } = useTheme();
  const [user, setUser] = useState(null);
  const [models, setModels] = useState([]);
  const [modelId, setModelId] = useState("");
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState("chat");
  const canIngest = Boolean(user?.permissions?.includes("documents:manage"));
  const selectedModel = models.find((m) => m.id === modelId);

  useEffect(() => {
    if (api.hasToken()) loadSession().catch(() => api.logout());
  }, []);

  async function loadSession() {
    const [me, m] = await Promise.all([api.me(), api.models()]);
    setUser(me);
    setModels(m.models);
    const usable = m.models.find((x) => x.id === m.default && x.available) || m.models.find((x) => x.available);
    setModelId(usable ? usable.id : m.default);
  }

  async function ask(question) {
    if (!question || busy) return;
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
        theme={theme}
        onToggleTheme={toggle}
        onLogin={async (u, p) => {
          await api.login(u, p);
          await loadSession();
        }}
      />
    );
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <Header
        user={user}
        view={view}
        onView={setView}
        canIngest={canIngest}
        models={models}
        modelId={modelId}
        onModel={setModelId}
        selectedModel={selectedModel}
        theme={theme}
        onToggleTheme={toggle}
        onSignOut={signOut}
      />
      {view === "ingest" && canIngest ? (
        <IngestPage />
      ) : (
        <ChatView messages={messages} busy={busy} onAsk={ask} user={user} />
      )}
    </div>
  );
}
