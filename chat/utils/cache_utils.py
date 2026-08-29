import hashlib
import logging
import threading
import time
from functools import wraps
from typing import Any, Optional

from utils.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

try:
    from cachetools import TTLCache

    HAS_CACHETOOLS = True
except ImportError:
    HAS_CACHETOOLS = False
    TTLCache = dict

try:
    import redis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    redis = None


def _hash_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


if HAS_CACHETOOLS:
    _es_cache = TTLCache(
        maxsize=getattr(settings, "cache_max_entries", 200),
        ttl=getattr(settings, "cache_ttl_seconds", 3600),
    )
    _llm_cache = TTLCache(maxsize=100, ttl=7 * 24 * 3600)
    _emb_cache = TTLCache(maxsize=200, ttl=24 * 3600)
else:

    _es_cache = {}
    _llm_cache = {}
    _emb_cache = {}
    _es_expiry = {}
    _llm_expiry = {}

_es_lock = threading.Lock()
_llm_lock = threading.Lock()
_collapse_locks: dict[str, threading.Lock] = {}
_collapse_global = threading.Lock()

_redis_client = None
if HAS_REDIS and getattr(settings, "redis_url", ""):
    try:
        _redis_client = redis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=2
        )
        _redis_client.ping()
        logger.info("Redis cache connected at %s", settings.redis_url[:30])
    except Exception as e:
        logger.warning("Redis unavailable (%s); using in-process cache", e)
        _redis_client = None


def _get_collapse_lock(key: str) -> threading.Lock:
    with _collapse_global:
        if key not in _collapse_locks:
            _collapse_locks[key] = threading.Lock()
        return _collapse_locks[key]


def _cache_get(cache, key: str, expiry_map: Optional[dict] = None) -> Optional[Any]:
    if HAS_CACHETOOLS:
        try:
            return cache[key]
        except KeyError:
            return None
    else:
        if expiry_map is None:
            return cache.get(key)
        exp = expiry_map.get(key, 0)
        if time.time() > exp:
            cache.pop(key, None)
            expiry_map.pop(key, None)
            return None
        return cache.get(key)


def _cache_set(
    cache, key: str, value: Any, ttl: int, expiry_map: Optional[dict] = None
):
    if HAS_CACHETOOLS:
        cache[key] = value
    else:
        cache[key] = value
        if expiry_map is not None:
            expiry_map[key] = time.time() + ttl


def get_es_cache(query: str) -> Optional[list]:
    """Lookup ES results by query hash."""

    if _redis_client:
        try:
            import json

            raw = _redis_client.get(f"cache:es:{_hash_key(query)}")
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug("Redis get ES cache failed: %s", e)
    with _es_lock:
        expiry = _es_expiry if not HAS_CACHETOOLS else None
        return _cache_get(_es_cache, _hash_key(query), expiry)


def set_es_cache(query: str, results: list, ttl: Optional[int] = None):
    ttl = ttl or getattr(settings, "cache_ttl_seconds", 3600)
    key = _hash_key(query)

    if _redis_client:
        try:
            import json

            _redis_client.setex(f"cache:es:{key}", ttl, json.dumps(results))
        except Exception as e:
            logger.debug("Redis set ES cache failed: %s", e)
    with _es_lock:
        expiry = _es_expiry if not HAS_CACHETOOLS else None
        _cache_set(_es_cache, key, results, ttl, expiry)


def get_llm_cache(prompt_hash: str) -> Optional[dict]:
    if _redis_client:
        try:
            import json

            raw = _redis_client.get(f"cache:llm:{prompt_hash}")
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug("Redis get LLM cache failed: %s", e)
    with _llm_lock:
        expiry = _llm_expiry if not HAS_CACHETOOLS else None
        return _cache_get(_llm_cache, prompt_hash, expiry)


def set_llm_cache(prompt_hash: str, answer_data: dict, ttl: Optional[int] = None):
    ttl = ttl or 7 * 24 * 3600
    if _redis_client:
        try:
            import json

            _redis_client.setex(
                f"cache:llm:{prompt_hash}", ttl, json.dumps(answer_data, default=str)
            )
        except Exception as e:
            logger.debug("Redis set LLM cache failed: %s", e)
    with _llm_lock:
        expiry = _llm_expiry if not HAS_CACHETOOLS else None
        _cache_set(_llm_cache, prompt_hash, answer_data, ttl, expiry)


def cached_es_search(func):
    """Decorator to cache elastic_search(query) results."""

    @wraps(func)
    def wrapper(query: str, *args, **kwargs):
        if not query or not query.strip():
            return func(query, *args, **kwargs)
        key = _hash_key(query.strip())

        lock = _get_collapse_lock(f"es:{key}")

        hit = get_es_cache(query.strip())
        if hit is not None:
            logger.debug("ES cache hit for %s", query[:40])
            return hit

        with lock:

            hit = get_es_cache(query.strip())
            if hit is not None:
                return hit
            results = func(query, *args, **kwargs)
            try:
                set_es_cache(query.strip(), results)
            except Exception as e:
                logger.warning("ES cache set failed: %s", e)
            return results

    return wrapper


def cached_llm(func):
    """Decorator for LLM calls keyed by prompt hash."""

    @wraps(func)
    def wrapper(prompt: str, *args, **kwargs):
        if not prompt:
            return func(prompt, *args, **kwargs)
        phash = _hash_key(prompt)
        hit = get_llm_cache(phash)
        if hit is not None:

            if isinstance(hit, dict):
                hit = dict(hit)
                hit["_cached"] = True
            return (
                hit.get("answer", ""),
                hit.get("tokens", {}),
                hit.get("response_time", 0) if isinstance(hit, dict) else hit,
            )
        result = func(prompt, *args, **kwargs)

        try:
            if isinstance(result, tuple) and len(result) == 3:
                answer, tokens, rt = result
                set_llm_cache(
                    phash, {"answer": answer, "tokens": tokens, "response_time": rt}
                )
        except Exception as e:
            logger.warning("LLM cache set failed: %s", e)
        return result

    return wrapper


def invalidate_es_cache():
    """Call after bulk reindex."""
    try:
        with _es_lock:
            if HAS_CACHETOOLS:
                _es_cache.clear()
            else:
                _es_cache.clear()
                _es_expiry.clear()
        if _redis_client:

            try:
                for key in _redis_client.scan_iter("cache:es:*"):
                    _redis_client.delete(key)
            except Exception as e:
                logger.debug("Redis invalidate scan failed: %s", e)
        logger.info("ES cache invalidated")
    except Exception as e:
        logger.warning("invalidate failed: %s", e)


_rate_buckets: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def is_rate_limited(
    key: str, limit_per_minute: Optional[int] = None, window: int = 60
) -> bool:
    """Return True if key exceeds limit. Sliding window."""
    limit = limit_per_minute or getattr(settings, "rate_limit_per_minute", 60)
    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets.get(key, [])

        bucket = [t for t in bucket if now - t < window]
        if len(bucket) >= limit:
            _rate_buckets[key] = bucket
            return True
        bucket.append(now)
        _rate_buckets[key] = bucket
        return False
