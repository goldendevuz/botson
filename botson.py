import asyncio
import json as _json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from os import getenv
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence, Union, Literal

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.types.input_file import FSInputFile

ChatId = Union[int, str]
EditTarget = Literal["previous", "message_id"]
DeleteTarget = Literal["context", "message_id"]
FileKind = Literal["photo", "video", "audio", "document", "voice", "animation", "sticker", "any"]

HandlerLike = Callable[[Any], Any]
Handler = Callable[[Any], Awaitable[None]]
Predicate = Callable[[Message], bool]


@dataclass(frozen=True)
class DownloadedFile:
    file_id: str
    file_unique_id: str
    file_path: str
    local_path: str
    kind: str


AfterDownload = Callable[[DownloadedFile], None]


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]
    text: str
    json: Any
    url: str
    method: str


@dataclass(frozen=True)
class CronSpec:
    kind: Literal["daily", "weekly", "monthly", "yearly"]
    hour: int
    minute: int
    weekday: Optional[int] = None
    day: Optional[int] = None
    month: Optional[int] = None


@dataclass
class CronJob:
    spec: CronSpec
    steps: list[Callable[["CronContext"], Awaitable[None]]]


class CronContext:
    def __init__(self, app: "BotApp", bot: Bot) -> None:
        self.app = app
        self.bot = bot


def _has_text(message: Message) -> bool:
    return bool(getattr(message, "text", None))


def _text(message: Message) -> str:
    return getattr(message, "text", "") or ""


def _is_command(message: Message, name: str) -> bool:
    t = _text(message).strip()
    if not t.startswith("/"):
        return False
    cmd = t.split()[0][1:].split("@")[0]
    return cmd == name.lstrip("/")


def _kind_pred(kind: str) -> Predicate:
    k = (kind or "").strip().lower()
    if k == "text":
        return lambda m: bool(m.text)
    if k == "photo":
        return lambda m: bool(m.photo)
    if k == "video":
        return lambda m: bool(m.video)
    if k == "audio":
        return lambda m: bool(m.audio)
    if k == "document":
        return lambda m: bool(m.document)
    if k == "voice":
        return lambda m: bool(m.voice)
    if k == "animation":
        return lambda m: bool(m.animation)
    if k == "sticker":
        return lambda m: bool(m.sticker)
    if k == "location":
        return lambda m: bool(m.location)
    if k == "contact":
        return lambda m: bool(m.contact)
    raise ValueError(f"Unknown kind: {kind}")


async def _delay(seconds: int) -> None:
    s = int(seconds)
    if s > 0:
        await asyncio.sleep(s)


def _pick_text(items: Sequence[str]) -> str:
    seq = [x for x in items if isinstance(x, str) and x.strip()]
    if not seq:
        raise ValueError("random_send requires a non-empty list of non-empty strings")
    return random.choice(seq)


def _cb_message(cb: CallbackQuery) -> Optional[Message]:
    return getattr(cb, "message", None)


def _ctx_chat_id(ctx: Any) -> int:
    chat = getattr(ctx, "chat", None)
    if chat is not None and getattr(chat, "id", None) is not None:
        return int(chat.id)
    msg = getattr(ctx, "message", None)
    if msg is not None and getattr(msg, "chat", None) is not None:
        return int(msg.chat.id)
    raise RuntimeError("Context has no chat id")


def _ctx_user_id(ctx: Any) -> int:
    fu = getattr(ctx, "from_user", None)
    if fu is not None and getattr(fu, "id", None) is not None:
        return int(fu.id)
    msg = getattr(ctx, "message", None)
    if msg is not None and getattr(msg, "from_user", None) is not None:
        return int(msg.from_user.id)
    raise RuntimeError("Context has no user id")


def _is_awaitable(x: Any) -> bool:
    return hasattr(x, "__await__")


async def _run_user_callable(fn: Callable[[Any], Any], ctx: Any) -> None:
    out = fn(ctx)
    if _is_awaitable(out):
        await out


def _wrap(fn: HandlerLike) -> Handler:
    async def _h(ctx: Any) -> None:
        await _run_user_callable(fn, ctx)
    return _h


