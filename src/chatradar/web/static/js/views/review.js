import { api } from "../api.js";
import { badge, clear, emptyState, errorBox, excerpt, externalLink, h, loading, timeEl } from "../dom.js";
import { num, t, tEnum } from "../i18n.js";

const SAMPLE_SIZE = 100;

function sampleItem(message, showReason) {
  return h(
    "li",
    {},
    h(
      "div",
      { className: "meta" },
      timeEl(message.date),
      showReason
        ? badge(message.noise_reason ? tEnum("noise_reason", message.noise_reason) : t("common.noise"), "noise")
        : null,
      externalLink(message.link),
    ),
    h(
      "p",
      { className: "body" },
      excerpt(message.text, 300) ||
        h("span", { className: "muted" }, `[${tEnum("media", message.media_type) || message.media_type}]`),
    ),
  );
}

function column(title, messages, showReason) {
  return h(
    "section",
    { className: "review-col" },
    h("h2", {}, `${title} (${num(messages.length)})`),
    messages.length === 0
      ? emptyState(t("common.nothing"))
      : h("ol", { className: "samples" }, messages.map((m) => sampleItem(m, showReason))),
  );
}

export async function renderReview({ root, signal }) {
  const body = h("div", { className: "review", "aria-live": "polite" });
  const load = async () => {
    clear(body).append(loading());
    try {
      const [noise, clean] = await Promise.all([
        api.review(true, SAMPLE_SIZE, signal),
        api.review(false, SAMPLE_SIZE, signal),
      ]);
      clear(body).append(column(t("review.noise"), noise, true), column(t("review.clean"), clean, false));
    } catch (error) {
      if (signal.aborted) return;
      clear(body).append(errorBox(error));
    }
  };
  root.append(
    h(
      "div",
      { className: "heading-row" },
      h("h1", {}, t("review.title")),
      h("button", { type: "button", onClick: load }, t("review.new_sample")),
    ),
    h("p", { className: "muted" }, t("review.sample_hint", { n: SAMPLE_SIZE })),
    body,
  );
  await load();
}
