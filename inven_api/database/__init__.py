"""Module for database specifics."""
# External Party
from asyncpg.exceptions import ForeignKeyViolationError
from asyncpg.exceptions import UniqueViolationError

from .connection import get_engine
from .models import BuildProducts
from .models import Builds
from .models import InventoryBase
from .models import Products
from .models import ProductTypes
from .models import Tools
from .session import DbSession

ASYNCPG_FK_VIOLATION_CODE = ForeignKeyViolationError.sqlstate
ASYNCPG_UNIQUE_VIOLATION_CODE = UniqueViolationError.sqlstate

_all = [
    get_engine,
    InventoryBase,
    Products,
    Tools,
    ProductTypes,
    Builds,
    BuildProducts,
    DbSession,
    ASYNCPG_UNIQUE_VIOLATION_CODE,
    ASYNCPG_FK_VIOLATION_CODE,
]
