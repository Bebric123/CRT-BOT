"""Проверка файлов в assets/images тем же пайплайном, что и перед отправкой (Pillow + модерация из .env)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from dotenv import load_dotenv


async def _main() -> int:
    env_path = _root / ".env"
    if env_path.is_file():
        load_dotenv(env_path)
    else:
        load_dotenv()

    from bot.config import _image_safety_from_env
    from bot.image_moderation import validate_image_for_send

    cfg = _image_safety_from_env()
    images_dir = _root / "assets" / "images"
    if not images_dir.is_dir():
        print("Нет каталога:", images_dir)
        return 1

    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    errors = 0
    checked = 0
    for path in sorted(images_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        checked += 1
        raw = path.read_bytes()
        ok, reason = await validate_image_for_send(raw, config=cfg)
        if ok:
            print("OK", path.name)
        else:
            errors += 1
            print("FAIL", path.name, reason or "?")

    if not checked:
        print("Нет изображений с расширениями", exts)
        return 0
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
