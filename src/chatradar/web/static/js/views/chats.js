import { api } from "../api.js";
import { emptyState, h, icon, loading, pageHead, table, tile, timeEl } from "../dom.js";
import { num, t, tEnum } from "../i18n.js";

function messagesHref(chat) {
  const query = new URLSearchParams({ source: chat.source, chat_id: chat.chat_id });
  return `#/messages?${query}`;
}

function totals(chats) {
  const sum = (key) => chats.reduce((acc, summary) => acc + summary[key], 0);
  return { messages: sum("message_count"), noise: sum("noise_count"), threads: sum("thread_count") };
}

export async function renderChats({ root, signal }) {
  root.append(pageHead(t("chats.title")));
  const status = root.appendChild(loading());
  const chats = await api.chats(signal);
  status.remove();

  if (chats.length === 0) {
    root.append(emptyState(t("chats.empty")));
    return;
  }
  const sum = totals(chats);
  const noiseShare = sum.messages === 0 ? 0 : sum.noise / sum.messages;
  root.append(
    h(
      "div",
      { className: "tiles" },
      tile(t("chats.tile.chats"), num(chats.length), { iconName: "chats" }),
      tile(t("chats.tile.messages"), num(sum.messages), { iconName: "messages" }),
      tile(t("chats.tile.noise"), num(sum.noise), {
        iconName: "mute",
        hint: t("chats.tile.noise_share", { share: Math.round(noiseShare * 100) }),
      }),
      tile(t("chats.tile.threads"), num(sum.threads), { iconName: "branch" }),
    ),
  );
  const rows = chats.map((summary) => {
    const chat = summary.chat;
    return h(
      "tr",
      {},
      h(
        "td",
        {},
        h("a", { href: messagesHref(chat) }, h("strong", {}, chat.title), icon("chevron-right", { size: "sm" })),
        chat.username ? h("div", { className: "muted small" }, `@${chat.username}`) : null,
      ),
      h("td", {}, tEnum("source", chat.source)),
      h("td", { className: "num" }, num(summary.message_count)),
      h("td", { className: "num" }, num(summary.noise_count)),
      h("td", { className: "num" }, num(summary.thread_count)),
      h("td", {}, timeEl(summary.first_message_at)),
      h("td", {}, timeEl(summary.last_message_at)),
      h("td", {}, timeEl(summary.last_sync_at)),
    );
  });
  root.append(
    table(
      [
        t("chats.col.chat"),
        t("chats.col.source"),
        t("chats.col.messages"),
        t("chats.col.noise"),
        t("chats.col.threads"),
        t("chats.col.first"),
        t("chats.col.last"),
        t("chats.col.sync"),
      ],
      rows,
      t("chats.caption"),
    ),
  );
}
