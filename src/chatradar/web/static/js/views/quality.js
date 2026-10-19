import { api } from "../api.js";
import {
  badge,
  bar,
  clear,
  emptyState,
  errorBox,
  h,
  linkButton,
  pageHead,
  skeleton,
  table,
  tile,
} from "../dom.js";
import { num, pct, t, tEnum } from "../i18n.js";

function metricCell(value) {
  return h("td", { className: "num" }, h("div", { className: "metric-cell" }, h("span", {}, pct(value)), bar(value, "ok")));
}

function reasonRow(metrics) {
  return h(
    "tr",
    {},
    h("td", {}, tEnum("noise_reason", metrics.label)),
    h("td", { className: "num" }, num(metrics.support)),
    h("td", { className: "num" }, num(metrics.tp)),
    h("td", { className: "num" }, num(metrics.fp)),
    h("td", { className: "num" }, num(metrics.fn)),
    metricCell(metrics.precision),
    metricCell(metrics.recall),
    metricCell(metrics.f1),
  );
}

function metricsHeaders() {
  return [
    t("quality.col.reason"),
    t("quality.col.support"),
    t("quality.col.tp"),
    t("quality.col.fp"),
    t("quality.col.fn"),
    t("quality.col.precision"),
    t("quality.col.recall"),
    t("quality.col.f1"),
  ];
}

function kpiTiles(metrics, titleKey) {
  return h(
    "section",
    { className: "stack" },
    h("h2", {}, titleKey),
    h(
      "div",
      { className: "tiles" },
      kpi(t("quality.precision"), metrics.precision, t("quality.precision_hint")),
      kpi(t("quality.recall"), metrics.recall, t("quality.recall_hint")),
      kpi(t("quality.f1"), metrics.f1, t("quality.f1_hint")),
      tile(t("quality.support"), num(metrics.support), { hint: `${t("quality.col.tp")} ${num(metrics.tp)} · ${t("quality.col.fp")} ${num(metrics.fp)} · ${t("quality.col.fn")} ${num(metrics.fn)}` }),
    ),
  );
}

function kpi(label, value, hint) {
  const el = tile(label, pct(value), { hint });
  el.append(bar(value, "ok"));
  return el;
}

function report(quality, labelCount) {
  const out = h("div", { className: "stack" });
  out.append(
    h(
      "div",
      { className: "chips" },
      badge(`${t("quality.source")}: ${tEnum("eval_source", quality.source)}`, "info", "info"),
      badge(`${t("quality.total")}: ${num(quality.total)}`, "", "messages"),
      quality.missing > 0 ? badge(`${t("quality.missing")}: ${num(quality.missing)}`, "warn", "alert") : null,
      labelCount === null ? null : badge(`${t("quality.labels")}: ${num(labelCount)}`, "", "tag"),
      badge(`${t("quality.lexicon_revision")}: #${num(quality.lexicon_revision)}`, "accent", "book"),
    ),
    kpiTiles(quality.noise, t("quality.noise_title")),
  );
  if (quality.reasons.length > 0) {
    out.append(
      h("h2", {}, t("quality.reasons_title")),
      table(metricsHeaders(), quality.reasons.map(reasonRow), t("quality.reasons_title")),
    );
  }
  out.append(
    kpiTiles(quality.question, t("quality.question_title")),
    h(
      "section",
      { className: "stack" },
      h("h2", {}, t("quality.language_title")),
      h(
        "div",
        { className: "tiles" },
        quality.language_accuracy === null
          ? tile(t("quality.accuracy"), "—", { hint: t("quality.language_none") })
          : kpi(t("quality.accuracy"), quality.language_accuracy, t("quality.language_hint", { n: num(quality.language_total) })),
      ),
    ),
  );
  const versions = Object.entries(quality.stage_versions);
  if (versions.length > 0) {
    out.append(
      h("h2", {}, t("quality.versions_title")),
      h(
        "div",
        { className: "chips" },
        versions.map(([stage, version]) => badge(`${tEnum("stage", stage)}: v${version}`, "", "pipeline")),
      ),
    );
  }
  return out;
}

export async function renderQuality({ root, signal }) {
  root.append(pageHead(t("quality.title"), { sub: t("quality.sub") }));
  const body = root.appendChild(h("div", { "aria-live": "polite" }, skeleton("tile-sk", 3)));
  try {
    const [quality, summary] = await Promise.all([
      api.quality(signal),
      api.lexiconSummary(signal).catch((error) => {
        if (signal.aborted) throw error;
        return null;
      }),
    ]);
    if (quality.total === 0) {
      clear(body).append(
        emptyState(t("quality.empty"), {
          illus: "illus-chart",
          action: linkButton("#/review", t("quality.go_review"), { iconName: "review", kind: "" }),
        }),
      );
      return;
    }
    clear(body).append(report(quality, summary ? summary.labels : null));
  } catch (error) {
    if (signal.aborted) return;
    clear(body).append(errorBox(error));
  }
}
