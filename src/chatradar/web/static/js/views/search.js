import { api } from "../api.js";
import {
  badge,
  emptyState,
  externalLink,
  field,
  h,
  icon,
  loading,
  markedSnippet,
  pageHead,
  skeleton,
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
    { className: "hit card" },
    h("p", { className: "body" }, markedSnippet(hit.snippet)),
    h(
      "div",
      { className: "meta" },
      badge(titles.get(`${thread.source}:${thread.chat_id}`) || thread.chat_id, "accent", "chats"),
      h("span", { className: "muted small" }, span(thread.started_at, thread.ended_at)),
      badge(tn("search.messages_count", thread.msg_count), "", "messages"),
      thread.has_question ? badge(t("common.question"), "question", "question") : null,
    ),
    h(
      "div",
      { className: "meta links" },
      h(
        "a",
        { href: threadHref(thread.thread_id), className: "btn secondary sm" },
        icon("branch", { size: "sm" }),
        t("search.open_thread"),
      ),
      externalLink(hit.link),
    ),
  );
}

export async function renderSearch({ root, params, signal }) {
  root.append(pageHead(t("search.title")));
  const status = root.appendChild(loading());
  const chats = await api.chats(signal);
  status.remove();

  const q = params.get("q") || "";
  const input = h("input", { type: "search", name: "q", placeholder: t("search.placeholder"), required: true });
  input.value = q;
  const queryField = field(t("search.query"), input);
  queryField.classList.add("wide");
  const panel = filterForm(
    "search",
    [queryField, field(t("common.chat"), chatSelect(chats, params)), ...dateFields(params)],
    t("search.submit"),
    params,
  );
  panel.open = true;
  root.append(panel);
  if (!q.trim()) {
    root.append(emptyState(t("search.hint"), { illus: "illus-search" }));
    if (!location.hash.includes("?")) input.focus();
    return;
  }

  const results = root.appendChild(h("section", { "aria-live": "polite" }, skeleton("row-sk", 3)));
  const hits = await api.search(q, apiFilters(params, API_KEYS), signal);
  results.replaceChildren();
  if (hits.length === 0) {
    results.append(emptyState(t("search.no_answer"), { illus: "illus-search" }));
    return;
  }
  const titles = new Map(chats.map((s) => [`${s.chat.source}:${s.chat.chat_id}`, s.chat.title]));
  results.append(
    h("p", { className: "muted results-count" }, tn("search.found", hits.length)),
    h("ol", { className: "hits" }, hits.map((hit) => hitItem(hit, titles))),
  );
}
