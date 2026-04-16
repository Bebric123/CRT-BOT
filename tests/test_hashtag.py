"""Триггер-хештег: целое слово, не подстрока."""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from bot.hashtag import text_has_trigger_hashtag


def test_exact_hashtag():
    assert text_has_trigger_hashtag("пост #predict_week тут", "#predict_week") is True


def test_longer_tag_not_triggered():
    assert text_has_trigger_hashtag("пост #predict_weekly тут", "#predict_week") is False


def test_prefix_false_positive_avoided():
    assert text_has_trigger_hashtag("xx#predict_week yy", "#predict_week") is False


def test_implicit_hash_prefix_in_config():
    """В настройках можно передать без # — нормализуется."""
    assert text_has_trigger_hashtag("тег #foo bar", "foo") is True


def test_multiple_occurrences():
    body = "a #predict_week b #predict_week c"
    assert text_has_trigger_hashtag(body, "#predict_week") is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
