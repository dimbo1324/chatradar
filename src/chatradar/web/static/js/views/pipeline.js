import { api } from "../api.js";
import { bar, badge, clear, errorBox, h, icon, loading, pageHead, tile, utcString } from "../dom.js";
import { num, t, tEnum } from "../i18n.js";

const REFRESH_MS = 10_000;
const STAGE_ICONS = { noise: "mute", enrich: "tag", threads: "branch", index: "search" };

function stageCard(stage) {
  const total = stage.done + stage.pending;
  const fraction = total === 0 ? 1 : stage.done / total;
  const percent = Math.round(fraction * 100);
  const finished = stage.pending === 0;
  const progress = bar(fraction, finished ? "ok" : "");
  progress.setAttribute("role", "progressbar");
  progress.setAttribute("aria-valuemin", "0");
  progress.setAttribute("aria-valuemax", "100");
  progress.setAttribute("aria-valuenow", String(percent));
  progress.setAttribute("aria-label", t("pipeline.progress_label", { stage: tEnum("stage", stage.stage) }));
  return h(
    "article",
    { className: "card stage-card" },
    h(
      "div",
      { className: "stage-head" },
      h("span", { className: "stage-icon" }, icon(STAGE_ICONS[stage.stage] || "pipeline")),
      h("h2", {}, tEnum("stage", stage.stage)),
      badge(`v${stage.version}`, "info"),
    ),
    progress,
    h(
      "div",
      { className: "stage-stats" },
      h("span", { className: "num-big" }, `${percent}%`),
      h("span", { className: "muted small" }, `${t("pipeline.col.done")}: ${num(stage.done)}`),
      stage.pending > 0
        ? badge(`${t("pipeline.col.pending")}: ${num(stage.pending)}`, "warn")
        : badge(t("pipeline.up_to_date"), "ok", "check-circle"),
    ),
  );
}

export async function renderPipeline({ root, signal }) {
  root.append(pageHead(t("pipeline.title")));
  const body = root.appendChild(h("div", { className: "stack", "aria-live": "polite" }, loading()));

  const refresh = async () => {
    try {
      const stats = await api.pipeline(signal);
      clear(body).append(
        h("div", { className: "tiles" }, tile(t("pipeline.total"), num(stats.total_messages), { iconName: "messages" })),
        h("div", { className: "stage-grid" }, stats.stages.map(stageCard)),
        h(
          "p",
          { className: "muted small" },
          t("pipeline.updated", {
            time: utcString(new Date().toISOString()),
            seconds: REFRESH_MS / 1000,
          }),
        ),
      );
    } catch (error) {
      if (signal.aborted) return;
      clear(body).append(errorBox(error));
    }
  };

  await refresh();
  const timer = setInterval(refresh, REFRESH_MS);
  signal.addEventListener("abort", () => clearInterval(timer), { once: true });
}
