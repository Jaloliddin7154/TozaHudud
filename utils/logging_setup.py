import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from config import LOG_DIR, LOG_LEVEL


def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)

    log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    # Prevent duplicated logs on restart/import
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(fmt)

    app_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(log_level)
    app_handler.setFormatter(fmt)

    error_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "error.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)

    root.addHandler(console_handler)
    root.addHandler(app_handler)
    root.addHandler(error_handler)

    # Dedicated performance log to track slow updates/operations
    perf_logger = logging.getLogger("performance")
    perf_logger.setLevel(logging.INFO)
    perf_logger.handlers.clear()
    perf_logger.propagate = False

    perf_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "performance.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    perf_handler.setFormatter(fmt)
    perf_logger.addHandler(perf_handler)

    # Human-friendly log for non-technical operators.
    human_logger = logging.getLogger("human")
    human_logger.setLevel(logging.INFO)
    human_logger.handlers.clear()
    human_logger.propagate = False

    human_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "human.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    human_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(message)s")
    )
    human_logger.addHandler(human_handler)