def _json_pick(obj: Any, path: str, default: Any = "") -> Any:
    if obj is None:
        return default
    p = (path or "").strip()
    if not p:
        return default
    if p.startswith("$."):
        p = p[2:]
    if p.startswith("$"):
        p = p[1:]
    if p.startswith("."):
        p = p[1:]
    if not p:
        return default
    cur = obj
    for part in p.split("."):
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(part, default)
        elif isinstance(cur, list):
            try:
                i = int(part)
            except Exception:
                return default
            if i < 0 or i >= len(cur):
                return default
            cur = cur[i]
        else:
            return default
    return cur


class StateStore:
    def __init__(self) -> None:
        self._data: dict[tuple[int, int], dict[str, Any]] = {}

    def _key(self, ctx: Any) -> tuple[int, int]:
        return (_ctx_chat_id(ctx), _ctx_user_id(ctx))

    def get(self, ctx: Any, key: str, default: Any = None) -> Any:
        return self._data.get(self._key(ctx), {}).get(key, default)

    def all(self, ctx: Any) -> dict[str, Any]:
        return dict(self._data.get(self._key(ctx), {}))

    def set(self, ctx: Any, key: str, value: Any) -> None:
        k = self._key(ctx)
        bucket = self._data.get(k)
        if bucket is None:
            bucket = {}
            self._data[k] = bucket
        bucket[key] = value

    def drop(self, ctx: Any, key: str) -> None:
        bucket = self._data.get(self._key(ctx))
        if not bucket:
            return
        bucket.pop(key, None)

    def clear(self, ctx: Any) -> None:
        self._data.pop(self._key(ctx), None)

    def inc(self, ctx: Any, key: str, step: int = 1) -> int:
        k = self._key(ctx)
        bucket = self._data.get(k)
        if bucket is None:
            bucket = {}
            self._data[k] = bucket
        cur = bucket.get(key, 0)
        try:
            cur_i = int(cur)
        except Exception:
            cur_i = 0
        cur_i += int(step)
        bucket[key] = cur_i
        return cur_i


class StateAPI:
    def __init__(self, store: StateStore) -> None:
        self._s = store

    def get(self, ctx: Any, key: str, default: Any = None) -> Any:
        return self._s.get(ctx, key, default)

    def all(self, ctx: Any) -> dict[str, Any]:
        return self._s.all(ctx)

    def set(self, key: str, value: Any) -> Handler:
        async def _a(ctx: Any) -> None:
            self._s.set(ctx, key, value)
        return _a

    def drop(self, key: str) -> Handler:
        async def _a(ctx: Any) -> None:
            self._s.drop(ctx, key)
        return _a

    def clear(self) -> Handler:
        async def _a(ctx: Any) -> None:
            self._s.clear(ctx)
        return _a

    def inc(self, key: str, step: int = 1) -> Handler:
        async def _a(ctx: Any) -> None:
            self._s.inc(ctx, key, step=step)
        return _a


class HttpStore:
    def __init__(self) -> None:
        self._data: dict[tuple[int, int], HttpResult] = {}

    def _key(self, ctx: Any) -> tuple[int, int]:
        return (_ctx_chat_id(ctx), _ctx_user_id(ctx))

    def set(self, ctx: Any, result: HttpResult) -> None:
        self._data[self._key(ctx)] = result

    def get(self, ctx: Any) -> Optional[HttpResult]:
        return self._data.get(self._key(ctx))

    def drop(self, ctx: Any) -> None:
        self._data.pop(self._key(ctx), None)


class HttpAPI:
    def __init__(self, store: HttpStore) -> None:
        self._s = store

    def last(self, ctx: Any) -> Optional[HttpResult]:
        return self._s.get(ctx)

    def clear(self, ctx: Any) -> None:
        self._s.drop(ctx)


