from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from cpmh_backend.config import Settings

_CONFIGURED = False


def setup_logging(settings: Settings) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("cpmh")
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    if _CONFIGURED:
        return logger
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = RotatingFileHandler(
        settings.log_dir / "cpmh.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(stream)
    logger.propagate = False
    _CONFIGURED = True
    return logger


def reset_logging() -> None:
    global _CONFIGURED
    logger = logging.getLogger("cpmh")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    _CONFIGURED = False
