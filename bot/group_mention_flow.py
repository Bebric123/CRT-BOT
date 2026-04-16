"""Упоминание бота в группе: проверки, предсказание, ответ."""

from __future__ import annotations

import io
import logging
import random
from dataclasses import dataclass
from pathlib import Path

from telegram import InputFile, Message, Update, User
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from bot.config import GroupMentionRuntime
from bot.discussion_cache import DiscussionTagStore
from bot.hashtag import text_has_trigger_hashtag
from bot.image_moderation import validate_image_for_send
from bot.local_llm import generate_prediction_via_local_llm
from bot.prediction import (
    image_path_to_png_bytes,
    list_asset_image_paths,
    pick_prediction,
    split_for_photo_caption,
    split_text_message_chunks,
)
from bot.storage import Storage
from bot.text_moderation import moderate_prediction_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ReadyGroupPrediction:
    """Все проверки пройдены; дальше — текст и картинка."""

    msg: Message
    rate_uid: int | None
    post_text: str


def _reply_chain_messages(msg: Message) -> list[Message]:
    out: list[Message] = []
    cur: Message | None = msg
    while cur is not None:
        out.append(cur)
        cur = cur.reply_to_message
    return out


def _thread_has_hashtag(msg: Message, hashtag: str) -> bool:
    for m in _reply_chain_messages(msg):
        if text_has_trigger_hashtag(_message_text(m), hashtag):
            return True
    return False


def _thread_combined_text(msg: Message) -> str:
    chain = _reply_chain_messages(msg)
    parts = [_message_text(m) for m in reversed(chain)]
    return "\n\n".join(p.strip() for p in parts if p.strip())


def _message_text(m: Message) -> str:
    parts: list[str] = []
    if m.text:
        parts.append(m.text)
    if m.caption:
        parts.append(m.caption)
    return "\n".join(parts)


def _entity_type_name(e) -> str:
    t = e.type
    if hasattr(t, "value"):
        return str(t.value).lower()
    s = str(t).lower()
    return s.rsplit(".", 1)[-1]


def _normalize_mention_text(s: str) -> str:
    return s.lower().replace("\u200b", "").replace("\ufe0f", "")


def _bot_mentioned(msg: Message, bot_username: str, bot_user_id: int | None = None) -> bool:
    uname = bot_username.strip().lower()
    raw = msg.text or msg.caption or ""
    if uname:
        text = _normalize_mention_text(raw)
        if f"@{uname}" in text:
            return True
    entities = list(msg.entities or []) + list(msg.caption_entities or [])
    for e in entities:
        kind = _entity_type_name(e)
        if kind == "text_mention" and bot_user_id is not None:
            u = getattr(e, "user", None)
            if u is not None and u.id == bot_user_id:
                return True
        if kind != "mention" or not uname:
            continue
        if e.offset < 0 or e.length <= 0 or e.offset + e.length > len(raw):
            continue
        frag = _normalize_mention_text(raw[e.offset : e.offset + e.length])
        if frag == f"@{uname}" or frag == uname:
            return True
    return False


def _rate_limit_user_id(update: Update, msg: Message) -> int | None:
    if msg.from_user is not None:
        return msg.from_user.id
    sender = update.effective_sender
    if isinstance(sender, User):
        return sender.id
    return None


def _format_wait(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h} ч. {m} мин."
    if m > 0:
        return f"{m} мин. {s} сек."
    return f"{s} сек."


def _group_message_guards(msg: Message | None, chat) -> bool:
    if not msg or not chat:
        return False
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return False
    sc = msg.sender_chat
    if sc is not None and sc.type == ChatType.CHANNEL:
        return False
    return bool(msg.text or msg.caption)


def _text_not_whitelisted(chat_id: int) -> str:
    return (
        "Здесь бот не работает (чат не в списке разрешённых).\n\n"
        f"ID этого чата в Telegram: {chat_id}\n"
        "Для комментариев под постами канала в whitelist нужен id именно "
        "группы обсуждения (супергруппы), а не id канала — они разные.\n"
        "Админ может добавить: /add_whitelist прямо в этом чате, "
        "или вписать это число в WHITELIST_CHAT_IDS и перезапустить бота."
    )


