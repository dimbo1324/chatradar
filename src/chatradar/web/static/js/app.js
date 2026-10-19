// Hash router: #/<view>[/<arg>][?query]. Each view renders into <main> and stops its work
// (fetches, timers) when the AbortSignal fires on the next navigation.

import { clear, errorBox, h, icon, iconButton } from "./dom.js";
import { loadLocale, t, tEnum } from "./i18n.js";
import { applyMode, currentMode, nextMode } from "./theme.js";
import { renderLexicon } from "./views/lexicon.js";
import { renderQuality } from "./views/quality.js";
import { renderChats } from "./views/chats.js";
import { renderMessages } from "./views/messages.js";
import { renderPipeline } from "./views/pipeline.js";
import { renderReview } from "./views/review.js";
import { renderSearch } from "./views/search.js";
import { renderThread } from "./views/thread.js";

// `label` is the i18n key of the page title; routes with `menu` appear in the top menu.
const routes = {
  chats: { render: renderChats, label: "nav.chats", menu: true, icon: "chats" },
  pipeline: { render: renderPipeline, label: "nav.pipeline", menu: true, icon: "pipeline" },
  messages: { render: renderMessages, label: "nav.messages", menu: true, icon: "messages" },
  threads: { render: renderThread, label: "nav.thread", nav: "messages" },
  search: { render: renderSearch, label: "nav.search", menu: true, icon: "search" },
  review: { render: renderReview, label: "nav.review", menu: true, icon: "review" },
  lexicon: { render: renderLexicon, label: "nav.lexicon", menu: true, icon: "book" },
  quality: { render: renderQuality, label: "nav.quality", menu: true, icon: "gauge" },
};

const THEME_ICON = { auto: "auto", light: "sun", dark: "moon" };

let controller = null;

export function parseHash(hash) {
  const body = hash.replace(/^#\/?/, "");
  const [pathPart, queryPart = ""] = body.split("?", 2);
  const [name = "", ...rest] = pathPart.split("/");
  const raw = rest.join("/");
  let arg = "";
  try {
    arg = decodeURIComponent(raw);
  } catch {
    arg = raw;
  }
  return { name, arg, params: new URLSearchParams(queryPart) };
}

function setDrawer(open) {
  document.body.classList.toggle("drawer-open", open);
  const button = document.querySelector(".menu-btn");
  if (button) button.setAttribute("aria-expanded", String(open));
  if (open) document.querySelector(".nav a")?.focus();
  else if (button && button.offsetParent !== null) button.focus();
}

function themeButton() {
  const button = h("button", { type: "button", className: "icon-btn theme-btn" });
  const paint = () => {
    const mode = currentMode();
    button.replaceChildren(icon(THEME_ICON[mode]));
    const label = `${t("theme.label")}: ${tEnum("theme", mode)}`;
    button.setAttribute("aria-label", label);
    button.title = label;
  };
  button.addEventListener("click", () => {
    applyMode(nextMode(currentMode()));
    paint();
  });
  paint();
  return button;
}

function buildChrome() {
  const brand = document.querySelector(".brand");
  brand.replaceChildren(icon("chats"), t("app.name"));
  const panel = document.querySelector(".nav-panel");
  const nav = panel.querySelector("nav");
  nav.setAttribute("aria-label", t("nav.aria"));
  const list = nav.querySelector(".nav");
  for (const [name, entry] of Object.entries(routes)) {
    if (!entry.menu) continue;
    list.append(
      h("li", {}, h("a", { href: `#/${name}`, "data-route": name }, icon(entry.icon), t(entry.label))),
    );
  }
  panel.querySelector(".nav-panel-head").append(
    h("span", {}, t("nav.menu")),
    iconButton("close", t("nav.close"), () => setDrawer(false)),
  );
  const menuButton = iconButton("menu", t("nav.menu"), () => setDrawer(true), "menu-btn");
  menuButton.setAttribute("aria-controls", "nav-panel");
  menuButton.setAttribute("aria-expanded", "false");
  panel.after(themeButton(), menuButton);
  document.querySelector(".scrim").addEventListener("click", () => setDrawer(false));
  panel.addEventListener("click", (event) => {
    if (event.target.closest("a")) setDrawer(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("drawer-open")) setDrawer(false);
  });
}

function markNav(active) {
  for (const link of document.querySelectorAll(".nav a")) {
    if (link.dataset.route === active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

async function route() {
  if (location.hash && !location.hash.startsWith("#/")) return; // in-page anchors
  const { name, arg, params } = parseHash(location.hash);
  const entry = routes[name];
  if (!entry) {
    location.replace("#/chats");
    return;
  }
  if (controller) controller.abort();
  controller = new AbortController();
  const { signal } = controller;

  const root = document.getElementById("view");
  clear(root);
  document.body.classList.remove("drawer-open");
  document.title = `${t(entry.label)} · ${t("app.name")}`;
  markNav(entry.nav || name);
  try {
    await entry.render({ root, arg, params, signal });
  } catch (error) {
    if (error.name === "AbortError" || signal.aborted) return;
    for (const status of root.querySelectorAll(".skeleton-stack")) status.remove();
    root.append(errorBox(error));
  }
}

async function start() {
  try {
    await loadLocale();
  } catch (error) {
    document.getElementById("view").textContent = String(error.message || error);
    return;
  }
  buildChrome();
  window.addEventListener("hashchange", route);
  await route();
}

start();
