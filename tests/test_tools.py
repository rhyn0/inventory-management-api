# Standard Library
import contextlib
from contextlib import asynccontextmanager
from tempfile import NamedTemporaryFile

# External Party
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

# Local Modules
from inven_api import database
from inven_api.database import InventoryBase
from inven_api.database.models import Tools
from inven_api.routes import tools

from .setup_deps import _setup_db
from .setup_deps import db_sessions
from .setup_deps import test_client
from .setup_deps import test_engine


@pytest.fixture(scope="session")
def sqlite_schema_file():
    with NamedTemporaryFile(mode="w+b", suffix=".db", delete=True) as f:
        yield f.name


@pytest.fixture()
async def _insert_tool_data(_setup_db, test_engine: AsyncEngine, tool_data: dict):
    with contextlib.suppress(RuntimeError):
        # if this was already awaited (setup)
        # ignore the error from awaiting again
        await _setup_db
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO tools (name, vendor, total_owned, total_avail)
                VALUES (:name, :vendor, :total_owned, :total_avail)"""
            ),
            [tool_data],
        )
        await conn.commit()


@pytest.fixture()
def tool_data() -> dict:
    return {
        "name": "Test Tool",
        "vendor": "Test Vendor",
        "total_owned": 10,
        "total_avail": 10,
    }


@pytest.fixture(scope="module")
def _mock_db_session(monkey_mod: pytest.MonkeyPatch):
    monkey_mod.setattr(database, "DbSession", db_sessions)
    yield
    monkey_mod.undo()


class TestAtomicReturnDataUnit:
    """Unit tests for the models of return data from atomic operations.

    These classes are tools.ToolPreAtomicUpdate and tools.ToolPostAtomicUpdate.
    """

    @given(st.integers(), st.integers(min_value=1), st.integers(min_value=0))
    def test_pre_atomic_update(
        self, given_tool_id: int, pre_total_owned: int, pre_total_avail: int
    ):
        """Test that the pre-atomic update object can be instantiated."""
        pre_update = tools.ToolPreAtomicUpdate(
            tool_id=given_tool_id,
            total_owned=pre_total_owned,
            total_avail=pre_total_avail,
        ).model_dump(by_alias=True)
        # This by_alias is necessary because of the serialization_alias
        # when used in FastAPI, the method receives response_model_by_alias=True
        assert pre_update["tool_id"] == given_tool_id
        assert "total_owned" not in pre_update
        assert pre_update["preTotalOwned"] == pre_total_owned
        assert "total_avail" not in pre_update
        assert pre_update["preTotalAvail"] == pre_total_avail


class TestUpdatePathEnumUnit:
    """Unit tests for the enumeration of fields editable in an atomic operation.

    The class is tools.ToolUpdatePaths.
    """

    @given(st.sampled_from(tools.ToolUpdatePaths))
    def test_update_path_data_column(self, given_field: tools.ToolUpdatePaths):
        """Test that column name is accessible."""
        assert issubclass(given_field.__class__, str)
        assert hasattr(given_field, "column_name")
        assert given_field.column_name is not None  # type: ignore


@pytest.mark.asyncio()
class TestUpdateRoutesIntegration:
    """Test that all routes for updating tools work as expected."""

    @pytest.fixture()
    async def test_tool(self, session: AsyncSession):
        tool = Tools(name="Test Tool", total_owned=10, total_avail=10)
        session.add(tool)
        await session.commit()
        tool_id = tool.tool_id
        yield tool_id
        await session.delete(tool)
        await session.commit()

    async def test_get_no_tools(  # noqa: PT019
        self, _setup_db, test_client: TestClient
    ):
        """Test that we can get no tools."""
        # no data inserted so
        await _setup_db
        response = test_client.get("/tools")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_all_tools(  # noqa: PT019
        self, _insert_tool_data, test_engine: AsyncEngine, test_client: TestClient
    ):
        """Test that we can get all tools.

        Only one in this case.
        """
        await _insert_tool_data
        response = test_client.get("/tools")
        assert response.status_code == 200
        response_data = response.json()
        assert isinstance(response_data, list)
        assert len(response_data) == 1
        # notice that this is not the same as the actual Table model
        assert all(
            col in response_data[0]
            for col in ("tool_id", "name", "vendor", "owned", "available")
        )
