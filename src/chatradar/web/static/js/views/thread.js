import { api } from "../api.js";
import { badge, emptyState, externalLink, h, loading, span, timeEl } from "../dom.js";

const MAX_INDENT = 8;

// Messages arrive chronologically, so a parent is always seen before its replies.
function replyDepths(messages) {
  const depths = new Map();
  for (const message of messages) {
    const parent = message.reply_to ? depths.get(message.reply_to) : undefined;
    depths.set(message.msg_id, parent === undefined ? 0 : parent + 1);
  }
  return depths;
}

function messageItem(message, depth) {
  const item = h(
    "li",
    { className: "thread-msg" },
    h(
      "div",
      { className: "meta" },
      timeEl(message.date),
      message.is_question ? badge("question", "question") : null,
      message.reply_to ? h("span", { className: "muted small" }, `reply to #${message.reply_to}`) : null,
      h("span", { className: "muted small" }, `#${message.msg_id}`),
      externalLink(message.link),
    ),
    h(
      "p",
      { className: "body" },
      message.text || h("span", { className: "muted" }, `[${message.media_type}]`),
    ),
  );
  item.style.setProperty("--depth", String(Math.min(depth, MAX_INDENT)));
  return item;
}

async function chatTitle(thread, signal) {
  try {
    const chats = await api.chats(signal);
    const found = chats.find(
      (s) => s.chat.source === thread.source && s.chat.chat_id === thread.chat_id,
    );
    return found ? found.chat.title : thread.chat_id;
  } catch (error) {
    if (signal.aborted) throw error;
    return thread.chat_id;
  }
}

export async function renderThread({ root, arg, signal }) {
  root.append(h("h1", {}, "Thread"));
  if (!arg) {
    root.append(emptyState("No thread selected."));
    return;
  }
  const status = root.appendChild(loading());
  const detail = await api.thread(arg, signal);
  const thread = detail.thread;
  const title = await chatTitle(thread, signal);
  status.remove();

  const messagesQuery = new URLSearchParams({ thread_id: thread.thread_id });
  root.append(
    h(
      "dl",
      { className: "summary" },
      h("dt", {}, "Chat"),
      h("dd", {}, title),
      h("dt", {}, "Time span"),
      h("dd", {}, span(thread.started_at, thread.ended_at)),
      h("dt", {}, "Messages"),
      h("dd", {}, String(thread.msg_count), thread.has_question ? badge("question", "question") : null),
      h("dt", {}, "Thread id"),
      h("dd", {}, h("code", {}, thread.thread_id), " ", h("a", { href: `#/messages?${messagesQuery}` }, "as table")),
    ),
  );
  if (detail.messages.length === 0) {
    root.append(emptyState("This thread has no messages."));
    return;
  }
  const depths = replyDepths(detail.messages);
  root.append(
    h(
      "ol",
      { className: "thread" },
      detail.messages.map((message) => messageItem(message, depths.get(message.msg_id) || 0)),
    ),
  );
}
