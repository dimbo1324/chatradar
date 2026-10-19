import { api } from "../api.js";
import {
  badge,
  button,
  clear,
  emptyState,
  errorBox,
  excerpt,
  externalLink,
  h,
  loading,
  pageHead,
  timeEl,
} from "../dom.js";
import { num, t, tEnum } from "../i18n.js";
import { labelControls, loadLabelContext } from "../labels.js";

const SAMPLE_SIZE = 100;

function sampleItem(message, showReason, context) {
  return h(
    "li",
    { className: "card sample" },
    h(
      "div",
      { className: "meta" },
      timeEl(message.date),
      showReason
        ? badge(message.noise_reason ? tEnum("noise_reason", message.noise_reason) : t("common.noise"), "noise", "mute")
        : null,
      externalLink(message.link),
    ),
    h(
      "p",
      { className: "body" },
      excerpt(message.text, 300) ||
        h("span", { className: "muted" }, `[${tEnum("media", message.media_type) || message.media_type}]`),
    ),
    labelControls(message, context),
  );
}

function column(id, title, messages, showReason, context) {
  return h(
    "section",
    { className: "review-col", id: `review-${id}`, "aria-labelledby": `review-${id}-h` },
    h("h2", { id: `review-${id}-h` }, `${title} (${num(messages.length)})`),
    messages.length === 0
      ? emptyState(t("common.nothing"))
      : h("ol", { className: "samples" }, messages.map((m) => sampleItem(m, showReason, context))),
  );
}

// On narrow screens the two columns become tabs; on wide ones the tab bar is hidden by CSS.
function tabBar(body) {
  const list = h("div", { className: "tabs review-tabs", role: "tablist" });
  const choose = (id) => {
    body.dataset.tab = id;
    for (const tab of list.children) tab.setAttribute("aria-selected", String(tab.dataset.tab === id));
  };
  for (const [id, label] of [
    ["noise", t("review.noise")],
    ["clean", t("review.clean")],
  ]) {
    const tab = h(
      "button",
      { type: "button", role: "tab", "aria-selected": "false", "aria-controls": `review-${id}`, "data-tab": id },
      label,
    );
    tab.addEventListener("click", () => choose(id));
    list.append(tab);
  }
  choose("noise");
  return list;
}

export async function renderReview({ root, signal }) {
  const body = h("div", { className: "review", "aria-live": "polite" });
  const load = async () => {
    clear(body).append(loading());
    try {
      const [noise, clean, context] = await Promise.all([
        api.review(true, SAMPLE_SIZE, signal),
        api.review(false, SAMPLE_SIZE, signal),
        loadLabelContext(signal),
      ]);
      clear(body).append(
        column("noise", t("review.noise"), noise, true, context),
        column("clean", t("review.clean"), clean, false, context),
      );
    } catch (error) {
      if (signal.aborted) return;
      clear(body).append(errorBox(error));
    }
  };
  root.append(
    pageHead(t("review.title"), {
      sub: t("review.sample_hint", { n: SAMPLE_SIZE }),
      actions: button(t("review.new_sample"), { iconName: "refresh", onClick: load }),
    }),
    tabBar(body),
    body,
  );
  await load();
}
