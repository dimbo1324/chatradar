// Filter form pieces shared by the Messages and Search views. Form state lives in the URL
// hash as plain values (dates as YYYY-MM-DD in local time); the API gets aware ISO instants.

import { dateInput, field, h, select } from "./dom.js";

export const TRI_STATE = [
  ["", "Any"],
  ["true", "Yes"],
  ["false", "No"],
];

export function chatKey(source, chatId) {
  return source && chatId ? `${source}:${chatId}` : "";
}

export function chatSelect(chats, params) {
  const options = [["", "All chats"]];
  for (const summary of chats) {
    options.push([chatKey(summary.chat.source, summary.chat.chat_id), summary.chat.title]);
  }
  return select("chat", options, chatKey(params.get("source"), params.get("chat_id")));
}

export function dateFields(params) {
  return [
    field("From", dateInput("date_from", params.get("date_from"))),
    field("To", dateInput("date_to", params.get("date_to"))),
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

export function filterForm(path, controls, submitLabel = "Apply") {
  const form = h(
    "form",
    { className: "filters" },
    controls,
    h(
      "div",
      { className: "actions" },
      h("button", { type: "submit" }, submitLabel),
      h("a", { href: `#/${path}`, className: "button secondary" }, "Reset"),
    ),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = formToParams(form).toString();
    location.hash = query ? `#/${path}?${query}` : `#/${path}`;
  });
  return form;
}
