# Standard Library
from tempfile import NamedTemporaryFile
from typing import Generator

# External Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

# Local Modules
from inven_api.database.models import InventoryBase
from inven_api.dependencies import get_db
from inven_api.main import APP as app

# make a test engine using sqlite in memory db
# _test_engine = create_engine("sqlite://", echo=True)
# db_sessions = sessionmaker(_test_engine, expire_on_commit=False)
_test_engine = create_async_engine("sqlite+aiosqlite://", echo=True)
db_sessions = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest.fixture(scope="module")
def test_client():
    with TestClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture(scope="session")
def test_engine():
    return _test_engine


@pytest.fixture(scope="session")
async def _setup_db(test_engine: AsyncEngine, sqlite_schema_file: str):
    async with test_engine.begin() as conn:
        await conn.execute(
            text("ATTACH DATABASE :file AS inventory"), [{"file": sqlite_schema_file}]
        )
        await conn.run_sync(InventoryBase.metadata.create_all)


@pytest.fixture(scope="module")
def monkey_mod() -> Generator[pytest.MonkeyPatch, None, None]:
    # External Party
    from _pytest.monkeypatch import MonkeyPatch

    monkey = MonkeyPatch()
    yield monkey
    monkey.undo()


async def session():
    async with db_sessions() as session:
        yield session


@pytest.fixture()
async def db_session(test_engine: AsyncEngine):
    return session()


# execute this whenever this module is required by another module
app.dependency_overrides[get_db] = session