def _text_no_hashtag(tag: str, bot_username: str | None) -> str:
    tail = f"@{bot_username}" if bot_username else "бота"
    return (
        f"Предсказание только под постами с хештегом {tag} в этом чате обсуждения.\n"
        f"Комментарий должен относиться к такому посту (тот же тред в группе с темами "
        f"или ответ на копию поста в чате). Упомяни {tail} в этом комментарии."
    )


def _log_flow_reject(
    runtime: GroupMentionRuntime,
    *,
    chat_id: int,
    log_uid: int,
    msg_id: int,
    reason_key: str,
) -> None:
    if runtime.log_rejections:
        logger.info(
            "reject chat_id=%s user_id=%s msg_id=%s reason=%s",
            chat_id,
            log_uid,
            msg_id,
            reason_key,
        )


async def _send_user_rejection(msg: Message, runtime: GroupMentionRuntime, text: str) -> None:
    if runtime.silent_reject:
        return
    try:
        await msg.reply_text(text, message_thread_id=msg.message_thread_id)
    except Exception:
        logger.exception("failed to send rejection")


async def _resolve_bot_me(context: ContextTypes.DEFAULT_TYPE):
    bot_me = context.bot_data.get("bot_me")
    if bot_me is None:
        bot_me = await context.bot.get_me()
        context.bot_data["bot_me"] = bot_me
    return bot_me


async def _build_prediction_text(
    post_text: str, runtime: GroupMentionRuntime, storage: Storage
) -> str:
    prediction = pick_prediction()
    llm = runtime.local_llm
    if not llm.enabled:
        return prediction
    post_ctx = post_text if llm.include_post else None
    max_chars = storage.get_llm_max_output_chars()
    generated = await generate_prediction_via_local_llm(
        backend=llm.backend,
        base_url=llm.base_url,
        model=llm.model,
        api_key=llm.api_key,
        timeout_sec=llm.timeout_sec,
        temperature=llm.temperature,
        max_tokens=llm.max_tokens,
        max_output_chars=max_chars,
        system_prompt=llm.system_prompt,
        user_prompt=llm.user_prompt,
        post_context=post_ctx,
    )
    if generated:
        return generated
    logger.info("local_llm: fallback to template prediction text")
    return prediction


async def _post_text_for_llm(
    msg: Message,
    cache: DiscussionTagStore,
    hashtag: str,
    chat_id: int,
    in_reply_chain: bool,
    thread_id: int | None,
) -> str:
    if in_reply_chain:
        return _thread_combined_text(msg)
    snip = await cache.thread_post_snippet(chat_id, thread_id)
    own = _message_text(msg)
    return "\n\n".join(p for p in (snip, own) if p.strip())


async def _prediction_text_after_moderation(
    post_text: str,
    runtime: GroupMentionRuntime,
    storage: Storage,
) -> str:
    prediction = await _build_prediction_text(post_text, runtime, storage)
    mod_ok, mod_reason = await moderate_prediction_text(
        prediction, runtime.text_moderation, runtime.local_llm
    )
    if not mod_ok:
        logger.warning("текст предсказания отклонён модерацией (%s), шаблон", mod_reason)
        prediction = pick_prediction()
    return prediction


async def _load_validated_image(
    assets_dir: Path,
    runtime: GroupMentionRuntime,
) -> bytes | None:
    try:
        paths = list_asset_image_paths(assets_dir)
    except Exception:
        logger.exception("list asset images failed")
        return None
    if not paths:
        return None
    order = list(paths)
    random.shuffle(order)
    for path in order:
        raw = image_path_to_png_bytes(
            path,
            max_side=runtime.image_max_side,
            max_source_file_bytes=runtime.image_max_source_bytes,
        )
        if not raw:
            continue
        ok, reason = await validate_image_for_send(raw, config=runtime.image_safety)
        if ok:
            return raw
        logger.warning(
            "asset image skipped (%s): %s",
            path.name,
            reason or "unknown",
        )
    return None


async def _send_text_chunks(
    msg: Message,
    chunks: list[str],
    *,
    message_thread_id: int | None,
) -> Message:
    last = await msg.reply_text(chunks[0], message_thread_id=message_thread_id)
    for part in chunks[1:]:
        last = await last.reply_text(part, message_thread_id=message_thread_id)
    return last


