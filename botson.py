import asyncio
from os import getenv
from typing import Awaitable, Callable, Iterable, Optional, Union

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

    def send_message(
        self,
        text: str,
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> "BotApp":
        action = self._app.action_send_message(text, recipients=recipients, silent=silent, protect=protect)
        return self.handle(action)

    def send_photo(
        self,
        photo: str,
        caption: str = "",
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
        **extra,
    ) -> "BotApp":
        action = self._app.action_send_media(
            "photo",
            photo,
            caption,
            recipients=recipients,
            silent=silent,
            protect=protect,
            from_path=from_path,
            **extra,
        )
        return self.handle(action)

    def send_video(
        self,
        video: str,
        caption: str = "",
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
        **extra,
    ) -> "BotApp":
        action = self._app.action_send_media(
            "video",
            video,
            caption,
            recipients=recipients,
            silent=silent,
            protect=protect,
            from_path=from_path,
            **extra,
        )
        return self.handle(action)

    def send_audio(
        self,
        audio: str,
        caption: str = "",
        *,
        performer: str = "",
        title: str = "",
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
        **extra,
    ) -> "BotApp":
        if performer:
            extra["performer"] = performer
        if title:
            extra["title"] = title
        action = self._app.action_send_media(
            "audio",
            audio,
            caption,
            recipients=recipients,
            silent=silent,
            protect=protect,
            from_path=from_path,
            **extra,
        )
        return self.handle(action)

    def send_file(
        self,
        file: str,
        caption: str = "",
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
        **extra,
    ) -> "BotApp":
        action = self._app.action_send_media(
            "document",
            file,
            caption,
            recipients=recipients,
            silent=silent,
            protect=protect,
            from_path=from_path,
            **extra,
        )
        return self.handle(action)

    def send_location(
        self,
        latitude: float,
        longitude: float,
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> "BotApp":
        action = self._app.action_send_location(
            latitude,
            longitude,
            recipients=recipients,
            silent=silent,
            protect=protect,
        )
        return self.handle(action)

    def send_contact(
        self,
        phone_number: str,
        first_name: str,
        last_name: str = "",
        vcard: str = "",
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> "BotApp":
        action = self._app.action_send_contact(
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            vcard=vcard,
            recipients=recipients,
            silent=silent,
            protect=protect,
        )
        return self.handle(action)


class BotApp:
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or getenv("BOT_TOKEN")
        if not self.token:
            raise RuntimeError("BOT_TOKEN is not set")
        self.dp = Dispatcher()

    def _targets(self, message: Message, recipients: Optional[Iterable[ChatId]]) -> list[ChatId]:
        return list(recipients) if recipients else [message.chat.id]

    def _maybe_file(self, src: str, from_path: bool):
        return FSInputFile(src) if from_path else src

    async def _send_to_many(self, message: Message, recipients: Optional[Iterable[ChatId]], send, **kwargs) -> None:
        for chat_id in self._targets(message, recipients):
            await send(chat_id=chat_id, **kwargs)

    def _register_trigger(self, trigger: str, handler: Handler, **params) -> None:
        t = (trigger or "").strip().lower()

        if t == "command":
            self.dp.message.register(handler, Command(params["name"]))
            return

        if t == "any":
            self.dp.message.register(handler)
            return

        if t == "kind":
            kind = (params.get("kind") or "").strip().lower()
            mapping = {
                "text": F.text,
                "location": F.location,
                "contact": F.contact,
                "document": F.document,
                "photo": F.photo,
                "video": F.video,
                "audio": F.audio,
                "sticker": F.sticker,
            }
            flt = mapping.get(kind)
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
        async def _action(message: Message) -> None:
            await self._send_to_many(
                message,
                recipients,
                message.bot.send_message,
                text=text,
                disable_notification=silent,
                protect_content=protect,
            )

        return _action

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
        methods = {
            "photo": ("send_photo", "photo"),
            "video": ("send_video", "video"),
            "audio": ("send_audio", "audio"),
            "document": ("send_document", "document"),
            "animation": ("send_animation", "animation"),
        }
        if k not in methods:
            raise ValueError(f"Unknown media kind: {kind}")
        method_name, arg_name = methods[k]

        async def _action(message: Message) -> None:
            send = getattr(message.bot, method_name)
            payload = {
                arg_name: self._maybe_file(media, from_path),
                "disable_notification": silent,
                "protect_content": protect,
                **extra,
            }
            if caption:
                payload["caption"] = caption
            await self._send_to_many(message, recipients, send, **payload)

        return _action

    def action_send_location(
        self,
        latitude: float,
        longitude: float,
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> Handler:
        async def _action(message: Message) -> None:
            await self._send_to_many(
                message,
                recipients,
                message.bot.send_location,
                latitude=latitude,
                longitude=longitude,
                disable_notification=silent,
                protect_content=protect,
            )

        return _action

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
        async def _action(message: Message) -> None:
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

        return _action

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

    def any(self, handler: Handler) -> None:
        self._register_trigger("any", handler)

    def on(self, kind: str, handler: Handler) -> None:
        self._register_trigger("kind", handler, kind=kind)

    def on_text(self, handler: Handler, filter: str = "any", value: Optional[str] = None) -> None:
        self._register_trigger("text", handler, filter=filter, value=value)

    def send_photo(self, name: str, photo: str, caption: str = "", **kwargs) -> None:
        self.node_command(name).send_photo(photo, caption, **kwargs)

    def send_video(self, name: str, video: str, caption: str = "", **kwargs) -> None:
        self.node_command(name).send_video(video, caption, **kwargs)

    def send_audio(self, name: str, audio: str, caption: str = "", **kwargs) -> None:
        self.node_command(name).send_audio(audio, caption, **kwargs)

    def send_file(self, name: str, file: str, caption: str = "", **kwargs) -> None:
        self.node_command(name).send_file(file, caption, **kwargs)

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
        self.node_command(name).send_contact(phone_number, first_name, last_name, vcard, **kwargs)

    async def _run(self) -> None:
        bot = Bot(token=self.token)
        await self.dp.start_polling(bot)

    def run(self) -> None:
        asyncio.run(self._run())
