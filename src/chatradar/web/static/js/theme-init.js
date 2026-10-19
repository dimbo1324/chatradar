// Runs before first paint (classic script, blocking) so a saved theme does not flash.
try {
  const saved = localStorage.getItem("chatradar.theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
} catch {
  // Storage is blocked: the system theme applies.
}
