import asyncio
from os import getenv
from typing import Awaitable, Callable, Iterable, Optional, Sequence, Union

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.types.input_file import FSInputFile

Handler = Callable[[Message], Awaitable[None]]
ChatId = Union[int, str]


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

    def action_send_message(
        self,
        text: str,
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> Handler:
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
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
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

    def action_send_location(
        self,
        *,
        latitude: float,
        longitude: float,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> Handler:
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
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
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
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
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

    def action_send_sticker(
        self,
        *,
        sticker: str,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> Handler:
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

    def action_send_dice(
        self,
        *,
        emoji: str = "🎲",
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> Handler:
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

    def action_send_game(
        self,
        *,
        game_type: str = "dice",
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> Handler:
        key = (game_type or "dice").strip().lower()
        emoji = self._GAME_EMOJI.get(key)
        if not emoji:
            raise ValueError(f"Unknown game_type: {game_type}")

        return self.action_send_dice(emoji=emoji, recipients=recipients, silent=silent, protect=protect)

    def node_command(self, name: str) -> Node:
        return Node(self, "command", name=name)

    def node_any(self) -> Node:
        return Node(self, "any")

    def node_kind(self, kind: str) -> Node:
        return Node(self, "kind", kind=kind)

    def node_text(self, *, filter: str = "any", value: Optional[str] = None) -> Node:
        return Node(self, "text", filter=filter, value=value)

    def command(
        self,
        name: str,
        reply_text: Optional[str] = None,
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ):
        if reply_text is None:
            return self.node_command(name)
        self.node_command(name).send_message(reply_text, recipients=recipients, silent=silent, protect=protect)
        return None

    def send_photo(self, name: str, photo: str, caption: str = "", **kwargs) -> None:
        self.node_command(name).send_photo(photo, caption, **kwargs)

    def send_video(self, name: str, video: str, caption: str = "", **kwargs) -> None:
        self.node_command(name).send_video(video, caption, **kwargs)

    def send_audio(self, name: str, audio: str, caption: str = "", **kwargs) -> None:
        self.node_command(name).send_audio(audio, caption, **kwargs)

    def send_file(self, name: str, file: str, caption: str = "", **kwargs) -> None:
        self.node_command(name).send_file(file, caption, **kwargs)

    def send_animation(self, name: str, animation: str, caption: str = "", **kwargs) -> None:
        self.node_command(name).send_animation(animation, caption, **kwargs)

    def send_location(self, name: str, latitude: float, longitude: float, **kwargs) -> None:
        self.node_command(name).send_location(latitude, longitude, **kwargs)

    def send_contact(
        self,
        name: str,
        phone_number: str,
        first_name: str,
        last_name: str = "",
        vcard: str = "",
        **kwargs,
    ) -> None:
        self.node_command(name).send_contact(phone_number, first_name, last_name=last_name, vcard=vcard, **kwargs)

    def send_poll(self, name: str, question: str, options: Sequence[str], **kwargs) -> None:
        self.node_command(name).send_poll(question, options, **kwargs)

    def send_sticker(self, name: str, sticker: str, **kwargs) -> None:
        self.node_command(name).send_sticker(sticker, **kwargs)

    def send_dice(self, name: str, *, emoji: str = "🎲", **kwargs) -> None:
        self.node_command(name).send_dice(emoji=emoji, **kwargs)

    def send_game(self, name: str, *, game_type: str = "dice", **kwargs) -> None:
        self.node_command(name).send_game(game_type=game_type, **kwargs)

    async def _run(self) -> None:
        bot = Bot(token=self.token)
        await self.dp.start_polling(bot)

    def run(self) -> None:
        asyncio.run(self._run())
