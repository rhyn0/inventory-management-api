# Standard Library
import asyncio
import contextlib
from contextlib import asynccontextmanager
from tempfile import NamedTemporaryFile

# External Party
from fastapi import status
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

# Local Modules
from inven_api import database
from inven_api.database import InventoryBase
from inven_api.database.models import Tools
from inven_api.routes import tools

from .setup_deps import db_sessions
from .setup_deps import event_loop
from .setup_deps import setup_db
from .setup_deps import sqlite_schema_file
from .setup_deps import test_client
from .setup_deps import test_engine
from .setup_deps import valid_avail_owned


@pytest_asyncio.fixture()
async def _pre_insert_tool_data(
    setup_db: AsyncSession, tool_data: dict, request: pytest.FixtureRequest
):
    """Fixture to insert tool data into the database."""
    marks = [m.name for m in request.node.iter_markers()]
    if "no_insert" in marks:
        return
    await insert_tool_data(setup_db, tool_data)


async def insert_tool_data(session: AsyncSession, tool_data: dict):
    """Function to actually insert a tool into the table.

    This makes it easier to call for variable amounts of tools in a table.
    """
    async with session.begin() as conn:
        await session.execute(
            text(
                """INSERT INTO inventory.tools (name, vendor, total_owned, total_avail)
                VALUES (:name, :vendor, :total_owned, :total_avail)"""
            ),
            [tool_data],
        )


@pytest.fixture(scope="session")
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


class TestToolUpdateUnit:
    """Unit tests for the request body parsing object for updating a tool.

    This body would parse it when calling with data:
        curl -X PUT -H "Content-Type: application/json" /tools/{tool_id} -d '{"owned": 10, "avail": 10}'
    """

    serialized_owned_field = "total_owned"
    serialized_avail_field = "total_avail"

    @given(valid_avail_owned())
    def test_update_tool_body_kw(self, qty_tuple: tuple[int, int]):
        """Test that the body can be instantiated."""
        update_body = tools.ToolUpdate(
            owned=qty_tuple[1],
            avail=qty_tuple[0],
        ).model_dump(exclude_unset=True, by_alias=True)
        assert update_body[self.serialized_owned_field] == qty_tuple[1]
        assert update_body[self.serialized_avail_field] == qty_tuple[0]

    @given(valid_avail_owned())
    def test_update_tool_body_dict(self, qty_tuple: tuple[int, int]):
        """Test that the body can be instantiated."""
        update_body = tools.ToolUpdate.model_validate(
            {"owned": qty_tuple[1], "avail": qty_tuple[0]}
        ).model_dump(exclude_unset=True, by_alias=True)
        assert update_body[self.serialized_owned_field] == qty_tuple[1]
        assert update_body[self.serialized_avail_field] == qty_tuple[0]


