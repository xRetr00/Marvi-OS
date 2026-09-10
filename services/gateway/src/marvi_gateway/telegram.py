"""Telegram: talking to Marvi from a phone.

Telegram is a **surface**, exactly as Chat is: the same identity, memory, tool
router and confirmation flow, reached over a different wire. Each Telegram chat
is one Chat thread, so a conversation started on the phone is in the Chat
sidebar when you sit down, and every turn goes through `Chat.send_stream` --
there is no second agent loop here to drift from the first.

## Local-only, outbound-only

The bot long-polls `getUpdates`. Nothing listens on a port, nothing needs a
public URL or a tunnel, and the only party that learns anything is Telegram,
which carries the messages. The SDK is python-telegram-bot (LGPL-3.0, used
unmodified -- see `docs/UPSTREAM.md`).

## One owner

Marvi is one person's assistant, so the bot answers exactly one Telegram
account. It is linked by a short-lived code shown on the desktop -- the one
place an attacker is not -- and sent back through a `t.me` deep link. Anyone
else gets a fixed refusal, is rate-limited, and is reported to the Mind as an
untrusted event. Group chats are ignored outright.

## What arrives is sorted by who wrote it

The owner's typed text is a user turn. Everything else -- forwarded messages,
contact cards, location labels, the caption on something forwarded -- was
written by someone else and goes to the model inside an untrusted envelope.
Those fields were the injection path in the OpenClaw message-object research;
here they never sit in instruction position to begin with.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import io
import json
import logging
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import inline_ask, paths
from .logs import get_logger
from .untrusted import wrap_external

log = get_logger("telegram")

#: The bot token BotFather issued. A secret: it lives in the provider settings
#: store beside the model keys and is scrubbed from every log line.
TOKEN_SETTING = "TELEGRAM_BOT_TOKEN"

REPO_ROOT = Path(__file__).resolve().parents[4]
ICON = REPO_ROOT / "assets" / "app-icon-source.png"

#: How long a link code stays good. Long enough to find the phone; short enough
#: that a code glimpsed over a shoulder is useless by the time it is typed.
PAIRING_SECONDS = 600
#: No 0/O or 1/I, so a code read off a screen is typed right the first time.
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

#: A stranger is told no once an hour, not once per message.
STRANGER_REPLY_SECONDS = 3600

#: Telegram's hard limit is 4096; HTML escaping grows the text, so the
#: markdown is cut well below it.
CHUNK_CHARS = 3500
#: How often a streaming draft is pushed. Every token would be a request per
#: word and a 429 soon after.
DRAFT_SECONDS = 0.6
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
#: A voice note longer than this is a podcast, not a message.
MAX_VOICE_SECONDS = 300

COMMANDS = (
    ("new", "Start a fresh conversation"),
    ("stop", "Stop what I'm doing"),
    ("help", "What I can do here"),
)
#: What anyone who finds the bot can read. Fixed on purpose: SOUL.md and USER.md
#: are private, and a bot profile is public.
PROFILE = {
    "name": "Marvi",
    "short": "A personal assistant running on her owner's own computer.",
    "description": (
        "Marvi is a personal assistant that runs on her owner's own Windows PC. "
        "She only talks to the person she belongs to; everyone else gets a polite no."
    ),
}

HELP = (
    "I'm Marvi, running on your computer. Talk to me here the way you would in "
    "the Chat window: I have my usual tools and memory, and I'll ask before "
    "doing anything that needs your OK.\n\n"
    "/new — start a fresh conversation\n"
    "/stop — stop what I'm doing"
)


class TelegramUnavailableError(Exception):
    """Telegram cannot deliver right now, with a reason a person can act on."""


class _RefusedError(Exception):
    """A message Marvi will not take, with the reply that says why."""


class _QuietPolling(logging.Filter):
    """Drops httpx's line per long poll.

    `getUpdates` returns every few seconds forever; at INFO that is a line in
    providers.log every poll, burying the provider calls that file exists for.
    Failures are WARNING and above, and still get through.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or "api.telegram.org" not in record.getMessage()


logging.getLogger("httpx").addFilter(_QuietPolling())


# -- formatting ---------------------------------------------------------------

_FENCE = re.compile(r"```[^\n`]*\n(.*?)(?:```|\Z)", re.S)
_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_STRIKE = re.compile(r"~~(.+?)~~")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$", re.M)
_BULLET = re.compile(r"^(\s*)[-*+]\s+", re.M)


def _inline(text: str) -> str:
    codes: list[str] = []

    def keep(match: re.Match[str]) -> str:
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE.sub(keep, text)
    text = _HEADING.sub(r"**\1**", text)
    text = _BULLET.sub(r"\1• ", text)
    text = html.escape(text, quote=False)
    text = _LINK.sub(
        lambda m: f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1)}</a>', text
    )
    text = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)
    text = _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)
    return re.sub(
        "\x00(\\d+)\x00",
        lambda m: f"<code>{html.escape(codes[int(m.group(1))], quote=False)}</code>",
        text,
    )


