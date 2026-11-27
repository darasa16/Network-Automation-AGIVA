import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'agiva_noc.log')

os.makedirs(LOG_DIR, exist_ok=True)

LOG_FORMAT = '%(asctime)s [%(levelname)s] [%(name)s]: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

_INITIALIZED = False

def get_configured_logger(name="AgivaNOC", level=logging.INFO):
    """
    Mengembalikan instance logger dengan StreamHandler (konsol) dan
    RotatingFileHandler (rotasi file otomatis).
    """
    global _INITIALIZED
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        try:
            file_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"Tidak dapat membuat RotatingFileHandler pada {LOG_FILE}: {e}")

    return logger

