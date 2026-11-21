import { useEffect, useState } from "react";

interface InstallPrompt extends Event {
  prompt(): Promise<unknown>;
}

let available: InstallPrompt | null = null;

window.addEventListener("beforeinstallprompt", event => {
  event.preventDefault();
  available = event as InstallPrompt;
  window.dispatchEvent(new Event("xeniex-install-change"));
});
window.addEventListener("appinstalled", () => {
  available = null;
  window.dispatchEvent(new Event("xeniex-install-change"));
});

export function InstallButton() {
  const [prompt, setPrompt] = useState(available);
  useEffect(() => {
    const refresh = () => setPrompt(available);
    refresh();
    window.addEventListener("xeniex-install-change", refresh);
    return () => window.removeEventListener("xeniex-install-change", refresh);
  }, []);
  if (!prompt) return null;
  return <button type="button" onClick={() => {
    available = null;
    setPrompt(null);
    void prompt.prompt().catch(() => {});
  }}>Install app</button>;
}
