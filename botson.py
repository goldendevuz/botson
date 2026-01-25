import asyncio
from os import getenv
from typing import Awaitable, Callable, Iterable, Optional, Union

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.types.input_file import FSInputFile

Handler = Callable[[Message], Awaitable[None]]
ChatId = Union[int, str]


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

    def command(
        self,
        name: str,
        reply_text: str,
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
    ) -> None:
        async def _handler(message: Message) -> None:
            await self._send_to_many(
                message,
                recipients,
                message.bot.send_message,
                text=reply_text,
                disable_notification=silent,
                protect_content=protect,
            )

        self.dp.message.register(_handler, Command(name))

    def media_command(
        self,
        name: str,
        kind: str,
        media: str,
        caption: str = "",
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
        **extra,
    ) -> None:
        k = (kind or "").strip().lower()
        methods = {
            "photo": ("send_photo", "photo"),
            "rasm": ("send_photo", "photo"),
            "video": ("send_video", "video"),
            "audio": ("send_audio", "audio"),
            "document": ("send_document", "document"),
            "file": ("send_document", "document"),
            "hujjat": ("send_document", "document"),
            "animation": ("send_animation", "animation"),
        }
        if k not in methods:
            raise ValueError(f"Unknown media kind: {kind}")
        method_name, arg_name = methods[k]

        async def _handler(message: Message) -> None:
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

        self.dp.message.register(_handler, Command(name))

    def photo_command(
        self,
        name: str,
        photo: str,
        caption: str = "",
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
        **extra,
    ) -> None:
        self.media_command(
            name,
            "photo",
            photo,
            caption,
            recipients=recipients,
            silent=silent,
            protect=protect,
            from_path=from_path,
            **extra,
        )

    def video_command(
        self,
        name: str,
        video: str,
        caption: str = "",
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
        **extra,
    ) -> None:
        self.media_command(
            name,
            "video",
            video,
            caption,
            recipients=recipients,
            silent=silent,
            protect=protect,
            from_path=from_path,
            **extra,
        )

    def audio_command(
        self,
        name: str,
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
    ) -> None:
        if performer:
            extra["performer"] = performer
        if title:
            extra["title"] = title

        self.media_command(
            name,
            "audio",
            audio,
            caption,
            recipients=recipients,
            silent=silent,
            protect=protect,
            from_path=from_path,
            **extra,
        )

    def file_command(
        self,
        name: str,
        file: str,
        caption: str = "",
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
        **extra,
    ) -> None:
        self.media_command(
            name,
            "document",
            file,
            caption,
            recipients=recipients,
            silent=silent,
            protect=protect,
            from_path=from_path,
            **extra,
        )

    def any(self, handler: Handler) -> None:
        self.dp.message.register(handler)

    def on(self, kind: str, handler: Handler) -> None:
        k = (kind or "").strip().lower()
        if k in ("har qanday", "har_qanday", "any"):
            self.dp.message.register(handler)
            return

        mapping = {
            "matn": F.text,
            "text": F.text,
            "joylashuv": F.location,
            "location": F.location,
            "kontakt": F.contact,
            "contact": F.contact,
            "telefon": F.contact,
            "hujjat": F.document,
            "document": F.document,
            "rasm": F.photo,
            "photo": F.photo,
            "video": F.video,
            "audio": F.audio,
            "stiker": F.sticker,
            "sticker": F.sticker,
        }
        flt = mapping.get(k)
        if flt is None:
            raise ValueError(f"Unknown kind: {kind}")
        self.dp.message.register(handler, flt)

    def on_text(self, handler: Handler, filter: str = "har qanday", value: Optional[str] = None) -> None:
        flt = self._build_text_filter(filter, value)
        if flt is None:
            self.dp.message.register(handler, F.text)
        else:
            self.dp.message.register(handler, F.text, flt)

    def _build_text_filter(self, filter: str, value: Optional[str]):
        op = (filter or "").strip().lower()

        if op in ("har qanday", "har_qanday", "any"):
            return None

        if op in ("teng", "equal"):
            if value is None:
                raise ValueError("value is required for 'teng'")
            return F.text == value

        if op in ("ichida", "contains"):
            if value is None:
                raise ValueError("value is required for 'ichida'")
            return F.text.contains(value)

        if op in ("ichida emas", "ichida_emas", "not_contains"):
            if value is None:
                raise ValueError("value is required for 'ichida emas'")
            return ~F.text.contains(value)

        if op in ("boshlanadi", "starts", "starts_with"):
            if value is None:
                raise ValueError("value is required for 'boshlanadi'")
            return F.text.startswith(value)

        if op in ("regex",):
            if value is None:
                raise ValueError("value is required for 'regex'")
            return F.text.regexp(value)

        if op in ("buyruq", "command"):
            if value is None:
                raise ValueError("value is required for 'buyruq'")
            return Command(value.lstrip("/"))

        raise ValueError(f"Unknown text filter: {filter}")

    async def _run(self) -> None:
        bot = Bot(token=self.token)
        await self.dp.start_polling(bot)

    def run(self) -> None:
        asyncio.run(self._run())
