import { api } from "../api.js";
import {
  badge,
  emptyState,
  excerpt,
  externalLink,
  field,
  h,
  loading,
  select,
  table,
  threadLink,
  timeEl,
} from "../dom.js";
import { apiFilters, chatSelect, dateFields, filterForm, triState } from "../filters.js";
import { num, t, tEnum } from "../i18n.js";

const API_KEYS = [
  "source",
  "chat_id",
  "date_from",
  "date_to",
  "lang",
  "is_noise",
  "noise_reason",
  "is_question",
  "thread_id",
  "limit",
  "offset",
];
const PAGE_SIZES = ["50", "100", "200", "500"];

function chatTitles(chats) {
  const titles = new Map();
  for (const summary of chats) {
    titles.set(`${summary.chat.source}:${summary.chat.chat_id}`, summary.chat.title);
  }
  return titles;
}

function buildForm(chats, reasons, params) {
  const reasonOptions = [["", t("common.any")]];
  for (const [reason, count] of Object.entries(reasons)) {
    reasonOptions.push([reason, `${tEnum("noise_reason", reason)} (${num(count)})`]);
  }
  const lang = h("input", { type: "text", name: "lang", size: 4, placeholder: t("messages.language_hint") });
  lang.value = params.get("lang") || "";
  const controls = [
    field(t("common.chat"), chatSelect(chats, params)),
    ...dateFields(params),
    field(t("messages.language"), lang),
    field(t("messages.noise"), select("is_noise", triState(), params.get("is_noise"))),
    field(t("messages.noise_reason"), select("noise_reason", reasonOptions, params.get("noise_reason"))),
    field(t("messages.question"), select("is_question", triState(), params.get("is_question"))),
    field(
      t("messages.per_page"),
      select(
        "limit",
        PAGE_SIZES.map((size) => [size, size]),
        params.get("limit") || "50",
      ),
    ),
  ];
  const threadId = params.get("thread_id");
  if (threadId) controls.push(h("input", { type: "hidden", name: "thread_id", value: threadId }));
  return filterForm("messages", controls);
}

function messageRow(message, titles) {
  return h(
    "tr",
    { className: message.is_noise ? "noise" : null },
    h("td", { className: "nowrap" }, timeEl(message.date)),
    h("td", {}, titles.get(`${message.source}:${message.chat_id}`) || message.chat_id),
    h(
      "td",
      { className: "text" },
      message.is_question ? badge("?", "question") : null,
      excerpt(message.text) ||
        h("span", { className: "muted" }, `[${tEnum("media", message.media_type) || message.media_type}]`),
    ),
    h("td", {}, message.lang ? tEnum("lang", message.lang) : "—"),
    h(
      "td",
      {},
      message.is_noise
        ? badge(message.noise_reason ? tEnum("noise_reason", message.noise_reason) : t("common.noise"), "noise")
        : "—",
    ),
    h("td", {}, threadLink(message.thread_id)),
    h("td", {}, externalLink(message.link)),
  );
}

function pager(page, params) {
  const pageLink = (offset, label) => {
    const next = new URLSearchParams(params);
    next.set("offset", String(offset));
    return h("a", { href: `#/messages?${next}`, className: "button secondary" }, label);
  };
  const first = page.total === 0 ? 0 : page.offset + 1;
  const last = page.offset + page.items.length;
  return h(
    "nav",
    { className: "pager", "aria-label": t("messages.pages") },
    page.offset > 0 ? pageLink(Math.max(0, page.offset - page.limit), t("messages.previous")) : null,
    h("span", {}, t("messages.range", { first: num(first), last: num(last), total: num(page.total) })),
    last < page.total ? pageLink(page.offset + page.limit, t("messages.next")) : null,
  );
}

export async function renderMessages({ root, params, signal }) {
  root.append(h("h1", {}, t("messages.title")));
  const status = root.appendChild(loading());
  const [chats, reasons, page] = await Promise.all([
    api.chats(signal),
    api.noiseReasons(signal),
    api.messages(apiFilters(params, API_KEYS), signal),
  ]);
  status.remove();

  root.append(buildForm(chats, reasons, params));
  const threadId = params.get("thread_id");
  if (threadId) root.append(h("p", {}, t("messages.only_thread"), threadLink(threadId, threadId)));
  if (page.items.length === 0) {
    root.append(emptyState(t("messages.empty")));
    return;
  }
  const titles = chatTitles(chats);
  root.append(
    pager(page, params),
    table(
      [
        t("messages.col.date"),
        t("messages.col.chat"),
        t("messages.col.text"),
        t("messages.col.lang"),
        t("messages.col.noise"),
        t("messages.col.thread"),
        t("messages.col.link"),
      ],
      page.items.map((message) => messageRow(message, titles)),
      t("messages.caption"),
    ),
    pager(page, params),
  );
}
