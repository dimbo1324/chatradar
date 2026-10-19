import { api } from "../api.js";
import {
  badge,
  banner,
  bar,
  clear,
  emptyState,
  errorBox,
  excerpt,
  externalLink,
  field,
  h,
  icon,
  pageHead,
  select,
  skeleton,
  threadHref,
  tile,
  timeEl,
} from "../dom.js";
import { apiFilters, filterForm, pager } from "../filters.js";
import { dec, num, t, tEnum } from "../i18n.js";
import { toast, toastError } from "../toast.js";

const KINDS = ["gratitude", "spam_offers", "spam_contacts", "questions", "question_phrases"];
const STATUSES = ["candidate", "active", "rejected", "dormant"];
const ORDERS = ["score", "occurrences", "recent"];
const LANGS = ["ru", "es", "en", "any"];
const API_KEYS = ["kind", "status", "lang", "order", "limit", "offset"];
const PAGE_SIZE = 50;
const MAX_EXAMPLES = 3;
const STATUS_CHIP = { candidate: "info", active: "ok", rejected: "bad", dormant: "" };
const STATUS_ICON = { candidate: "info", active: "check-circle", rejected: "x-circle", dormant: "refresh" };
const TARGET = { accept: "active", reject: "rejected", reset: "candidate" };

function toastText(decision, term) {
  if (decision === "accept") return t("lexicon.toast.accept", { term });
  if (decision === "reject") return t("lexicon.toast.reject", { term });
  return t("lexicon.toast.reset", { term });
}

function summaryView(summary) {
  const out = h("div", { className: "stack" });
  if (summary.pending_apply) {
    out.append(banner(t("lexicon.pending_apply"), { iconName: "alert" }));
  }
  const statusTile = (status) => {
    return h(
      "a",
      { href: `#/lexicon?status=${status}`, className: "tile-link" },
      tile(tEnum("term_status", status), num(summary.by_status[status] || 0), { iconName: STATUS_ICON[status] }),
    );
  };
  out.append(
    h(
      "div",
      { className: "tiles" },
      tile(t("lexicon.revision"), `#${num(summary.revision)}`, { iconName: "book" }),
      ...STATUSES.map(statusTile),
      tile(t("lexicon.labels"), num(summary.labels), { iconName: "tag", hint: t("lexicon.labels_hint") }),
    ),
  );
  return out;
}

function exampleRow(message, example) {
  if (!message) {
    return h("li", { className: "example muted" }, `${t("lexicon.example_missing")} (#${example.msg_id})`);
  }
  return h(
    "li",
    { className: "example" },
    h("div", { className: "meta" }, timeEl(message.date), externalLink(message.link)),
    h("p", { className: "body" }, excerpt(message.text, 200) || `[${tEnum("media", message.media_type)}]`),
    message.thread_id
      ? h(
          "a",
          { href: threadHref(message.thread_id), className: "btn secondary sm" },
          icon("branch", { size: "sm" }),
          t("lexicon.open_thread"),
        )
      : h("span", { className: "muted small" }, t("lexicon.no_thread")),
  );
}

function examplesBlock(term, signal) {
  const examples = term.examples.slice(0, MAX_EXAMPLES);
  if (examples.length === 0) return h("p", { className: "muted small" }, t("lexicon.no_examples"));
  const list = h("ul", { className: "examples" });
  const details = h(
    "details",
    { className: "examples-box" },
    h(
      "summary",
      {},
      icon("chevron-right", { size: "sm" }),
      t("lexicon.examples", { n: examples.length }),
    ),
    list,
  );
  let loaded = false;
  details.addEventListener("toggle", async () => {
    if (!details.open || loaded) return;
    loaded = true;
    list.replaceChildren(skeleton("row-sk", 1));
    const found = await Promise.all(
      examples.map((ex) => api.message(ex.source, ex.chat_id, ex.msg_id, signal).catch(() => null)),
    );
    if (signal.aborted) return;
    list.replaceChildren(...examples.map((ex, i) => exampleRow(found[i], ex)));
  });
  return details;
}

function metric(label, value) {
  return h("div", { className: "metric" }, h("dt", {}, label), h("dd", {}, value));
}

function decisionLine(term) {
  if (!term.decided_at) return null;
  return h(
    "p",
    { className: "muted small decision" },
    t("lexicon.decided"),
    " ",
    timeEl(term.decided_at),
    term.decided_by ? ` · ${term.decided_by}` : null,
    term.note ? ` · ${term.note}` : null,
  );
}

