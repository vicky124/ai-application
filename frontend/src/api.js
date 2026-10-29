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
};
