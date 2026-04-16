"""Telegram updates: admin commands."""

from __future__ import annotations

from telegram import ReplyKeyboardRemove, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from bot.admin_keyboard import admin_reply_keyboard
from bot.cmd_guards import admin_message_user, admin_message_user_chat, is_supergroup_or_group
from bot.defaults import (
    LOCAL_LLM_MAX_OUTPUT_CHARS_DEFAULT,
    LOCAL_LLM_MAX_OUTPUT_CHARS_MAX,
    LOCAL_LLM_MAX_OUTPUT_CHARS_MIN,
    RATE_LIMIT_SECONDS_DEFAULT,
)
from bot.handlers_texts import help_admin_message_body, start_message_body, status_message_body
from bot.storage import Storage


async def cmd_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat:
        return
    admin_private = chat.type == ChatType.PRIVATE and user.id in admin_ids
    text = start_message_body(admin_in_private=admin_private)
    markup = admin_reply_keyboard() if admin_private else None
    await msg.reply_text(text, reply_markup=markup)


async def cmd_help_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.id not in admin_ids:
        if msg:
            await msg.reply_text("Нет доступа.")
        return
    markup = admin_reply_keyboard() if msg.chat.type == ChatType.PRIVATE else None
    await msg.reply_text(help_admin_message_body(), reply_markup=markup)


async def cmd_hide_keyboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat:
        return
    if user.id not in admin_ids:
        await msg.reply_text("Нет доступа.")
        return
    if chat.type != ChatType.PRIVATE:
        await msg.reply_text("Скрытие клавиатуры имеет смысл в личке с ботом.")
        return
    await msg.reply_text(
        "Кнопки скрыты. Снова показать: /start или /help_admin",
        reply_markup=ReplyKeyboardRemove(),
    )


async def cmd_add_whitelist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    muc = admin_message_user_chat(update, admin_ids)
    if not muc:
        return
    msg, chat, _user = muc
    if not is_supergroup_or_group(chat):
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
    muc = admin_message_user_chat(update, admin_ids)
    if not muc:
        return
    msg, chat, _user = muc
    if not is_supergroup_or_group(chat):
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
    mu = admin_message_user(update, admin_ids)
    if not mu:
        return
    msg, _user = mu
    ids = storage.whitelist_list()
    await msg.reply_text("Whitelist:\n" + ("\n".join(str(i) for i in ids) or "(пусто)"))


async def cmd_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_ids: frozenset[int],
) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    if user.id not in admin_ids:
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
    mu = admin_message_user(update, admin_ids)
    if not mu:
        return
    msg, _user = mu
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
    mu = admin_message_user(update, admin_ids)
    if not mu:
        return
    msg, _user = mu
    await msg.reply_text(f"Текущий тег: {storage.get_hashtag()}")


async def cmd_set_rate_limit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    mu = admin_message_user(update, admin_ids)
    if not mu:
        return
    msg, _user = mu
    args = context.args or []
    if not args:
        cur = storage.get_rate_limit_period_sec()
        await msg.reply_text(
            f"Сейчас: {cur} сек. между предсказаниями для одного пользователя.\n"
            f"Задать: /set_rate_limit {RATE_LIMIT_SECONDS_DEFAULT}"
        )
        return
    try:
        sec = int(args[0])
    except ValueError:
        await msg.reply_text(
            f"Нужно целое число секунд, например: /set_rate_limit {RATE_LIMIT_SECONDS_DEFAULT}"
        )
        return
    storage.set_rate_limit_period_sec(sec)
    await msg.reply_text(f"Интервал установлен: {storage.get_rate_limit_period_sec()} сек.")


async def cmd_bot_on(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    mu = admin_message_user(update, admin_ids)
    if not mu:
        return
    msg, _user = mu
    storage.set_enabled(True)
    await msg.reply_text("Бот включён.")


async def cmd_bot_off(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    mu = admin_message_user(update, admin_ids)
    if not mu:
        return
    msg, _user = mu
    storage.set_enabled(False)
    await msg.reply_text("Бот выключен.")


async def cmd_set_llm_max_chars(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    mu = admin_message_user(update, admin_ids)
    if not mu:
        return
    msg, _user = mu
    args = context.args or []
    if not args:
        cur = storage.get_llm_max_output_chars()
        await msg.reply_text(
            f"Сейчас лимит ответа LLM: {cur} символов.\n"
            f"Задать: /set_llm_max_chars {LOCAL_LLM_MAX_OUTPUT_CHARS_DEFAULT} "
            f"({LOCAL_LLM_MAX_OUTPUT_CHARS_MIN}…{LOCAL_LLM_MAX_OUTPUT_CHARS_MAX})"
        )
        return
    try:
        n = int(args[0])
    except ValueError:
        await msg.reply_text(
            f"Нужно целое число, например: /set_llm_max_chars {LOCAL_LLM_MAX_OUTPUT_CHARS_DEFAULT}"
        )
        return
    storage.set_llm_max_output_chars(n)
    await msg.reply_text(f"Лимит символов LLM: {storage.get_llm_max_output_chars()}")


async def cmd_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    admin_ids: frozenset[int],
) -> None:
    mu = admin_message_user(update, admin_ids)
    if not mu:
        return
    msg, _user = mu
    await msg.reply_text(
        status_message_body(
            enabled=storage.is_enabled(),
            hashtag=storage.get_hashtag(),
            rate_limit_sec=storage.get_rate_limit_period_sec(),
            llm_max_output_chars=storage.get_llm_max_output_chars(),
            whitelist_count=len(storage.whitelist_list()),
        )
    )
