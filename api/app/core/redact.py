import re

_SENSITIVE_KEYS = {
    "patient_name",
    "patient_id",
    "notes",
}

_PATTERNS = [
    (re.compile(r"(patient_name['\"]?\s*[:=]\s*['\"])([^'\"]+)(['\"])"), r"\1[REDACTED]\3"),
    (re.compile(r"(patient_id['\"]?\s*[:=]\s*['\"])([^'\"]+)(['\"])"),   r"\1[REDACTED]\3"),
    (re.compile(r"(notes['\"]?\s*[:=]\s*['\"])([^'\"]{0,200})(['\"])"),   r"\1[REDACTED]\3"),
]


def redact(data) -> any:
    if isinstance(data, dict):
        return {k: _mask(k, v) for k, v in data.items()}
    if isinstance(data, list):
        return [redact(item) for item in data]
    if isinstance(data, str):
        return _redact_string(data)
    return data


def _mask(key: str, value) -> any:
    if key not in _SENSITIVE_KEYS:
        return redact(value)
    if isinstance(value, str) and value:
        return "[REDACTED]"
    return value


def _redact_string(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
