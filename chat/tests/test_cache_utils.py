import time
from utils.cache_utils import is_rate_limited

def test_rate_limit_basic():
    key = "test-rate-1"

    assert not is_rate_limited(key, limit_per_minute=2)
    assert not is_rate_limited(key, limit_per_minute=2)

    assert is_rate_limited(key, limit_per_minute=2)

def test_elo_extract():
    from utils.llm_utils import _extract_elo_range, _has_san_tokens
    assert _extract_elo_range("1200-1600") == (1200, 1600)
    assert _extract_elo_range("elo 1500") == (1300, 1700)
    assert _extract_elo_range("no elo") is None
    assert _has_san_tokens("e4 Nf3 O-O")
    assert not _has_san_tokens("analyze my game")
