"""Текст предсказания (шаблоны) + подготовка картинки из папки без текста на ней."""

from __future__ import annotations

import datetime
import io
import logging
import random
from pathlib import Path

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Запасной пул, если LLM недоступна: про рабочую неделю + уточнение под текущий день недели.
_PREDICTIONS_NEUTRAL_RU: list[str] = [
    "На этой рабочей неделе кофе окажется кстати в самые плотные часы: напиток сработает как тихий союзник, а дела постепенно сдадут позиции без лишней драмы. "
    "К середине недели ты поймёшь, что самые шумные задачи можно разложить по полочкам, если не пытаться съесть слона за один присест.",
    "Коллега на неделе случайно скажет то, что ты давно хотел услышать — может, это будет похвала, может, просто «да, давай так». "
    "Запомни момент и улыбнись: иногда неделя держится на таких маленьких человеческих совпадениях, а не только на календаре встреч.",
    "Одна встреча на неделе окажется короче планов, другая затянется, но не критично — в сумме неделя выровняется. "
    "Прими короткую встречу как подарок судьбы: лишние двадцать минут лучше потратить на воду, разминку или просто выдох.",
    "Ты найдёшь потерянный файл там, где его «точно не было», и поймёшь, что хаос в папках — это тоже система, просто пока без названия. "
    "К пятнице цифровой беспорядок чуть уступит, если не откладывать переименование «в последний момент».",
    "Эта рабочая неделя принесёт маленькую победу: закроешь задачу, которую откладывал, и почувствуешь, как груз со спины слезает хотя бы на сантиметр. "
    "Не обязательно кричать о победе — достаточно тихо отметить её для себя.",
    "Кто-то на неделе похвалит твою идею — не обязательно начальство, может, это будет человек из соседнего чата. Не скромничай: ты это заслужил, и лучше запомнить тон, в котором тебя поддержали.",
    "Техника подведёт один раз, но ты подстрахуешься и всё сохранишь — неделя научит ещё раз делать копии до, а не после. "
    "Пусть это будет скучный, но надёжный урок.",
    "К пятнице ты хотя бы раз скажешь «успел» и почувствуешь гордость без сарказма. Остальные дни могут быть обычными — для хорошей недели достаточно одного такого момента.",
    "План на неделе изменится, но в лучшую сторону: что-то отвалится, что-то приедет неожиданно, и гибкость окажется твоим супергероем без плаща. "
    "Главное — не цепляться за старый план из упрямства.",
    "К концу рабочей недели останется чуть больше спокойствия, чем в её начале ты ожидал: не потому что всё идеально, а потому что ты научишься чуть меньше тревожиться о том, что не подконтрольно.",
]

_PREDICTIONS_FOR_WEEKDAY_RU: dict[int, list[str]] = {
    0: [
        "Новая рабочая неделя начнётся спокойнее, чем ты боишься: расставь три главных дела — остальное подождёт.",
    ],
    1: [
        "Середина недели ещё впереди: маленькая награда за труд сегодня сделает остальные дни мягче.",
    ],
    2: [
        "Середина рабочей недели принесёт ясность: то, что казалось сложным, вдруг уляжется.",
    ],
    3: [
        "Вторая половина недели держит удачное совпадение: нужный человек окажется как раз вовремя.",
    ],
    4: [
        "Финиш рабочей недели близко — дотяни важное до вечера, потом заслуженный выдох.",
    ],
    5: [
        "Выходные не спрашивают отчётов — отпусти рабочее, чтобы следующая неделя встретила тебя свежее.",
    ],
    6: [
        "Воскресенье для перезагрузки: понедельник начнётся спокойнее, если сегодня не тащить задачи в голове.",
    ],
}


def pick_prediction() -> str:
    wd = datetime.date.today().weekday()
    pool = list(_PREDICTIONS_NEUTRAL_RU)
    pool.extend(_PREDICTIONS_FOR_WEEKDAY_RU.get(wd, []))
    return random.choice(pool)


def list_asset_image_paths(assets_dir: Path) -> list[Path]:
    """Все .png и .jpg из папки (стабильный порядок)."""
    return sorted(assets_dir.glob("*.png")) + sorted(assets_dir.glob("*.jpg"))


def load_random_image_path(assets_dir: Path) -> Path | None:
    files = list_asset_image_paths(assets_dir)
    return random.choice(files) if files else None


def image_path_to_png_bytes(
    path: Path,
    *,
    max_side: int = 900,
    max_source_file_bytes: int = 25 * 1024 * 1024,
) -> bytes | None:
    """Один файл: ресайз, PNG. None при ошибке или слишком большом исходнике."""
    try:
        sz = path.stat().st_size
    except OSError:
        return None
    if sz > max_source_file_bytes:
        logger.warning("skip large asset file %s (%s bytes)", path.name, sz)
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if getattr(im, "n_frames", 1) > 1:
                im.seek(0)
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
    except (OSError, ValueError, UnidentifiedImageError):
        logger.warning("skip unreadable asset file %s", path.name)
        return None


def load_random_image_png_bytes(
    assets_dir: Path | None,
    *,
    max_side: int = 900,
    max_source_file_bytes: int = 25 * 1024 * 1024,
) -> bytes | None:
    """Случайный файл из папки, ресайз, PNG."""
    if not assets_dir:
        return None
    path = load_random_image_path(assets_dir)
    if not path:
        return None
    return image_path_to_png_bytes(
        path,
        max_side=max_side,
        max_source_file_bytes=max_source_file_bytes,
    )


def split_for_photo_caption(text: str, limit: int = 1024) -> tuple[str, str | None]:
    """Telegram caption до limit символов; хвост для второго сообщения."""
    if len(text) <= limit:
        return text, None
    cut = text.rfind(" ", 0, limit)
    if cut < limit // 2:
        cut = limit
    head = text[:cut].rstrip()
    tail = text[cut:].lstrip()
    return head, tail if tail else None


def split_text_message_chunks(text: str, limit: int = 4096) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return chunks
