import { Moon, Sun } from "./icons.jsx";

export default function ThemeToggle({ theme, onToggle }) {
  const dark = theme === "dark";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="Dark mode"
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={onToggle}
      className="group relative inline-flex h-9 w-[4.25rem] shrink-0 cursor-pointer items-center rounded-full border border-border bg-surface-2 px-1 transition-colors hover:border-ring/60"
    >
      <Sun className="absolute left-2 size-4 text-warn" />
      <Moon className="absolute right-2 size-4 text-accent-text" />
      <span
        className={`relative z-10 grid size-7 place-items-center rounded-full bg-surface shadow-card ring-1 ring-border transition-transform duration-200 ${
          dark ? "translate-x-[2.125rem]" : "translate-x-0"
        }`}
      >
        {dark ? <Moon className="size-4 text-accent-text" /> : <Sun className="size-4 text-warn" />}
      </span>
    </button>
  );
}
