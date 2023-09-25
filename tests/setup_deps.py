# Standard Library
import asyncio
from collections.abc import Generator
from tempfile import NamedTemporaryFile

# External Party
from fastapi.testclient import TestClient
from hypothesis import strategies as st
import pytest
import pytest_asyncio
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
from inven_api.main import APP as app  # noqa: N811

# make a test engine using sqlite in memory db
# _test_engine = create_engine("sqlite://", echo=True)
# db_sessions = sessionmaker(_test_engine, expire_on_commit=False)
_test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
db_sessions = async_sessionmaker(_test_engine, expire_on_commit=False)


@st.composite
def valid_avail_owned(draw) -> tuple[int, int]:
    """Strategy to generate valid avail and owned values.

    Owned value must be greater than zero and greater than or equal to avail.
    Testing can occur on a SQLite in memory database,
    so the max value is 9_223_372_036_854_775_807

    Returns:
        tuple[int, int]: (avail, owned) where owned >= avail
    """
    avail = draw(st.integers(min_value=0, max_value=100_000))
    owned = draw(
        st.integers(min_value=1, max_value=100_000).filter(lambda x: x >= avail)
    )
    return avail, owned


@pytest.fixture(scope="session")
def test_client():
    """Accessor to the API without spawning the server."""
    with TestClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture(scope="session")
def test_engine():
    """Wrap the private test engine."""
    return _test_engine


@pytest.fixture(scope="session")
def sqlite_schema_file():
    """Where the attached SQLite database is stored."""
    with NamedTemporaryFile(mode="w+b", suffix=".db", delete=True) as f:
        yield f.name


@pytest.fixture(scope="session")
def event_loop():
    """Override the pytest_asyncio event_loop fixture.

    Want this to be session scoped.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def setup_db(test_engine: AsyncEngine, sqlite_schema_file: str):
    """Setup the database for the session."""
    async with db_sessions() as session:
        async with test_engine.begin() as conn:
            await conn.execute(
                text("ATTACH DATABASE :file AS inventory"),
                [{"file": sqlite_schema_file}],
            )
            await conn.run_sync(InventoryBase.metadata.create_all)
        # loud during call
        test_engine.echo = True
        yield session
        # quiet during teardown and setup
        test_engine.echo = False
        async with test_engine.begin() as conn:
            await conn.run_sync(InventoryBase.metadata.drop_all)


@pytest.fixture(scope="module")
def monkey_mod() -> Generator[pytest.MonkeyPatch, None, None]:
    """If you need to monkeypatch something that could be 'module' scoped, use this."""
    # External Party
    from _pytest.monkeypatch import MonkeyPatch

    monkey = MonkeyPatch()
    yield monkey
    monkey.undo()


async def session():
    """Function to override the APP's database dependency."""
    async with db_sessions() as session:
        yield session


@pytest_asyncio.fixture()
async def db_session(test_engine: AsyncEngine):
    """If a function wants to use async_sessionmaker, instead of engine."""
    return session()


# execute this whenever this module is required by another module
app.dependency_overrides[get_db] = session


@pytest.fixture(scope="session")
def request_headers() -> dict[str, str]:
    """Headers to send with each request.

    Defines simple content type and acceptable content responses.
    """
    return {"accept": "application/json", "Content-Type": "application/json"}
