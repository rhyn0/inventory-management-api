"""Module containing commonly used functions and configuration."""
from .config import EnvConfig

DbConfig = EnvConfig("common/.env.db")

_all = [DbConfig, EnvConfig]
