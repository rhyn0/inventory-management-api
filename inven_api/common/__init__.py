"""Module containing commonly used functions and configuration."""
# Standard Library
from pathlib import Path

from .config import EnvConfig
from .log import LogConfig

DbConfig = EnvConfig(Path(__file__).parent / ".env.db")
LOG_NAME = "api"
_all = [DbConfig, EnvConfig, LogConfig, LOG_NAME]
