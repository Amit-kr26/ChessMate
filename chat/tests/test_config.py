import os
from utils.config import get_settings

def test_settings_defaults():
    s = get_settings()
    assert s.index_name == os.getenv("INDEX_NAME", "chess-rag")
    assert s.elastic_url
    assert s.postgres_host

def test_settings_pydantic_fallback():

    s = get_settings()
    for attr in ["openai_model", "stockfish_path", "pgn_path", "cache_ttl_seconds"]:
        assert hasattr(s, attr)
