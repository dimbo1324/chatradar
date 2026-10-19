// Human labels on messages (ADR-0004): "noise" with an optional reason, or "not noise".
// The store is loaded once per view; every control reflects it and writes through it.

import { api } from "./api.js";
import { badge, h, icon } from "./dom.js";
import { t, tEnum } from "./i18n.js";
import { toast, toastError } from "./toast.js";

const keyOf = (m) => `${m.source}:${m.chat_id}:${m.msg_id}`;

export async function loadLabelContext(signal) {
  const [labels, reasons] = await Promise.all([
    api.labels(signal).catch((error) => {
      if (signal.aborted) throw error;
      toastError(error);
      return [];
    }),
    api.noiseReasonList(signal).catch((error) => {
      if (signal.aborted) throw error;
      return [];
    }),
  ]);
  const byKey = new Map();
  for (const label of labels) {
    const key = keyOf(label);
    if (!byKey.has(key)) byKey.set(key, label); // newest first: keep the first
  }
  return { byKey, reasons };
}

function summaryChip(label) {
  if (!label) return null;
  if (!label.is_noise) return badge(t("labels.not_noise"), "ok", "check-circle");
  const reason = label.reason ? `: ${tEnum("noise_reason", label.reason)}` : "";
  return badge(`${t("labels.noise")}${reason}`, "noise", "mute");
}

// Buttons "noise" / "not noise" plus a reason select. Works with the keyboard like any form.
export function labelControls(message, context) {
  const key = keyOf(message);
  const root = h("div", { className: "label-controls", role: "group", "aria-label": t("labels.group") });

  const reasonSelect = h("select", { "aria-label": t("labels.reason"), className: "reason-select" });
  reasonSelect.append(h("option", { value: "" }, t("labels.reason_none")));
  for (const reason of context.reasons) {
    reasonSelect.append(h("option", { value: reason }, tEnum("noise_reason", reason)));
  }

  const save = async (isNoise) => {
    const body = { source: message.source, chat_id: message.chat_id, msg_id: message.msg_id, is_noise: isNoise };
    if (isNoise && reasonSelect.value) body.reason = reasonSelect.value;
    root.setAttribute("aria-busy", "true");
    try {
      context.byKey.set(key, await api.saveLabel(body));
      toast(isNoise ? t("labels.saved_noise") : t("labels.saved_clean"));
    } catch (error) {
      toastError(error);
    }
    root.removeAttribute("aria-busy");
    paint();
  };

  const noiseButton = h("button", { type: "button", className: "noise-btn sm", onClick: () => save(true) });
  const cleanButton = h("button", { type: "button", className: "ok sm", onClick: () => save(false) });
  reasonSelect.addEventListener("change", () => {
    if (context.byKey.get(key)?.is_noise) save(true);
  });

  const status = h("span", { className: "label-status" });
  function paint() {
    const current = context.byKey.get(key);
    noiseButton.replaceChildren(icon("mute", { size: "sm" }), t("labels.noise"));
    cleanButton.replaceChildren(icon("check", { size: "sm" }), t("labels.not_noise"));
    noiseButton.setAttribute("aria-pressed", String(Boolean(current?.is_noise)));
    cleanButton.setAttribute("aria-pressed", String(current ? !current.is_noise : false));
    reasonSelect.value = current?.is_noise && current.reason ? current.reason : reasonSelect.value;
    status.replaceChildren(...(current ? [summaryChip(current)] : []));
  }
  paint();
  root.append(noiseButton, reasonSelect, cleanButton, status);
  return root;
}
