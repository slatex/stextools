import configparser
import functools
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


CACHE_DIR = Path('~/.cache/stextools').expanduser()
CONFIG_DIR = Path('~/.config/stextools').expanduser()


@functools.cache
def get_config() -> configparser.ConfigParser:
    config_path = CONFIG_DIR / 'config.ini'
    config = configparser.ConfigParser()
    if config_path.exists():
        logger.info(f'Loading config from {config_path}')
        config.read(config_path)
    else:
        logger.info(f'No config file found at {config_path}. Using defaults.')
    return config
