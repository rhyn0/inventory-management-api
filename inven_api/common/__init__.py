"""Module containing commonly used functions and configuration."""
# Standard Library
from pathlib import Path

from .config import EnvConfig

DbConfig = EnvConfig(Path(__file__).parent / ".env.db")

_all = [DbConfig, EnvConfig]