class HttpChain:
    def __init__(
        self,
        app: "BotApp",
        trigger: str,
        params: dict,
        method: str,
        url: Union[str, Callable[[Any], str]],
        *,
        params_q: Optional[Union[dict[str, Any], Callable[[Any], dict[str, Any]]]] = None,
        headers: Optional[Union[dict[str, str], Callable[[Any], dict[str, str]]]] = None,
        json_body: Optional[Union[dict[str, Any], list[Any], str, Callable[[Any], Any]]] = None,
        data: Optional[Union[dict[str, Any], str, bytes, Callable[[Any], Any]]] = None,
        timeout: float = 10.0,
        store_last: bool = True,
    ) -> None:
        self._app = app
        self._trigger = trigger
        self._params = params
        self._method = str(method).upper()
        self._url = url
        self._params_q = params_q
        self._headers = headers
        self._json_body = json_body
        self._data = data
        self._timeout = float(timeout)
        self._store_last = bool(store_last)
        self._steps: list[Callable[[Any, HttpResult], Awaitable[None]]] = []

    def then(self, fn: Callable[[Any, HttpResult], Any]) -> "HttpChain":
        async def _s(ctx: Any, result: HttpResult) -> None:
            out = fn(ctx, result)
            if _is_awaitable(out):
                await out
        self._steps.append(_s)
        return self

    def then_send_text(self, text: Union[str, Callable[[Any, HttpResult], str]]) -> "HttpChain":
        async def _s(ctx: Any, result: HttpResult) -> None:
            t = text(ctx, result) if callable(text) else str(text)
            if isinstance(ctx, Message):
                await ctx.answer(t)
        self._steps.append(_s)
        return self

    def then_send_json(self, path: str, default: str = "") -> "HttpChain":
        async def _s(ctx: Any, result: HttpResult) -> None:
            v = _json_pick(result.json, path, default)
            if isinstance(v, (dict, list)):
                t = _json.dumps(v, ensure_ascii=False)
            else:
                t = str(v)
            if isinstance(ctx, Message):
                await ctx.answer(t)
        self._steps.append(_s)
        return self

    def then_state_set_json(self, key: str, path: str, default: Any = None) -> "HttpChain":
        async def _s(ctx: Any, result: HttpResult) -> None:
            v = _json_pick(result.json, path, default)
            self._app._state_store.set(ctx, key, v)
        self._steps.append(_s)
        return self

    def done(self) -> "BotApp":
        method = self._method
        url = self._url
        params_q = self._params_q
        headers = self._headers
        json_body = self._json_body
        data = self._data
        timeout = self._timeout
        steps = list(self._steps)
        store_last = self._store_last

        async def _handler(ctx: Any) -> None:
            u = url(ctx) if callable(url) else str(url)

            pq = None
            if params_q is not None:
                pq = params_q(ctx) if callable(params_q) else dict(params_q)

            hd = None
            if headers is not None:
                hd = headers(ctx) if callable(headers) else dict(headers)

            jb = None
            if json_body is not None:
                jb = json_body(ctx) if callable(json_body) else json_body

            dt = None
            if data is not None:
                dt = data(ctx) if callable(data) else data

            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.request(
                    method=method,
                    url=u,
                    params=pq,
                    headers=hd,
                    json=jb,
                    data=dt,
                )

            txt = resp.text
            try:
                js = resp.json()
            except Exception:
                js = None

            result = HttpResult(
                status=int(resp.status_code),
                headers={k: v for k, v in resp.headers.items()},
                text=txt,
                json=js,
                url=str(resp.url),
                method=method,
            )

            if store_last:
                self._app._http_store.set(ctx, result)

            for s in steps:
                await s(ctx, result)

        self._app._register_trigger(self._trigger, _handler, **self._params)
        return self._app


