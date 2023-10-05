"""Session maker logic and stuff."""
# External Party
from sqlalchemy.ext.asyncio import async_sessionmaker

# Local Modules
from inven_api.common import DbConfig
from inven_api.database.connection import get_engine

_engine = get_engine(
    hostname=DbConfig.INVEN_DB_ENDPOINT,
    port=DbConfig.INVEN_DB_PORT,
    username=DbConfig.INVEN_DB_USERNAME,
    password=DbConfig.INVEN_DB_PASSWD,
    dbname=DbConfig.INVEN_DB_DBNAME,
)

# define this here to make imports easier later
DbSession = async_sessionmaker(_engine, expire_on_commit=False)
