"""Модерация текста предсказания перед отправкой: блоклист и/или запрос к локальной LLM."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from bot.config import LocalLlmConfig, TextModerationConfig
from bot.russian_mat_filter import text_contains_russian_obscene

logger = logging.getLogger(__name__)

_MOD_SYSTEM = """Ты модератор публичного Telegram-бота. Ниже текст ответа бота пользователю.
Отклонить (ok:false), если есть: нецензурная брань, оскорбления социальных групп, угрозы, призывы к насилию или наркотикам, откровенный сексуальный контент, экстремизм, политическая агитация, дискриминация.
Особенно внимательно к русскому мату и эвфемизмам: корни и производные (в т.ч. «схуяли», «нахрен», «пох», завуалированная брань, латиница вместо кириллицы в мате).
Допустимы: лёгкий дружелюбный юмор про офис и будни, нейтральные формулировки.
Ответь ТОЛЬКО одним JSON-объектом без пояснений: {"ok":true} или {"ok":false}."""


def _blocklist_hit(text: str, fragments: frozenset[str]) -> bool:
    if not fragments:
        return False
    low = text.lower()
    return any(f in low for f in fragments if f)


def _parse_ok_from_llm_response(content: str) -> bool | None:
    """True/False/None если не удалось разобрать."""
    t = (content or "").strip()
    if not t:
        return None
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{[^{}]*\}", t)
        if not m:
            return None
        try:
            obj = json.loads(m.group())
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict):
        return None
    if obj.get("ok") is True:
        return True
    if obj.get("ok") is False:
        return False
    return None


async def _moderation_llm_content_ollama(
    client: httpx.AsyncClient,
    *,
    llm: LocalLlmConfig,
    sample: str,
    max_tok: int,
) -> str | None:
    url = llm.base_url.rstrip("/") + "/api/chat"
    body: dict[str, Any] = {
        "model": llm.model,
        "messages": [
            {"role": "system", "content": _MOD_SYSTEM},
            {"role": "user", "content": sample},
        ],
        "stream": False,
        "options": {"temperature": 0.05, "num_predict": max_tok},
    }
    r = await client.post(url, json=body)
    r.raise_for_status()
    data = r.json()
    msg = data.get("message") or {}
    content = msg.get("content") or data.get("response") or ""
    return content if isinstance(content, str) else None


async def _moderation_llm_content_openai(
    client: httpx.AsyncClient,
    *,
    llm: LocalLlmConfig,
    sample: str,
    max_tok: int,
) -> str | None:
    url = llm.base_url.rstrip("/") + "/chat/completions"
    headers: dict[str, str] = {}
    if llm.api_key:
        headers["Authorization"] = f"Bearer {llm.api_key}"
    body = {
        "model": llm.model,
        "messages": [
            {"role": "system", "content": _MOD_SYSTEM},
            {"role": "user", "content": sample},
        ],
        "temperature": 0.05,
        "max_tokens": max_tok,
    }
    r = await client.post(url, json=body, headers=headers)
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        return None
    msg = choices[0].get("message") or {}
    content = msg.get("content") or ""
    return content if isinstance(content, str) else None


async def _llm_text_safe(text: str, llm: LocalLlmConfig, cfg: TextModerationConfig) -> bool | None:
    """None — сеть/парсинг; True — можно; False — отклонить."""
    if not llm.enabled:
        return None
    sample = text.strip()[:4000]
    if not sample:
        return True
    b = (llm.backend or "openai").lower().strip()
    timeout = min(max(3.0, cfg.llm_timeout_sec), 120.0)
    max_tok = max(16, min(256, cfg.llm_max_tokens))
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            if b == "ollama":
                content = await _moderation_llm_content_ollama(
                    client, llm=llm, sample=sample, max_tok=max_tok
                )
            else:
                content = await _moderation_llm_content_openai(
                    client, llm=llm, sample=sample, max_tok=max_tok
                )
            if content is None:
                return None
            return _parse_ok_from_llm_response(content)
    except httpx.HTTPError as e:
        logger.warning("text moderation LLM HTTP: %s", e)
        return None
    except Exception:
        logger.exception("text moderation LLM error")
        return None


async def moderate_prediction_text(
    text: str,
    cfg: TextModerationConfig,
    llm: LocalLlmConfig,
) -> tuple[bool, str | None]:
    """
    (True, None) — пускать.
    (False, reason) — заменить на запасной текст (blocklist / llm).
    """
    if not cfg.enabled:
        return True, None
    mode = (cfg.mode or "none").strip().lower()
    if mode == "none":
        return True, None

    if cfg.ru_mat_heuristic and text_contains_russian_obscene(text):
        return False, "text_ru_mat"

    if mode in ("regex", "both"):
        if _blocklist_hit(text, cfg.blocklist_lower):
            return False, "text_blocklist"

    if mode in ("llm", "both"):
        verdict = await _llm_text_safe(text, llm, cfg)
        if verdict is False:
            return False, "text_llm_reject"
        if verdict is None and mode == "llm":
            # Только LLM, ответ не получен — не блокируем из-за инфраструктуры
            logger.warning("text moderation: LLM недоступен, пропускаем проверку")
            return True, None
        if verdict is None and mode == "both":
            # При both без ответа LLM — блоклист уже пройден; осторожно пропускаем
            logger.warning("text moderation: LLM не вернул вердикт, пропускаем LLM-шаг")
            return True, None

    return True, None


def parse_moderation_llm_verdict(content: str) -> bool | None:
    """Разбор JSON из ответа модели-модератора (для тестов)."""
    return _parse_ok_from_llm_response(content)
