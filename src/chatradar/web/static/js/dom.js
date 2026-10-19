// Safe DOM helpers. User content only ever becomes text nodes: nothing here parses HTML.

import { t } from "./i18n.js";

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

// Dates are written day.month.year, the Russian convention.
export function utcString(iso) {
  const d = new Date(iso);
  return (
    `${pad(d.getUTCDate())}.${pad(d.getUTCMonth() + 1)}.${d.getUTCFullYear()} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} ${t("common.utc")}`
  );
}

export function localString(iso) {
  const d = new Date(iso);
  return (
    `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ` +
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

export function externalLink(url, label = t("common.telegram_link")) {
  const href = safeUrl(url);
  if (!href) return h("span", { className: "muted" }, "—");
  return h(
    "a",
    { href, target: "_blank", rel: "noopener noreferrer", className: "ext" },
    label,
    icon("external", { size: "sm" }),
  );
}

export function threadHref(threadId) {
  return `#/threads/${encodeURIComponent(threadId)}`;
}

export function threadLink(threadId, label = t("messages.open_thread")) {
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

const SVG_NS = "http://www.w3.org/2000/svg";
export const SPRITE = "/static/icons/sprite.svg";

// An icon from the sprite. Decorative by default; a `label` makes it announce itself.
export function icon(name, { size = "", label = "" } = {}) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", `icon ${size}`.trim());
  svg.setAttribute("viewBox", "0 0 24 24");
  if (label) {
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
  } else svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `${SPRITE}#${name}`);
  svg.append(use);
  return svg;
}

// A larger monochrome illustration from the sprite (empty states).
export function illustration(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "illus");
  svg.setAttribute("viewBox", "0 0 120 90");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `${SPRITE}#${name}`);
  svg.append(use);
  return svg;
}

export function badge(text, kind = "", iconName = "") {
  return h("span", { className: `chip ${kind}`.trim() }, iconName ? icon(iconName, { size: "sm" }) : null, text);
}

export const chip = badge;

export function iconButton(iconName, label, onClick, className = "") {
  return h(
    "button",
    { type: "button", className: `icon-btn ${className}`.trim(), "aria-label": label, title: label, onClick },
    icon(iconName),
  );
}

export function button(label, { iconName = "", kind = "", onClick = undefined, type = "button" } = {}) {
  return h("button", { type, className: kind, onClick }, iconName ? icon(iconName, { size: "sm" }) : null, label);
}

export function linkButton(href, label, { iconName = "", kind = "secondary" } = {}) {
  return h("a", { href, className: `btn ${kind}` }, iconName ? icon(iconName, { size: "sm" }) : null, label);
}

export function pageHead(title, { sub = "", actions = null } = {}) {
  return h(
    "div",
    { className: "page-head" },
    h("h1", {}, title),
    actions ? h("div", { className: "actions" }, actions) : null,
    sub ? h("p", { className: "sub" }, sub) : null,
  );
}

export function tile(label, value, { hint = "", iconName = "" } = {}) {
  return h(
    "div",
    { className: "tile" },
    h("span", { className: "label" }, iconName ? icon(iconName, { size: "sm" }) : null, label),
    h("span", { className: "value" }, value),
    hint ? h("span", { className: "hint" }, hint) : null,
  );
}

// A horizontal bar; `fraction` is 0..1 and drives the width through a CSS custom property.
export function bar(fraction, kind = "") {
  const fill = h("span");
  const el = h("div", { className: `bar ${kind}`.trim(), role: "presentation" }, fill);
  el.style.setProperty("--v", String(Math.max(0, Math.min(1, fraction || 0))));
  return el;
}

// Skeleton placeholders shown while a view loads.
export function skeleton(kind = "row-sk", count = 3) {
  const stack = h("div", { className: "skeleton-stack", role: "status", "aria-label": t("common.loading") });
  for (let i = 0; i < count; i += 1) stack.append(h("span", { className: `skeleton ${kind}` }));
  return stack;
}

export function loading() {
  return skeleton("row-sk", 3);
}

export function emptyState(text, { illus = "illus-empty", action = null } = {}) {
  return h("div", { className: "empty" }, illustration(illus), h("p", {}, text), action);
}

export function errorBox(error) {
  const label = error && error.status ? t("common.error_http", { status: error.status }) : `${t("common.error")}: `;
  return h(
    "div",
    { className: "error", role: "alert" },
    icon("alert"),
    h("div", {}, h("strong", {}, label), error && error.message ? error.message : String(error)),
  );
}

export function banner(text, { kind = "", iconName = "alert" } = {}) {
  return h("div", { className: `banner ${kind}`.trim(), role: "status" }, icon(iconName), h("p", {}, text));
}

// Tables become stacked cards on narrow screens: every cell carries its column title.
export function table(headers, rows, caption) {
  const first = rows[0];
  const numeric = first ? Array.from(first.children).map((td) => td.classList.contains("num")) : [];
  for (const row of rows) {
    Array.from(row.children).forEach((td, index) => td.setAttribute("data-label", headers[index] ?? ""));
  }
  return h(
    "div",
    { className: "table-wrap" },
    h(
      "table",
      { className: "data" },
      caption ? h("caption", { className: "visually-hidden" }, caption) : null,
      h(
        "thead",
        {},
        h("tr", {}, headers.map((title, i) => h("th", { scope: "col", className: numeric[i] ? "num" : null }, title))),
      ),
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
