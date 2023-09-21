# Standard Library
import time
from typing import Any

# External Party
from pydantic import BaseModel
from pydantic import field_validator
from uvicorn.logging import DefaultFormatter


class UtcUvicornFormatter(DefaultFormatter):
    """Override Uvicorn formatter as we want Level colored logging.

    But log timestamps in UTC make easier to parse usually.
    """

    converter = time.gmtime


# TODO: https://docs.python.org/3/library/logging.config.html#logging-config-dictschema
# make this model a dumpable dictConfig for Python Logging.
# Will make our coupling to uvicorn higher by using their logging formatter


class LogConfig(BaseModel):
    """Object to build Logging dictConfig at runtime."""

    LOGGER_NAME: str
    LOG_LEVEL: str
    LOG_FORMAT: str = "hi"

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def log_level_as_str(cls, value: Any) -> str:  # noqa: D102
        # TODO: https://docs.pydantic.dev/2.3/usage/validators/#field-validators
        # Goal is to input either the string name of the level "INFO"
        # or the int value of the level 20, and set it to str
        ...
