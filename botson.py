import asyncio
from os import getenv
from typing import Awaitable, Callable, Optional

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

Handler = Callable[[Message], Awaitable[None]]


class BotApp:
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or getenv("BOT_TOKEN")
        if not self.token:
            raise RuntimeError("BOT_TOKEN is not set")

        self.dp = Dispatcher()

    def command(self, name: str, reply_text: str) -> None:
        async def _handler(message: Message) -> None:
            await message.answer(reply_text)

        self.dp.message.register(_handler, Command(name))

    def any(self, handler: Handler) -> None:
        self.dp.message.register(handler)

    async def _run(self) -> None:
        bot = Bot(token=self.token)
        await self.dp.start_polling(bot)

    def run(self) -> None:
        asyncio.run(self._run())
