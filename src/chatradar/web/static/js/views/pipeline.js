import { api } from "../api.js";
import { clear, errorBox, h, loading, table, utcString } from "../dom.js";

const REFRESH_MS = 10_000;

function stageRow(stage) {
  const total = stage.done + stage.pending;
  const percent = total === 0 ? 100 : Math.round((stage.done / total) * 100);
  return h(
    "tr",
    {},
    h("td", {}, stage.stage),
    h("td", { className: "num" }, `v${stage.version}`),
    h("td", { className: "num" }, stage.done),
    h("td", { className: "num" }, stage.pending),
    h(
      "td",
      { className: "progress-cell" },
      h("progress", { max: total || 1, value: stage.done, "aria-label": `${stage.stage} progress` }),
      h("span", { className: "small" }, ` ${percent}%`),
    ),
  );
}

export async function renderPipeline({ root, signal }) {
  root.append(h("h1", {}, "Pipeline"));
  const body = root.appendChild(h("div", { "aria-live": "polite" }, loading()));

  const refresh = async () => {
    try {
      const stats = await api.pipeline(signal);
      clear(body).append(
        h("p", {}, "Total messages: ", h("strong", {}, stats.total_messages)),
        table(["Stage", "Version", "Done", "Pending", "Progress"], stats.stages.map(stageRow), "Stages"),
        h(
          "p",
          { className: "muted small" },
          `Updated ${utcString(new Date().toISOString())}; refreshes every ${REFRESH_MS / 1000} s.`,
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
