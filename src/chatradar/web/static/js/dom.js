// Safe DOM helpers. User content only ever becomes text nodes: nothing here parses HTML.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "className") el.className = value;
    else if (name.startsWith("on") && typeof value === "function") {
      el.addEventListener(name.slice(2).toLowerCase(), value);
    } else el.setAttribute(name, value === true ? "" : String(value));
  }
  append(el, children);
  return el;
}

export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

const pad = (n) => String(n).padStart(2, "0");

export function utcString(iso) {
  const d = new Date(iso);
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`
  );
}

export function localString(iso) {
  const d = new Date(iso);
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

// A date shown in local time, with the exact UTC moment in the tooltip.
export function timeEl(iso) {
  if (!iso) return h("span", { className: "muted" }, "—");
  return h("time", { datetime: iso, title: utcString(iso) }, localString(iso));
}

export function span(fromIso, toIso) {
  return h("span", { className: "span" }, timeEl(fromIso), " → ", timeEl(toIso));
}

// Only http(s) links from the data are rendered as links; anything else stays text.
export function safeUrl(url) {
  if (!url) return null;
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export function externalLink(url, label = "Telegram") {
  const href = safeUrl(url);
  if (!href) return h("span", { className: "muted" }, "—");
  return h("a", { href, target: "_blank", rel: "noopener noreferrer", className: "ext" }, label);
}

export function threadHref(threadId) {
  return `#/threads/${encodeURIComponent(threadId)}`;
}

export function threadLink(threadId, label = "Thread") {
  if (!threadId) return h("span", { className: "muted" }, "—");
  return h("a", { href: threadHref(threadId) }, label);
}

export function excerpt(text, max = 160) {
  const flat = (text || "").replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

// "[[word]]" markers from the search index become <mark> elements built node by node.
export function markedSnippet(snippet) {
  const out = h("span", { className: "snippet" });
  const parts = (snippet || "").split(/(\[\[.*?\]\])/s);
  for (const part of parts) {
    if (part.startsWith("[[") && part.endsWith("]]")) out.append(h("mark", {}, part.slice(2, -2)));
    else if (part) out.append(document.createTextNode(part));
  }
  return out;
}

export function badge(text, kind = "") {
  return h("span", { className: `badge ${kind}`.trim() }, text);
}

export function loading(text = "Loading…") {
  return h("p", { className: "status", role: "status" }, text);
}

export function emptyState(text) {
  return h("p", { className: "empty" }, text);
}

export function errorBox(error) {
  const status = error && error.status ? ` (HTTP ${error.status})` : "";
  return h(
    "div",
    { className: "error", role: "alert" },
    h("strong", {}, `Error${status}: `),
    error && error.message ? error.message : String(error),
  );
}

export function table(headers, rows, caption) {
  return h(
    "div",
    { className: "table-wrap" },
    h(
      "table",
      {},
      caption ? h("caption", { className: "visually-hidden" }, caption) : null,
      h("thead", {}, h("tr", {}, headers.map((title) => h("th", { scope: "col" }, title)))),
      h("tbody", {}, rows),
    ),
  );
}

export function field(label, control) {
  return h("label", { className: "field" }, h("span", {}, label), control);
}

export function select(name, options, value) {
  const el = h("select", { name });
  for (const [optValue, optLabel] of options) {
    const option = h("option", { value: optValue }, optLabel);
    if (optValue === (value ?? "")) option.selected = true;
    el.append(option);
  }
  return el;
}

export function dateInput(name, isoValue) {
  const el = h("input", { type: "date", name });
  if (isoValue) el.value = isoValue;
  return el;
}
