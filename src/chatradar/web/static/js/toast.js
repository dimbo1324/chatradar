// Short messages in a live region. A toast may carry one action (for example Undo).

import { button, h, icon } from "./dom.js";
import { t } from "./i18n.js";

const LIFETIME_MS = 6000;
let region = null;

function ensureRegion() {
  if (region && region.isConnected) return region;
  region = h("div", { className: "toasts", "aria-live": "polite", role: "status" });
  document.body.append(region);
  return region;
}

export function toast(message, { kind = "", action = null, lifetime = LIFETIME_MS } = {}) {
  const item = h("div", { className: `toast ${kind}`.trim() });
  const dismiss = () => item.remove();
  item.append(h("span", { className: "msg" }, message));
  if (action) {
    item.append(
      button(action.label, {
        kind: "sm",
        onClick: () => {
          dismiss();
          action.onClick();
        },
      }),
    );
  }
  item.append(
    h(
      "button",
      { type: "button", className: "icon-btn", "aria-label": t("common.close"), onClick: dismiss },
      icon("close", { size: "sm" }),
    ),
  );
  ensureRegion().append(item);
  setTimeout(dismiss, kind === "error" ? lifetime * 1.5 : lifetime);
  return dismiss;
}

export function toastError(error) {
  toast(error && error.message ? error.message : String(error), { kind: "error" });
}
