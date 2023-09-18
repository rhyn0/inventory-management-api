"""Module for interacting with this project's configuration."""

# Standard Library
from collections import UserDict
from collections.abc import Sequence
import os
from pathlib import Path
from typing import Any

# External Party
import dotenv

DictKey = str
DictValue = Any


class InvalidCaseInsenstiveKeyError(Exception):
    """Error to raise when the type of the key is not supported."""

    def __init__(self, argument_name: str, *args: object) -> None:
        """Error message wraps the function's argument name."""
        super().__init__(f"{argument_name} must be of type str", *args)


class FrozenInstanceError(Exception):
    """Error to raise when trying to set attributes on a frozen instance."""

    def __init__(self, *args: object) -> None:
        """Create error with default message."""
        super().__init__("Trying to set attribute on a frozen instance", *args)


class CaseInsensitiveDict(UserDict):
    """Class that can stores key -> value pairs with insensitive keys.

    Keys of this dictionary must always be strings.

    Has the ability to return the original Key -> Value pair.
    """

    def __init__(self, existing_data: dict[DictKey, DictValue] | None = None) -> None:
        """Initialize the insensitive dictionary.

        Raises:
            InvalidCaseInsenstiveKeyError: if any key of `existing_data` is not a str

        Args:
            existing_data (dict[str, Any] | None, optional): Pre existing data to use.
                Defaults to None.
        """
        super().__init__()
        if existing_data is None:
            existing_data = {}
        if not all(isinstance(key, DictKey) for key in existing_data):
            raise InvalidCaseInsenstiveKeyError("Keys")
        # make case insensitive, using __setitem__
        self.update(existing_data)

    def __getitem__(self, key: DictKey) -> DictValue:
        """Return the Value that corresponds to this key - case insensitive.

        Args:
            key (DictKey): Key to lookup

        Raises:
            KeyError: If no such key exists

        Returns:
            DictValue: Whatever the value is
        """
        _, value = self.data[self._key_modifier(key)]
        return value

    def __setitem__(self, key: DictKey, item: DictValue) -> None:
        """Store data as case insensitive.

        Preserve the original key by storing as Key -> (Key,Value).

        Args:
            key (DictKey): String key to use
            item (DictValue): value to store
        """
        self.data[self._key_modifier(key)] = (key, item)

    def __contains__(self, key: object) -> bool:
        """Return whether a key is contained in this collection.

        Will only check when `key` is a string.

        Args:
            key (object): Key to check for

        Returns:
            bool: True if contained, False otherwise
        """
        if not isinstance(key, DictKey):
            return False
        return self._key_modifier(key) in self.data

    def __repr__(self) -> str:
        """Return regular dictionary repr.

        Should make it easier for other devs to debug.
        """
        return repr(dict(self.items()))

    def __delitem__(self, key: DictKey) -> None:
        """Remove a key from this collection.

        This method is invoked when using the `del` keyword.

        Raises:
            KeyError: if no such key in this collection

        Args:
            key (DictKey): value to remove
        """
        del self.data[self._key_modifier(key)]

    @staticmethod
    def _key_modifier(key: Any) -> str:
        """Return key according to common key modification requirements.

        Raises:
            InvalidCaseInsenstiveKeyError: if key is not of type str

        Args:
            key (Any): Key to modify
        """
        if not isinstance(key, str):
            raise InvalidCaseInsenstiveKeyError("Key")
        return key.lower()

    def update(self, incoming: dict[DictKey, DictValue]) -> None:
        """Update this collection with the items from `incoming`.

        Args:
            incoming (dict[DictKey, DictValue]): collection of items to update with
        """
        for key, value in incoming.items():
            self[key] = value

    def get(self, key: DictKey, default: DictValue | None = None) -> DictValue:
        """Return the value associated with the given key.

        Args:
            key (DictKey): key of item to lookup
            default (DictValue | None, optional): Value to return if no such key found.
                Defaults to None.

        Returns:
            DictValue: Associated value of the key or `default`.
        """
        if key in self:
            _, value = self[key]
            return value
        return default

    def keys(self) -> Sequence[DictKey]:
        """Return sequence of all original keys contained."""
        return [key for key, _ in self.data.values()]

    def values(self) -> Sequence[DictValue]:
        """Return sequence of all values contained in this collection."""
        return [value for _, value in self.data.values()]

    def items(self) -> Sequence[tuple[DictKey, DictValue]]:
        """Return sequence of all key->value pairs in this collection."""
        return self.data.values()  # type: ignore


class EnvConfig:
    """Class to hold a loaded .env config.

    Reconciles keys in the .env file against ENVIRONMENT variables.
    ENV variables have higher precedence and will overwrite
    values from .env file. Case sensitive when comparing .env with ENV.

    If a file just has a variable name 'FOO' it will be stored in this object
    as 'FOO' -> None.
    """

    _frozen: bool = False

    def __init__(self, file_path: str | Path) -> None:
        """Load the dotenv config from the given `file_path`."""
        if not isinstance(file_path, str | Path):
            raise TypeError(type(file_path))

        if isinstance(file_path, str):
            file_path = Path(file_path)
        # Empty string is converted to relative cwd
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(file_path)

        dotenv_dict = dotenv.dotenv_values(file_path)
        self.config = CaseInsensitiveDict(
            {
                key: (
                    dotenv_value if (env_value := os.getenv(key)) is None else env_value
                )
                for key, dotenv_value in dotenv_dict.items()
            }
        )
        self._frozen = True

    def __setattr__(self, __name: str, __value: Any) -> None:
        """Override normal behavior to implement frozen."""
        if self._frozen:
            raise FrozenInstanceError()
        return super().__setattr__(__name, __value)

    def __getattr__(self, name: str) -> Any:
        """Return the config value associated with `name`.

        Raises:
            AttributeError: if `name` does not exist

        Returns:
            str | None: Value stored in env config
        """
        if name in self.config:
            return self.config[name]
        raise AttributeError(name=name, obj=self)

    def __len__(self) -> int:
        """Return length of the config object.

        Helpful for making a truthy object.
        """
        return len(self.config)

    def __bool__(self) -> bool:
        """Override default truthy behavior to be based on length."""
        return bool(len(self))

    def __repr__(self) -> str:
        """Don't show config values in repr, assuming sensitive details."""
        return f"EnvConfig(items={len(self)})"
