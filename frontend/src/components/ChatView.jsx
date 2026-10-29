import { useEffect, useRef, useState } from "react";
import { Logo } from "./Header.jsx";
import { Send, Sparkles } from "./icons.jsx";
import Message from "./Message.jsx";

const SUGGESTIONS = [
  "How many days of annual leave do I get?",
  "What is the gift limit from vendors?",
  "How long must my password be?",
  "What happens during probation?",
];

function Typing() {
  return (
    <div className="flex items-start gap-3" role="status" aria-label="Searching policies">
      <Logo className="size-8" />
      <div className="card flex items-center gap-1.5 rounded-tl-md px-4 py-3.5">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="size-2 rounded-full bg-muted/70 motion-safe:animate-bounce"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
        <span className="ml-2 text-xs text-muted">Searching policies…</span>
      </div>
    </div>
  );
}

function EmptyState({ onPick, name }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center pt-8 text-center sm:pt-14">
      <Logo className="size-14" />
      <h2 className="mt-5 text-2xl font-semibold tracking-tight">Hi {name.split(" ")[0]}, what can I look up?</h2>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        Ask about leave, conduct, IT security or onboarding. Every answer cites the approved policy it came from, and
        I'll say so when I can't find one.
      </p>
      <div className="mt-6 grid w-full gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="card group flex cursor-pointer items-start gap-2.5 p-3.5 text-left text-sm transition-all hover:-translate-y-0.5 hover:border-ring/60"
          >
            <Sparkles className="mt-0.5 size-4 shrink-0 text-accent-text" />
            <span>{s}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function ChatView({ messages, busy, onAsk, user }) {
  const [input, setInput] = useState("");
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  function submit(e) {
    e.preventDefault();
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    onAsk(q);
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4">
      <div className="flex-1 space-y-6 py-6" aria-live="polite">
        {messages.length === 0 ? (
          <EmptyState onPick={onAsk} name={user.name} />
        ) : (
          messages.map((m, i) => <Message key={i} m={m} />)
        )}
        {busy && <Typing />}
        <div ref={endRef} />
      </div>

      <form
        onSubmit={submit}
        className="sticky bottom-0 -mx-4 bg-gradient-to-t from-bg via-bg/95 to-transparent px-4 pb-4 pt-6"
      >
        <div className="card flex items-center gap-2 p-2 pl-4 focus-within:border-ring/70">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a policy question…"
            aria-label="Ask a policy question"
            className="min-w-0 flex-1 bg-transparent py-2 text-sm text-fg outline-none placeholder:text-muted/70"
            autoFocus
          />
          <button className="btn-primary !px-3.5" disabled={busy || !input.trim()} aria-label="Send">
            <Send className="size-4" />
            <span className="hidden sm:inline">Send</span>
          </button>
        </div>
        <p className="mt-2 text-center text-xs text-muted">
          Answers come from approved documents only. Confirm important decisions with HR.
        </p>
      </form>
    </main>
  );
}
