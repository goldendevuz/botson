import asyncio
from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional, Sequence, Union, Literal

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.types.input_file import FSInputFile

Handler = Callable[[Message], Awaitable[None]]
ChatId = Union[int, str]
EditTarget = Literal["previous", "message_id"]
DeleteTarget = Literal["context", "message_id"]
FileKind = Literal["photo", "video", "audio", "document", "voice", "animation", "sticker", "any"]


@dataclass(frozen=True)
class DownloadedFile:
    file_id: str
    file_unique_id: str
    file_path: str
    local_path: str
    kind: str


AfterDownload = Callable[[DownloadedFile], None]


class Node:
    def __init__(self, app: "BotApp", trigger: str, **params) -> None:
        self._app = app
        self._trigger = trigger
        self._params = params

    def handle(self, handler: Handler) -> "BotApp":
        self._app._register_trigger(self._trigger, handler, **self._params)
        return self._app

    def send_message(self, text: str, **opts) -> "BotApp":
        return self.handle(self._app.action_send_message(text, **opts))

    def send_media(self, kind: str, media: str, caption: str = "", **opts) -> "BotApp":
        return self.handle(self._app.action_send_media(kind, media, caption, **opts))

    def send_photo(self, photo: str, caption: str = "", **opts) -> "BotApp":
        return self.send_media("photo", photo, caption, **opts)

    def send_video(self, video: str, caption: str = "", **opts) -> "BotApp":
        return self.send_media("video", video, caption, **opts)

    def send_audio(self, audio: str, caption: str = "", *, performer: str = "", title: str = "", **opts) -> "BotApp":
        extra = dict(opts)
        if performer:
            extra["performer"] = performer
        if title:
            extra["title"] = title
        return self.send_media("audio", audio, caption, **extra)

    def send_file(self, file: str, caption: str = "", **opts) -> "BotApp":
        return self.send_media("document", file, caption, **opts)

    def send_animation(self, animation: str, caption: str = "", **opts) -> "BotApp":
        return self.send_media("animation", animation, caption, **opts)

    def send_location(self, latitude: float, longitude: float, **opts) -> "BotApp":
        return self.handle(self._app.action_send_location(latitude=latitude, longitude=longitude, **opts))

    def send_contact(
        self,
        phone_number: str,
        first_name: str,
        *,
        last_name: str = "",
        vcard: str = "",
        **opts,
    ) -> "BotApp":
        return self.handle(
            self._app.action_send_contact(
                phone_number=phone_number,
                first_name=first_name,
                last_name=last_name,
                vcard=vcard,
                **opts,
            )
        )

    def send_poll(self, question: str, options: Sequence[str], **opts) -> "BotApp":
        return self.handle(self._app.action_send_poll(question=question, options=options, **opts))

    def send_sticker(self, sticker: str, **opts) -> "BotApp":
        return self.handle(self._app.action_send_sticker(sticker=sticker, **opts))

    def send_dice(self, *, emoji: str = "🎲", **opts) -> "BotApp":
        return self.handle(self._app.action_send_dice(emoji=emoji, **opts))

    def send_game(self, *, game_type: str = "dice", **opts) -> "BotApp":
        return self.handle(self._app.action_send_game(game_type=game_type, **opts))

    def edit_caption(
        self,
        new_caption: str,
        *,
        target: EditTarget = "previous",
        message_id: Optional[int] = None,
        recipients: Optional[Iterable[ChatId]] = None,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> "BotApp":
        return self.handle(
            self._app.action_edit_caption(
                new_caption=new_caption,
                target=target,
                message_id=message_id,
                recipients=recipients,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        )

    def edit_text(
        self,
        new_text: str,
        *,
        target: EditTarget = "previous",
        message_id: Optional[int] = None,
        recipients: Optional[Iterable[ChatId]] = None,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> "BotApp":
        return self.handle(
            self._app.action_edit_text(
                new_text=new_text,
                target=target,
                message_id=message_id,
                recipients=recipients,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        )

    def forward_message(self, *, recipients: Iterable[ChatId], silent: bool = False, protect: bool = False) -> "BotApp":
        return self.handle(self._app.action_forward_message(recipients=recipients, silent=silent, protect=protect))

    def delete_message(
        self,
        *,
        target: DeleteTarget = "context",
        message_id: Optional[int] = None,
        recipients: Optional[Iterable[ChatId]] = None,
    ) -> "BotApp":
        return self.handle(self._app.action_delete_message(target=target, message_id=message_id, recipients=recipients))

    def show_activity(
        self,
        *,
        activity: str = "typing",
        seconds: int = 5,
        recipients: Optional[Iterable[ChatId]] = None,
    ) -> "BotApp":
        return self.handle(self._app.action_show_activity(activity=activity, seconds=seconds, recipients=recipients))

    def download_file(
        self,
        *,
        kind: FileKind = "any",
        to_dir: str = "downloads",
        filename: str = "",
        on_done: Optional[AfterDownload] = None,
    ) -> "BotApp":
        return self.handle(self._app.action_download_file(kind=kind, to_dir=to_dir, filename=filename, on_done=on_done))


class BotApp:
    _KIND_FILTERS = {
        "text": F.text,
        "location": F.location,
        "contact": F.contact,
        "document": F.document,
        "photo": F.photo,
        "video": F.video,
        "audio": F.audio,
        "sticker": F.sticker,
        "voice": F.voice,
        "animation": F.animation,
    }

    _MEDIA_METHODS = {
        "photo": ("send_photo", "photo"),
        "video": ("send_video", "video"),
        "audio": ("send_audio", "audio"),
        "document": ("send_document", "document"),
        "animation": ("send_animation", "animation"),
    }

    _GAME_EMOJI = {
        "dice": "🎲",
        "cube": "🎲",
        "darts": "🎯",
        "basketball": "🏀",
        "football": "⚽",
        "soccer": "⚽",
        "bowling": "🎳",
        "slot": "🎰",
        "slot_machine": "🎰",
    }

    _CHAT_ACTION = {
        "typing": "typing",
        "upload_photo": "upload_photo",
        "upload_video": "upload_video",
        "upload_audio": "upload_audio",
        "upload_document": "upload_document",
        "find_location": "find_location",
        "record_video": "record_video",
        "record_voice": "record_voice",
        "record_audio": "record_audio",
    }

    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or getenv("BOT_TOKEN")
        if not self.token:
            raise RuntimeError("BOT_TOKEN is not set")
        self.dp = Dispatcher()

    def _targets(self, message: Message, recipients: Optional[Iterable[ChatId]]) -> list[ChatId]:
        return list(recipients) if recipients else [message.chat.id]

    def _file(self, src: str, from_path: bool):
        return FSInputFile(src) if from_path else src

    async def _send_to_many(self, message: Message, recipients: Optional[Iterable[ChatId]], send, **kwargs) -> None:
        for chat_id in self._targets(message, recipients):
            await send(chat_id=chat_id, **kwargs)

    def _register_trigger(self, trigger: str, handler: Handler, **params) -> None:
        t = (trigger or "").strip().lower()

        if t == "command":
            name = params.get("name")
            if not name:
                raise ValueError("command trigger requires name")
            self.dp.message.register(handler, Command(str(name)))
            return

        if t == "any":
            self.dp.message.register(handler)
            return

        if t == "kind":
            kind = (params.get("kind") or "").strip().lower()
            flt = self._KIND_FILTERS.get(kind)
            if flt is None:
                raise ValueError(f"Unknown kind: {params.get('kind')}")
            self.dp.message.register(handler, flt)
            return

        if t == "text":
            flt = self._build_text_filter(params.get("filter", "any"), params.get("value"))
            if flt is None:
                self.dp.message.register(handler, F.text)
            else:
                self.dp.message.register(handler, F.text, flt)
            return

        raise ValueError(f"Unknown trigger: {trigger}")

    def _build_text_filter(self, filter: str, value: Optional[str]):
        op = (filter or "any").strip().lower()

        if op == "any":
            return None

        if op == "equal":
            if value is None:
                raise ValueError("value is required for filter='equal'")
            return F.text == value

        if op == "contains":
            if value is None:
                raise ValueError("value is required for filter='contains'")
            return F.text.contains(value)

        if op in ("not_contains", "not-contains"):
            if value is None:
                raise ValueError("value is required for filter='not_contains'")
            return ~F.text.contains(value)

        if op in ("starts", "starts_with", "starts-with"):
            if value is None:
                raise ValueError("value is required for filter='starts'")
            return F.text.startswith(value)

        if op == "regex":
            if value is None:
                raise ValueError("value is required for filter='regex'")
            return F.text.regexp(value)

        if op == "command":
            if value is None:
                raise ValueError("value is required for filter='command'")
            return Command(value.lstrip("/"))

        raise ValueError(f"Unknown text filter: {filter}")

    def action_send_message(self, text: str, *, recipients=None, silent=False, protect=False) -> Handler:
        async def _a(message: Message) -> None:
            await self._send_to_many(
                message,
                recipients,
                message.bot.send_message,
                text=text,
                disable_notification=silent,
                protect_content=protect,
            )

        return _a

    def action_send_media(
        self,
        kind: str,
        media: str,
        caption: str = "",
        *,
        recipients=None,
        silent=False,
        protect=False,
        from_path=False,
        **extra,
    ) -> Handler:
        k = (kind or "").strip().lower()
        spec = self._MEDIA_METHODS.get(k)
        if spec is None:
            raise ValueError(f"Unknown media kind: {kind}")
        method_name, arg_name = spec

        async def _a(message: Message) -> None:
            send = getattr(message.bot, method_name)
            payload = {
                arg_name: self._file(media, from_path),
                "disable_notification": silent,
                "protect_content": protect,
                **extra,
            }
            if caption:
                payload["caption"] = caption
            await self._send_to_many(message, recipients, send, **payload)

        return _a

    def action_send_location(self, *, latitude: float, longitude: float, recipients=None, silent=False, protect=False) -> Handler:
        async def _a(message: Message) -> None:
            await self._send_to_many(
                message,
                recipients,
                message.bot.send_location,
                latitude=latitude,
                longitude=longitude,
                disable_notification=silent,
                protect_content=protect,
            )

        return _a

    def action_send_contact(
        self,
        *,
        phone_number: str,
        first_name: str,
        last_name: str = "",
        vcard: str = "",
        recipients=None,
        silent=False,
        protect=False,
    ) -> Handler:
        async def _a(message: Message) -> None:
            payload = {
                "phone_number": phone_number,
                "first_name": first_name,
                "disable_notification": silent,
                "protect_content": protect,
            }
            if last_name:
                payload["last_name"] = last_name
            if vcard:
                payload["vcard"] = vcard
            await self._send_to_many(message, recipients, message.bot.send_contact, **payload)

        return _a

    def action_send_poll(
        self,
        *,
        question: str,
        options: Sequence[str],
        poll_type: str = "regular",
        anonymous: bool = True,
        multiple_answers: bool = False,
        open_period: Optional[int] = None,
        correct_option_id: Optional[int] = None,
        explanation: str = "",
        recipients=None,
        silent=False,
        protect=False,
    ) -> Handler:
        pt = (poll_type or "regular").strip().lower()
        pt = "quiz" if pt in ("quiz", "test") else "regular"

        async def _a(message: Message) -> None:
            payload = {
                "question": question,
                "options": list(options),
                "type": pt,
                "is_anonymous": anonymous,
                "allows_multiple_answers": multiple_answers,
                "disable_notification": silent,
                "protect_content": protect,
            }

            if open_period is not None:
                payload["open_period"] = int(open_period)

            if pt == "quiz":
                if correct_option_id is not None:
                    payload["correct_option_id"] = int(correct_option_id)
                if explanation:
                    payload["explanation"] = explanation

            await self._send_to_many(message, recipients, message.bot.send_poll, **payload)

        return _a

    def action_send_sticker(self, *, sticker: str, recipients=None, silent=False, protect=False) -> Handler:
        async def _a(message: Message) -> None:
            await self._send_to_many(
                message,
                recipients,
                message.bot.send_sticker,
                sticker=sticker,
                disable_notification=silent,
                protect_content=protect,
            )

        return _a

    def action_send_dice(self, *, emoji: str = "🎲", recipients=None, silent=False, protect=False) -> Handler:
        async def _a(message: Message) -> None:
            await self._send_to_many(
                message,
                recipients,
                message.bot.send_dice,
                emoji=emoji,
                disable_notification=silent,
                protect_content=protect,
            )

        return _a

    def action_send_game(self, *, game_type: str = "dice", recipients=None, silent=False, protect=False) -> Handler:
        key = (game_type or "dice").strip().lower()
        emoji = self._GAME_EMOJI.get(key)
        if not emoji:
            raise ValueError(f"Unknown game_type: {game_type}")
        return self.action_send_dice(emoji=emoji, recipients=recipients, silent=silent, protect=protect)

    def action_edit_caption(
        self,
        *,
        new_caption: str,
        target: EditTarget = "previous",
        message_id: Optional[int] = None,
        recipients: Optional[Iterable[ChatId]] = None,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> Handler:
        if target == "message_id" and message_id is None:
            raise ValueError("message_id is required when target='message_id'")

        async def _a(message: Message) -> None:
            chat_ids = list(recipients) if recipients else [message.chat.id]
            mid = message_id if target == "message_id" else message.message_id - 1
            for chat_id in chat_ids:
                await message.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=mid,
                    caption=new_caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )

        return _a

    def action_edit_text(
        self,
        *,
        new_text: str,
        target: EditTarget = "previous",
        message_id: Optional[int] = None,
        recipients: Optional[Iterable[ChatId]] = None,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> Handler:
        if target == "message_id" and message_id is None:
            raise ValueError("message_id is required when target='message_id'")

        async def _a(message: Message) -> None:
            chat_ids = list(recipients) if recipients else [message.chat.id]
            mid = message_id if target == "message_id" else message.message_id - 1
            for chat_id in chat_ids:
                await message.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=mid,
                    text=new_text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )

        return _a

    def action_forward_message(self, *, recipients: Iterable[ChatId], silent: bool = False, protect: bool = False) -> Handler:
        rec = list(recipients)
        if not rec:
            raise ValueError("recipients must not be empty")

        async def _a(message: Message) -> None:
            from_chat_id = message.chat.id
            message_id = message.message_id
            for to_chat_id in rec:
                await message.bot.forward_message(
                    chat_id=to_chat_id,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                    disable_notification=silent,
                    protect_content=protect,
                )

        return _a

    def action_delete_message(self, *, target: DeleteTarget = "context", message_id: Optional[int] = None, recipients=None) -> Handler:
        if target == "message_id" and message_id is None:
            raise ValueError("message_id is required when target='message_id'")

        async def _a(message: Message) -> None:
            chat_ids = list(recipients) if recipients else [message.chat.id]
            mid = message_id if target == "message_id" else message.message_id
            for chat_id in chat_ids:
                await message.bot.delete_message(chat_id=chat_id, message_id=mid)

        return _a

    def action_show_activity(self, *, activity: str = "typing", seconds: int = 5, recipients=None) -> Handler:
        key = (activity or "typing").strip().lower()
        action = self._CHAT_ACTION.get(key)
        if not action:
            raise ValueError(f"Unknown activity: {activity}")

        async def _a(message: Message) -> None:
            chat_ids = list(recipients) if recipients else [message.chat.id]
            total = max(1, int(seconds))
            interval = 4
            steps = max(1, (total + interval - 1) // interval)
            for _ in range(steps):
                for chat_id in chat_ids:
                    await message.bot.send_chat_action(chat_id=chat_id, action=action)
                await asyncio.sleep(interval)

        return _a

    def _extract_file(self, message: Message, kind: FileKind):
        if kind == "photo" or (kind == "any" and message.photo):
            p = message.photo[-1]
            return ("photo", p.file_id, p.file_unique_id)

        if kind == "video" or (kind == "any" and message.video):
            v = message.video
            return ("video", v.file_id, v.file_unique_id)

        if kind == "audio" or (kind == "any" and message.audio):
            a = message.audio
            return ("audio", a.file_id, a.file_unique_id)

        if kind == "document" or (kind == "any" and message.document):
            d = message.document
            return ("document", d.file_id, d.file_unique_id)

        if kind == "voice" or (kind == "any" and message.voice):
            v = message.voice
            return ("voice", v.file_id, v.file_unique_id)

        if kind == "animation" or (kind == "any" and message.animation):
            a = message.animation
            return ("animation", a.file_id, a.file_unique_id)

        if kind == "sticker" or (kind == "any" and message.sticker):
            s = message.sticker
            return ("sticker", s.file_id, s.file_unique_id)

        return None

    def action_download_file(
        self,
        *,
        kind: FileKind = "any",
        to_dir: str = "downloads",
        filename: str = "",
        on_done: Optional[AfterDownload] = None,
    ) -> Handler:
        k = (kind or "any").strip().lower()
        if k not in ("photo", "video", "audio", "document", "voice", "animation", "sticker", "any"):
            raise ValueError(f"Unknown kind: {kind}")

        async def _a(message: Message) -> None:
            info = self._extract_file(message, k)  # (kind, file_id, file_unique_id)
            if info is None:
                return

            file_kind, file_id, file_unique_id = info
            tg_file = await message.bot.get_file(file_id)

            out_dir = Path(to_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            if filename:
                out_path = out_dir / filename
            else:
                suffix = Path(tg_file.file_path).suffix
                out_path = out_dir / f"{file_kind}_{file_unique_id}{suffix}"

            await message.bot.download_file(tg_file.file_path, destination=str(out_path))

            if on_done:
                on_done(
                    DownloadedFile(
                        file_id=file_id,
                        file_unique_id=file_unique_id,
                        file_path=tg_file.file_path,
                        local_path=str(out_path),
                        kind=file_kind,
                    )
                )

        return _a

    def node_command(self, name: str) -> Node:
        return Node(self, "command", name=name)

    def node_any(self) -> Node:
        return Node(self, "any")

    def node_kind(self, kind: str) -> Node:
        return Node(self, "kind", kind=kind)

    def node_text(self, *, filter: str = "any", value: Optional[str] = None) -> Node:
        return Node(self, "text", filter=filter, value=value)

    def command(self, name: str, reply_text: Optional[str] = None, *, recipients=None, silent=False, protect=False):
        if reply_text is None:
            return self.node_command(name)
        self.node_command(name).send_message(reply_text, recipients=recipients, silent=silent, protect=protect)
        return None

    def download_file(self, name: str, *, kind: FileKind = "any", to_dir: str = "downloads", filename: str = "", on_done: Optional[AfterDownload] = None) -> None:
        self.node_command(name).download_file(kind=kind, to_dir=to_dir, filename=filename, on_done=on_done)

    async def _run(self) -> None:
        bot = Bot(token=self.token)
        await self.dp.start_polling(bot)

    def run(self) -> None:
        asyncio.run(self._run())
