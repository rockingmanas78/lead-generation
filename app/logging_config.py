import json
import logging
import sys
from typing import Any, Dict

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        # Allow structured payload via `extra={"json": {...}}`
        if hasattr(record, "json"):
            try:
                base.update(getattr(record, "json"))  # type: ignore[arg-type]
            except Exception:
                pass
        return json.dumps(base, ensure_ascii=False)

def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
