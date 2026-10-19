import { api } from "../api.js";
import { badge, clear, emptyState, errorBox, excerpt, externalLink, h, loading, timeEl } from "../dom.js";

const SAMPLE_SIZE = 100;

function sampleItem(message, showReason) {
  return h(
    "li",
    {},
    h(
      "div",
      { className: "meta" },
      timeEl(message.date),
      showReason ? badge(message.noise_reason || "noise", "noise") : null,
      externalLink(message.link),
    ),
    h("p", { className: "body" }, excerpt(message.text, 300) || h("span", { className: "muted" }, `[${message.media_type}]`)),
  );
}

function column(title, messages, showReason) {
  return h(
    "section",
    { className: "review-col" },
    h("h2", {}, `${title} (${messages.length})`),
    messages.length === 0
      ? emptyState("Nothing to show.")
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
      clear(body).append(column("Noise", noise, true), column("Not noise", clean, false));
    } catch (error) {
      if (signal.aborted) return;
      clear(body).append(errorBox(error));
    }
  };
  root.append(
    h(
      "div",
      { className: "heading-row" },
      h("h1", {}, "Filter review"),
      h("button", { type: "button", onClick: load }, "New sample"),
    ),
    h("p", { className: "muted" }, `A random sample of up to ${SAMPLE_SIZE} messages from each side.`),
    body,
  );
  await load();
}
