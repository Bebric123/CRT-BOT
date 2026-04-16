"""Load settings from environment."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from bot import defaults as D
from bot.image_moderation import ImageSafetyConfig

load_dotenv()


def _int_env(key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.environ.get(key, str(default)).strip())
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def _float_env(key: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.environ.get(key, str(default)).strip())
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def _resolve_image_moderation_provider() -> str:
    """
    none | sightengine | custom_url.
    auto: Sightengine, если заданы user+secret; иначе свой URL, если задан; иначе none.
    """
    prov = os.environ.get("IMAGE_MODERATION_PROVIDER", "auto").strip().lower()
    se_user = os.environ.get("SIGHTENGINE_API_USER", "").strip()
    se_secret = os.environ.get("SIGHTENGINE_API_SECRET", "").strip()
    safe_url = os.environ.get("SAFE_IMAGE_URL", "").strip()
    if prov in ("none", "off", "false", "0"):
        return "none"
    if prov == "sightengine":
        return "sightengine"
    if prov == "custom_url":
        return "custom_url" if safe_url else "none"
    if prov == "auto":
        if se_user and se_secret:
            return "sightengine"
        if safe_url:
            return "custom_url"
        return "none"
    return "none"


def _parse_text_blocklist(raw: str | None) -> frozenset[str]:
    if not raw or not raw.strip():
        return frozenset()
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def _parse_sightengine_text_reject_only(raw: str | None) -> frozenset[str] | None:
    """Пустая строка / отсутствует — любая detected_categories; непустая — только перечисленные."""
    if raw is None or not raw.strip():
        return None
    s = frozenset(p.strip().lower() for p in raw.split(",") if p.strip())
    return s if s else None


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
class TextModerationConfig:
    """Проверка текста предсказания перед отправкой."""

    enabled: bool
    """none | regex | llm | both"""
    mode: str
    blocklist_lower: frozenset[str]
    llm_timeout_sec: float
    llm_max_tokens: int
    """Подстроки по русскому мату (TEXT_MODERATION_RU_MAT, по умолчанию вкл.)."""
    ru_mat_heuristic: bool


def _local_llm_from_env() -> LocalLlmConfig:
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
        llm_max_chars = int(
            os.environ.get(
                "LOCAL_LLM_MAX_OUTPUT_CHARS", str(D.LOCAL_LLM_MAX_OUTPUT_CHARS_DEFAULT)
            ).strip()
        )
    except ValueError:
        llm_max_chars = D.LOCAL_LLM_MAX_OUTPUT_CHARS_DEFAULT
    llm_max_chars = max(
        D.LOCAL_LLM_MAX_OUTPUT_CHARS_MIN,
        min(D.LOCAL_LLM_MAX_OUTPUT_CHARS_MAX, llm_max_chars),
    )
    llm_post = os.environ.get("LOCAL_LLM_INCLUDE_POST", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    llm_sys = os.environ.get("LOCAL_LLM_SYSTEM_PROMPT", "").strip()
    llm_user = os.environ.get("LOCAL_LLM_USER_PROMPT", "").strip()
    return LocalLlmConfig(
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


def _image_safety_from_env() -> ImageSafetyConfig | None:
    img_on = os.environ.get("IMAGE_VALIDATION_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not img_on:
        return None
    try:
        safe_timeout = float(os.environ.get("SAFE_IMAGE_TIMEOUT", "15").strip())
    except ValueError:
        safe_timeout = 15.0
    safe_timeout = max(3.0, min(120.0, safe_timeout))
    mod_prov = _resolve_image_moderation_provider()
    se_u = os.environ.get("SIGHTENGINE_API_USER", "").strip()
    se_s = os.environ.get("SIGHTENGINE_API_SECRET", "").strip()
    safe_u = os.environ.get("SAFE_IMAGE_URL", "").strip()
    if mod_prov == "sightengine" and (not se_u or not se_s):
        logging.getLogger(__name__).warning(
            "IMAGE_MODERATION_PROVIDER=sightengine, но не заданы "
            "SIGHTENGINE_API_USER / SIGHTENGINE_API_SECRET — внешняя модерация отключена"
        )
        mod_prov = "none"
    if mod_prov == "custom_url" and not safe_u:
        mod_prov = "none"
    se_models_raw = os.environ.get("SIGHTENGINE_MODELS", "nudity-2.1").strip()
    se_text_cat = os.environ.get("SIGHTENGINE_TEXT_CATEGORIES", "").strip()
    se_has_text_model = "text-content" in se_models_raw.lower()
    se_wants_ru_text = bool(se_text_cat or se_has_text_model)
    se_opt_lang = os.environ.get("SIGHTENGINE_OPT_LANG", "").strip() or (
        "ru" if se_wants_ru_text else ""
    )
    se_append_ocr = se_wants_ru_text and os.environ.get(
        "SIGHTENGINE_APPEND_OCR", "1"
    ).strip().lower() not in ("0", "false", "no")
    se_moderate_severe = os.environ.get(
        "SIGHTENGINE_MODERATE_SEVERE", "1"
    ).strip().lower() not in ("0", "false", "no")
    se_def_severe_prob = 0.5 if se_moderate_severe else 1.0
    se_max_gore = _float_env(
        "SIGHTENGINE_MAX_GORE_PROB", se_def_severe_prob, 0.0, 1.0
    )
    se_max_self_harm = _float_env(
        "SIGHTENGINE_MAX_SELF_HARM_PROB", se_def_severe_prob, 0.0, 1.0
    )
    se_max_drug = _float_env(
        "SIGHTENGINE_MAX_RECREATIONAL_DRUG_PROB", se_def_severe_prob, 0.0, 1.0
    )
    return ImageSafetyConfig(
        max_file_bytes=_int_env(
            "IMAGE_MAX_FILE_BYTES",
            D.IMAGE_MAX_FILE_BYTES_DEFAULT,
            D.IMAGE_MAX_FILE_BYTES_MIN,
            D.IMAGE_MAX_FILE_BYTES_MAX,
        ),
        max_width=_int_env(
            "IMAGE_MAX_WIDTH",
            D.IMAGE_MAX_WIDTH_DEFAULT,
            D.IMAGE_MAX_DIMENSION_MIN,
            D.IMAGE_MAX_DIMENSION_MAX,
        ),
        max_height=_int_env(
            "IMAGE_MAX_HEIGHT",
            D.IMAGE_MAX_HEIGHT_DEFAULT,
            D.IMAGE_MAX_DIMENSION_MIN,
            D.IMAGE_MAX_DIMENSION_MAX,
        ),
        moderation_provider=mod_prov,
        safe_image_url=os.environ.get("SAFE_IMAGE_URL", "").strip(),
        safe_image_api_key=os.environ.get("SAFE_IMAGE_API_KEY", "").strip(),
        safe_image_timeout_sec=safe_timeout,
        sightengine_api_user=se_u,
        sightengine_api_secret=se_s,
        sightengine_models=se_models_raw,
        sightengine_max_raw=_float_env("SIGHTENGINE_MAX_RAW", 0.45, 0.05, 0.99),
        sightengine_max_sexual=_float_env("SIGHTENGINE_MAX_SEXUAL", 0.55, 0.05, 0.99),
        sightengine_max_alcohol_prob=_float_env(
            "SIGHTENGINE_MAX_ALCOHOL_PROB", 1.0, 0.0, 1.0
        ),
        sightengine_max_tobacco_prob=_float_env(
            "SIGHTENGINE_MAX_TOBACCO_PROB", 1.0, 0.0, 1.0
        ),
        sightengine_max_recreational_drug_prob=se_max_drug,
        sightengine_moderate_severe=se_moderate_severe,
        sightengine_max_gore_prob=se_max_gore,
        sightengine_max_self_harm_prob=se_max_self_harm,
        sightengine_text_categories=se_text_cat,
        sightengine_opt_lang=se_opt_lang,
        sightengine_image_text_reject_only=_parse_sightengine_text_reject_only(
            os.environ.get("SIGHTENGINE_IMAGE_TEXT_REJECT_ONLY")
        ),
        sightengine_append_ocr=se_append_ocr,
    )


def _text_moderation_from_env() -> TextModerationConfig:
    txt_mod_on = os.environ.get("TEXT_MODERATION_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    txt_mode = os.environ.get("TEXT_MODERATION_MODE", "both").strip().lower()
    if txt_mode not in ("none", "regex", "llm", "both"):
        txt_mode = "both"
    try:
        txt_llm_timeout = float(
            os.environ.get("TEXT_MODERATION_LLM_TIMEOUT", "20").strip()
        )
    except ValueError:
        txt_llm_timeout = 20.0
    txt_llm_timeout = max(3.0, min(120.0, txt_llm_timeout))
    txt_llm_max_tok = _int_env("TEXT_MODERATION_LLM_MAX_TOKENS", 96, 32, 256)
    txt_ru_mat = (
        txt_mod_on
        and os.environ.get("TEXT_MODERATION_RU_MAT", "1").strip().lower()
        not in ("0", "false", "no")
    )
    return TextModerationConfig(
        enabled=txt_mod_on,
        mode=txt_mode,
        blocklist_lower=_parse_text_blocklist(os.environ.get("TEXT_BLOCKLIST")),
        llm_timeout_sec=txt_llm_timeout,
        llm_max_tokens=txt_llm_max_tok,
        ru_mat_heuristic=txt_ru_mat,
    )


@dataclass(frozen=True)
class GroupMentionRuntime:
    """Параметры ответа в группах (без секретов токена)."""

    silent_reject: bool
    log_rejections: bool
    local_llm: LocalLlmConfig
    text_moderation: TextModerationConfig
    image_safety: ImageSafetyConfig | None
    image_max_side: int
    image_max_source_bytes: int


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_user_ids: frozenset[int]
    initial_whitelist_chat_ids: frozenset[int]
    sqlite_path: Path
    log_rejections: bool
    silent_reject: bool
    local_llm: LocalLlmConfig
    default_rate_limit_sec: int
    redis_url: str
    discussion_snippet_max: int
    image_max_side: int
    image_safety: ImageSafetyConfig | None
    text_moderation: TextModerationConfig

    def group_mention_runtime(self) -> GroupMentionRuntime:
        max_src = (
            self.image_safety.max_file_bytes
            if self.image_safety
            else D.IMAGE_MAX_SOURCE_BYTES_NO_SAFETY
        )
        return GroupMentionRuntime(
            silent_reject=self.silent_reject,
            log_rejections=self.log_rejections,
            local_llm=self.local_llm,
            text_moderation=self.text_moderation,
            image_safety=self.image_safety,
            image_max_side=self.image_max_side,
            image_max_source_bytes=max_src,
        )

    @classmethod
    def from_env(cls) -> Settings:
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required")

        db = os.environ.get("SQLITE_PATH", "data/bot.db").strip()
        sqlite_path = Path(db)
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        default_rate = _int_env(
            "RATE_LIMIT_SECONDS",
            D.RATE_LIMIT_SECONDS_DEFAULT,
            D.RATE_LIMIT_SECONDS_MIN,
            D.RATE_LIMIT_SECONDS_MAX,
        )
        redis_url = os.environ.get("REDIS_URL", "").strip()
        disc_snip = _int_env(
            "DISCUSSION_SNIPPET_MAX_CHARS",
            D.DISCUSSION_SNIPPET_MAX_CHARS_DEFAULT,
            D.DISCUSSION_SNIPPET_MAX_CHARS_MIN,
            D.DISCUSSION_SNIPPET_MAX_CHARS_MAX,
        )
        img_side = _int_env(
            "IMAGE_MAX_SIDE",
            D.IMAGE_MAX_SIDE_DEFAULT,
            D.IMAGE_MAX_SIDE_MIN,
            D.IMAGE_MAX_SIDE_MAX,
        )
        image_safety = _image_safety_from_env()
        local_llm = _local_llm_from_env()
        text_moderation = _text_moderation_from_env()

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
            default_rate_limit_sec=default_rate,
            redis_url=redis_url,
            discussion_snippet_max=disc_snip,
            image_max_side=img_side,
            image_safety=image_safety,
            text_moderation=text_moderation,
        )
