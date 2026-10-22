"use client";

import { useEffect, useSyncExternalStore } from "react";

type Theme = "dark" | "light";
const storageKey = "novalton-theme";
const changeEvent = "novalton-theme-change";
function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(changeEvent, callback);
  return () => { window.removeEventListener("storage", callback); window.removeEventListener(changeEvent, callback); };
}
function snapshot(): Theme {
  try { return localStorage.getItem(storageKey) === "light" ? "light" : "dark"; }
  catch { return "dark"; }
}

export function ThemeSync() {
  const theme = useSyncExternalStore(subscribe, snapshot, () => "dark" as Theme);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  return null;
}

export function AppearanceControl() {
  const theme = useSyncExternalStore(subscribe, snapshot, () => "dark" as Theme);
  function select(value: Theme) {
    document.documentElement.dataset.theme = value;
    try { localStorage.setItem(storageKey, value); } catch { /* The selection still works for this page. */ }
    window.dispatchEvent(new Event(changeEvent));
  }
  return <div className="appearance-control" role="group" aria-label="Apparence">
    <button type="button" aria-pressed={theme === "dark"} onClick={() => select("dark")}>Sombre</button>
    <button type="button" aria-pressed={theme === "light"} onClick={() => select("light")}>Clair</button>
  </div>;
}
