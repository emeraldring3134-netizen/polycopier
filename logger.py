from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone


LOG_DIR = "logs"


class RedactPrivateKeyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        msg = re.sub(r"0x[a-fA-F0-9]{64}", "[REDACTED_PRIVATE_KEY]", msg)
        record.msg = msg
        record.args = ()
        return True


class IterationFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "iteration"):
            record.iteration = "-"
        return super().format(record)


def setup_logger() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("polymarket_copy_bot")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    formatter = IterationFormatter("[%(asctime)s] [%(levelname)s] [迭代#%(iteration)s] %(message)s")

    main_file = os.path.join(LOG_DIR, f"live-{day}.log")
    err_file = os.path.join(LOG_DIR, f"error-{day}.log")

    main_handler = logging.FileHandler(main_file, encoding="utf-8")
    main_handler.setLevel(logging.INFO)
    main_handler.setFormatter(formatter)
    main_handler.addFilter(RedactPrivateKeyFilter())

    err_handler = logging.FileHandler(err_file, encoding="utf-8")
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(formatter)
    err_handler.addFilter(RedactPrivateKeyFilter())

    logger.addHandler(main_handler)
    logger.addHandler(err_handler)
    logger.propagate = False
    return logger