@pytest.mark.asyncio()
@pytest.mark.usefixtures("_pre_insert_tool_data")
class TestUpdateRoutesIntegration:
    """Test that all routes for updating tools work as expected."""

    def full_update_fields_present(self, data: dict) -> bool:
        """Test that all the required fields of a returned Tool are present."""
        return all(
            key in data for key in ("tool_id", "name", "vendor", "owned", "available")
        )

    @pytest.fixture()
    async def test_tool(self, session: AsyncSession):
        tool = Tools(name="Test Tool", total_owned=10, total_avail=10)
        session.add(tool)
        await session.commit()
        tool_id = tool.tool_id
        yield tool_id
        await session.delete(tool)
        await session.commit()

    @pytest.mark.no_insert()
    @pytest.mark.usefixtures("setup_db")
    async def test_get_no_tools(self, test_client: TestClient):
        """Test that we can get no tools."""
        # no data inserted so
        response = test_client.get("/tools")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_all_tools(self, test_client: TestClient):
        """Test that we can get all tools.

        Only one in this case.
        """
        response = test_client.get("/tools")
        assert response.status_code == 200
        response_data = response.json()
        assert isinstance(response_data, list)
        assert len(response_data) == 1
        # notice that this is not the same as the actual Table model
        assert self.full_update_fields_present(response_data[0])

    async def test_delete_tools_fail(
        self, test_engine: AsyncEngine, test_client: TestClient
    ):
        """Test that we can get all tools.

        Only one in this case.
        """
        response = test_client.delete("/tools")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        response_data = response.json()
        assert "detail" in response_data
        assert "not allowed" in response_data["detail"].lower()
        # verify that a tool still exists
        async with test_engine.connect() as conn:
            result = await conn.execute(text("SELECT * FROM inventory.tools"))
            # result.rowcount is not useful in SQLAlchemy 2.0 except for in DELETE or UPDATE
            assert len(result.fetchall()) > 0

    async def test_delete_tool(self, test_engine: AsyncEngine, test_client: TestClient):
        """Test that we can get all tools.

        Only one in this case.
        """
        # get an existing tool_id
        async with test_engine.connect() as conn:
            after_result = await conn.execute(select(Tools.tool_id).limit(1))
            tool_id = after_result.scalar_one()

        print(f"found {tool_id=}")
        response = test_client.delete(f"/tools/{tool_id}")

        assert response.status_code == 200
        response_data = response.json()
        # returns the object that was in the database
        assert isinstance(response_data, dict)
        # notice that this is not the same as the actual Table model
        assert self.full_update_fields_present(response_data)

        # check that the tool is deleted
        async with test_engine.connect() as conn:
            after_result = await conn.execute(
                select(Tools).where(Tools.tool_id == tool_id)
            )
        assert after_result.one_or_none() is None

    async def test_patch_fail_root(self, test_client: TestClient):
        """Test that we cannot patch a root route."""
        response = test_client.patch("/tools")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        response_data = response.json()
        assert "detail" in response_data
        assert "not allowed" in response_data["detail"].lower()

    async def test_patch_fail(self, test_engine: AsyncEngine, test_client: TestClient):
        """Test that we cannot patch a tool_id route."""
        # obtain a tool_id
        async with test_engine.connect() as conn:
            result = await conn.execute(select(Tools.tool_id).limit(1))
            tool_id = result.scalar_one()
        response = test_client.patch(f"/tools/{tool_id}")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        response_data = response.json()
        assert "detail" in response_data
        assert "not allowed" in response_data["detail"].lower()

    @given(valid_avail_owned())
    async def test_put_happy(
        self,
        test_engine: AsyncEngine,
        test_client: TestClient,
        qty_tuple: tuple[int, int],
    ):
        """Test that we can update a tool_id route with proper body format."""
        # obtain a tool_id
        async with test_engine.connect() as conn:
            result = await conn.execute(select(Tools.tool_id).limit(1))
            tool_id = result.scalar_one()

        # this request needs a Content-Type header of application/json
        response = test_client.put(
            f"/tools/{tool_id}",
            json={"owned": qty_tuple[1], "avail": qty_tuple[0]},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert self.full_update_fields_present(response_data)

    @given(valid_avail_owned())
    async def test_put_fail(
        self,
        test_engine: AsyncEngine,
        test_client: TestClient,
        qty_tuple: tuple[int, int],
    ):
        """Test that we get a 400 if we try to update a tool_id route with invalid data.

        The quantity owned must always be greater than or equal to the quantity available.
        So we should get an error if we try to break this on purpose.
        """
        # obtain a tool_id
        async with test_engine.connect() as conn:
            result = await conn.execute(select(Tools.tool_id).limit(1))
            tool_id = result.scalar_one()

        # this request needs a Content-Type header of application/json
        response = test_client.put(
            f"/tools/{tool_id}",
            json={"owned": qty_tuple[1], "avail": 2 * sum(qty_tuple)},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_data = response.json()
        assert "detail" in response_data