class Node:
    def __init__(self, app: "BotApp", trigger: str, **params) -> None:
        self._app = app
        self._trigger = trigger
        self._params = params

    def handle(self, handler: HandlerLike) -> "BotApp":
        self._app._register_trigger(self._trigger, _wrap(handler), **self._params)
        return self._app

    def delay(self, seconds: int) -> "BotApp":
        s = max(0, int(seconds))

        async def _h(ctx: Any) -> None:
            await _delay(s)

        self._app._register_trigger(self._trigger, _h, **self._params)
        return self._app

    def send_message(self, text: str, **opts) -> "BotApp":
        return self.handle(self._app.action_send_message(text, **opts))

    def random_send(self, texts: Sequence[str], **opts) -> "BotApp":
        return self.handle(self._app.action_random_send_message(texts, **opts))

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

    def send_contact(self, phone_number: str, first_name: str, *, last_name: str = "", vcard: str = "", **opts) -> "BotApp":
        return self.handle(self._app.action_send_contact(phone_number=phone_number, first_name=first_name, last_name=last_name, vcard=vcard, **opts))

    def send_poll(self, question: str, options: Sequence[str], **opts) -> "BotApp":
        return self.handle(self._app.action_send_poll(question=question, options=options, **opts))

    def send_sticker(self, sticker: str, **opts) -> "BotApp":
        return self.handle(self._app.action_send_sticker(sticker=sticker, **opts))

    def send_game(self, *, game_type: str = "dice", **opts) -> "BotApp":
        return self.handle(self._app.action_send_game(game_type=game_type, **opts))

    def edit_text(self, new_text: str, **opts) -> "BotApp":
        return self.handle(self._app.action_edit_text(new_text=new_text, **opts))

    def edit_caption(self, new_caption: str, **opts) -> "BotApp":
        return self.handle(self._app.action_edit_caption(new_caption=new_caption, **opts))

    def forward_message(self, *, recipients: Iterable[ChatId], silent: bool = False, protect: bool = False) -> "BotApp":
        return self.handle(self._app.action_forward_message(recipients=recipients, silent=silent, protect=protect))

    def delete_message(self, **opts) -> "BotApp":
        return self.handle(self._app.action_delete_message(**opts))

    def show_activity(self, **opts) -> "BotApp":
        return self.handle(self._app.action_show_activity(**opts))

    def download_file(self, **opts) -> "BotApp":
        return self.handle(self._app.action_download_file(**opts))

    def state_set(self, key: str, value: Any) -> "BotApp":
        return self.handle(self._app.state.set(key, value))

    def state_drop(self, key: str) -> "BotApp":
        return self.handle(self._app.state.drop(key))

    def state_clear(self) -> "BotApp":
        return self.handle(self._app.state.clear())

    def state_inc(self, key: str, step: int = 1) -> "BotApp":
        return self.handle(self._app.state.inc(key, step=step))

    def http(
        self,
        *,
        method: str,
        url: Union[str, Callable[[Any], str]],
        params: Optional[Union[dict[str, Any], Callable[[Any], dict[str, Any]]]] = None,
        headers: Optional[Union[dict[str, str], Callable[[Any], dict[str, str]]]] = None,
        json: Optional[Union[dict[str, Any], list[Any], str, Callable[[Any], Any]]] = None,
        data: Optional[Union[dict[str, Any], str, bytes, Callable[[Any], Any]]] = None,
        timeout: float = 10.0,
        store_last: bool = True,
    ) -> HttpChain:
        return HttpChain(
            self._app,
            self._trigger,
            dict(self._params),
            method,
            url,
            params_q=params,
            headers=headers,
            json_body=json,
            data=data,
            timeout=timeout,
            store_last=store_last,
        )


class CallbackNode:
    def __init__(self, app: "BotApp", **params) -> None:
        self._app = app
        self._params = params

    def handle(self, handler: HandlerLike) -> "BotApp":
        self._app._register_callback(_wrap(handler), **self._params)
        return self._app

    def answer(self, text: str = "", *, alert: bool = False, cache_time: int = 0) -> "BotApp":
        return self.handle(self._app.action_callback_answer(text=text, alert=alert, cache_time=cache_time))

    def send_message(self, text: str, *, silent: bool = False, protect: bool = False) -> "BotApp":
        return self.handle(self._app.action_callback_send_message(text=text, silent=silent, protect=protect))

    def random_send(self, texts: Sequence[str], *, silent: bool = False, protect: bool = False) -> "BotApp":
        return self.handle(self._app.action_callback_random_send(texts=texts, silent=silent, protect=protect))

    def edit_text(self, new_text: str, *, parse_mode: Optional[str] = "HTML", reply_markup: Optional[InlineKeyboardMarkup] = None) -> "BotApp":
        return self.handle(self._app.action_callback_edit_text(new_text=new_text, parse_mode=parse_mode, reply_markup=reply_markup))

    def edit_caption(self, new_caption: str, *, parse_mode: Optional[str] = "HTML", reply_markup: Optional[InlineKeyboardMarkup] = None) -> "BotApp":
        return self.handle(self._app.action_callback_edit_caption(new_caption=new_caption, parse_mode=parse_mode, reply_markup=reply_markup))

    def delete_message(self) -> "BotApp":
        return self.handle(self._app.action_callback_delete_message())

    def show_activity(self, *, activity: str = "typing", seconds: int = 5) -> "BotApp":
        return self.handle(self._app.action_callback_show_activity(activity=activity, seconds=seconds))

    def state_set(self, key: str, value: Any) -> "BotApp":
        return self.handle(self._app.state.set(key, value))

    def state_drop(self, key: str) -> "BotApp":
        return self.handle(self._app.state.drop(key))

    def state_clear(self) -> "BotApp":
        return self.handle(self._app.state.clear())

    def state_inc(self, key: str, step: int = 1) -> "BotApp":
        return self.handle(self._app.state.inc(key, step=step))