def _block(text: str) -> str:
    """Prose, with GitHub tables kept legible as preformatted text."""
    out: list[str] = []
    table: list[str] = []
    for line in text.split("\n"):
        if line.lstrip().startswith("|"):
            table.append(line)
            continue
        if table:
            out.append("<pre>" + html.escape("\n".join(table), quote=False) + "</pre>")
            table = []
        out.append(_inline(line))
    if table:
        out.append("<pre>" + html.escape("\n".join(table), quote=False) + "</pre>")
    return "\n".join(out)


def telegram_html(markdown: str) -> str:
    """The model's GitHub Markdown as the HTML subset Telegram renders.

    ponytail: a regex converter, not a Markdown parser. Anything it gets wrong
    Telegram rejects as a parse error, and the caller resends plain text -- so
    the worst case is asterisks, never a lost message.
    """
    out: list[str] = []
    position = 0
    for match in _FENCE.finditer(markdown):
        out.append(_block(markdown[position : match.start()]))
        out.append("<pre>" + html.escape(match.group(1).rstrip("\n"), quote=False) + "</pre>")
        position = match.end()
    out.append(_block(markdown[position:]))
    return "".join(out).strip()


def chunks(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split on paragraphs, then lines, then hard, so nothing exceeds `limit`."""
    parts: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        while len(paragraph) > limit:
            cut = paragraph.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                parts.append(current)
                current = ""
            parts.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip("\n")
        if current and len(current) + len(paragraph) + 2 > limit:
            parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current.strip():
        parts.append(current)
    return parts


# -- audio --------------------------------------------------------------------


def pcm16_from_audio(data: bytes) -> bytes:
    """A voice note (OGG/Opus, or any container PyAV reads) as 16 kHz mono PCM16.

    The dictation worker takes exactly that shape, so the phone's voice note
    goes through the same local recogniser as the Chat microphone -- nothing
    is sent to a cloud speech service.
    """
    import av

    pcm = bytearray()
    limit = MAX_VOICE_SECONDS * 16_000 * 2
    with av.open(io.BytesIO(data)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16_000)
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                pcm += out.to_ndarray().tobytes()
            if len(pcm) > limit:
                raise _RefusedError("That voice note is too long for me — keep it under five minutes.")
        for out in resampler.resample(None):
            pcm += out.to_ndarray().tobytes()
    return bytes(pcm)


def _profile_photo() -> bytes:
    """The app icon as the square JPEG Telegram wants for a profile photo."""
    from PIL import Image

    with Image.open(ICON) as image:
        icon = image.convert("RGBA")
        side = max(icon.size)
        canvas = Image.new("RGB", (side, side), (0, 0, 0))
        canvas.paste(icon, ((side - icon.width) // 2, (side - icon.height) // 2), icon)
        canvas = canvas.resize((640, 640))
        buffer = io.BytesIO()
        canvas.save(buffer, format="JPEG", quality=92)
        return buffer.getvalue()


# -- state ----------------------------------------------------------------------


class _State:
    """Who the owner is, which Chat thread each Telegram chat maps to, and the
    two small preferences. JSON, because it is a handful of fields."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        try:
            self.data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("threads", {})
        self.data.setdefault("when_away", True)

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            temporary.replace(self.path)


# -- the bridge -------------------------------------------------------------------


class TelegramBridge:
    """The Telegram surface. Async inside the Gateway's loop; thread-safe outside it."""

    def __init__(
        self,
        chat: Any,
        *,
        journal: Any = None,
        settle: Callable[[str, bool], dict[str, Any]] | None = None,
        transcribe: Callable[[bytes], str] | None = None,
        workspace: Any = None,
        yolo: Callable[[], bool] = lambda: False,
        state_path: Path | None = None,
        base_url: str = "",
    ) -> None:
        self.chat = chat
        self.journal = journal
        #: `(token, approve) -> ToolInvocation dict`: the Gateway's own
        #: confirmation path, so a tap in Telegram is the same decision as a
        #: click on the Island.
        self.settle = settle
        #: `(pcm16) -> text`, the local dictation recogniser. None disables
        #: voice notes rather than sending audio anywhere else.
        self.transcribe = transcribe
        self.workspace = workspace
        self.yolo = yolo
        self.state = _State(state_path or paths.root() / "state" / "telegram.json")
        #: A test's fake Bot API. Empty means the real one.
        self.base_url = base_url
        self._app: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._phase, self._detail = "off", ""
        self._pairing: tuple[str, float] | None = None
        self._running: dict[int, threading.Event] = {}
        self._asks: dict[int, str] = {}
        self._choices: dict[str, list[str]] = {}
        self._warned: dict[int, float] = {}

    # -- settings -------------------------------------------------------------

    @staticmethod
    def token() -> str:
        return os.environ.get(TOKEN_SETTING, "").strip()

    @property
    def owner(self) -> dict[str, Any] | None:
        owner = self.state.data.get("owner")
        return owner if isinstance(owner, dict) and owner.get("id") else None

    def is_owner(self, user_id: int | None) -> bool:
        owner = self.owner
        return bool(owner and user_id is not None and int(owner["id"]) == int(user_id))

    def ready(self) -> bool:
        return self._phase == "ready" and self._app is not None

    def linked(self) -> bool:
        return self.ready() and self.owner is not None

    def set_when_away(self, enabled: bool) -> None:
        self.state.data["when_away"] = bool(enabled)
        self.state.save()

    def unlink(self) -> None:
        self.state.data.pop("owner", None)
        self.state.data["threads"] = {}
        self.state.save()
        log.info("telegram owner unlinked")

    def status(self) -> dict[str, Any]:
        bot = self._app.bot if self._app is not None else None
        owner = self.owner
        pairing = None
        if self._pairing and self._pairing[1] > time.time() and bot is not None:
            code, expires = self._pairing
            pairing = {
                "code": code,
                "link": f"https://t.me/{bot.username}?start={code}",
                "expires_at": datetime.fromtimestamp(expires, UTC).isoformat(),
            }
        return {
            "configured": bool(self.token()),
            "state": self._phase,
            "detail": self._detail,
            "bot": (
                {"username": bot.username, "name": bot.first_name, "link": f"https://t.me/{bot.username}"}
                if bot is not None and self.ready()
                else None
            ),
            "owner": (
                {"name": owner.get("name", ""), "username": owner.get("username", "")}
                if owner
                else None
            ),
            "pairing": pairing,
            "when_away": bool(self.state.data.get("when_away", True)),
            "thread_id": self._owner_thread() or "",
        }

    # -- lifecycle ------------------------------------------------------------

    async def check(self, token: str) -> str:
        """The bot's username if Telegram accepts `token`.

        ValueError for a token that is wrong, TelegramUnavailableError for a
        Telegram that could not be asked -- so the page can say which.
        """
        from telegram import Bot
        from telegram.error import InvalidToken

        if not re.fullmatch(r"\d{6,}:[A-Za-z0-9_\-]{30,}", token):
            raise ValueError("That doesn't look like a bot token from @BotFather.")
        bot = Bot(token, base_url=f"{self.base_url}/bot" if self.base_url else "https://api.telegram.org/bot")
        try:
            async with bot:
                return str(bot.username)
        except InvalidToken as exc:
            raise ValueError("Telegram refused that token.") from exc
        except Exception as exc:
            raise TelegramUnavailableError(f"could not reach Telegram: {str(exc)[:160]}") from exc

    async def start(self) -> None:
        """Connect in the background. Never raises and never delays startup."""
        await self.stop()
        token = self.token()
        if not token:
            self._phase, self._detail = "off", "no bot token"
            return
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._connect(token))

    async def _connect(self, token: str) -> None:
        from telegram.error import InvalidToken

        delay = 5.0
        while True:
            self._phase, self._detail = "connecting", ""
            app = self._build(token)
            try:
                await app.initialize()
                await app.start()
                await app.updater.start_polling(allowed_updates=["message", "callback_query"])
            except InvalidToken:
                await self._shutdown(app)
                self._phase, self._detail = "error", "Telegram refused the bot token"
                log.warning("telegram refused the bot token")
                return
            except Exception as exc:
                await self._shutdown(app)
                self._phase, self._detail = "error", f"cannot reach Telegram: {str(exc)[:160]}"
                log.warning("telegram connect failed; retrying in %.0fs: %s", delay, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300.0)
                continue
            self._app = app
            self._phase, self._detail = "ready", ""
            log.info("telegram connected as @%s", app.bot.username)
            try:
                await self.sync_identity()
            except Exception as exc:  # a profile is cosmetic; the bot still works
                log.warning("telegram profile sync failed: %s", exc)
            return

    def _build(self, token: str) -> Any:
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
            MessageHandler,
            filters,
        )

        builder = (
            Application.builder()
            .token(token)
            # Button taps must be handled while a turn is still running --
            # an Approve that queues behind the turn waiting for it never lands.
            .concurrent_updates(True)
            .job_queue(None)
        )
        if self.base_url:
            builder = builder.base_url(f"{self.base_url}/bot").base_file_url(
                f"{self.base_url}/file/bot"
            )
        app = builder.build()
        private = filters.ChatType.PRIVATE
        app.add_handler(CommandHandler("start", self._on_start, filters=private))
        app.add_handler(CommandHandler("new", self._on_new, filters=private))
        app.add_handler(CommandHandler("stop", self._on_stop, filters=private))
        app.add_handler(CommandHandler("help", self._on_help, filters=private))
        app.add_handler(MessageHandler(private & ~filters.COMMAND, self._on_message))
        app.add_handler(CallbackQueryHandler(self._on_button))
        app.add_error_handler(self._on_error)
        return app

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        for event in self._running.values():
            event.set()
        app, self._app = self._app, None
        if app is not None:
            await self._shutdown(app)
        self._phase, self._detail = "off", ""

    @staticmethod
    async def _shutdown(app: Any) -> None:
        with contextlib.suppress(Exception):
            if app.updater is not None and app.updater.running:
                await app.updater.stop()
        with contextlib.suppress(Exception):
            if app.running:
                await app.stop()
        with contextlib.suppress(Exception):
            await app.shutdown()

    # -- identity -------------------------------------------------------------

    async def sync_identity(self, force: bool = False) -> bool:
        """Name, descriptions, commands and avatar, from Marvi rather than BotFather.

        Only when something changed: Telegram rate-limits `setMyName` to a few
        calls a day, and a Gateway restarts far more often than that.
        """
        from telegram import BotCommand, InputProfilePhotoStatic

        if self._app is None:
            return False
        bot = self._app.bot
        icon = ICON.read_bytes() if ICON.is_file() else b""
        fingerprint = hashlib.sha256(
            (json.dumps(PROFILE, sort_keys=True) + json.dumps(COMMANDS)).encode() + icon
        ).hexdigest()
        if not force and self.state.data.get("profile") == fingerprint:
            return False
        if bot.first_name != PROFILE["name"]:
            await bot.set_my_name(PROFILE["name"])
        await bot.set_my_short_description(PROFILE["short"])
        await bot.set_my_description(PROFILE["description"])
        await bot.set_my_commands([BotCommand(name, said) for name, said in COMMANDS])
        if icon:
            try:
                photo = await asyncio.to_thread(_profile_photo)
                await bot.set_my_profile_photo(InputProfilePhotoStatic(photo=photo))
            except Exception as exc:  # the avatar is the one part BotFather can still do
                log.warning("telegram profile photo not set: %s", exc)
        self.state.data["profile"] = fingerprint
        self.state.save()
        log.info("telegram bot profile synced")
        return True

    # -- pairing --------------------------------------------------------------

    def pair(self) -> dict[str, Any]:
        """A fresh one-time link code. Replaces any code already out there."""
        if not self.ready():
            raise TelegramUnavailableError("connect the bot before linking an account")
        code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
        self._pairing = (code, time.time() + PAIRING_SECONDS)
        return self.status()["pairing"]

    def claim(self, code: str, user: Any) -> bool:
        """Link `user` as the owner if `code` is the live one. Burns it either way."""
        live = self._pairing
        if live is None or not code or live[1] < time.time():
            return False
        if not secrets.compare_digest(code.strip().upper(), live[0]):
            return False
        self._pairing = None
        self.state.data["owner"] = {
            "id": int(user.id),
            "name": " ".join(filter(None, [user.first_name, user.last_name])) or "",
            "username": user.username or "",
            "linked_at": datetime.now(UTC).isoformat(),
        }
        self.state.data["threads"] = {}
        self.state.save()
        if self.journal is not None:
            self.journal.append(
                "telegram", "linked", "Telegram is linked to your account",
                {"id": f"linked-{user.id}"}, trusted=True, dedupe=False,
            )
        log.info("telegram owner linked")
        return True

    # -- threads --------------------------------------------------------------

    def _thread_for(self, chat_id: int, name: str = "") -> str:
        threads = self.state.data["threads"]
        known = threads.get(str(chat_id))
        if known:
            try:
                self.chat.store.get_thread(known)
                return str(known)
            except KeyError:
                pass  # deleted from the Chat sidebar; start a new one
        made = self.chat.store.create_thread(f"Telegram · {name or 'you'}")
        threads[str(chat_id)] = made["id"]
        self.state.save()
        return str(made["id"])

    def _owner_thread(self) -> str | None:
        owner = self.owner
        return self.state.data["threads"].get(str(owner["id"])) if owner else None

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        thread = self._owner_thread()
        if not thread:
            return []
        try:
            rows = self.chat.store.history(limit=200, thread_id=thread)
        except KeyError:
            return []
        said = [r for r in rows if r["role"] in ("user", "assistant") and r["content"]]
        return [
            {"at": r["at"], "from": "you" if r["role"] == "user" else "marvi", "text": r["content"][:2000]}
            for r in said[-max(1, min(limit, 50)) :]
        ]

    # -- outbound, from any thread --------------------------------------------

    def send(self, text: str, file: Path | None = None, origin: str = "") -> dict[str, Any]:
        """Send the owner a message. Blocking; for tools, cron and the Mind.

        The message is also written into the owner's thread, so a reply to a
        reminder arrives in a conversation that knows what the reminder said.
        """
        if not self.ready():
            raise TelegramUnavailableError("Telegram is not connected")
        owner = self.owner
        if owner is None:
            raise TelegramUnavailableError("no Telegram account is linked yet")
        if self._loop is None or _on_loop(self._loop):
            raise TelegramUnavailableError("send() must not be called from the event loop")
        future = asyncio.run_coroutine_threadsafe(
            self._deliver(int(owner["id"]), text, file), self._loop
        )
        message_id = future.result(timeout=60)
        thread = self._thread_for(int(owner["id"]), owner.get("name", ""))
        self.chat.store.append(
            "assistant", text or (file.name if file else ""), thread_id=thread,
            surface="telegram", origin=origin or "sent",
        )
        return {"sent": True, "message_id": message_id}

    async def _deliver(self, chat_id: int, text: str, file: Path | None) -> int:
        if file is not None:
            caption = text[:1000] or None
            with file.open("rb") as handle:
                sent = await self._app.bot.send_document(
                    chat_id, document=handle, filename=file.name, caption=caption
                )
            rest = text[1000:]
            if rest:
                await self._reply(chat_id, rest)
            return int(sent.message_id)
        return await self._reply(chat_id, text)

    def text_when_away(self, sentence: str, event: dict[str, Any]) -> bool:
        """The Mind's hook: say it here instead of into an empty room.

        False whenever it could not, so the Mind falls back to holding the item
        for later exactly as it did before Telegram existed.
        """
        if not sentence.strip() or not self.state.data.get("when_away", True):
            return False
        if not self.linked():
            return False
        try:
            self.send(sentence, origin=f"mind:{event.get('source')}:{event.get('kind')}")
        except Exception as exc:
            log.warning("could not text a Mind decision: %s", exc)
            return False
        return True

    # -- sending helpers ------------------------------------------------------

    async def _reply(self, chat_id: int, markdown: str, reply_markup: Any = None) -> int:
        """Send a whole answer, split, formatted, with a plain-text fallback."""
        from telegram.constants import ParseMode
        from telegram.error import BadRequest

        bot = self._app.bot
        pieces = chunks(markdown) or [markdown or "…"]
        last = 0
        for index, piece in enumerate(pieces):
            markup = reply_markup if index == len(pieces) - 1 else None
            try:
                sent = await bot.send_message(
                    chat_id, telegram_html(piece), parse_mode=ParseMode.HTML, reply_markup=markup
                )
            except BadRequest:
                # A formatting guess Telegram would not parse. The words matter
                # more than the bold.
                sent = await bot.send_message(chat_id, piece, reply_markup=markup)
            last = int(sent.message_id)
        return last

    async def _typing(self, chat_id: int) -> None:
        from telegram.constants import ChatAction

        while True:
            with contextlib.suppress(Exception):
                await self._app.bot.send_chat_action(chat_id, ChatAction.TYPING)
            await asyncio.sleep(4.5)

    # -- inbound --------------------------------------------------------------

    async def _stranger(self, update: Any) -> None:
        user = update.effective_user
        if user is None:
            return
        now = time.time()
        if now - self._warned.get(user.id, 0.0) < STRANGER_REPLY_SECONDS:
            return
        self._warned[user.id] = now
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(
                "I'm a personal assistant and I only talk to the person I belong to."
            )
        if self.journal is not None:
            # Untrusted: the name is whatever the stranger typed into their
            # profile, and it is shown, never obeyed.
            self.journal.append(
                "telegram", "stranger",
                "Someone who isn't linked tried to message Marvi on Telegram",
                {
                    "id": f"stranger-{user.id}",
                    "name": " ".join(filter(None, [user.first_name, user.last_name])),
                    "username": user.username or "",
                },
                trusted=False,
            )
        log.info("telegram message from an unlinked account refused")

    async def _on_start(self, update: Any, context: Any) -> None:
        user, message = update.effective_user, update.effective_message
        if user is None or message is None:
            return
        code = context.args[0] if context.args else ""
        if self.is_owner(user.id):
            await message.reply_text("I'm here. " + HELP)
            return
        if self.owner is None and self.claim(code, user):
            await message.reply_text(
                f"Linked. Hi{(' ' + user.first_name) if user.first_name else ''} — it's Marvi, "
                "running on your computer. " + HELP
            )
            return
        if self.owner is None:
            await message.reply_text(
                "This Marvi isn't linked yet. Open Marvi on your computer, go to "
                "Channels → Telegram, and press Link my account."
            )
            return
        await self._stranger(update)

    async def _on_help(self, update: Any, _context: Any) -> None:
        if self.is_owner(update.effective_user.id if update.effective_user else None):
            await update.effective_message.reply_text(HELP)
        else:
            await self._stranger(update)

    async def _on_new(self, update: Any, _context: Any) -> None:
        user = update.effective_user
        if not self.is_owner(user.id if user else None):
            await self._stranger(update)
            return
        chat_id = update.effective_message.chat_id
        self.state.data["threads"].pop(str(chat_id), None)
        self._thread_for(chat_id, user.first_name or "")
        await update.effective_message.reply_text("Fresh start. What's up?")

    async def _on_stop(self, update: Any, _context: Any) -> None:
        user = update.effective_user
        if not self.is_owner(user.id if user else None):
            await self._stranger(update)
            return
        running = self._running.get(update.effective_message.chat_id)
        if running is None:
            await update.effective_message.reply_text("I'm not doing anything right now.")
            return
        running.set()
        await update.effective_message.reply_text("Stopping.")

    async def _on_error(self, _update: object, context: Any) -> None:
        log.warning("telegram handler error: %s", context.error)

    async def _on_message(self, update: Any, context: Any) -> None:
        message, user = update.effective_message, update.effective_user
        if message is None or user is None:
            return
        if not self.is_owner(user.id):
            await self._stranger(update)
            return
        chat_id = message.chat_id
        # An answer to a question she asked, typed rather than tapped.
        ask = self._asks.get(chat_id)
        if ask and message.text and inline_ask.ASKS.settle(ask, " ".join(message.text.split())):
            self._asks.pop(chat_id, None)
            self._choices.pop(ask, None)
            return
        if chat_id in self._running:
            await message.reply_text("Still on your last message. Send /stop to cancel it.")
            return
        stop = threading.Event()
        self._running[chat_id] = stop  # claimed before any await, so two messages cannot race
        try:
            thread = self._thread_for(chat_id, user.first_name or "")
            try:
                text, attachments = await self._read(message, context, thread)
            except _RefusedError as exc:
                await message.reply_text(str(exc))
                return
            if text:
                await self._turn(chat_id, thread, text, attachments, stop)
        finally:
            self._running.pop(chat_id, None)

    async def _download(self, context: Any, file_id: str, size: int | None) -> bytes:
        if size and size > MAX_DOWNLOAD_BYTES:
            raise _RefusedError("That's over 10 MB — too big for me to take from Telegram.")
        handle = await context.bot.get_file(file_id)
        return bytes(await handle.download_as_bytearray())

    async def _read(self, message: Any, context: Any, thread: str) -> tuple[str, list[str]]:
        """Turn one Telegram message into a user turn and attachments.

        Only what the owner typed or said is theirs. Anything another person
        wrote -- a forward, a contact card, a place name -- is enveloped.
        """
        forwarded = message.forward_origin is not None
        origin = _origin_name(message.forward_origin) if forwarded else ""
        own: list[str] = []
        foreign: list[tuple[str, Any]] = []
        body = message.text or message.caption or ""
        if body and forwarded:
            foreign.append((f"telegram forward from {origin}", body))
        elif body:
            own.append(body)

        attachments: list[str] = []
        store = self.chat.store
        if message.photo:
            photo = message.photo[-1]
            data = await self._download(context, photo.file_id, photo.file_size)
            row = await asyncio.to_thread(store.add_attachment, thread, "photo.jpg", "image/jpeg", data)
            attachments.append(row["id"])
        elif message.document is not None:
            document = message.document
            data = await self._download(context, document.file_id, document.file_size)
            try:
                row = await asyncio.to_thread(
                    store.add_attachment, thread, document.file_name or "file",
                    document.mime_type or "", data,
                )
            except ValueError as exc:
                raise _RefusedError(f"I can't open that file: {exc}.") from exc
            attachments.append(row["id"])

        audio = message.voice or message.audio
        if audio is not None:
            if self.transcribe is None:
                raise _RefusedError("I can't listen to voice notes on this computer yet — type it instead.")
            data = await self._download(context, audio.file_id, audio.file_size)
            try:
                heard = await asyncio.to_thread(lambda: self.transcribe(pcm16_from_audio(data)))
            except _RefusedError:
                raise
            except Exception as exc:
                log.warning("telegram voice note transcription failed: %s", exc)
                raise _RefusedError("I couldn't listen to that voice note just now — try typing it.") from exc
            heard = " ".join((heard or "").split())
            if not heard:
                raise _RefusedError("I couldn't make out any words in that voice note.")
            if forwarded:
                foreign.append((f"telegram voice note forwarded from {origin}", heard))
            else:
                own.insert(0, heard)
                with contextlib.suppress(Exception):
                    await message.reply_text(f"🎙 “{heard}”")

        if message.contact is not None:
            contact = message.contact
            foreign.append(("telegram contact card", {
                "name": " ".join(filter(None, [contact.first_name, contact.last_name])),
                "phone": contact.phone_number,
            }))
        if message.venue is not None:
            venue = message.venue
            foreign.append(("telegram venue", {
                "title": venue.title, "address": venue.address,
                "latitude": venue.location.latitude, "longitude": venue.location.longitude,
            }))
        elif message.location is not None:
            own.append(
                f"[my location: {message.location.latitude:.5f}, {message.location.longitude:.5f}]"
            )
        if message.sticker is not None and not own:
            own.append(f"[sticker {message.sticker.emoji or ''}]".replace(" ]", "]"))

        parts = list(own)
        if forwarded and not own:
            parts.append("I'm forwarding you this.")
        parts += [wrap_external(source, content).text for source, content in foreign]
        if not parts and attachments:
            parts.append("[photo]" if message.photo else "[file]")
        return "\n\n".join(parts).strip(), attachments

    # -- the turn -------------------------------------------------------------

    async def _turn(
        self, chat_id: int, thread: str, text: str, attachments: list[str], stop: threading.Event
    ) -> None:
        """One Chat turn, streamed into Telegram as a native draft."""
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce() -> None:
            try:
                for event in self.chat.send_stream(
                    text, cancelled=stop.is_set, thread_id=thread,
                    attachment_ids=attachments, surface="telegram",
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:  # pragma: no cover - defensive, as in /chat/stream
                loop.call_soon_threadsafe(queue.put_nowait, {"done": True, "error": str(exc)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=produce, name="marvi-telegram-turn", daemon=True).start()
        typing = asyncio.create_task(self._typing(chat_id))
        draft = _Draft(self._app.bot, chat_id)
        answer, done, used = "", {}, []
        try:
            while (event := await queue.get()) is not None:
                if "delta" in event:
                    answer += str(event["delta"])
                    await draft.push(answer)
                elif "tool" in event:
                    used.append(str(event["tool"]))
                elif "ask" in event:
                    await self._show_ask(chat_id, event["ask"])
                elif event.get("done"):
                    done = event
        finally:
            typing.cancel()
            self._asks.pop(chat_id, None)

        reply = str(done.get("reply") or answer).strip()
        if done.get("cancelled"):
            reply = (reply + "\n\n_(stopped)_").strip()
        if reply and used and self.yolo():
            reply += "\n\n⚡ YOLO mode is on — actions ran without asking."
        if reply:
            await self._reply(chat_id, reply)
        if done.get("error") and not done.get("cancelled") and not reply:
            await self._app.bot.send_message(chat_id, f"⚠️ {str(done['error'])[:500]}")
        if pending := done.get("pending_confirmation"):
            await self._show_confirmation(chat_id, pending)

    async def _show_ask(self, chat_id: int, ask: dict[str, Any]) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        ask_id = str(ask.get("id") or "")
        if ask.get("kind") == "secret":
            # A credential typed into Telegram would sit in Telegram's history
            # forever. It is entered on the computer, or not at all.
            await self._app.bot.send_message(
                chat_id,
                f"I need a setting called {ask.get('name')} to do that. For safety I only take "
                "secrets on your computer — open Marvi there to enter it. I'll wait a few minutes.",
            )
            return
        self._asks[chat_id] = ask_id
        choices = [str(choice) for choice in ask.get("choices") or []][:10]
        self._choices[ask_id] = choices
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(choice[:60], callback_data=f"ak:{ask_id}:{i}")] for i, choice in enumerate(choices)]
        ) if choices else None
        await self._reply(
            chat_id,
            str(ask.get("question") or "") + ("\n\nTap one, or just type your answer." if choices else ""),
            reply_markup=keyboard,
        )

    async def _show_confirmation(self, chat_id: int, pending: dict[str, Any]) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        tool, token = str(pending.get("tool") or ""), str(pending.get("token") or "")
        if not token:
            return
        shown = json.dumps(pending.get("arguments") or {}, ensure_ascii=False, indent=1)[:800]
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Approve", callback_data=f"cf:a:{token}"),
            InlineKeyboardButton("Deny", callback_data=f"cf:d:{token}"),
        ]])
        await self._app.bot.send_message(
            chat_id,
            f"<b>Marvi wants to run</b> <code>{html.escape(tool)}</code>\n"
            f"<pre>{html.escape(shown)}</pre>\nApprove within two minutes.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    async def _on_button(self, update: Any, _context: Any) -> None:
        query = update.callback_query
        if query is None:
            return
        if not self.is_owner(query.from_user.id if query.from_user else None):
            await query.answer("Not yours to press.")
            return
        data = str(query.data or "")
        chat_id = query.message.chat_id if query.message else None
        if data.startswith("ak:"):
            _, ask_id, index = data.split(":", 2)
            choices = self._choices.get(ask_id) or []
            answer = choices[int(index)] if index.isdigit() and int(index) < len(choices) else ""
            settled = bool(answer) and inline_ask.ASKS.settle(ask_id, answer)
            await query.answer("Got it." if settled else "That question has moved on.")
            if settled:
                self._choices.pop(ask_id, None)
                if chat_id is not None:
                    self._asks.pop(chat_id, None)
                with contextlib.suppress(Exception):
                    await query.edit_message_reply_markup(None)
            return
        if not data.startswith("cf:") or self.settle is None or chat_id is None:
            await query.answer()
            return
        _, verdict, token = data.split(":", 2)
        approve = verdict == "a"
        outcome = await asyncio.to_thread(self.settle, token, approve)
        status = str(outcome.get("status") or "")
        tool = str(outcome.get("tool") or "the action")
        said = {
            "executed": f"✅ Approved — {tool} ran.",
            "failed": f"⚠️ Approved, but {tool} failed.",
            "denied": f"✖ Denied — {tool} did not run.",
        }.get(status, "⌛ That request expired or was already answered.")
        await query.answer()
        with contextlib.suppress(Exception):
            await query.edit_message_text(said)
        if status not in ("executed", "failed", "denied"):
            return
        thread = self._thread_for(chat_id, query.from_user.first_name or "")
        self.chat.store.append(
            "tool",
            _outcome_text(tool, status, outcome),
            thread_id=thread, tool=tool, arguments=outcome.get("arguments") or {},
            call_id=f"confirmed-{token[:8]}", failed=status != "executed",
        )
        # Approved: let her finish the thought with the result in hand.
        if approve and chat_id not in self._running:
            stop = threading.Event()
            self._running[chat_id] = stop
            try:
                await self._turn(chat_id, thread, "Approved.", [], stop)
            finally:
                self._running.pop(chat_id, None)


class _Draft:
    """Bot API 9.5 `sendMessageDraft`: the reply animates as it is written.

    Throttled, and abandoned for the turn on the first refusal -- the final
    message is always sent normally, so a draft that never shows costs nothing.
    """

    def __init__(self, bot: Any, chat_id: int) -> None:
        self.bot, self.chat_id = bot, chat_id
        self.id = secrets.randbelow(2**31 - 2) + 1
        self.at = 0.0
        self.on = True

    async def push(self, text: str) -> None:
        now = time.monotonic()
        if not self.on or not text.strip() or now - self.at < DRAFT_SECONDS:
            return
        self.at = now
        try:
            await self.bot.send_message_draft(self.chat_id, self.id, text[-4000:])
        except Exception as exc:
            self.on = False
            log.info("telegram drafts unavailable for this turn: %s", exc)


def _origin_name(origin: Any) -> str:
    for attribute in ("sender_user", "sender_chat", "chat"):
        who = getattr(origin, attribute, None)
        if who is not None:
            return str(getattr(who, "full_name", None) or getattr(who, "title", None) or "someone")
    return str(getattr(origin, "sender_user_name", "") or "someone")


def _outcome_text(tool: str, status: str, outcome: dict[str, Any]) -> str:
    if status == "denied":
        return f"The user denied {tool} in Telegram. It did not run; do not retry it unasked."
    if status == "failed":
        error = wrap_external(f"tool:{tool}", outcome.get("error") or "no reason given").text
        return f"The user approved {tool}, but it failed and did nothing.\n{error}"
    from .chat_widgets import external_text

    result = outcome.get("result")
    return external_text(result) or wrap_external(f"tool:{tool}", result).text


def _on_loop(loop: asyncio.AbstractEventLoop) -> bool:
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False


# -- cron delivery ------------------------------------------------------------------


class TelegramDelivery:
    """The scheduler's messaging seam, with Telegram behind it.

    `local` behaves exactly as before; `telegram` sends the job's output to the
    owner's chat.
    """

    def __init__(self, bridge: TelegramBridge, local: Any = None) -> None:
        from .schedule import LocalDelivery

        self.bridge = bridge
        self.local = local or LocalDelivery()

    def targets(self) -> list[dict[str, Any]]:
        return [
            *self.local.targets(),
            {"id": "telegram", "name": "Telegram (your phone)", "available": self.bridge.linked()},
        ]

    def deliver(self, target: str, text: str, context: dict[str, Any]) -> str:
        if target != "telegram":
            return self.local.deliver(target, text, context)
        from .schedule import ScheduleError

        name = str(context.get("name") or "").strip()
        body = f"**{name}**\n\n{text}".strip() if name and text else (text or name)
        try:
            self.bridge.send(body or "(no output)", origin=f"cron:{context.get('schedule_id')}")
        except TelegramUnavailableError as exc:
            raise ScheduleError(f"Telegram delivery failed: {exc}") from exc
        return "sent_telegram"


# -- tools ------------------------------------------------------------------------------


def register_telegram_tools(registry: Any, bridge: TelegramBridge) -> None:
    from .tools import ToolSpec

    def telegram_send(text: str = "", file: str = "") -> dict[str, Any]:
        if not text.strip() and not file.strip():
            raise ValueError("give text, a file, or both")
        path = None
        if file.strip():
            if bridge.workspace is None:
                raise ValueError("no workspace is configured to send files from")
            path = bridge.workspace.resolve(file.strip())
            if not path.is_file():
                raise ValueError(f"{file} is not a file")
            if path.stat().st_size > 50 * 1024 * 1024:
                raise ValueError("Telegram bots can only send files up to 50 MB")
        return bridge.send(text.strip(), file=path, origin="tool")

    def telegram_status() -> dict[str, Any]:
        status = bridge.status()
        status.pop("pairing", None)  # the code is for the person at the desk, not the model
        return status

    registry.register(ToolSpec(
        name="telegram_send",
        description="Send the user a Telegram message, optionally with a workspace file.",
        arguments={},
        optional={"text": str, "file": str},
        describes={
            "text": "The message, in Markdown. Short: it lands on a phone.",
            "file": "Optional workspace path of a file to attach.",
        },
        # To the owner's own chat and nobody else's, so not a confirmation;
        # still an external write, so a retried call is not a second message.
        sensitive=False,
        external=True,
        handler=telegram_send,
    ))
    registry.register(ToolSpec(
        name="telegram_status",
        description="Whether Telegram is connected and linked.",
        arguments={},
        sensitive=False,
        handler=telegram_status,
    ))
    registry.register(ToolSpec(
        name="telegram_recent",
        description="The latest messages in the user's Telegram conversation with Marvi.",
        arguments={},
        optional={"limit": int},
        describes={"limit": "How many messages, newest last. Default 10, at most 50."},
        sensitive=False,
        handler=lambda limit=10: {"messages": bridge.recent(limit)},
    ))
