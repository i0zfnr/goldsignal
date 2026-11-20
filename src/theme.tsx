import { useState } from "react";
import { Moon, Sun } from "lucide-react";

export type Theme = "light" | "dark";

export function readTheme(): Theme {
  try {
    return localStorage.getItem("goldsignal-theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0b0c0f" : "#ffffff");
  window.dispatchEvent(new Event("goldsignal-theme"));
}

export function ThemeToggle() {
  const [theme, setTheme] = useState(readTheme);
  const next = theme === "light" ? "dark" : "light";
  return <button className="toolbar-icon" type="button" aria-label={`Switch to ${next} theme`} onClick={() => {
    try { localStorage.setItem("goldsignal-theme", next); } catch {}
    applyTheme(next);
    setTheme(next);
  }}>{theme === "light" ? <Moon size={19} aria-hidden="true" /> : <Sun size={19} aria-hidden="true" />}</button>;
}
