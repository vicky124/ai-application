import { useCallback, useEffect, useState } from "react";

const KEY = "theme";
const query = () => window.matchMedia("(prefers-color-scheme: dark)");

function readStored() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch {
    // storage can be blocked (private mode); fall back to the system preference
  }
  return null;
}

/**
 * Light/dark theme. Starts from the saved choice, otherwise the operating system preference, and follows the
 * system setting until the user picks one explicitly with the toggle. The `dark` class on <html> drives all colors.
 */
export function useTheme() {
  const [stored, setStored] = useState(readStored);
  const [systemDark, setSystemDark] = useState(() => query().matches);
  const theme = stored ?? (systemDark ? "dark" : "light");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    const mq = query();
    const onChange = (e) => setSystemDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    setStored(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // not persisted; still applies for this session
    }
  }, [theme]);

  return { theme, toggle };
}
