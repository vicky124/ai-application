import { useState } from "react";

const DEMO = [
  ["alice", "alice123", "Employee"],
  ["mark", "mark123", "Manager"],
  ["hannah", "hannah123", "HR"],
];

export default function Login({ onLogin }) {
  const [u, setU] = useState("alice");
  const [p, setP] = useState("alice123");
  const [err, setErr] = useState("");

  async function submit(e) {
    e.preventDefault();
    setErr("");
    try {
      await onLogin(u, p);
    } catch (ex) {
      setErr(ex.message);
    }
  }

  return (
    <form className="login" onSubmit={submit}>
      <h1>Policy &amp; HR Copilot</h1>
      <input value={u} onChange={(e) => setU(e.target.value)} placeholder="Username" />
      <input type="password" value={p} onChange={(e) => setP(e.target.value)} placeholder="Password" />
      {err && <p className="error">{err}</p>}
      <button>Sign in</button>
      <p className="hint">
        Demo users:{" "}
        {DEMO.map(([name, pw, role]) => (
          <button
            type="button"
            key={name}
            className="link"
            onClick={() => {
              setU(name);
              setP(pw);
            }}
          >
            {role}{" "}
          </button>
        ))}
      </p>
    </form>
  );
}
