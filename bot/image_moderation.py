"""Проверка ассетов: размер/разрешение + модерация (Sightengine или свой URL)."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import httpx
from PIL import Image, UnidentifiedImageError

from bot.russian_mat_filter import text_contains_russian_obscene

logger = logging.getLogger(__name__)

SIGHTENGINE_CHECK_URL = "https://api.sightengine.com/1.0/check.json"


@dataclass(frozen=True)
class ImageSafetyConfig:
    max_file_bytes: int
    max_width: int
    max_height: int
    """none | sightengine | custom_url"""
    moderation_provider: str
    safe_image_url: str
    safe_image_api_key: str
    safe_image_timeout_sec: float
    sightengine_api_user: str
    sightengine_api_secret: str
    sightengine_models: str
    """Выше порога — отклонить (0…1, поле nudity.raw)."""
    sightengine_max_raw: float
    """Выше порога — отклонить по sexual_activity / sexual_display."""
    sightengine_max_sexual: float
    """Пороги alcohol / tobacco (модели в SIGHTENGINE_MODELS)."""
    sightengine_max_alcohol_prob: float
    sightengine_max_tobacco_prob: float
    """Наркотики: prob recreational_drug; при SIGHTENGINE_MODERATE_SEVERE модель подставляется автоматически."""
    sightengine_max_recreational_drug_prob: float
    """Автодобавление gore-2.0, self-harm, recreational_drug в запрос (кровь / самоповреждение / наркотики)."""
    sightengine_moderate_severe: bool
    sightengine_max_gore_prob: float
    sightengine_max_self_harm_prob: float
    """Для models=text-content-2.0: список категорий через запятую (дока Sightengine). Пусто — не слать."""
    sightengine_text_categories: str
    """ISO 639-1 через запятую, напр. ru — язык для правил OCR-текста на картинке."""
    sightengine_opt_lang: str
    """
    Если задано — отклонять только при пересечении с detected_categories (нижний регистр).
    None — отклонять при любой непустой detected_categories (когда text_categories заданы).
    """
    sightengine_image_text_reject_only: frozenset[str] | None
    """Добавить модель ocr в запрос (сырой text.content) для локальной проверки русского мата."""
    sightengine_append_ocr: bool


def _sightengine_prob_over(
    body: dict[str, object], key: str, max_prob: float
) -> bool:
    """True если блок модели есть и prob строго выше порога; max_prob>=1 — проверка выключена."""
    if max_prob >= 1.0:
        return False
    block = body.get(key)
    if not isinstance(block, dict):
        return False
    try:
        prob = float(block.get("prob") or 0.0)
    except (TypeError, ValueError):
        return False
    return prob > max_prob


def _deep_collect_strings_for_ru_scan(
    obj: object,
    out: list[str],
    *,
    _depth: int = 0,
    max_strings: int = 400,
    max_joined_len: int = 120_000,
) -> None:
    """Все строки под деревом text/ocr (content, match, поля регионов и т.д.)."""
    if _depth > 48 or len(out) >= max_strings:
        return
    if sum(len(s) for s in out) > max_joined_len:
        return
    if isinstance(obj, str):
        s = obj.strip()
        if len(s) >= 2:
            out.append(s)
    elif isinstance(obj, dict):
        for v in obj.values():
            _deep_collect_strings_for_ru_scan(
                v, out, _depth=_depth + 1, max_strings=max_strings, max_joined_len=max_joined_len
            )
    elif isinstance(obj, list):
        for item in obj:
            _deep_collect_strings_for_ru_scan(
                item, out, _depth=_depth + 1, max_strings=max_strings, max_joined_len=max_joined_len
            )


def _sightengine_text_blob_for_ru_scan(body: dict[str, object]) -> str:
    parts: list[str] = []
    for key in ("text", "ocr"):
        node = body.get(key)
        if isinstance(node, dict):
            _deep_collect_strings_for_ru_scan(node, parts)
        elif isinstance(node, str) and node.strip():
            parts.append(node.strip())
    return "\n".join(parts)


def _sightengine_russian_mat_in_response(body: dict[str, object]) -> bool:
    blob = _sightengine_text_blob_for_ru_scan(body)
    return bool(blob) and text_contains_russian_obscene(blob)


def _sightengine_nudity_unsafe(
    body: dict[str, object], *, max_raw: float, max_sexual: float
) -> bool:
    nudity = body.get("nudity")
    if not isinstance(nudity, dict):
        return False
    raw = float(nudity.get("raw") or 0)
    if raw > max_raw:
        return True
    sa = float(nudity.get("sexual_activity") or 0)
    sd = float(nudity.get("sexual_display") or 0)
    return max(sa, sd) > max_sexual


def _sightengine_alcohol_tobacco_unsafe(
    body: dict[str, object],
    *,
    max_alcohol_prob: float,
    max_tobacco_prob: float,
) -> bool:
    if _sightengine_prob_over(body, "alcohol", max_alcohol_prob):
        return True
    return _sightengine_prob_over(body, "tobacco", max_tobacco_prob)


def _sightengine_gore_selfharm_drug_unsafe(
    body: dict[str, object],
    *,
    max_gore_prob: float,
    max_self_harm_prob: float,
    max_recreational_drug_prob: float,
) -> bool:
    if _sightengine_prob_over(body, "gore", max_gore_prob):
        return True
    if _sightengine_prob_over(body, "self-harm", max_self_harm_prob):
        return True
    return _sightengine_prob_over(
        body, "recreational_drug", max_recreational_drug_prob
    )


def _sightengine_image_text_unsafe(
    body: dict[str, object],
    *,
    expect_image_text: bool,
    reject_only_categories: frozenset[str] | None,
) -> bool:
    """OCR + модерация текста на изображении (модель text-content-2.0)."""
    if not expect_image_text:
        return False
    text = body.get("text")
    if not isinstance(text, dict):
        return False
    cats = text.get("detected_categories")
    if not isinstance(cats, list) or not cats:
        return False
    norm = frozenset(str(c).strip().lower() for c in cats if c is not None and str(c).strip())
    if not norm:
        return False
    if reject_only_categories:
        return bool(norm & reject_only_categories)
    return True


def sightengine_is_safe(
    body: object,
    *,
    max_raw: float,
    max_sexual: float,
    max_alcohol_prob: float = 1.0,
    max_tobacco_prob: float = 1.0,
    max_recreational_drug_prob: float = 1.0,
    max_gore_prob: float = 1.0,
    max_self_harm_prob: float = 1.0,
    expect_image_text_moderation: bool = False,
    image_text_reject_only_categories: frozenset[str] | None = None,
) -> bool:
    """Разбор ответа Sightengine после status=success."""
    if not isinstance(body, dict):
        return False
    if body.get("status") != "success":
        return False
    if _sightengine_nudity_unsafe(body, max_raw=max_raw, max_sexual=max_sexual):
        return False
    if _sightengine_alcohol_tobacco_unsafe(
        body,
        max_alcohol_prob=max_alcohol_prob,
        max_tobacco_prob=max_tobacco_prob,
    ):
        return False
    if _sightengine_gore_selfharm_drug_unsafe(
        body,
        max_gore_prob=max_gore_prob,
        max_self_harm_prob=max_self_harm_prob,
        max_recreational_drug_prob=max_recreational_drug_prob,
    ):
        return False
    if _sightengine_image_text_unsafe(
        body,
        expect_image_text=expect_image_text_moderation,
        reject_only_categories=image_text_reject_only_categories,
    ):
        return False
    if _sightengine_russian_mat_in_response(body):
        return False
    return True


async def validate_image_for_send(
    raw_bytes: bytes,
    *,
    config: ImageSafetyConfig | None,
) -> tuple[bool, str | None]:
    """
    Возвращает (ok, reason_key).
    reason_key: too_large, bad_image, dimensions, moderation_reject, moderation_error
    """
    if not raw_bytes:
        return False, "bad_image"
    try:
        with Image.open(io.BytesIO(raw_bytes)) as im:
            im.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return False, "bad_image"
    if config is None:
        return True, None
    if len(raw_bytes) > config.max_file_bytes:
        return False, "too_large"
    try:
        with Image.open(io.BytesIO(raw_bytes)) as im:
            im = im.convert("RGB")
            w, h = im.size
    except (UnidentifiedImageError, OSError, ValueError):
        return False, "bad_image"
    if w > config.max_width or h > config.max_height:
        return False, "dimensions"

    prov = (config.moderation_provider or "none").strip().lower()
    if prov == "sightengine":
        ok, err = await _sightengine_check(raw_bytes, config)
        if not ok:
            return False, err or "moderation_error"
    elif prov == "custom_url" and config.safe_image_url.strip():
        ok, err = await _remote_safe_check(raw_bytes, config)
        if not ok:
            return False, err or "moderation_error"
    return True, None


_SEVERE_MODELS: tuple[str, ...] = ("gore-2.0", "self-harm", "recreational_drug")


def _sightengine_models_for_request(config: ImageSafetyConfig) -> str:
    models = (config.sightengine_models or "nudity-2.1").strip() or "nudity-2.1"
    parts = [p.strip() for p in models.split(",") if p.strip()]
    if config.sightengine_append_ocr and "ocr" not in parts:
        parts.append("ocr")
    if _sightengine_needs_severe_models(config):
        lowered = {p.lower() for p in parts}
        for m in _SEVERE_MODELS:
            if m.lower() not in lowered:
                parts.append(m)
                lowered.add(m.lower())
    return ",".join(parts) if parts else "nudity-2.1"


def _sightengine_needs_severe_models(config: ImageSafetyConfig) -> bool:
    if config.sightengine_moderate_severe:
        return True
    return (
        config.sightengine_max_gore_prob < 1.0
        or config.sightengine_max_self_harm_prob < 1.0
        or config.sightengine_max_recreational_drug_prob < 1.0
    )


def _sightengine_form_fields(config: ImageSafetyConfig) -> dict[str, str]:
    user = (config.sightengine_api_user or "").strip()
    secret = (config.sightengine_api_secret or "").strip()
    form: dict[str, str] = {
        "api_user": user,
        "api_secret": secret,
        "models": _sightengine_models_for_request(config),
    }
    tc = (config.sightengine_text_categories or "").strip()
    if tc:
        form["text_categories"] = tc
    ol = (config.sightengine_opt_lang or "").strip()
    if ol:
        form["opt_lang"] = ol
    return form


async def _sightengine_post_json(
    data: bytes, config: ImageSafetyConfig
) -> dict[str, object] | None:
    form = _sightengine_form_fields(config)
    if not form.get("api_user") or not form.get("api_secret"):
        logger.error(
            "sightengine: задан провайдер, но нет SIGHTENGINE_API_USER / SIGHTENGINE_API_SECRET"
        )
        return None
    try:
        async with httpx.AsyncClient(timeout=config.safe_image_timeout_sec) as client:
            r = await client.post(
                SIGHTENGINE_CHECK_URL,
                data=form,
                files={"media": ("image.png", data, "image/png")},
            )
        r.raise_for_status()
        body = r.json()
    except Exception:
        logger.exception("sightengine request failed")
        return None
    if not isinstance(body, dict):
        return None
    if body.get("error"):
        logger.warning("sightengine api error: %s", body.get("error"))
        return None
    return body


async def _sightengine_check(data: bytes, config: ImageSafetyConfig) -> tuple[bool, str | None]:
    body = await _sightengine_post_json(data, config)
    if body is None:
        return False, "moderation_error"
    expect_txt = bool((config.sightengine_text_categories or "").strip())
    if not sightengine_is_safe(
        body,
        max_raw=config.sightengine_max_raw,
        max_sexual=config.sightengine_max_sexual,
        max_alcohol_prob=config.sightengine_max_alcohol_prob,
        max_tobacco_prob=config.sightengine_max_tobacco_prob,
        max_recreational_drug_prob=config.sightengine_max_recreational_drug_prob,
        max_gore_prob=config.sightengine_max_gore_prob,
        max_self_harm_prob=config.sightengine_max_self_harm_prob,
        expect_image_text_moderation=expect_txt,
        image_text_reject_only_categories=config.sightengine_image_text_reject_only,
    ):
        return False, "moderation_reject"
    return True, None


async def _remote_safe_check(data: bytes, config: ImageSafetyConfig) -> tuple[bool, str | None]:
    """POST multipart; ожидается JSON с полем safe или ok == true."""
    headers = {}
    if config.safe_image_api_key:
        headers["Authorization"] = f"Bearer {config.safe_image_api_key}"
    try:
        async with httpx.AsyncClient(timeout=config.safe_image_timeout_sec) as client:
            r = await client.post(
                config.safe_image_url.strip(),
                files={"image": ("probe.png", data, "image/png")},
                headers=headers or None,
            )
        r.raise_for_status()
        body = r.json()
    except Exception:
        logger.exception("safe_image_url request failed")
        return False, "moderation_error"
    if isinstance(body, dict):
        if body.get("safe") is True or body.get("ok") is True:
            return True, None
        if body.get("safe") is False or body.get("ok") is False:
            return False, "moderation_reject"
    return False, "moderation_error"
