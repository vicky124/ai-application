// Tokens live in sessionStorage (cleared when the tab closes). For production, prefer an httpOnly
// cookie for the refresh token so scripts cannot read it.
let accessToken = sessionStorage.getItem("access_token");
let refreshToken = sessionStorage.getItem("refresh_token");
let refreshing = null; // single in-flight refresh shared by concurrent requests

function saveTokens(data) {
  accessToken = data.access_token;
  refreshToken = data.refresh_token;
  sessionStorage.setItem("access_token", accessToken);
  sessionStorage.setItem("refresh_token", refreshToken);
}

function clearTokens() {
  accessToken = refreshToken = null;
  sessionStorage.removeItem("access_token");
  sessionStorage.removeItem("refresh_token");
}

async function errorFrom(res) {
  const body = await res.json().catch(() => ({}));
  const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail;
  const err = new Error(detail || `Request failed (${res.status})`);
  err.status = res.status;
  return err;
}

async function refreshAccessToken() {
  if (!refreshToken) return false;
  refreshing ??= fetch("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
    .then(async (res) => {
      if (!res.ok) return false;
      saveTokens(await res.json());
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

// fetch with the bearer token; on 401 it refreshes once and retries.
async function authFetch(path, options = {}) {
  const send = () =>
    fetch(path, { ...options, headers: { ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...options.headers } });
  let res = await send();
  if (res.status === 401 && (await refreshAccessToken())) res = await send();
  if (res.status === 401) clearTokens();
  return res;
}

async function request(path, options = {}) {
  const res = await authFetch(path, { ...options, headers: { "Content-Type": "application/json", ...options.headers } });
  if (!res.ok) throw await errorFrom(res);
  return res.status === 204 ? null : res.json();
}

export const api = {
  hasToken: () => Boolean(accessToken),
  async login(username, password) {
    const res = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) throw await errorFrom(res);
    const data = await res.json();
    saveTokens(data);
    return data.user;
  },
  async logout() {
    const token = refreshToken;
    clearTokens();
    if (token) {
      await fetch("/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: token }),
      }).catch(() => {});
    }
  },
  me: () => request("/api/me"),
  models: () => request("/api/models"),
  chat: (question, model_id) =>
    request("/api/chat", { method: "POST", body: JSON.stringify({ question, model_id }) }),
  documents: () => request("/api/documents"),
  deleteDocument: (docId) => request(`/api/documents/${encodeURIComponent(docId)}`, { method: "DELETE" }),

  // Runs the ingestion pipeline and calls onEvent for each NDJSON event as it arrives.
  async ingest(formData, onEvent) {
    const res = await authFetch("/api/documents/ingest", { method: "POST", body: formData });
    if (!res.ok) throw await errorFrom(res);
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
