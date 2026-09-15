import json
import sys
import traceback

from loguru import logger

TEXT_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} | {message} | {extra}"


def _json_sink(message) -> None:
    """Write one flat JSON object per log line: timestamp, level, event name and bound fields."""
    record = message.record
    payload = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "event": record["message"],
        **record["extra"],
    }
    if record["exception"] is not None:
        exc_type, exc_value, exc_traceback = record["exception"]
        payload["exception"] = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    sys.stdout.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def setup_logger(level: str = "INFO", json_logs: bool = True) -> None:
    """Configure loguru for the whole process.

    Structured fields are attached with `logger.bind(...)` / `logger.contextualize(...)`.
    `diagnose=False` keeps local variable values (which may contain guest messages) out of tracebacks.
    """
    logger.remove()
    if json_logs:
        logger.add(_json_sink, level=level, backtrace=False, diagnose=False)
    else:
        logger.add(sys.stdout, level=level, format=TEXT_FORMAT, backtrace=False, diagnose=False)
