"""Клавиатура админа: кнопки с префиксом /."""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from bot.admin_keyboard import admin_reply_keyboard


def test_admin_keyboard_buttons_are_commands():
    kb = admin_reply_keyboard()
    flat = [b.text for row in kb.keyboard for b in row]
    assert all(t.startswith("/") for t in flat)
    assert "/hide_keyboard" in flat
    assert "/status" in flat


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
