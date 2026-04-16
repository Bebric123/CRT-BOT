from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from bot.config import LocalLlmConfig, TextModerationConfig  # noqa: E402
from bot.text_moderation import (  # noqa: E402
    moderate_prediction_text,
    parse_moderation_llm_verdict,
)


def test_parse_moderation_true_false():
    assert parse_moderation_llm_verdict('{"ok": true}') is True
    assert parse_moderation_llm_verdict('{"ok": false}') is False
    assert parse_moderation_llm_verdict('```json\n{"ok": true}\n```') is True


def test_blocklist_rejects():
    cfg = TextModerationConfig(
        enabled=True,
        mode="regex",
        blocklist_lower=frozenset({"плохоеслово"}),
        llm_timeout_sec=10.0,
        llm_max_tokens=64,
        ru_mat_heuristic=False,
    )
    llm = LocalLlmConfig(
        enabled=False,
        backend="openai",
        base_url="http://x",
        model="m",
        api_key="",
        timeout_sec=1.0,
        temperature=0.0,
        max_tokens=10,
        max_output_chars=100,
        include_post=False,
        system_prompt="",
        user_prompt="",
    )
    ok, reason = asyncio.run(moderate_prediction_text("чистый текст", cfg, llm))
    assert ok is True and reason is None
    ok2, reason2 = asyncio.run(
        moderate_prediction_text("тут ПЛОХОЕСЛОВО в тексте", cfg, llm)
    )
    assert ok2 is False and reason2 == "text_blocklist"


def test_ru_mat_heuristic_rejects_before_llm():
    cfg = TextModerationConfig(
        enabled=True,
        mode="llm",
        blocklist_lower=frozenset(),
        llm_timeout_sec=10.0,
        llm_max_tokens=64,
        ru_mat_heuristic=True,
    )
    llm = LocalLlmConfig(
        enabled=False,
        backend="openai",
        base_url="http://x",
        model="m",
        api_key="",
        timeout_sec=1.0,
        temperature=0.0,
        max_tokens=10,
        max_output_chars=100,
        include_post=False,
        system_prompt="",
        user_prompt="",
    )
    ok, reason = asyncio.run(moderate_prediction_text("и схуяли на русском", cfg, llm))
    assert ok is False and reason == "text_ru_mat"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
