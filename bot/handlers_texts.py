"""Тексты ответов команд (вынесены из handlers для коротких обработчиков)."""

from __future__ import annotations

from bot.defaults import (
    LOCAL_LLM_MAX_OUTPUT_CHARS_MAX,
    LOCAL_LLM_MAX_OUTPUT_CHARS_MIN,
    RATE_LIMIT_SECONDS_MAX,
    RATE_LIMIT_SECONDS_MIN,
)


def start_message_body(*, admin_in_private: bool) -> str:
    base = (
        "Бот предсказаний на рабочую неделю.\n"
        "В комментариях под постом канала (чат обсуждения) упомяни бота и хештег должен быть у этого поста. "
        "В группах с темами — комментарий в теме поста; иначе можно ответить на копию поста в чате.\n"
        "Админы: /help_admin"
    )
    if admin_in_private:
        base += (
            "\n\nВ личке с ботом у тебя есть кнопки команд и расширенное меню «/» у поля ввода. "
            "Скрыть кнопки: /hide_keyboard."
        )
    return base


def help_admin_message_body() -> str:
    return (
        "Команды (только для админов):\n"
        "/add_whitelist — в группе: добавить этот чат в whitelist\n"
        "/remove_whitelist — убрать чат\n"
        "/list_whitelist — список chat_id\n"
        "/chat_id — id текущего чата (проверка для группы обсуждения)\n"
        "/set_hashtag #тег — триггер в тексте поста\n"
        "/get_hashtag\n"
        f"/set_rate_limit <сек> — пауза между предсказаниями одному пользователю "
        f"({RATE_LIMIT_SECONDS_MIN}…{RATE_LIMIT_SECONDS_MAX})\n"
        f"/set_llm_max_chars <n> — лимит символов ответа LLM "
        f"({LOCAL_LLM_MAX_OUTPUT_CHARS_MIN}…{LOCAL_LLM_MAX_OUTPUT_CHARS_MAX}), без аргумента — текущее\n"
        "/bot_on /bot_off — включить и выключить ответы\n"
        "/status\n"
        "/hide_keyboard — убрать кнопки внизу (в личке)"
    )


def status_message_body(
    *,
    enabled: bool,
    hashtag: str,
    rate_limit_sec: int,
    llm_max_output_chars: int,
    whitelist_count: int,
) -> str:
    return (
        f"enabled={enabled}\nhashtag={hashtag}\n"
        f"rate_limit_sec={rate_limit_sec}\n"
        f"llm_max_output_chars={llm_max_output_chars}\n"
        f"whitelist_count={whitelist_count}"
    )
