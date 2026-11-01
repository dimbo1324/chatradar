"""Who is signed in: a short-lived client that only connects, checks the session and asks `get_me`.

It never sends anything and never logs in. Used by the window to show the account of a session
while the service is not running (the service itself holds the session otherwise).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from telethon import errors

from chatimport.ports import ChatImportError
from chatimport.telegram.client import _make_client, protect_session  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.config import TelegramConfig


@dataclass(frozen=True, slots=True)
class SessionInfo:
    handle: str


async def probe_session(config: TelegramConfig, session_path: Path) -> SessionInfo | None:
    """The signed-in account (`@username` or `id N`, never the phone), or None when the
    credentials are missing, the session file does not exist or it is not signed in."""
    if not config.is_configured or not await asyncio.to_thread(session_path.is_file):
        return None
    client: Any = _make_client(config, session_path)
    try:
        await client.connect()
        protect_session(session_path)
        if not await client.is_user_authorized():
            return None
        me = await client.get_me()
    except errors.AuthKeyError, errors.UnauthorizedError:
        return None
    except (errors.RPCError, OSError, TimeoutError) as error:
        raise ChatImportError(
            f"cannot check the Telegram session: {type(error).__name__}"
        ) from error
    finally:
        await client.disconnect()
    username = getattr(me, "username", None)
    return SessionInfo(f"@{username}" if username else f"id {me.id}")
