import functools
from logging import Logger


@functools.cache
def warn_once(logger: Logger, message: str):
    logger.warning(message)