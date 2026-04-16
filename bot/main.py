"""Entry: long polling, handlers, logging."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.admin_keyboard import setup_bot_command_menus
from bot.config import Settings
from bot.discussion_cache import MemoryDiscussionTagStore, track_discussion_channel_mirror
from bot.group_mention_flow import handle_group_message
from bot.handlers import (
    cmd_add_whitelist,
    cmd_bot_off,
    cmd_bot_on,
    cmd_chat_id,
    cmd_get_hashtag,
    cmd_help_admin,
    cmd_hide_keyboard,
    cmd_list_whitelist,
    cmd_remove_whitelist,
    cmd_set_hashtag,
    cmd_set_llm_max_chars,
    cmd_set_rate_limit,
    cmd_start,
    cmd_status,
)
from bot.storage import Storage


def _telegram_http_timeouts() -> tuple[float, float, float]:
    """connect, read, write — сек. Загрузка фото требует больший write_timeout."""

    def _f(key: str, default: float) -> float:
        try:
            v = float(os.environ.get(key, str(default)))
            return max(5.0, min(300.0, v))
        except ValueError:
            return default

    return (
        _f("TELEGRAM_CONNECT_TIMEOUT", 15.0),
        _f("TELEGRAM_READ_TIMEOUT", 45.0),
        _f("TELEGRAM_WRITE_TIMEOUT", 180.0),
    )


def _setup_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        level=logging.INFO,
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _attach_discussion_cache(application: Application, settings: Settings) -> None:
    log = logging.getLogger(__name__)
    if settings.redis_url:
        from bot.redis_discussion_cache import RedisDiscussionTagStore

        store = RedisDiscussionTagStore(
            settings.redis_url, snippet_max=settings.discussion_snippet_max
        )
        await store.connect()
        application.bot_data["discussion_cache"] = store
        application.bot_data["_redis_discussion"] = store
        log.info("discussion_cache=redis")
    else:
        application.bot_data["discussion_cache"] = MemoryDiscussionTagStore(
            settings.discussion_snippet_max
        )
        log.info("discussion_cache=memory")


async def _post_init(application: Application) -> None:
    me = await application.bot.get_me()
    application.bot_data["bot_me"] = me
    log = logging.getLogger(__name__)
    log.info("Bot @%s (id=%s) — polling", me.username or "?", me.id)

    settings: Settings = application.bot_data["settings"]
    await _attach_discussion_cache(application, settings)
    await setup_bot_command_menus(application.bot, settings.admin_user_ids)


async def _post_shutdown(application: Application) -> None:
    rstore = application.bot_data.pop("_redis_discussion", None)
    if rstore is not None:
        await rstore.aclose()


async def _on_group_message(update, context):
    bd = context.application.bot_data
    await handle_group_message(
        update,
        context,
        bd["storage"],
        bd["assets_dir"],
        bd["mention_runtime"],
    )


def _register_handlers(
    application: Application,
    storage: Storage,
    admins: frozenset[int],
) -> None:
    async def wrap_start(u, c):
        await cmd_start(u, c, admins)

    async def wrap_help(u, c):
        await cmd_help_admin(u, c, admins)

    async def wrap_add(u, c):
        await cmd_add_whitelist(u, c, storage, admins)

    async def wrap_rem(u, c):
        await cmd_remove_whitelist(u, c, storage, admins)

    async def wrap_list(u, c):
        await cmd_list_whitelist(u, c, storage, admins)

    async def wrap_chat_id(u, c):
        await cmd_chat_id(u, c, admins)

    async def wrap_seth(u, c):
        await cmd_set_hashtag(u, c, storage, admins)

    async def wrap_geth(u, c):
        await cmd_get_hashtag(u, c, storage, admins)

    async def wrap_set_rl(u, c):
        await cmd_set_rate_limit(u, c, storage, admins)

    async def wrap_set_llm_ch(u, c):
        await cmd_set_llm_max_chars(u, c, storage, admins)

    async def wrap_on(u, c):
        await cmd_bot_on(u, c, storage, admins)

    async def wrap_off(u, c):
        await cmd_bot_off(u, c, storage, admins)

    async def wrap_status(u, c):
        await cmd_status(u, c, storage, admins)

    async def wrap_hide_kb(u, c):
        await cmd_hide_keyboard(u, c, admins)

    application.add_handler(CommandHandler("start", wrap_start))
    application.add_handler(CommandHandler("help_admin", wrap_help))
    application.add_handler(CommandHandler("add_whitelist", wrap_add))
    application.add_handler(CommandHandler("remove_whitelist", wrap_rem))
    application.add_handler(CommandHandler("list_whitelist", wrap_list))
    application.add_handler(CommandHandler("chat_id", wrap_chat_id))
    application.add_handler(CommandHandler("set_hashtag", wrap_seth))
    application.add_handler(CommandHandler("get_hashtag", wrap_geth))
    application.add_handler(CommandHandler("set_rate_limit", wrap_set_rl))
    application.add_handler(CommandHandler("set_llm_max_chars", wrap_set_llm_ch))
    application.add_handler(CommandHandler("bot_on", wrap_on))
    application.add_handler(CommandHandler("bot_off", wrap_off))
    application.add_handler(CommandHandler("status", wrap_status))
    application.add_handler(CommandHandler("hide_keyboard", wrap_hide_kb))

    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS, track_discussion_channel_mirror),
        group=-1,
    )
    group_filter = filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL & ~filters.COMMAND
    application.add_handler(MessageHandler(group_filter, _on_group_message))


def _fill_bot_data(
    application: Application,
    *,
    settings: Settings,
    storage: Storage,
    assets_dir: Path,
) -> None:
    application.bot_data["settings"] = settings
    application.bot_data["storage"] = storage
    application.bot_data["assets_dir"] = assets_dir
    application.bot_data["silent_reject"] = settings.silent_reject
    application.bot_data["log_rejections"] = settings.log_rejections
    application.bot_data["admin_ids"] = settings.admin_user_ids
    application.bot_data["local_llm"] = settings.local_llm
    application.bot_data["mention_runtime"] = settings.group_mention_runtime()
    # post_init подменит на Redis или оставит memory
    application.bot_data["discussion_cache"] = MemoryDiscussionTagStore(
        settings.discussion_snippet_max
    )


def main() -> None:
    _setup_logging()
    settings = Settings.from_env()
    storage = Storage(
        settings.sqlite_path,
        settings.default_rate_limit_sec,
        settings.local_llm.max_output_chars,
    )
    storage.seed_whitelist(settings.initial_whitelist_chat_ids)
    log = logging.getLogger(__name__)
    if not settings.admin_user_ids:
        log.warning("ADMIN_USER_IDS пуст: команды whitelist/hashtag будут недоступны.")
    if not storage.whitelist_list():
        log.warning(
            "Whitelist пуст: добавьте WHITELIST_CHAT_IDS в .env или /add_whitelist в группе."
        )

    assets_dir = Path(__file__).resolve().parent.parent / "assets" / "images"
    assets_dir.mkdir(parents=True, exist_ok=True)

    conn_t, read_t, write_t = _telegram_http_timeouts()
    application = (
        Application.builder()
        .token(settings.bot_token)
        .concurrent_updates(True)
        .connect_timeout(conn_t)
        .read_timeout(read_t)
        .write_timeout(write_t)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    _fill_bot_data(application, settings=settings, storage=storage, assets_dir=assets_dir)

    _register_handlers(application, storage, settings.admin_user_ids)

    application.run_polling(allowed_updates=Update.ALL_TYPES)
