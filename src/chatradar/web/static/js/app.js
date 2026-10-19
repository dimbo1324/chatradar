// Hash router: #/<view>[/<arg>][?query]. Each view renders into <main> and stops its work
// (fetches, timers) when the AbortSignal fires on the next navigation.

import { clear, errorBox } from "./dom.js";
import { renderChats } from "./views/chats.js";
import { renderMessages } from "./views/messages.js";
import { renderPipeline } from "./views/pipeline.js";
import { renderReview } from "./views/review.js";
import { renderSearch } from "./views/search.js";
import { renderThread } from "./views/thread.js";

const routes = {
  chats: { render: renderChats, title: "Chats" },
  pipeline: { render: renderPipeline, title: "Pipeline" },
  messages: { render: renderMessages, title: "Messages" },
  threads: { render: renderThread, title: "Thread", nav: "messages" },
  search: { render: renderSearch, title: "Search" },
  review: { render: renderReview, title: "Review" },
};

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
  document.title = `${entry.title} · ChatRadar`;
  markNav(entry.nav || name);
  try {
    await entry.render({ root, arg, params, signal });
  } catch (error) {
    if (error.name === "AbortError" || signal.aborted) return;
    for (const status of root.querySelectorAll(".status")) status.remove();
    root.append(errorBox(error));
  }
}

window.addEventListener("hashchange", route);
route();
