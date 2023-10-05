"""Connection definition to Postgres Database."""
# External Party
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine


def get_engine(
    *,
    hostname: str,
    port: int | str,
    username: str,
    password: str,
    dbname: str,
    **kwargs
) -> AsyncEngine:
    """Create SQLAlchemy engine to connect to database.

    All arguments are Keyword arguments, additional kwargs go on to URL query.

    Args:
        hostname (str): endpoint to connect to database at
        port (int | str): What port to connect on
        username (str): database username
        password (str): connection password auth
        dbname (str): database name to connect to

    Keyword Args:
        kwargs: All get passed to sa.engine.url.URL query parameter.

    Returns:
        sa.Engine
    """
    return create_async_engine(
        URL(
            "postgresql+asyncpg",  # default to async driver
            username=username,
            password=password,
            host=hostname,
            port=int(port),
            database=dbname,
            query=kwargs,  # type: ignore
        ),
        echo=True,
    )
