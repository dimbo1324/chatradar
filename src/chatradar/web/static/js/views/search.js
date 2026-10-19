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
      h("span", {}, `${thread.msg_count} messages`),
      thread.has_question ? badge("question", "question") : null,
      h("a", { href: threadHref(thread.thread_id) }, "Open thread"),
      externalLink(hit.link),
    ),
  );
}

export async function renderSearch({ root, params, signal }) {
  root.append(h("h1", {}, "Search"));
  const status = root.appendChild(loading());
  const chats = await api.chats(signal);
  status.remove();

  const q = params.get("q") || "";
  const input = h("input", { type: "search", name: "q", placeholder: "Words to find", required: true });
  input.value = q;
  const queryField = field("Query", input);
  queryField.classList.add("wide");
  root.append(
    filterForm(
      "search",
      [queryField, field("Chat", chatSelect(chats, params)), ...dateFields(params)],
      "Search",
    ),
  );
  if (!q.trim()) {
    root.append(emptyState("Type a question or a few words and press Search."));
    if (!location.hash.includes("?")) input.focus();
    return;
  }

  const results = root.appendChild(h("section", { "aria-live": "polite" }, loading("Searching…")));
  const hits = await api.search(q, apiFilters(params, API_KEYS), signal);
  results.replaceChildren();
  if (hits.length === 0) {
    results.append(emptyState("No answer in the chats: nothing matched this query."));
    return;
  }
  const titles = new Map(chats.map((s) => [`${s.chat.source}:${s.chat.chat_id}`, s.chat.title]));
  results.append(
    h("p", { className: "muted" }, `${hits.length} threads found`),
    h("ol", { className: "hits" }, hits.map((hit) => hitItem(hit, titles))),
  );
}
