const KEY = "mtos_display_mode";

export function getSavedDisplayMode() {
  const v = (localStorage.getItem(KEY) || "").trim().toLowerCase();
  if (v === "light" || v === "easy") return v;
  return "dark";
}

export function applyDisplayMode(mode) {
  const m = (mode || "dark").toLowerCase();
  const root = document.documentElement;
  root.classList.remove("theme-light", "theme-easy");
  if (m === "light") root.classList.add("theme-light");
  if (m === "easy") root.classList.add("theme-easy");
  localStorage.setItem(KEY, m);
  return m;
}

