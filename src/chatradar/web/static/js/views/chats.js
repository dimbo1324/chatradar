import { api } from "../api.js";
import { emptyState, h, loading, table, timeEl } from "../dom.js";

function messagesHref(chat) {
  const query = new URLSearchParams({ source: chat.source, chat_id: chat.chat_id });
  return `#/messages?${query}`;
}

export async function renderChats({ root, signal }) {
  root.append(h("h1", {}, "Chats"));
  const status = root.appendChild(loading());
  const chats = await api.chats(signal);
  status.remove();

  if (chats.length === 0) {
    root.append(emptyState("No chats yet. Import an export or add a chat to sync."));
    return;
  }
  const rows = chats.map((summary) => {
    const chat = summary.chat;
    return h(
      "tr",
      {},
      h(
        "td",
        {},
        h("a", { href: messagesHref(chat) }, chat.title),
        chat.username ? h("div", { className: "muted small" }, `@${chat.username}`) : null,
      ),
      h("td", {}, chat.source),
      h("td", { className: "num" }, summary.message_count),
      h("td", { className: "num" }, summary.noise_count),
      h("td", { className: "num" }, summary.thread_count),
      h("td", {}, timeEl(summary.first_message_at)),
      h("td", {}, timeEl(summary.last_message_at)),
      h("td", {}, timeEl(summary.last_sync_at)),
    );
  });
  root.append(
    table(
      ["Chat", "Source", "Messages", "Noise", "Threads", "First message", "Last message", "Last sync"],
      rows,
      "Tracked chats",
    ),
  );
}
