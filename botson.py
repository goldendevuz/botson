import asyncio
from os import getenv
from typing import Awaitable, Callable, Iterable, Optional, Union

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

Handler = Callable[[Message], Awaitable[None]]
ChatId = Union[int, str]


class BotApp:
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or getenv("BOT_TOKEN")
        if not self.token:
            raise RuntimeError("BOT_TOKEN is not set")
        self.dp = Dispatcher()

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
            targets = list(recipients) if recipients else [message.chat.id]
            for chat_id in targets:
                await message.bot.send_message(
                    chat_id=chat_id,
                    text=reply_text,
                    disable_notification=silent,
                    protect_content=protect,
                )

        self.dp.message.register(_handler, Command(name))

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

    def on_text(
        self,
        handler: Handler,
        filter: str = "har qanday",
        value: Optional[str] = None,
    ) -> None:
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
