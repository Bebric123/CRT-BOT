"""Память: в каком треде обсуждения (message_thread_id) последний пост канала содержал триггер-хештег.

Нужна, чтобы выполнять ТЗ: тег бота в комментарии под постом — без обязательного «Ответить»
в клиентах, где комментарий попадает в тот же тред, что и копия поста."""

from __future__ import annotations

import logging
from telegram import Message, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def text_has_trigger_hashtag(body: str, hashtag: str) -> bool:
    tag = hashtag.strip().lower()
    if not tag.startswith("#"):
        tag = "#" + tag
    return tag in body.lower()


def _visible_text(msg: Message) -> str:
    parts: list[str] = []
    if msg.text:
        parts.append(msg.text)
    if msg.caption:
        parts.append(msg.caption)
    return "\n".join(parts)


class DiscussionTagCache:
    """(chat_id, thread_id) → был ли триггер в последней копии поста канала в этом треде."""

    def __init__(self) -> None:
        self._has_tag: dict[tuple[int, int], bool] = {}
        self._post_snippet: dict[tuple[int, int], str] = {}

    def _key(self, chat_id: int, message_thread_id: int | None) -> tuple[int, int]:
        return (chat_id, 0 if message_thread_id is None else message_thread_id)

    def record_channel_mirror(
        self, chat_id: int, message_thread_id: int | None, body: str, configured_tag: str
    ) -> None:
        k = self._key(chat_id, message_thread_id)
        ok = text_has_trigger_hashtag(body, configured_tag)
        self._has_tag[k] = ok
        if body.strip():
            self._post_snippet[k] = body.strip()[:2500]
        logger.debug("discussion mirror chat=%s thread=%s trigger=%s", k[0], k[1], ok)

    def thread_matches_trigger(self, chat_id: int, message_thread_id: int | None) -> bool:
        return self._has_tag.get(self._key(chat_id, message_thread_id), False)

    def thread_post_snippet(self, chat_id: int, message_thread_id: int | None) -> str:
        return self._post_snippet.get(self._key(chat_id, message_thread_id), "")


async def track_discussion_channel_mirror(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Любое сообщение в группе: если это копия поста канала — обновить кэш треда."""
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    sc = msg.sender_chat
    if not sc or sc.type != ChatType.CHANNEL:
        return

    storage = context.application.bot_data.get("storage")
    if storage is None or not storage.is_enabled():
        return
    if not storage.is_whitelisted(chat.id):
        return

    cache: DiscussionTagCache = context.application.bot_data["discussion_cache"]
    cache.record_channel_mirror(
        chat.id,
        msg.message_thread_id,
        _visible_text(msg),
        storage.get_hashtag(),
    )
