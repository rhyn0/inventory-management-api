# Standard Library
import logging
import time
from typing import Self

# External Party
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from uvicorn.logging import DefaultFormatter


class UtcUvicornFormatter(DefaultFormatter):
    """Override Uvicorn formatter as we want Level colored logging.

    But log timestamps in UTC make easier to parse usually.
    """

    converter = time.gmtime


# More info: https://docs.python.org/3/library/logging.config.html#logging-config-dictschema
# make this model a dumpable dictConfig for Python Logging.
# Will make our coupling to uvicorn higher by using their logging formatter
class LogConfig(BaseModel):
    """Object to build Logging dictConfig at runtime."""

    LOGGER_NAME: str
    LOG_LEVEL: str
    LOG_FORMAT: str = "%(levelprefix)s | %(asctime)s | %(filename)s::%(lineno)s %(message)s"  # noqa: E501

    # non initialize-able fields
    version: int = Field(1, frozen=True, init_var=False)
    disable_existing_loggers: bool = Field(False, frozen=True, init_var=False)
    # https://stackoverflow.com/a/67937084
    formatters: dict = Field(
        {
            "default": {
                "()": UtcUvicornFormatter,
                "fmt": LOG_FORMAT,
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        frozen=True,
        init_var=False,
    )
    handlers: dict = Field(
        {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
        },
        frozen=True,
        init_var=False,
    )
    loggers: dict = Field({}, init_var=False)

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def log_level_as_str(cls, value: str | int) -> str:
        """Validate that given LOG_LEVEL is a valid Python logging level.

        Can either be given the int value of the level or the string name of the level.

        Args:
            value (str | int): value to map to a valid Python logging level

        Returns:
            str: NAME of the Python logging level
        """
        if isinstance(value, int):
            # Logging levels are actually ints
            # but multiples of 10, so we can floor the value
            return logging.getLevelName(value // 10)
        # Otherwise it is a string, so just check that it is a valid level name
        assert (
            value.upper() in logging._nameToLevel
        ), "Need a valid Python logging level name"
        return value.upper()

    @model_validator(mode="after")
    def set_loggers(self) -> Self:
        """Set loggers based on LOGGER_NAME and LOG_LEVEL."""
        self.loggers = {
            self.LOGGER_NAME: {
                "handlers": ["default"],
                "level": self.LOG_LEVEL,
            }
        }
        return self
