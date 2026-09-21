import logging
import re
import sys

_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")


def redact(text: str) -> str:
    """Mask API keys: anything shaped like an Anthropic key, plus the configured key itself."""
    from app.core.config import get_settings

    text = _KEY_PATTERN.sub("sk-ant-***", text)
    key = get_settings().anthropic_api_key
    return text.replace(key, "***") if key else text


class RedactingFormatter(logging.Formatter):
    """Formats the full record (message + traceback) and redacts secrets from the result."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter("%(asctime)s level=%(levelname)s logger=%(name)s %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def log_event(logger: logging.Logger, **fields) -> None:
    """Structured key=value log line. Callers must never pass secrets or prompts."""
    logger.info(" ".join(f"{k}={v}" for k, v in fields.items() if v is not None))


def log_failure(logger: logging.Logger, exc: BaseException, **fields) -> None:
    """Log a failure with the real exception message and traceback (developer-side only).

    Secrets are masked by RedactingFormatter; nothing here is ever returned to the user.
    """
    fields = {**fields, "error_type": type(exc).__name__, "error": str(exc) or None}
    logger.error(" ".join(f"{k}={v}" for k, v in fields.items() if v is not None), exc_info=exc)
