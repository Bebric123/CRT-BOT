"""Генерация текста предсказания через локальную LLM (OpenAI-compatible или Ollama)."""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)

_MONTHS_GEN_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def today_context_ru(d: datetime.date | None = None) -> str:
    """Текущая дата по-русски (часовой пояс сервера бота), для привязки к рабочей неделе."""
    day = d or datetime.date.today()
    wd = _WEEKDAYS_RU[day.weekday()]
    month = _MONTHS_GEN_RU[day.month - 1]
    return f"{wd}, {day.day} {month} {day.year} года"


DEFAULT_SYSTEM_PROMPT = """Ты генерируешь развёрнутое развлекательное предсказание на РАБОЧУЮ НЕДЕЛЮ (понедельник–пятница как цикл офиса и задач) для подписчиков Telegram-канала.
Предсказание охватывает неделю целиком или её ближайшую часть — не про один только «сегодня». Учитывай, на какой день недели приходится запрос (старт, середина, финиш недели или выходные перед следующей неделей).
Тон: лёгкий, дружелюбный юмор про офис и будни, без язвительности в адрес конкретных людей. Можно добавить маленькую «сценку», бытовую деталь или ироничный поворот — но без воды и повторов одной мысли.
Строго запрещено: мат и грубая лексика, алкоголь, сигареты и вейпы, наркотики, секс и откровенный контент, насилие, политика, оскорбления социальных групп.
Текст может быть автоматически отклонён модерацией — не нарушай эти правила даже в ироничной форме.
Объём: примерно 5–9 предложений на русском (или один связный абзац примерно на 130–220 слов). Без нумерованных списков и хештегов.
Выведи только текст предсказания, без вступлений («Вот предсказание», «Конечно» и т.п.)."""

DEFAULT_USER_PROMPT = (
    "Сгенерируй новое уникальное, достаточно подробное предсказание на текущую рабочую неделю — не одной фразой, а развёрнуто. "
    "Учитывай день недели: в будни — про задачи, встречи и коллег; ближе к пятнице — про финиш недели; в выходные — про отдых и мягкий настрой на следующую неделю. "
    "Не используй штампы вроде «звёзды говорят»."
)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _normalize_prediction(raw: str, max_len: int) -> str | None:
    t = _strip_fences(raw)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) < 40:
        return None
    if len(t) > max_len:
        t = t[: max_len - 1].rsplit(" ", 1)[0] + "…"
    return t


def _build_prediction_user_prompt(
    *,
    user_prompt: str,
    post_context: str | None,
) -> str:
    sys_p = user_prompt.strip() if user_prompt.strip() else DEFAULT_USER_PROMPT
    ctx_day = today_context_ru()
    usr = (
        f"{sys_p}\n\n"
        f"Календарь для ориентира: сегодня {ctx_day}. "
        f"Нужно предсказание именно на эту рабочую неделю (не на один день): "
        f"охватывай неделю целиком или оставшиеся до воскресенья будни, выходные — в контексте отдыха и следующей недели."
    )
    if post_context and post_context.strip():
        snippet = post_context.strip()[:500]
        usr = f"{usr}\n\nНастроение поста в канале (не цитируй дословно, только для тона):\n{snippet}"
    return usr


async def _prediction_llm_ollama(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
) -> str | None:
    url = base_url.rstrip("/") + "/api/chat"
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    r = await client.post(url, json=body)
    r.raise_for_status()
    data = r.json()
    msg = data.get("message") or {}
    content = msg.get("content") or data.get("response") or ""
    return content if isinstance(content, str) else None


async def _prediction_llm_openai(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
) -> str | None:
    url = base_url.rstrip("/") + "/chat/completions"
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = await client.post(url, json=body, headers=headers)
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        logger.warning("local_llm: empty choices: %s", data)
        return None
    msg = choices[0].get("message") or {}
    content = msg.get("content") or ""
    return content if isinstance(content, str) else None


async def generate_prediction_via_local_llm(
    *,
    backend: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float,
    temperature: float,
    max_tokens: int,
    max_output_chars: int,
    system_prompt: str,
    user_prompt: str,
    post_context: str | None,
) -> str | None:
    """
    backend: openai | ollama
    base_url: openai → http://127.0.0.1:1234/v1 ; ollama → http://127.0.0.1:11434
    """
    sys_p = system_prompt.strip() if system_prompt.strip() else DEFAULT_SYSTEM_PROMPT
    usr = _build_prediction_user_prompt(
        user_prompt=user_prompt,
        post_context=post_context,
    )
    b = (backend or "openai").lower().strip()
    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
            if b == "ollama":
                content = await _prediction_llm_ollama(
                    client,
                    base_url=base_url,
                    model=model,
                    system_prompt=sys_p,
                    user_message=usr,
                    temperature=temperature,
                )
            else:
                content = await _prediction_llm_openai(
                    client,
                    base_url=base_url,
                    model=model,
                    api_key=api_key,
                    system_prompt=sys_p,
                    user_message=usr,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            if content is None:
                return None
            return _normalize_prediction(content, max_output_chars)
    except httpx.HTTPError as e:
        logger.warning("local_llm HTTP error: %s", e)
        return None
    except Exception:
        logger.exception("local_llm unexpected error")
        return None
