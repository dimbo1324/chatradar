// Fetch wrapper for the JSON API (docs/api.md). Errors carry the HTTP status and detail.

import { t } from "./i18n.js";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function describe(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => `${(item.loc || []).slice(1).join(".") || t("common.request")}: ${item.msg}`)
      .join("; ");
  }
  return t("common.unexpected");
}

// The server's detail text is English; what the user reads depends on the status class.
function explain(status, detail) {
  if (status === 404) return t("common.not_found");
  if (status === 422) return `${t("common.bad_request")} ${detail}`;
  if (status >= 500) return t("common.server_error");
  return detail;
}

export async function getJson(path, params = {}, signal = undefined) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  }
  const qs = query.toString();
  let response;
  try {
    response = await fetch(qs ? `${path}?${qs}` : path, {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(t("common.unreachable"), 0);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = describe((await response.json()).detail);
    } catch {
      // The body is not JSON: keep the status text.
    }
    throw new ApiError(explain(response.status, detail), response.status);
  }
  return response.json();
}

export const api = {
  chats: (signal) => getJson("/api/chats", {}, signal),
  pipeline: (signal) => getJson("/api/pipeline", {}, signal),
  messages: (filters, signal) => getJson("/api/messages", filters, signal),
  thread: (id, signal) => getJson(`/api/threads/${encodeURIComponent(id)}`, {}, signal),
  search: (q, filters, signal) => getJson("/api/search", { q, ...filters }, signal),
  review: (noise, n, signal) => getJson("/api/review", { noise, n }, signal),
  noiseReasons: (signal) => getJson("/api/noise-reasons", {}, signal),
};
