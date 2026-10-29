let token = sessionStorage.getItem("token");

async function request(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.detail || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  hasToken: () => Boolean(token),
  async login(username, password) {
    const data = await request("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
    token = data.access_token;
    sessionStorage.setItem("token", token);
  },
  logout() {
    token = null;
    sessionStorage.removeItem("token");
  },
  me: () => request("/api/me"),
  models: () => request("/api/models"),
  chat: (question, model_id) =>
    request("/api/chat", { method: "POST", body: JSON.stringify({ question, model_id }) }),
  documents: () => request("/api/documents"),
  deleteDocument: (docId) => request(`/api/documents/${encodeURIComponent(docId)}`, { method: "DELETE" }),

  // Runs the ingestion pipeline and calls onEvent for each NDJSON event as it arrives.
  async ingest(formData, onEvent) {
    const res = await fetch("/api/documents/ingest", {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (line) onEvent(JSON.parse(line));
      }
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer));
  },
};
