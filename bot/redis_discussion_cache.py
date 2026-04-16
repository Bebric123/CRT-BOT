"""Redis-бэкенд для кэша тредов обсуждения (переживает рестарт пода)."""

from __future__ import annotations

import logging

import redis.asyncio as redis

from bot.hashtag import text_has_trigger_hashtag

logger = logging.getLogger(__name__)


class RedisDiscussionTagStore:
    def __init__(self, url: str, snippet_max: int = 2500) -> None:
        self._url = url
        self._snippet_max = max(100, min(8000, snippet_max))
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(self._url, decode_responses=True)
        await self._client.ping()
        logger.info("Redis discussion cache connected")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _hash_key(self, chat_id: int, message_thread_id: int | None) -> str:
        tid = 0 if message_thread_id is None else message_thread_id
        return f"crt:disc:{chat_id}:{tid}"

    async def record_channel_mirror(
        self, chat_id: int, message_thread_id: int | None, body: str, configured_tag: str
    ) -> None:
        if not self._client:
            raise RuntimeError("RedisDiscussionTagStore not connected")
        key = self._hash_key(chat_id, message_thread_id)
        ok = text_has_trigger_hashtag(body, configured_tag)
        snippet = body.strip()[: self._snippet_max] if body.strip() else ""
        await self._client.hset(
            key,
            mapping={"has_tag": "1" if ok else "0", "snippet": snippet},
        )
        logger.debug("discussion mirror redis chat=%s thread=%s trigger=%s", chat_id, key, ok)

    async def thread_matches_trigger(
        self, chat_id: int, message_thread_id: int | None
    ) -> bool:
        if not self._client:
            return False
        v = await self._client.hget(self._hash_key(chat_id, message_thread_id), "has_tag")
        return v == "1"

    async def thread_post_snippet(
        self, chat_id: int, message_thread_id: int | None
    ) -> str:
        if not self._client:
            return ""
        v = await self._client.hget(self._hash_key(chat_id, message_thread_id), "snippet")
        return v or ""
