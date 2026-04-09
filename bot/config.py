"""Load settings from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _parse_int_list(raw: str | None) -> list[int]:
    if not raw or not raw.strip():
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip().strip("`").strip("'").strip('"')
        if not part:
            continue
        out.append(int(part))
    return out


@dataclass(frozen=True)
class LocalLlmConfig:
    """Параметры HTTP-доступа к локальной модели (OpenAI-compatible или Ollama /api/chat)."""

    enabled: bool
    backend: str
    base_url: str
    model: str
    api_key: str
    timeout_sec: float
    temperature: float
    max_tokens: int
    max_output_chars: int
    include_post: bool
    system_prompt: str
    user_prompt: str


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_user_ids: frozenset[int]
    initial_whitelist_chat_ids: frozenset[int]
    sqlite_path: Path
    log_rejections: bool
    silent_reject: bool
    local_llm: LocalLlmConfig

    @classmethod
    def from_env(cls) -> Settings:
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required")

        db = os.environ.get("SQLITE_PATH", "data/bot.db").strip()
        sqlite_path = Path(db)
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        llm_on = os.environ.get("LOCAL_LLM_ENABLED", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        llm_backend = os.environ.get("LOCAL_LLM_BACKEND", "openai").strip().lower()
        if llm_backend not in ("openai", "ollama"):
            llm_backend = "openai"
        llm_base = os.environ.get(
            "LOCAL_LLM_BASE_URL", "http://127.0.0.1:1234/v1"
        ).strip()
        if llm_backend == "ollama" and llm_base.rstrip("/").endswith("/v1"):
            llm_base = llm_base.rstrip("/")[:-3] or "http://127.0.0.1:11434"
        llm_model = os.environ.get("LOCAL_LLM_MODEL", "llama3.2").strip()
        llm_key = os.environ.get("LOCAL_LLM_API_KEY", "").strip()
        try:
            llm_timeout = float(os.environ.get("LOCAL_LLM_TIMEOUT", "90").strip())
        except ValueError:
            llm_timeout = 90.0
        llm_timeout = max(5.0, min(600.0, llm_timeout))
        try:
            llm_temp = float(os.environ.get("LOCAL_LLM_TEMPERATURE", "0.85").strip())
        except ValueError:
            llm_temp = 0.85
        llm_temp = max(0.0, min(2.0, llm_temp))
        try:
            llm_max_tok = int(os.environ.get("LOCAL_LLM_MAX_TOKENS", "768").strip())
        except ValueError:
            llm_max_tok = 768
        llm_max_tok = max(64, min(8192, llm_max_tok))
        try:
            llm_max_chars = int(os.environ.get("LOCAL_LLM_MAX_OUTPUT_CHARS", "2400").strip())
        except ValueError:
            llm_max_chars = 2400
        llm_max_chars = max(200, min(8000, llm_max_chars))
        llm_post = os.environ.get("LOCAL_LLM_INCLUDE_POST", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        llm_sys = os.environ.get("LOCAL_LLM_SYSTEM_PROMPT", "").strip()
        llm_user = os.environ.get("LOCAL_LLM_USER_PROMPT", "").strip()

        local_llm = LocalLlmConfig(
            enabled=llm_on,
            backend=llm_backend,
            base_url=llm_base,
            model=llm_model,
            api_key=llm_key,
            timeout_sec=llm_timeout,
            temperature=llm_temp,
            max_tokens=llm_max_tok,
            max_output_chars=llm_max_chars,
            include_post=llm_post,
            system_prompt=llm_sys,
            user_prompt=llm_user,
        )

        return cls(
            bot_token=token,
            admin_user_ids=frozenset(_parse_int_list(os.environ.get("ADMIN_USER_IDS"))),
            initial_whitelist_chat_ids=frozenset(
                _parse_int_list(os.environ.get("WHITELIST_CHAT_IDS"))
            ),
            sqlite_path=sqlite_path,
            log_rejections=os.environ.get("LOG_REJECTIONS", "1").strip().lower()
            not in ("0", "false", "no"),
            silent_reject=os.environ.get("SILENT_REJECT", "0").strip().lower()
            in ("1", "true", "yes"),
            local_llm=local_llm,
        )
