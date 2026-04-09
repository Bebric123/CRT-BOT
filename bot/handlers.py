"""Telegram updates: mentions, checks, replies, admin commands."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from telegram import InputFile, Message, Update, User
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from bot.config import LocalLlmConfig
from bot.local_llm import generate_prediction_via_local_llm
from bot.prediction import (
    load_random_image_png_bytes,
    pick_prediction,
    split_for_photo_caption,
    split_text_message_chunks,
)
from bot.discussion_cache import text_has_trigger_hashtag
from bot.storage import Storage

logger = logging.getLogger(__name__)


def _root_message(msg: Message) -> Message:
    cur = msg
    while cur.reply_to_message is not None:
        cur = cur.reply_to_message
    return cur


def _reply_chain_messages(msg: Message) -> list[Message]:
    """От текущего сообщения вверх к корню цепочки (включая само сообщение)."""
    out: list[Message] = []
    cur: Message | None = msg
    while cur is not None:
        out.append(cur)
        cur = cur.reply_to_message
    return out


def _thread_has_hashtag(msg: Message, hashtag: str) -> bool:
    """Хештег в любом сообщении цепочки ответов (не только в корне)."""
    for m in _reply_chain_messages(msg):
        if text_has_trigger_hashtag(_message_text(m), hashtag):
            return True
    return False


def _thread_combined_text(msg: Message) -> str:
    """Тексты от корня поста к твоему сообщению — для контекста LLM."""
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
        # Выбор бота из подсказки — часто приходит как text_mention, а не mention
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
    """Для лимита; None — пропускаем лимит (нет from_user и не User в effective_sender)."""
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


async def handle_group_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    assets_dir: Path,
    silent_reject: bool,
    log_rejections: bool,
    local_llm: LocalLlmConfig,
) -> None:
    msg = update.effective_message
    if not msg or not update.effective_chat:
        return
    chat = update.effective_chat

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    sc = msg.sender_chat
    if sc is not None and sc.type == ChatType.CHANNEL:
        return

    if not (msg.text or msg.caption):
        return

    rate_uid = _rate_limit_user_id(update, msg)
    log_uid = rate_uid if rate_uid is not None else (msg.from_user.id if msg.from_user else 0)

    bot_me = context.bot_data.get("bot_me")
    if bot_me is None:
        bot_me = await context.bot.get_me()
        context.bot_data["bot_me"] = bot_me
    if not _bot_mentioned(
        msg, bot_me.username or "", bot_user_id=bot_me.id
    ):
        return

    def log_reject(reason: str) -> None:
        if log_rejections:
            logger.info(
                "reject chat_id=%s user_id=%s msg_id=%s reason=%s",
                chat.id,
                log_uid,
                msg.message_id,
                reason,
            )

    async def reject(text: str, reason_key: str) -> None:
        log_reject(reason_key)
        if silent_reject:
            return
        try:
            await msg.reply_text(
                text,
                message_thread_id=msg.message_thread_id,
            )
        except Exception:
            logger.exception("failed to send rejection")

    if not storage.is_enabled():
        await reject("Бот временно выключен.", "bot_disabled")
        return

    if not storage.is_whitelisted(chat.id):
        await reject(
            "Здесь бот не работает (чат не в списке разрешённых).\n\n"
            f"ID этого чата в Telegram: {chat.id}\n"
            "Для комментариев под постами канала в whitelist нужен id именно "
            "группы обсуждения (супергруппы), а не id канала — они разные.\n"
            "Админ может добавить: /add_whitelist прямо в этом чате, "
            "или вписать это число в WHITELIST_CHAT_IDS и перезапустить бота.",
            "chat_not_whitelisted",
        )
        return

    tag = storage.get_hashtag()
    cache = context.application.bot_data["discussion_cache"]
    in_reply_chain = _thread_has_hashtag(msg, tag)
    in_same_thread = cache.thread_matches_trigger(chat.id, msg.message_thread_id)
    if not in_reply_chain and not in_same_thread:
        tail = f"@{bot_me.username}" if bot_me.username else "бота"
        await reject(
            f"Предсказание только под постами с хештегом {tag} в этом чате обсуждения.\n"
            f"Комментарий должен относиться к такому посту (тот же тред в группе с темами "
            f"или ответ на копию поста). Упомяни {tail} в этом комментарии.",
            "no_hashtag",
        )
        return

    if in_reply_chain:
        post_text = _thread_combined_text(msg)
    else:
        snip = cache.thread_post_snippet(chat.id, msg.message_thread_id)
        own = _message_text(msg)
        post_text = "\n\n".join(p for p in (snip, own) if p.strip())

    if rate_uid is not None:
        left = storage.rate_limit_seconds_left(rate_uid, 60)
        if left > 0:
            await reject(
                f"Уже выдавали предсказание недавно. Следующий раз через {_format_wait(left)}.",
                "rate_limit",
            )
            return

    prediction = pick_prediction()
    if local_llm.enabled:
        post_ctx = post_text if local_llm.include_post else None
        generated = await generate_prediction_via_local_llm(
            backend=local_llm.backend,
            base_url=local_llm.base_url,
            model=local_llm.model,
            api_key=local_llm.api_key,
            timeout_sec=local_llm.timeout_sec,
            temperature=local_llm.temperature,
            max_tokens=local_llm.max_tokens,
            max_output_chars=local_llm.max_output_chars,
            system_prompt=local_llm.system_prompt,
            user_prompt=local_llm.user_prompt,
            post_context=post_ctx,
        )
        if generated:
            prediction = generated
        else:
            logger.info("local_llm: fallback to template prediction text")

    image_bytes: bytes | None = None
    try:
        image_bytes = load_random_image_png_bytes(assets_dir)
    except Exception:
        logger.exception("load image from assets failed")

    try:
        if image_bytes:
            cap, tail = split_for_photo_caption(prediction)
            sent = await msg.reply_photo(
                photo=InputFile(io.BytesIO(image_bytes), filename="image.png"),
                caption=cap,
                message_thread_id=msg.message_thread_id,
            )
            if tail:
                await sent.reply_text(
                    tail,
                    message_thread_id=msg.message_thread_id,
                )
        else:
            chunks = split_text_message_chunks(prediction)
            last = await msg.reply_text(
                chunks[0],
                message_thread_id=msg.message_thread_id,
            )
            for part in chunks[1:]:
                last = await last.reply_text(
                    part,
                    message_thread_id=msg.message_thread_id,
                )
        if rate_uid is not None:
            storage.touch_rate_limit(rate_uid)
    except Exception:
        logger.exception("send reply failed")
        try:
            chunks = split_text_message_chunks(prediction)
            last = await msg.reply_text(
                chunks[0],
                message_thread_id=msg.message_thread_id,
            )
            for part in chunks[1:]:
                last = await last.reply_text(
                    part,
                    message_thread_id=msg.message_thread_id,
                )
            if rate_uid is not None:
                storage.touch_rate_limit(rate_uid)
        except Exception:
            logger.exception("text fallback failed")


def _is_admin(user_id: int, admin_ids: frozenset[int]) -> bool:
    return user_id in admin_ids


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
        "Бот предсказаний на рабочую неделю.\n"
        "В комментариях под постом канала (чат обсуждения) упомяни бота и хештег должен быть у этого поста. "
        "В группах с темами — комментарий в теме поста; иначе можно ответить на копию поста в чате.\n"
        "Админы: /help_admin"
    )


async def cmd_help_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not _is_admin(user.id, admin_ids):
        if msg:
            await msg.reply_text("Нет доступа.")
        return
    await msg.reply_text(
        "Команды (только для админов):\n"
        "/add_whitelist — в группе: добавить этот чат в whitelist\n"
        "/remove_whitelist — убрать чат\n"
        "/list_whitelist — список chat_id\n"
        "/chat_id — id текущего чата (проверка для группы обсуждения)\n"
        "/set_hashtag #тег — триггер в тексте поста\n"
        "/get_hashtag\n"
        "/bot_on /bot_off — включить и выключить ответы\n"
        "/status"
    )


async def cmd_add_whitelist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user or not _is_admin(user.id, admin_ids):
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await msg.reply_text("Команду нужно вызвать внутри группы обсуждения.")
        return
    storage.whitelist_add(chat.id)
    await msg.reply_text(f"Чат {chat.id} добавлен в whitelist.")


async def cmd_remove_whitelist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user or not _is_admin(user.id, admin_ids):
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await msg.reply_text("Команду нужно вызвать внутри группы.")
        return
    if storage.whitelist_remove(chat.id):
        await msg.reply_text(f"Чат {chat.id} убран из whitelist.")
    else:
        await msg.reply_text("Этого чата не было в whitelist.")


async def cmd_list_whitelist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not _is_admin(user.id, admin_ids):
        return
    ids = storage.whitelist_list()
    await msg.reply_text("Whitelist:\n" + ("\n".join(str(i) for i in ids) or "(пусто)"))


async def cmd_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_ids: frozenset[int],
) -> None:
    """Показать chat.id текущего чата — удобно для группы обсуждения канала."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    if not _is_admin(user.id, admin_ids):
        await msg.reply_text("Нет доступа.")
        return
    title = chat.title or "(без названия)"
    await msg.reply_text(
        f"chat.id: {chat.id}\n"
        f"type: {chat.type}\n"
        f"title: {title}\n\n"
        "Для комментариев к каналу в whitelist указывают id именно этой группы, не канала.\n"
        "Добавить в whitelist: /add_whitelist здесь."
    )


async def cmd_set_hashtag(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not _is_admin(user.id, admin_ids):
        return
    args = context.args or []
    if not args:
        await msg.reply_text("Укажи тег: /set_hashtag #predict_week")
        return
    storage.set_hashtag(" ".join(args))
    await msg.reply_text(f"Хештег-триггер: {storage.get_hashtag()}")


async def cmd_get_hashtag(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not _is_admin(user.id, admin_ids):
        return
    await msg.reply_text(f"Текущий тег: {storage.get_hashtag()}")


async def cmd_bot_on(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not _is_admin(user.id, admin_ids):
        return
    storage.set_enabled(True)
    await msg.reply_text("Бот включён.")


async def cmd_bot_off(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not _is_admin(user.id, admin_ids):
        return
    storage.set_enabled(False)
    await msg.reply_text("Бот выключен.")


async def cmd_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not _is_admin(user.id, admin_ids):
        return
    on = storage.is_enabled()
    await msg.reply_text(
        f"enabled={on}\nhashtag={storage.get_hashtag()}\n"
        f"whitelist_count={len(storage.whitelist_list())}"
    )
