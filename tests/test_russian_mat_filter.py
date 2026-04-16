from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from bot.russian_mat_filter import text_contains_russian_obscene  # noqa: E402


def test_detects_skhuyali():
    assert text_contains_russian_obscene("надпись схуяли на картинке") is True


def test_detects_pizd():
    assert text_contains_russian_obscene("какой пиздец день") is True


def test_clean_office_text():
    assert text_contains_russian_obscene("На неделе кофе окажется кстати.") is False


def test_pererbor_no_false_positive():
    assert text_contains_russian_obscene("перебор задач на неделе") is False


def test_detects_suka():
    assert text_contains_russian_obscene("текст сука на изображении") is True


def test_detects_latin_translit():
    assert text_contains_russian_obscene("OCR wrote: suka here") is True
    assert text_contains_russian_obscene("sign says blyat") is True


def test_homoglyph_latin_x_for_kh():
    assert text_contains_russian_obscene("graffiti xуй") is True
