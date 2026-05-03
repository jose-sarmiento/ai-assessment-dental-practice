import json
import logging
import traceback
from datetime import datetime, timezone

from .redact import _redact_string


class PHIRedactFilter(logging.Filter):
    """Strips PHI from all log records before they are written."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_string(str(record.getMessage()))
        record.args = None
        return True


class JSONFormatter(logging.Formatter):
    """Emits one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":      datetime.now(timezone.utc).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = traceback.format_exception(*record.exc_info)
        return json.dumps(payload)
