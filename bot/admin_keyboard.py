"""Клавиатура и меню команд для админов (личка с ботом)."""

from __future__ import annotations

import logging

from telegram import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

log = logging.getLogger(__name__)


def admin_reply_keyboard() -> ReplyKeyboardMarkup:
    """Кнопки отправляют текст `/команда` — срабатывают те же обработчики."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("/status"), KeyboardButton("/help_admin")],
            [KeyboardButton("/list_whitelist"), KeyboardButton("/get_hashtag")],
            [KeyboardButton("/bot_on"), KeyboardButton("/bot_off")],
            [KeyboardButton("/set_rate_limit"), KeyboardButton("/set_llm_max_chars")],
            [KeyboardButton("/set_hashtag"), KeyboardButton("/chat_id")],
            [KeyboardButton("/add_whitelist"), KeyboardButton("/remove_whitelist")],
            [KeyboardButton("/hide_keyboard")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


async def setup_bot_command_menus(bot, admin_user_ids: frozenset[int]) -> None:
    """Меню «/» у всех — только /start; у каждого админа в личке — полный список."""
    try:
        await bot.set_my_commands(
            [BotCommand("start", "О боте")],
            scope=BotCommandScopeDefault(),
        )
    except Exception as exc:
        log.warning("set_my_commands (default): %s", exc)

    admin_cmds = [
        BotCommand("start", "О боте"),
        BotCommand("help_admin", "Справка по командам"),
        BotCommand("status", "Статус, лимиты, whitelist"),
        BotCommand("list_whitelist", "Список chat_id"),
        BotCommand("get_hashtag", "Текущий хештег-триггер"),
        BotCommand("set_hashtag", "Сменить тег (аргумент #тег)"),
        BotCommand("set_rate_limit", "Пауза между предсказаниями, сек"),
        BotCommand("set_llm_max_chars", "Лимит символов ответа LLM"),
        BotCommand("bot_on", "Включить ответы"),
        BotCommand("bot_off", "Выключить ответы"),
        BotCommand("add_whitelist", "В группе: добавить чат"),
        BotCommand("remove_whitelist", "В группе: убрать чат"),
        BotCommand("chat_id", "Показать id чата"),
        BotCommand("hide_keyboard", "Скрыть кнопки"),
    ]
    for aid in admin_user_ids:
        try:
            await bot.set_my_commands(
                admin_cmds,
                scope=BotCommandScopeChat(chat_id=aid),
            )
        except Exception as exc:
            log.warning("set_my_commands для админа chat_id=%s: %s", aid, exc)
