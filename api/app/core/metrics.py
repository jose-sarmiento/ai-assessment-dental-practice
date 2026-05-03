from collections import deque
from threading import Lock

_lock = Lock()
_MAX_LATENCIES = 1000

_state = {
    "ask_count":        0,
    "latencies":        deque(maxlen=_MAX_LATENCIES),
    "tool_calls":       {},   # name → count
    "retrieval_hits":   0,
    "retrieval_total":  0,
}


def record_request(latency_ms: float) -> None:
    with _lock:
        _state["ask_count"] += 1
        _state["latencies"].append(latency_ms)


def record_tool_call(name: str) -> None:
    with _lock:
        _state["tool_calls"][name] = _state["tool_calls"].get(name, 0) + 1


def record_retrieval(hit: bool) -> None:
    with _lock:
        _state["retrieval_total"] += 1
        if hit:
            _state["retrieval_hits"] += 1


def snapshot() -> dict:
    with _lock:
        lats = sorted(_state["latencies"])
        p95  = lats[int(len(lats) * 0.95)] if lats else 0.0
        hit_at_k = (
            round(_state["retrieval_hits"] / _state["retrieval_total"], 4)
            if _state["retrieval_total"] > 0 else 0.0
        )
        return {
            "ask_count":       _state["ask_count"],
            "p95_latency_ms":  round(p95, 2),
            "retrieval_hit_at_k": hit_at_k,
            "tool_call_counts": dict(_state["tool_calls"]),
        }