class CronNode:
    def __init__(self, app: "BotApp", spec: CronSpec) -> None:
        self._app = app
        self._spec = spec
        self._steps: list[Callable[[CronContext], Awaitable[None]]] = []

    def handle(self, handler: HandlerLike) -> "BotApp":
        self._steps.append(_wrap(handler))
        self._app._cron_jobs.append(CronJob(self._spec, list(self._steps)))
        return self._app

    def send_message(
        self,
        *,
        chat_id: ChatId,
        text: str,
        silent: bool = False,
        protect: bool = False,
        parse_mode: Optional[str] = None,
    ) -> "BotApp":
        async def _a(ctx: CronContext) -> None:
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=text,
                disable_notification=bool(silent),
                protect_content=bool(protect),
                parse_mode=parse_mode,
            )

        self._steps.append(_a)
        self._app._cron_jobs.append(CronJob(self._spec, list(self._steps)))
        return self._app

    def http(
        self,
        *,
        method: str,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        timeout: float = 10.0,
    ) -> "CronNode":
        method_u = str(method).upper()

        async def _a(_: CronContext) -> None:
            async with httpx.AsyncClient(timeout=float(timeout), follow_redirects=True) as client:
                await client.request(method=method_u, url=str(url), params=params, headers=headers, json=json, data=data)

        self._steps.append(_a)
        return self


