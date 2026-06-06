"""
utils/logger.py — configures root logger from config.LOG_LEVEL.
Call setup_logging() once at program startup.
"""
import logging
import sys
import config


def setup_logging() -> None:
    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    fmt   = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
