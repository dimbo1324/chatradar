import { api } from "../api.js";
import { clear, errorBox, h, loading, table, utcString } from "../dom.js";
import { num, t, tEnum } from "../i18n.js";

const REFRESH_MS = 10_000;

function stageRow(stage) {
  const total = stage.done + stage.pending;
  const percent = total === 0 ? 100 : Math.round((stage.done / total) * 100);
  return h(
    "tr",
    {},
    h("td", {}, tEnum("stage", stage.stage)),
    h("td", { className: "num" }, `v${stage.version}`),
    h("td", { className: "num" }, num(stage.done)),
    h("td", { className: "num" }, num(stage.pending)),
    h(
      "td",
      { className: "progress-cell" },
      h("progress", { max: total || 1, value: stage.done, "aria-label": t("pipeline.progress_label", { stage: tEnum("stage", stage.stage) }) }),
      h("span", { className: "small" }, ` ${percent}%`),
    ),
  );
}

export async function renderPipeline({ root, signal }) {
  root.append(h("h1", {}, t("pipeline.title")));
  const body = root.appendChild(h("div", { "aria-live": "polite" }, loading()));

  const refresh = async () => {
    try {
      const stats = await api.pipeline(signal);
      clear(body).append(
        h("p", {}, t("pipeline.total"), h("strong", {}, num(stats.total_messages))),
        table(
          [
            t("pipeline.col.stage"),
            t("pipeline.col.version"),
            t("pipeline.col.done"),
            t("pipeline.col.pending"),
            t("pipeline.col.progress"),
          ],
          stats.stages.map(stageRow),
          t("pipeline.caption"),
        ),
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
