import asyncio
from dataclasses import dataclass
from os import getenv
from typing import Awaitable, Callable, Iterable, Optional, Union

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.types.input_file import FSInputFile

Handler = Callable[[Message], Awaitable[None]]
ChatId = Union[int, str]


@dataclass(frozen=True)
class Opt:
    recipients: Optional[Iterable[ChatId]] = None
    silent: bool = False
    protect: bool = False
    from_path: bool = False


class BotApp:
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or getenv("BOT_TOKEN")
        if not self.token:
            raise RuntimeError("BOT_TOKEN is not set")
        self.dp = Dispatcher()

    def opt(
        self,
        *,
        recipients: Optional[Iterable[ChatId]] = None,
        silent: bool = False,
        protect: bool = False,
        from_path: bool = False,
    ) -> Opt:
        return Opt(
            recipients=recipients,
            silent=silent,
            protect=protect,
            from_path=from_path,
        )

    def _targets(self, message: Message, opt: Opt) -> list[ChatId]:
        return list(opt.recipients) if opt.recipients else [message.chat.id]

    def _src(self, src: str, opt: Opt):
        return FSInputFile(src) if opt.from_path else src

    async def _send_many(self, message: Message, opt: Opt, send, **payload) -> None:
        for chat_id in self._targets(message, opt):
            await send(chat_id=chat_id, **payload)

    def command(self, name: str, reply_text: str, *, opt: Optional[Opt] = None) -> None:
        o = opt or Opt()

        async def _handler(message: Message) -> None:
            await self._send_many(
                message,
                o,
                message.bot.send_message,
                text=reply_text,
                disable_notification=o.silent,
                protect_content=o.protect,
            )

        self.dp.message.register(_handler, Command(name))

    def media_command(
        self,
        name: str,
        kind: str,
        media: str,
        caption: str = "",
        *,
        opt: Optional[Opt] = None,
    ) -> None:
        o = opt or Opt()

        kinds = {
            "photo": ("send_photo", "photo"),
            "rasm": ("send_photo", "photo"),
            "video": ("send_video", "video"),
            "audio": ("send_audio", "audio"),
            "document": ("send_document", "document"),
            "hujjat": ("send_document", "document"),
            "animation": ("send_animation", "animation"),
        }

        if kind not in kinds:
            raise ValueError(f"Unknown media kind: {kind}")

        method, arg = kinds[kind]

        async def _handler(message: Message) -> None:
            payload = {
                arg: self._src(media, o),
                "disable_notification": o.silent,
                "protect_content": o.protect,
            }
            if caption:
                payload["caption"] = caption

            await self._send_many(
                message,
                o,
                getattr(message.bot, method),
                **payload,
            )

        self.dp.message.register(_handler, Command(name))

    def photo_command(self, name: str, photo: str, caption: str = "", *, opt: Optional[Opt] = None) -> None:
        self.media_command(name, "photo", photo, caption, opt=opt)

    def video_command(self, name: str, video: str, caption: str = "", *, opt: Optional[Opt] = None) -> None:
        self.media_command(name, "video", video, caption, opt=opt)

    def any(self, handler: Handler) -> None:
        self.dp.message.register(handler)

    def on(self, kind: str, handler: Handler) -> None:
        k = (kind or "").lower()

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

    async def _run(self) -> None:
        bot = Bot(token=self.token)
        await self.dp.start_polling(bot)

    def run(self) -> None:
        asyncio.run(self._run())
