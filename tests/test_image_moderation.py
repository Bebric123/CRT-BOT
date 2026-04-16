from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from bot.image_moderation import sightengine_is_safe  # noqa: E402


def test_sightengine_safe_high_safe_score():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "safe": 0.99, "sexual_activity": 0.0, "sexual_display": 0.0},
    }
    assert sightengine_is_safe(body, max_raw=0.45, max_sexual=0.55) is True


def test_sightengine_reject_high_raw():
    body = {"status": "success", "nudity": {"raw": 0.9, "sexual_activity": 0.0, "sexual_display": 0.0}}
    assert sightengine_is_safe(body, max_raw=0.45, max_sexual=0.55) is False


def test_sightengine_reject_sexual_activity():
    body = {"status": "success", "nudity": {"raw": 0.1, "sexual_activity": 0.8, "sexual_display": 0.0}}
    assert sightengine_is_safe(body, max_raw=0.45, max_sexual=0.55) is False


def test_sightengine_non_success():
    assert sightengine_is_safe({"status": "failure"}, max_raw=0.45, max_sexual=0.55) is False


def test_sightengine_alcohol_tobacco_default_off():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "alcohol": {"prob": 0.99},
        "tobacco": {"prob": 0.9, "classes": {"regular_tobacco": 0.9}},
    }
    assert sightengine_is_safe(body, max_raw=0.45, max_sexual=0.55) is True


def test_sightengine_reject_alcohol_when_enabled():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "alcohol": {"prob": 0.8},
    }
    assert (
        sightengine_is_safe(
            body,
            max_raw=0.45,
            max_sexual=0.55,
            max_alcohol_prob=0.5,
        )
        is False
    )


def test_sightengine_no_nudity_block_still_checks_substances():
    body = {"status": "success", "tobacco": {"prob": 0.99}}
    assert (
        sightengine_is_safe(
            body,
            max_raw=0.45,
            max_sexual=0.55,
            max_tobacco_prob=0.5,
        )
        is False
    )


def test_sightengine_image_text_off_by_default():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "text": {"language": "ru", "detected_categories": ["insult"]},
    }
    assert sightengine_is_safe(body, max_raw=0.45, max_sexual=0.55) is True


def test_sightengine_reject_image_text_when_enabled():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "text": {"language": "ru", "detected_categories": ["insult"]},
    }
    assert (
        sightengine_is_safe(
            body,
            max_raw=0.45,
            max_sexual=0.55,
            expect_image_text_moderation=True,
        )
        is False
    )


def test_sightengine_image_text_filter_categories():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "text": {"detected_categories": ["phone_number"]},
    }
    assert (
        sightengine_is_safe(
            body,
            max_raw=0.45,
            max_sexual=0.55,
            expect_image_text_moderation=True,
            image_text_reject_only_categories=frozenset({"insult", "inappropriate"}),
        )
        is True
    )


def test_sightengine_reject_russian_mat_in_ocr_content():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "text": {"content": "схуяли", "detected_categories": []},
    }
    assert sightengine_is_safe(body, max_raw=0.45, max_sexual=0.55) is False


def test_sightengine_reject_mat_only_in_nested_detections():
    """Текст только во вложенных match — раньше могли пропустить без content."""
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "text": {
            "language": "ru",
            "detected_categories": [],
            "detections": {"insult": [{"match": "сука", "severity": "low"}]},
        },
    }
    assert sightengine_is_safe(body, max_raw=0.45, max_sexual=0.55) is False


def test_sightengine_reject_latin_mat_in_text_content():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "text": {"content": "fun suka meme", "detected_categories": []},
    }
    assert sightengine_is_safe(body, max_raw=0.45, max_sexual=0.55) is False


def test_sightengine_reject_gore_when_enabled():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "gore": {"prob": 0.9, "classes": {"very_bloody": 0.1}},
    }
    assert (
        sightengine_is_safe(
            body,
            max_raw=0.45,
            max_sexual=0.55,
            max_gore_prob=0.5,
        )
        is False
    )


def test_sightengine_reject_self_harm_when_enabled():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "self-harm": {"prob": 0.8, "type": {"real": 0.7, "fake": 0.0, "animated": 0.0}},
    }
    assert (
        sightengine_is_safe(
            body,
            max_raw=0.45,
            max_sexual=0.55,
            max_self_harm_prob=0.5,
        )
        is False
    )


def test_sightengine_reject_recreational_drug_separate_from_alcohol():
    body = {
        "status": "success",
        "nudity": {"raw": 0.01, "sexual_activity": 0.0, "sexual_display": 0.0},
        "recreational_drug": {"prob": 0.95, "classes": {"cannabis": 0.9}},
    }
    assert (
        sightengine_is_safe(
            body,
            max_raw=0.45,
            max_sexual=0.55,
            max_recreational_drug_prob=0.5,
        )
        is False
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