async def _send_prediction_with_photo(
    msg: Message,
    prediction: str,
    image_bytes: bytes,
    *,
    message_thread_id: int | None,
) -> None:
    cap, tail = split_for_photo_caption(prediction)
    sent = await msg.reply_photo(
        photo=InputFile(io.BytesIO(image_bytes), filename="image.png"),
        caption=cap,
        message_thread_id=message_thread_id,
    )
    if tail:
        await sent.reply_text(tail, message_thread_id=message_thread_id)


async def _send_prediction_text_only(
    msg: Message,
    prediction: str,
    *,
    message_thread_id: int | None,
) -> None:
    chunks = split_text_message_chunks(prediction)
    await _send_text_chunks(msg, chunks, message_thread_id=message_thread_id)


async def _send_prediction_reply(
    msg: Message,
    prediction: str,
    image_bytes: bytes | None,
    rate_uid: int | None,
    storage: Storage,
) -> None:
    tid = msg.message_thread_id
    try:
        if image_bytes:
            await _send_prediction_with_photo(
                msg, prediction, image_bytes, message_thread_id=tid
            )
        else:
            await _send_prediction_text_only(msg, prediction, message_thread_id=tid)
        if rate_uid is not None:
            storage.touch_rate_limit(rate_uid)
    except Exception:
        logger.exception("send reply failed")
        try:
            await _send_prediction_text_only(msg, prediction, message_thread_id=tid)
            if rate_uid is not None:
                storage.touch_rate_limit(rate_uid)
        except Exception:
            logger.exception("text fallback failed")


async def _try_prepare_group_prediction(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    runtime: GroupMentionRuntime,
) -> _ReadyGroupPrediction | None:
    msg = update.effective_message
    chat = update.effective_chat
    if not _group_message_guards(msg, chat):
        return None
    assert msg is not None and chat is not None

    rate_uid = _rate_limit_user_id(update, msg)
    log_uid = rate_uid if rate_uid is not None else (msg.from_user.id if msg.from_user else 0)

    bot_me = await _resolve_bot_me(context)
    if not _bot_mentioned(msg, bot_me.username or "", bot_user_id=bot_me.id):
        return None

    async def reject(text: str, reason_key: str) -> None:
        _log_flow_reject(
            runtime,
            chat_id=chat.id,
            log_uid=log_uid,
            msg_id=msg.message_id,
            reason_key=reason_key,
        )
        await _send_user_rejection(msg, runtime, text)

    if not storage.is_enabled():
        await reject("Бот временно выключен.", "bot_disabled")
        return None

    if not storage.is_whitelisted(chat.id):
        await reject(_text_not_whitelisted(chat.id), "chat_not_whitelisted")
        return None

    tag = storage.get_hashtag()
    cache: DiscussionTagStore = context.application.bot_data["discussion_cache"]
    in_reply_chain = _thread_has_hashtag(msg, tag)
    in_same_thread = await cache.thread_matches_trigger(chat.id, msg.message_thread_id)
    if not in_reply_chain and not in_same_thread:
        await reject(
            _text_no_hashtag(tag, bot_me.username),
            "no_hashtag",
        )
        return None

    post_text = await _post_text_for_llm(
        msg, cache, tag, chat.id, in_reply_chain, msg.message_thread_id
    )

    period = storage.get_rate_limit_period_sec()
    if rate_uid is not None:
        left = storage.rate_limit_seconds_left(rate_uid, period)
        if left > 0:
            await reject(
                f"Уже выдавали предсказание недавно. Следующий раз через {_format_wait(left)}.",
                "rate_limit",
            )
            return None

    return _ReadyGroupPrediction(msg=msg, rate_uid=rate_uid, post_text=post_text)


async def _deliver_group_prediction(
    work: _ReadyGroupPrediction,
    storage: Storage,
    assets_dir: Path,
    runtime: GroupMentionRuntime,
) -> None:
    prediction = await _prediction_text_after_moderation(work.post_text, runtime, storage)
    image_bytes = await _load_validated_image(assets_dir, runtime)
    await _send_prediction_reply(
        work.msg, prediction, image_bytes, work.rate_uid, storage
    )


async def handle_group_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    assets_dir: Path,
    runtime: GroupMentionRuntime,
) -> None:
    work = await _try_prepare_group_prediction(update, context, storage, runtime)
    if work is None:
        return
    await _deliver_group_prediction(work, storage, assets_dir, runtime)
