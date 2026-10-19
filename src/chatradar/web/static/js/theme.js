// Theme preference: auto (follow the system), light or dark. Saved in localStorage when it works.

const KEY = "chatradar.theme";
export const MODES = ["auto", "light", "dark"];

export function currentMode() {
  const set = document.documentElement.dataset.theme;
  return set === "light" || set === "dark" ? set : "auto";
}

export function applyMode(mode) {
  if (mode === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = mode;
  try {
    if (mode === "auto") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, mode);
  } catch {
    // Storage is blocked: the choice lasts until the page is closed.
  }
}

export function nextMode(mode) {
  return MODES[(MODES.indexOf(mode) + 1) % MODES.length];
}
