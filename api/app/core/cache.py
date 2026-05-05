import logging
import os

log = logging.getLogger(__name__)

_redis = None


def _get_client():
    global _redis
    if _redis is not None:
        return _redis
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis
        _redis = redis.from_url(url, decode_responses=True)
        _redis.ping()
        log.info(f"[cache] connected to Redis at {url}")
    except Exception as e:
        log.warning(f"[cache] Redis unavailable — caching disabled: {e}")
        _redis = None
    return _redis


def get(key: str) -> str | None:
    client = _get_client()
    if not client:
        return None
    try:
        return client.get(key)
    except Exception as e:
        log.warning(f"[cache] get failed: {e}")
        return None


def set(key: str, value: str, ttl: int = 900) -> None:
    client = _get_client()
    if not client:
        return
    try:
        client.setex(key, ttl, value)
    except Exception as e:
        log.warning(f"[cache] set failed: {e}")
