from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler


LOG_DIR = "logs"


def setup_logger() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("polymarket_copy_bot")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    bot_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "bot.log"), maxBytes=5 * 1024 * 1024, backupCount=3
    )
    bot_handler.setLevel(logging.INFO)
    bot_handler.setFormatter(formatter)

    err_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "error.log"), maxBytes=5 * 1024 * 1024, backupCount=3
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(formatter)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    logger.addHandler(bot_handler)
    logger.addHandler(err_handler)
    logger.addHandler(console)
    return logger
