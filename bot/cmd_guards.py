"""Общие проверки для команд: админ, чат, сообщение."""

from __future__ import annotations

from telegram import Chat, Message, Update, User
from telegram.constants import ChatType


def admin_message_user(
    update: Update, admin_ids: frozenset[int]
) -> tuple[Message, User] | None:
    """Сообщение + пользователь, если оба есть и пользователь в admin_ids."""
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.id not in admin_ids:
        return None
    return msg, user


def admin_message_user_chat(
    update: Update, admin_ids: frozenset[int]
) -> tuple[Message, Chat, User] | None:
    """Как admin_message_user плюс чат (супергруппа/группа для whitelist-команд)."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user or user.id not in admin_ids:
        return None
    return msg, chat, user


def is_supergroup_or_group(chat: Chat) -> bool:
    return chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
