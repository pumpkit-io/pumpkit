import logging

from pumpkit.core.config import settings

log_level_name_to_value: dict[str, int] = logging.getLevelNamesMapping()

logging.basicConfig(
    level=log_level_name_to_value.get(settings.LOG_LEVEL, logging.INFO),
    datefmt="%Y-%m-%d %H:%M:%S",
    format="[%(asctime)s] [%(filename)s:%(funcName)s:%(lineno)d] [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)

_REDACTED = "[redacted]"


class _AccessPathRedactor(logging.Filter):
    def __init__(self, prefix: str) -> None:
        super().__init__()
        self.prefix = prefix

    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn logs (client, method, path with its query, HTTP version, status).
        args = record.args
        if isinstance(args, tuple) and len(args) > 2 and str(args[2]).startswith(self.prefix):
            record.args = (*args[:2], self.prefix + _REDACTED, *args[3:])
        return True


def redact_access_log_paths(prefix: str) -> None:
    """Keep what follows `prefix` in a request's path, a credential, out of uvicorn's access log."""
    logging.getLogger("uvicorn.access").addFilter(_AccessPathRedactor(prefix))
