"""SQLite: период rate limit из настроек."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from bot.storage import Storage


def test_rate_limit_period_default_and_set():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.db"
        s = Storage(p, default_rate_limit_sec=7200, default_llm_max_output_chars=2400)
        assert s.get_rate_limit_period_sec() == 7200
        s.set_rate_limit_period_sec(300)
        assert s.get_rate_limit_period_sec() == 300
        s2 = Storage(p, default_rate_limit_sec=60, default_llm_max_output_chars=2400)
        assert s2.get_rate_limit_period_sec() == 300


def test_llm_max_output_chars_persisted():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.db"
        s = Storage(p, default_llm_max_output_chars=3000)
        assert s.get_llm_max_output_chars() == 3000
        s.set_llm_max_output_chars(1200)
        assert s.get_llm_max_output_chars() == 1200
        s2 = Storage(p, default_llm_max_output_chars=5000)
        assert s2.get_llm_max_output_chars() == 1200


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
