import logging

from app.core.config import settings

log_level_name_to_value: dict[str, int] = logging.getLevelNamesMapping()

logging.basicConfig(
    level=log_level_name_to_value.get(settings.LOG_LEVEL, logging.INFO),
    datefmt="%Y-%m-%d %H:%M:%S",
    format="[%(asctime)s] [%(filename)s:%(funcName)s:%(lineno)d] [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)
