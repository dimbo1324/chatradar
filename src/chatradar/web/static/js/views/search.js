import { api } from "../api.js";
import {
  badge,
  emptyState,
  externalLink,
  field,
  h,
  loading,
  markedSnippet,
  span,
  threadHref,
} from "../dom.js";
import { apiFilters, chatSelect, dateFields, filterForm } from "../filters.js";
import { t, tn } from "../i18n.js";

const API_KEYS = ["source", "chat_id", "date_from", "date_to"];

function hitItem(hit, titles) {
  const thread = hit.thread;
  return h(
    "li",
    { className: "hit" },
    h("p", { className: "body" }, markedSnippet(hit.snippet)),
    h(
      "div",
      { className: "meta" },
      h("span", {}, titles.get(`${thread.source}:${thread.chat_id}`) || thread.chat_id),
      span(thread.started_at, thread.ended_at),
      h("span", {}, tn("search.messages_count", thread.msg_count)),
      thread.has_question ? badge(t("common.question"), "question") : null,
      h("a", { href: threadHref(thread.thread_id) }, t("search.open_thread")),
      externalLink(hit.link),
    ),
  );
}

export async function renderSearch({ root, params, signal }) {
  root.append(h("h1", {}, t("search.title")));
  const status = root.appendChild(loading());
  const chats = await api.chats(signal);
  status.remove();

  const q = params.get("q") || "";
  const input = h("input", { type: "search", name: "q", placeholder: t("search.placeholder"), required: true });
  input.value = q;
  const queryField = field(t("search.query"), input);
  queryField.classList.add("wide");
  root.append(
    filterForm(
      "search",
      [queryField, field(t("common.chat"), chatSelect(chats, params)), ...dateFields(params)],
      t("search.submit"),
    ),
  );
  if (!q.trim()) {
    root.append(emptyState(t("search.hint")));
    if (!location.hash.includes("?")) input.focus();
    return;
  }

  const results = root.appendChild(h("section", { "aria-live": "polite" }, loading(t("common.searching"))));
  const hits = await api.search(q, apiFilters(params, API_KEYS), signal);
  results.replaceChildren();
  if (hits.length === 0) {
    results.append(emptyState(t("search.no_answer")));
    return;
  }
  const titles = new Map(chats.map((s) => [`${s.chat.source}:${s.chat.chat_id}`, s.chat.title]));
  results.append(
    h("p", { className: "muted" }, tn("search.found", hits.length)),
    h("ol", { className: "hits" }, hits.map((hit) => hitItem(hit, titles))),
  );
}
