# ChatImport — Vision

A quiet background service that keeps a complete, machine-readable local archive of the
Telegram groups and channels the owner cares about, so later programs (ChatRadar first) can
work with that history without ever touching Telegram themselves.

## What it is for

- The full text history of about eight topical chats, on the owner's own disk, as JSONL.
- New messages land within seconds, but are written in small batches.
- Control is simple and physical: delete a folder to refetch it, run `trim` to drop old
  history, edit `chats.toml` to change what is tracked.
- It never lets itself fill the disk.
- Media (voice, round videos, photos, documents) can be switched on later without changing
  the format.

## What it is not

- Not a reader of Telegram Desktop's local database; it is its own client.
- Not an analyser: search, threads, digests and answers belong to ChatRadar.
- Not a publisher: nothing leaves the owner's machine.
- Not a collector of private dialogs: only the chats in the library.

## Where it goes

ChatImport and ChatRadar are developed on separate branches of one repository and are meant
to become one product: ChatImport's folder becomes a raw store for ChatRadar, or its
listener moves into ChatRadar as `chatradar listen` (`docs/architecture.md` §15).
