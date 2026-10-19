// Filter form pieces shared by the Messages and Search views. Form state lives in the URL
// hash as plain values (dates as YYYY-MM-DD in local time); the API gets aware ISO instants.

import { badge, dateInput, field, h, icon, select } from "./dom.js";
import { num, t } from "./i18n.js";

export const triState = () => [
  ["", t("common.any")],
  ["true", t("common.yes")],
  ["false", t("common.no")],
];

export function chatKey(source, chatId) {
  return source && chatId ? `${source}:${chatId}` : "";
}

export function chatSelect(chats, params) {
  const options = [["", t("common.all_chats")]];
  for (const summary of chats) {
    options.push([chatKey(summary.chat.source, summary.chat.chat_id), summary.chat.title]);
  }
  return select("chat", options, chatKey(params.get("source"), params.get("chat_id")));
}

export function dateFields(params) {
  return [
    field(t("common.from"), dateInput("date_from", params.get("date_from"))),
    field(t("common.to"), dateInput("date_to", params.get("date_to"))),
  ];
}

// Reads a submitted form into hash parameters; empty values are dropped.
export function formToParams(form) {
  const params = new URLSearchParams();
  for (const [name, value] of new FormData(form)) {
    if (value === "") continue;
    if (name === "chat") {
      const cut = value.indexOf(":");
      params.set("source", value.slice(0, cut));
      params.set("chat_id", value.slice(cut + 1));
    } else params.set(name, String(value));
  }
  return params;
}

function startOfDay(day) {
  return day ? new Date(`${day}T00:00:00`).toISOString() : undefined;
}

function endOfDay(day) {
  return day ? new Date(`${day}T23:59:59.999`).toISOString() : undefined;
}

// Hash parameters → API query parameters (only the names in `keys` pass through).
export function apiFilters(params, keys) {
  const out = {};
  for (const key of keys) {
    const value = params.get(key);
    if (value === null || value === "") continue;
    if (key === "date_from") out[key] = startOfDay(value);
    else if (key === "date_to") out[key] = endOfDay(value);
    else out[key] = value;
  }
  return out;
}

const WIDE = "(min-width: 1000px)";

// Collapsible filter panel: open on wide screens, folded on narrow ones. `params` only
// feeds the badge that counts the filters currently applied.
export function filterForm(path, controls, submitLabel = t("common.apply"), params = null) {
  const form = h(
    "form",
    { className: "filters" },
    controls,
    h(
      "div",
      { className: "actions" },
      h("button", { type: "submit" }, icon("check", { size: "sm" }), submitLabel),
      h("a", { href: `#/${path}`, className: "btn secondary" }, icon("refresh", { size: "sm" }), t("common.reset")),
    ),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = formToParams(form).toString();
    location.hash = query ? `#/${path}?${query}` : `#/${path}`;
  });
  const active = params ? [...params.keys()].filter((k) => !["offset", "limit"].includes(k)).length : 0;
  const panel = h(
    "details",
    { className: "filter-panel" },
    h(
      "summary",
      {},
      icon("filter"),
      t("common.filters"),
      active > 0 ? badge(String(active), "accent") : null,
      icon("chevron-down", { size: "sm" }),
    ),
    form,
  );
  panel.querySelector(".icon:last-child").classList.add("chev");
  panel.open = window.matchMedia(WIDE).matches;
  return panel;
}

// Previous / next links over a paged result; `path` is the hash route without the query.
export function pager(page, params, path) {
  const link = (offset, label, side) => {
    const next = new URLSearchParams(params);
    next.set("offset", String(offset));
    return h(
      "a",
      { href: `#/${path}?${next}`, className: "btn secondary" },
      side === "left" ? icon("chevron-left", { size: "sm" }) : null,
      label,
      side === "right" ? icon("chevron-right", { size: "sm" }) : null,
    );
  };
  const first = page.total === 0 ? 0 : page.offset + 1;
  const last = page.offset + page.items.length;
  return h(
    "nav",
    { className: "pager", "aria-label": t("messages.pages") },
    page.offset > 0 ? link(Math.max(0, page.offset - page.limit), t("messages.previous"), "left") : null,
    h("span", {}, t("messages.range", { first: num(first), last: num(last), total: num(page.total) })),
    last < page.total ? link(page.offset + page.limit, t("messages.next"), "right") : null,
  );
}