function termCard(term, ctx) {
  const decide = (decision) => ctx.decide(term, decision);
  const act = (decision, label, iconName, kind, disabledWhen) =>
    h(
      "button",
      { type: "button", className: `${kind} sm`, disabled: term.status === disabledWhen, onClick: () => decide(decision) },
      icon(iconName, { size: "sm" }),
      label,
    );
  const card = h(
    "article",
    { className: "card term", "data-status": term.status },
    h(
      "div",
      { className: "term-head" },
      h("h3", { className: "term-text" }, term.term),
      h(
        "div",
        { className: "chips" },
        badge(tEnum("lexicon_kind", term.kind), "accent", "tag"),
        badge(tEnum("term_status", term.status), STATUS_CHIP[term.status], STATUS_ICON[term.status]),
        term.lang !== "any" ? badge(tEnum("lang", term.lang), "lang", "language") : null,
        badge(tEnum("term_source", term.source)),
      ),
    ),
    h(
      "dl",
      { className: "metrics" },
      metric(t("lexicon.occurrences"), num(term.occurrences)),
      metric(t("lexicon.chats"), num(term.chats)),
      metric(t("lexicon.authors"), num(term.authors)),
      metric(
        t("lexicon.score"),
        h("span", { className: "score" }, h("span", { className: "num" }, dec(term.score)), bar(ctx.scoreFraction(term.score))),
      ),
    ),
    decisionLine(term),
    h(
      "div",
      { className: "term-actions" },
      act("accept", t("lexicon.accept"), "check", "ok", "active"),
      act("reject", t("lexicon.reject"), "x-circle", "bad", "rejected"),
      act("reset", t("lexicon.reset"), "undo", "secondary", "candidate"),
    ),
    examplesBlock(term, ctx.signal),
  );
  return card;
}

export async function renderLexicon({ root, params, signal }) {
  root.append(pageHead(t("lexicon.title"), { sub: t("lexicon.sub") }));
  const summaryBox = root.appendChild(h("div", { "aria-live": "polite" }, skeleton("tile-sk", 2)));

  const options = (values, prefix) => [["", t("common.any")], ...values.map((v) => [v, tEnum(prefix, v)])];
  root.append(
    filterForm(
      "lexicon",
      [
        field(t("lexicon.kind"), select("kind", options(KINDS, "lexicon_kind"), params.get("kind"))),
        field(t("lexicon.status"), select("status", options(STATUSES, "term_status"), params.get("status"))),
        field(
          t("lexicon.language"),
          select("lang", [["", t("common.any")], ...LANGS.map((l) => [l, tEnum("lang", l)])], params.get("lang")),
        ),
        field(
          t("lexicon.order"),
          select("order", ORDERS.map((o) => [o, tEnum("lexicon_order", o)]), params.get("order") || "score"),
        ),
      ],
      undefined,
      params,
    ),
  );
  const list = root.appendChild(h("div", { className: "stack", "aria-live": "polite" }, skeleton("row-sk", 4)));

  const loadSummary = async () => {
    try {
      clear(summaryBox).append(summaryView(await api.lexiconSummary(signal)));
    } catch (error) {
      if (signal.aborted) return;
      clear(summaryBox).append(errorBox(error));
    }
  };
  const filters = { limit: PAGE_SIZE, ...apiFilters(params, API_KEYS) };
  const [, page] = await Promise.all([loadSummary(), api.lexiconTerms(filters, signal)]);

  if (page.items.length === 0) {
    clear(list).append(emptyState(t("lexicon.empty"), { illus: "illus-search" }));
    return;
  }
  const maxScore = Math.max(1, ...page.items.map((term) => Math.abs(term.score)));
  const cards = new Map();
  const ctx = {
    signal,
    scoreFraction: (score) => Math.max(0, score) / maxScore,
    decide: (term, decision) => decide(term, decision),
  };
  const keyOf = (term) => `${term.kind}|${term.lang}|${term.term}`;
  const latest = new Map(page.items.map((term) => [keyOf(term), term]));

  async function decide(term, decision) {
    const key = keyOf(term);
    const previous = latest.get(key) || term;
    const optimistic = {
      ...previous,
      status: TARGET[decision],
      decided_at: new Date().toISOString(),
      decided_by: previous.decided_by || "human",
    };
    latest.set(key, optimistic);
    swap(key, optimistic);
    try {
      const saved = await api.decide(previous, decision);
      latest.set(key, saved);
      swap(key, saved);
      toast(toastText(decision, saved.term), {
        action:
          decision === "reset"
            ? null
            : { label: t("lexicon.undo"), onClick: () => decide(saved, "reset") },
      });
      loadSummary();
    } catch (error) {
      latest.set(key, previous);
      swap(key, previous);
      toastError(error);
    }
  }

  function swap(key, term) {
    const old = cards.get(key);
    const fresh = termCard(term, ctx);
    if (old) old.replaceWith(fresh);
    cards.set(key, fresh);
  }

  clear(list).append(
    ...page.items.map((term) => {
      const card = termCard(term, ctx);
      cards.set(keyOf(term), card);
      return card;
    }),
    pager(page, params, "lexicon"),
  );
}