class CronBuilder:
    def __init__(self, app: "BotApp") -> None:
        self._app = app

    def daily(self, *, hour: int, minute: int = 0) -> CronNode:
        return CronNode(self._app, CronSpec(kind="daily", hour=int(hour), minute=int(minute)))

    def weekly(self, *, hour: int, minute: int = 0, weekday: int = 0) -> CronNode:
        return CronNode(self._app, CronSpec(kind="weekly", hour=int(hour), minute=int(minute), weekday=int(weekday)))

    def monthly(self, *, day: int = 1, hour: int = 9, minute: int = 0) -> CronNode:
        return CronNode(self._app, CronSpec(kind="monthly", hour=int(hour), minute=int(minute), day=int(day)))

    def yearly(self, *, month: int = 1, day: int = 1, hour: int = 9, minute: int = 0) -> CronNode:
        return CronNode(self._app, CronSpec(kind="yearly", hour=int(hour), minute=int(minute), month=int(month), day=int(day)))


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
        self._member_cache: dict[tuple[str, int], tuple[bool, float]] = {}
        self._state_store = StateStore()
        self.state = StateAPI(self._state_store)
        self._http_store = HttpStore()
        self.http = HttpAPI(self._http_store)
        self._cron_jobs: list[CronJob] = []

    def _targets(self, message: Message, recipients: Optional[Iterable[ChatId]]) -> list[ChatId]:
        return list(recipients) if recipients else [message.chat.id]

    def _file(self, src: str, from_path: bool):
        return FSInputFile(src) if from_path else src

    async def _send_to_many(self, message: Message, recipients: Optional[Iterable[ChatId]], send, **kwargs) -> None:
        for chat_id in self._targets(message, recipients):
            await send(chat_id=chat_id, **kwargs)

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

    def _build_callback_filter(self, filter: str, value):
        op = (filter or "any").strip().lower()

        if op == "any":
            return None
        if op in ("equal", "equals", "static"):
            if value is None:
                raise ValueError("value is required for callback filter='equal'")
            return F.data == str(value)
        if op in ("contains", "in"):
            if value is None:
                raise ValueError("value is required for callback filter='contains'")
            return F.data.contains(str(value))
        if op in ("starts", "starts_with", "startswith"):
            if value is None:
                raise ValueError("value is required for callback filter='starts'")
            return F.data.startswith(str(value))
        if op == "regex":
            if value is None:
                raise ValueError("value is required for callback filter='regex'")
            return F.data.regexp(str(value))
        if op in ("collection", "one_of", "in_list"):
            if value is None:
                raise ValueError("value is required for callback filter='collection'")
            items = list(value) if isinstance(value, (list, tuple, set)) else [value]
            items = [str(x) for x in items]
            return F.data.in_(items)
        raise ValueError(f"Unknown callback filter: {filter}")

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

        if t == "reply":
            ignore_commands = bool(params.get("ignore_commands", True))
            flt_text = self._build_text_filter(params.get("filter", "any"), params.get("value"))
            base = F.text
            if ignore_commands:
                base = base & ~F.text.startswith("/")
            if flt_text is None:
                self.dp.message.register(handler, base)
            else:
                self.dp.message.register(handler, base, flt_text)
            return

        raise ValueError(f"Unknown trigger: {trigger}")

    def _register_callback(self, handler: Handler, **params) -> None:
        flt = self._build_callback_filter(params.get("filter", "any"), params.get("value"))
        if flt is None:
            self.dp.callback_query.register(handler)  # type: ignore[arg-type]
        else:
            self.dp.callback_query.register(handler, flt)  # type: ignore[arg-type]

    def action_send_message(self, text: str, *, recipients=None, silent=False, protect=False) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, Message):
                return
            await self._send_to_many(
                ctx,
                recipients,
                ctx.bot.send_message,
                text=text,
                disable_notification=bool(silent),
                protect_content=bool(protect),
            )
        return _a

    def action_random_send_message(self, texts: Sequence[str], *, recipients=None, silent=False, protect=False) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, Message):
                return
            picked = _pick_text(texts)
            await self._send_to_many(
                ctx,
                recipients,
                ctx.bot.send_message,
                text=picked,
                disable_notification=bool(silent),
                protect_content=bool(protect),
            )
        return _a

    def action_send_media(self, kind: str, media: str, caption: str = "", *, recipients=None, silent=False, protect=False, from_path=False, **extra) -> Handler:
        k = (kind or "").strip().lower()
        spec = self._MEDIA_METHODS.get(k)
        if spec is None:
            raise ValueError(f"Unknown media kind: {kind}")
        method_name, arg_name = spec

        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, Message):
                return
            send = getattr(ctx.bot, method_name)
            payload = {
                arg_name: FSInputFile(media) if from_path else media,
                "disable_notification": bool(silent),
                "protect_content": bool(protect),
                **extra,
            }
            if caption:
                payload["caption"] = caption
            await self._send_to_many(ctx, recipients, send, **payload)
        return _a

    def action_send_location(self, *, latitude: float, longitude: float, recipients=None, silent=False, protect=False) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, Message):
                return
            await self._send_to_many(
                ctx,
                recipients,
                ctx.bot.send_location,
                latitude=latitude,
                longitude=longitude,
                disable_notification=bool(silent),
                protect_content=bool(protect),
            )
        return _a

    def action_send_contact(self, *, phone_number: str, first_name: str, last_name: str = "", vcard: str = "", recipients=None, silent=False, protect=False) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, Message):
                return
            payload = {
                "phone_number": phone_number,
                "first_name": first_name,
                "disable_notification": bool(silent),
                "protect_content": bool(protect),
            }
            if last_name:
                payload["last_name"] = last_name
            if vcard:
                payload["vcard"] = vcard
            await self._send_to_many(ctx, recipients, ctx.bot.send_contact, **payload)
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

        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, Message):
                return
            payload = {
                "question": question,
                "options": list(options),
                "type": pt,
                "is_anonymous": bool(anonymous),
                "allows_multiple_answers": bool(multiple_answers),
                "disable_notification": bool(silent),
                "protect_content": bool(protect),
            }
            if open_period is not None:
                payload["open_period"] = int(open_period)
            if pt == "quiz":
                if correct_option_id is not None:
                    payload["correct_option_id"] = int(correct_option_id)
                if explanation:
                    payload["explanation"] = explanation
            await self._send_to_many(ctx, recipients, ctx.bot.send_poll, **payload)
        return _a

    def action_send_sticker(self, *, sticker: str, recipients=None, silent=False, protect=False) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, Message):
                return
            await self._send_to_many(
                ctx,
                recipients,
                ctx.bot.send_sticker,
                sticker=sticker,
                disable_notification=bool(silent),
                protect_content=bool(protect),
            )
        return _a

    def action_send_game(self, *, game_type: str = "dice", recipients=None, silent=False, protect=False) -> Handler:
        key = (game_type or "dice").strip().lower()
        emoji = self._GAME_EMOJI.get(key)
        if not emoji:
            raise ValueError(f"Unknown game_type: {game_type}")

        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, Message):
                return
            await self._send_to_many(
                ctx,
                recipients,
                ctx.bot.send_dice,
                emoji=emoji,
                disable_notification=bool(silent),
                protect_content=bool(protect),
            )
        return _a

    def action_callback_answer(self, *, text: str = "", alert: bool = False, cache_time: int = 0) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, CallbackQuery):
                return
            await ctx.answer(text=text or None, show_alert=bool(alert), cache_time=int(cache_time))
        return _a

    def action_callback_send_message(self, *, text: str, silent: bool = False, protect: bool = False) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, CallbackQuery):
                return
            msg = _cb_message(ctx)
            if not msg:
                return
            await msg.bot.send_message(
                chat_id=msg.chat.id,
                text=text,
                disable_notification=bool(silent),
                protect_content=bool(protect),
            )
        return _a

    def action_callback_random_send(self, *, texts: Sequence[str], silent: bool = False, protect: bool = False) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, CallbackQuery):
                return
            msg = _cb_message(ctx)
            if not msg:
                return
            picked = _pick_text(texts)
            await msg.bot.send_message(
                chat_id=msg.chat.id,
                text=picked,
                disable_notification=bool(silent),
                protect_content=bool(protect),
            )
        return _a

    def action_callback_edit_text(self, *, new_text: str, parse_mode: Optional[str] = "HTML", reply_markup: Optional[InlineKeyboardMarkup] = None) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, CallbackQuery):
                return
            msg = _cb_message(ctx)
            if not msg:
                return
            await msg.bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text=new_text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        return _a

    def action_callback_edit_caption(self, *, new_caption: str, parse_mode: Optional[str] = "HTML", reply_markup: Optional[InlineKeyboardMarkup] = None) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, CallbackQuery):
                return
            msg = _cb_message(ctx)
            if not msg:
                return
            await msg.bot.edit_message_caption(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                caption=new_caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        return _a

    def action_callback_delete_message(self) -> Handler:
        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, CallbackQuery):
                return
            msg = _cb_message(ctx)
            if not msg:
                return
            await msg.bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        return _a

    def action_callback_show_activity(self, *, activity: str = "typing", seconds: int = 5) -> Handler:
        key = (activity or "typing").strip().lower()
        action = self._CHAT_ACTION.get(key)
        if not action:
            raise ValueError(f"Unknown activity: {activity}")

        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, CallbackQuery):
                return
            msg = _cb_message(ctx)
            if not msg:
                return
            total = max(1, int(seconds))
            interval = 4
            steps = max(1, (total + interval - 1) // interval)
            for _ in range(steps):
                await msg.bot.send_chat_action(chat_id=msg.chat.id, action=action)
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

    def action_download_file(self, *, kind: FileKind = "any", to_dir: str = "downloads", filename: str = "", on_done: Optional[AfterDownload] = None) -> Handler:
        k = (kind or "any").strip().lower()
        if k not in ("photo", "video", "audio", "document", "voice", "animation", "sticker", "any"):
            raise ValueError(f"Unknown kind: {kind}")

        async def _a(ctx: Any) -> None:
            if not isinstance(ctx, Message):
                return
            info = self._extract_file(ctx, k)
            if info is None:
                return
            file_kind, file_id, file_unique_id = info
            tg_file = await ctx.bot.get_file(file_id)
            out_dir = Path(to_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            if filename:
                out_path = out_dir / filename
            else:
                suffix = Path(tg_file.file_path).suffix
                out_path = out_dir / f"{file_kind}_{file_unique_id}{suffix}"
            await ctx.bot.download_file(tg_file.file_path, destination=str(out_path))
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

    def on_command(self, name: str) -> Node:
        return Node(self, "command", name=name)

    def on_any(self) -> Node:
        return Node(self, "any")

    def on_kind(self, kind: str) -> Node:
        return Node(self, "kind", kind=kind)

    def on_text(self, *, filter: str = "any", value: Optional[str] = None) -> Node:
        return Node(self, "text", filter=filter, value=value)

    def on_reply(self, *, filter: str = "any", value: Optional[str] = None, ignore_commands: bool = True) -> Node:
        return Node(self, "reply", filter=filter, value=value, ignore_commands=bool(ignore_commands))

    def on_callback(self, *, filter: str = "any", value=None) -> CallbackNode:
        return CallbackNode(self, filter=filter, value=value)

    def cron(self) -> CronBuilder:
        return CronBuilder(self)

    def command(self, name: str, reply_text: Optional[str] = None, *, recipients=None, silent=False, protect=False):
        if reply_text is None:
            return self.on_command(name)
        self.on_command(name).send_message(reply_text, recipients=recipients, silent=silent, protect=protect)
        return None

    def _register_callback(self, handler: Handler, **params) -> None:
        flt = self._build_callback_filter(params.get("filter", "any"), params.get("value"))
        if flt is None:
            self.dp.callback_query.register(handler)  # type: ignore[arg-type]
        else:
            self.dp.callback_query.register(handler, flt)  # type: ignore[arg-type]

    def _cron_next(self, spec: CronSpec, now: datetime) -> datetime:
        h = max(0, min(23, int(spec.hour)))
        m = max(0, min(59, int(spec.minute)))

        if spec.kind == "daily":
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            return t if t > now else t + timedelta(days=1)

        if spec.kind == "weekly":
            wd = 0 if spec.weekday is None else int(spec.weekday)
            wd = max(0, min(6, wd))
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            days_ahead = (wd - t.weekday()) % 7
            if days_ahead == 0 and t <= now:
                days_ahead = 7
            return t + timedelta(days=days_ahead)

        if spec.kind == "monthly":
            day = 1 if spec.day is None else int(spec.day)
            day = max(1, min(31, day))
            y, mo = now.year, now.month
            t = datetime(y, mo, 1, h, m)
            while True:
                try:
                    cand = datetime(t.year, t.month, day, h, m)
                except ValueError:
                    cand = datetime(t.year, t.month, 1, h, m) + timedelta(days=40)
                    t = datetime(cand.year, cand.month, 1, h, m)
                    continue
                if cand > now:
                    return cand
                cand2 = datetime(t.year, t.month, 1, h, m) + timedelta(days=40)
                t = datetime(cand2.year, cand2.month, 1, h, m)

        if spec.kind == "yearly":
            month = 1 if spec.month is None else int(spec.month)
            day = 1 if spec.day is None else int(spec.day)
            month = max(1, min(12, month))
            day = max(1, min(31, day))
            y = now.year
            while True:
                try:
                    cand = datetime(y, month, day, h, m)
                except ValueError:
                    y += 1
                    continue
                if cand > now:
                    return cand
                y += 1

        raise ValueError(f"Unknown cron kind: {spec.kind}")

    async def _run_cron(self, bot: Bot) -> None:
        ctx = CronContext(self, bot)

        async def _runner(job: CronJob) -> None:
            while True:
                now = datetime.now()
                nxt = self._cron_next(job.spec, now)
                sleep_s = max(0.0, (nxt - now).total_seconds())
                await asyncio.sleep(sleep_s)
                for step in job.steps:
                    await step(ctx)

        tasks = [asyncio.create_task(_runner(job)) for job in list(self._cron_jobs)]
        try:
            if tasks:
                await asyncio.gather(*tasks)
            else:
                while True:
                    await asyncio.sleep(3600)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise

    async def _run(self) -> None:
        bot = Bot(token=self.token)
        cron_task = asyncio.create_task(self._run_cron(bot))
        try:
            await self.dp.start_polling(bot)
        finally:
            cron_task.cancel()
            with asyncio.CancelledError.__class__:
                pass
            try:
                await cron_task
            except Exception:
                pass
            await bot.session.close()

    def run(self) -> None:
        asyncio.run(self._run())
