# Standard Library
import asyncio
import contextlib
from contextlib import asynccontextmanager
from itertools import product
from string import ascii_letters
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
    async with session.begin():
        await session.execute(
            text(
                """INSERT INTO inventory.tools (name, vendor, total_owned, total_avail)
                VALUES (:name, :vendor, :total_owned, :total_avail)"""
            ),
            [tool_data],
        )


@pytest.fixture(scope="session")
def tool_data() -> dict:
    """Example tool request body."""
    return {
        "name": "Test Tool",
        "vendor": "Test Vendor",
        "total_owned": 10,
        "total_avail": 9,
    }


@pytest.fixture(scope="session")
def tool_orm_data(tool_data: dict) -> Tools:
    """Default object of what a Tools record could be like in DB."""
    return Tools(
        tool_id=1,
        name=tool_data["name"],
        vendor=tool_data["vendor"],
        total_owned=tool_data["total_owned"],
        total_avail=tool_data["total_avail"],
    )


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

    @given(st.integers(), st.integers(min_value=1), st.integers(min_value=0))
    def test_pre_atomic_update_validate(
        self, given_tool_id: int, pre_total_owned: int, pre_total_avail: int
    ):
        """Test that the pre-atomic update object can be instantiated via dict."""
        pre_update = tools.ToolPreAtomicUpdate.model_validate(
            {
                "tool_id": given_tool_id,
                "total_owned": pre_total_owned,
                "total_avail": pre_total_avail,
            }
        ).model_dump(by_alias=True)
        # This by_alias is necessary because of the serialization_alias
        # when used in FastAPI, the method receives response_model_by_alias=True
        assert pre_update["tool_id"] == given_tool_id
        assert "total_owned" not in pre_update
        assert pre_update["preTotalOwned"] == pre_total_owned
        assert "total_avail" not in pre_update
        assert pre_update["preTotalAvail"] == pre_total_avail

    @given(st.integers(), st.integers(min_value=1), st.integers(min_value=0))
    def test_post_atomic_update(
        self, given_tool_id: int, post_total_owned: int, post_total_avail: int
    ):
        """Test that the pre-atomic update object can be instantiated."""
        post_update = tools.ToolPostAtomicUpdate(
            tool_id=given_tool_id,
            total_owned=post_total_owned,
            total_avail=post_total_avail,
        ).model_dump(by_alias=True)
        # This by_alias is necessary because of the serialization_alias
        # when used in FastAPI, the method receives response_model_by_alias=True
        assert post_update["tool_id"] == given_tool_id
        assert "total_owned" not in post_update
        assert post_update["postTotalOwned"] == post_total_owned
        assert "total_avail" not in post_update
        assert post_update["postTotalAvail"] == post_total_avail

    @given(st.integers(), st.integers(min_value=1), st.integers(min_value=0))
    def test_post_atomic_update_validate(
        self, given_tool_id: int, post_total_owned: int, post_total_avail: int
    ):
        """Test that the pre-atomic update object can be instantiated."""
        post_update = tools.ToolPostAtomicUpdate.model_validate(
            {
                "tool_id": given_tool_id,
                "total_owned": post_total_owned,
                "total_avail": post_total_avail,
            }
        ).model_dump(by_alias=True)
        # This by_alias is necessary because of the serialization_alias
        # when used in FastAPI, the method receives response_model_by_alias=True
        assert post_update["tool_id"] == given_tool_id
        assert "total_owned" not in post_update
        assert post_update["postTotalOwned"] == post_total_owned
        assert "total_avail" not in post_update
        assert post_update["postTotalAvail"] == post_total_avail

    def test_pre_atomic_update_row(self, tool_orm_data: Tools):
        """Test that the pre-atomic update object can be instantiated from a row."""
        pre_update = tools.ToolPreAtomicUpdate.model_validate(tool_orm_data).model_dump(
            by_alias=True
        )
        # This by_alias is necessary because of the serialization_alias
        # when used in FastAPI, the method receives response_model_by_alias=True
        assert pre_update["tool_id"] == tool_orm_data.tool_id
        assert "total_owned" not in pre_update
        assert pre_update["preTotalOwned"] == tool_orm_data.total_owned
        assert "total_avail" not in pre_update
        assert pre_update["preTotalAvail"] == tool_orm_data.total_avail

    def test_post_atomic_update_row(self, tool_orm_data: Tools):
        """Test that the pre-atomic update object can be instantiated from a row."""
        post_update = tools.ToolPostAtomicUpdate.model_validate(
            tool_orm_data
        ).model_dump(by_alias=True)
        # This by_alias is necessary because of the serialization_alias
        # when used in FastAPI, the method receives response_model_by_alias=True
        assert post_update["tool_id"] == tool_orm_data.tool_id
        assert "total_owned" not in post_update
        assert post_update["postTotalOwned"] == tool_orm_data.total_owned
        assert "total_avail" not in post_update
        assert post_update["postTotalAvail"] == tool_orm_data.total_avail


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
        curl -X PUT -H "Content-Type: application/json" /tools/{tool_id} \
            -d '{"owned": 10, "avail": 10}'
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


class TestToolFullUnit:
    """Set of tests for testing the FullTool response model."""

    @given(valid_avail_owned())
    def test_full_tool_model(self, qty_tuple: tuple[int, int]):
        """Test that the FullTool response model can be instantiated."""
        full_tool = tools.ToolFull(
            tool_id=1,  # type: ignore
            name="Test Tool",
            vendor="Test Vendor",
            total_owned=qty_tuple[1],  # type: ignore
            total_avail=qty_tuple[0],  # type: ignore
        ).model_dump(by_alias=True)
        assert full_tool["tool_id"] == 1
        assert full_tool["name"] == "Test Tool"
        assert full_tool["vendor"] == "Test Vendor"
        assert full_tool["owned"] == qty_tuple[1]
        assert full_tool["available"] == qty_tuple[0]

    @given(valid_avail_owned())
    def test_full_tool_model_dict(self, qty_tuple: tuple[int, int]):
        """Test that the FullTool response model can be instantiated."""
        full_tool = tools.ToolFull.model_validate(
            {
                "tool_id": 1,
                "name": "Test Tool",
                "vendor": "Test Vendor",
                "total_owned": qty_tuple[1],
                "total_avail": qty_tuple[0],
            }
        ).model_dump(by_alias=True)
        assert full_tool["tool_id"] == 1
        assert full_tool["name"] == "Test Tool"
        assert full_tool["vendor"] == "Test Vendor"
        assert full_tool["owned"] == qty_tuple[1]
        assert full_tool["available"] == qty_tuple[0]


@pytest.mark.asyncio()
@pytest.mark.usefixtures("_pre_insert_tool_data")
class TestToolRoutesIntegration:
    """Test that all routes for updating tools work as expected."""

    def full_tool_fields_present(self, data: dict) -> bool:
        """Test that all the required fields of a returned Tool are present."""
        return all(
            key in data for key in ("tool_id", "name", "vendor", "owned", "available")
        )

    @pytest_asyncio.fixture()
    async def example_tool(self, setup_db: AsyncSession):
        tool = Tools(name="Test Tool", vendor="Vendor", total_owned=10, total_avail=10)
        setup_db.add(tool)
        await setup_db.commit()
        tool_id = tool.tool_id
        yield tool_id
        await setup_db.delete(tool)
        await setup_db.commit()

    @pytest.mark.no_insert()
    @pytest.mark.usefixtures("setup_db")
    async def test_get_no_tools(self, test_client: TestClient):
        """Test that we can get no tools."""
        # no data inserted so
        response = test_client.get("/tools")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_get_all_tools(self, test_client: TestClient):
        """Test that we can get all tools.

        Only one in this case.
        """
        response = test_client.get("/tools")
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert isinstance(response_data, list)
        assert len(response_data) == 1
        # notice that this is not the same as the actual Table model
        assert self.full_tool_fields_present(response_data[0])

    @given(
        st.text(min_size=1, alphabet=ascii_letters),
        st.integers(min_value=1, max_value=10),
    )
    async def test_get_tools_by_vendor_query(
        self,
        test_engine: AsyncEngine,
        test_client: TestClient,
        new_vendor_name: str,
        new_tools_inserted: int,
    ):
        """Test getting all tools by vendor name in the query url."""
        new_tool = {
            "vendor": new_vendor_name,
            "total_owned": 10,
            "total_avail": 10,
        }
        async with test_engine.connect() as conn:
            for i in range(1, new_tools_inserted + 1):
                new_tool["name"] = f"Hammer {i}"
                await insert_tool_data(conn, new_tool)  # type: ignore
            await conn.commit()
        # now our lovely new hammers are in the db
        # lets get them by this particular vendor
        # this get all endpoint is paginated
        # so we need to make page size equal to our entries
        response = test_client.get(
            f"/tools?vendor={new_vendor_name}&page_size={new_tools_inserted}"
        )
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert isinstance(response_data, list)
        assert all("Hammer" in tool["name"] for tool in response_data)
        assert len(response_data) == new_tools_inserted
        assert all(
            self.full_tool_fields_present(ret_tool) for ret_tool in response_data
        )
        # clean out these new tools
        async with test_engine.begin() as conn:
            await conn.execute(
                text(
                    """DELETE FROM inventory.tools
                    WHERE vendor = :vendor
                    RETURNING *"""
                ),
                [{"vendor": new_vendor_name}],
            )
            await conn.commit()

    async def test_get_tools_by_empty_vendor_query(self, test_client: TestClient):
        """Test getting all tools by vendor name in the query url.

        But this time the vendor name is empty.
        """
        # There is only one tool in the database at this time
        response = test_client.get("/tools?vendor=&page_size=1")
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert isinstance(response_data, list)
        # having an empty vendor name doesn't actually match anything
        # so this should be empty
        assert len(response_data) == 0

    async def test_get_tool_by_id(self, test_client: TestClient, example_tool: int):
        """Test that we can get a tool by its id."""
        response = test_client.get(f"/tools/{example_tool}")
        print(response.json())
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert self.full_tool_fields_present(response_data)

    async def test_get_tool_by_bad_id(self, test_client: TestClient):
        """Test that we can get a tool by its id."""
        response = test_client.get("/tools/-1")
        print(response.json())
        assert response.status_code == status.HTTP_404_NOT_FOUND

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
            # result.rowcount is not useful in SQLAlchemy 2.0
            # except for in DELETE or UPDATE
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

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        # returns the object that was in the database
        assert isinstance(response_data, dict)
        # notice that this is not the same as the actual Table model
        assert self.full_tool_fields_present(response_data)

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
        assert self.full_tool_fields_present(response_data)

    @given(valid_avail_owned())
    async def test_put_fail(
        self,
        test_engine: AsyncEngine,
        test_client: TestClient,
        qty_tuple: tuple[int, int],
    ):
        """Test that we get a 400 if we try to update a tool_id route with invalid data.

        The quantity owned must always be
        greater than or equal to the quantity available.
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

    @given(valid_avail_owned())
    async def test_put_fail_bad_id(
        self,
        test_engine: AsyncEngine,
        test_client: TestClient,
        qty_tuple: tuple[int, int],
    ):
        """Test that we get a 404 if we try to update a tool_id that doesn't exist."""
        # fake a tool_id
        tool_id = -1

        # this request needs a Content-Type header of application/json
        response = test_client.put(
            f"/tools/{tool_id}",
            json={"owned": qty_tuple[1], "avail": qty_tuple[0]},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @given(st.integers(min_value=1, max_value=10))
    async def test_post_atomic_update_incr(
        self, test_engine: AsyncEngine, test_client: TestClient, qty: int
    ):
        """Test that we can update a tool's owned quantity and then get the new value.

        Check database before and after.
        """
        # obtain a tool_id
        async with test_engine.connect() as conn:
            result = await conn.execute(
                select(Tools.tool_id, Tools.total_owned, Tools.total_avail).limit(1)
            )
            tool_id, tool_owned_qty, tool_avail_qty = result.one()

        response = test_client.put(
            f"/tools/{tool_id}/owned/increment/get?value={qty}",
        )
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert all(
            col in response_data
            for col in ("tool_id", "postTotalOwned", "postTotalAvail")
        )
        assert response_data["postTotalOwned"] == tool_owned_qty + qty
        assert response_data["postTotalAvail"] == tool_avail_qty

    async def test_post_atomic_update_decr(
        self, test_engine: AsyncEngine, test_client: TestClient
    ):
        """Test that update a tool's owned quantity and then get the new value."""
        # obtain a tool_id
        async with test_engine.connect() as conn:
            result = await conn.execute(
                select(Tools.tool_id, Tools.total_owned, Tools.total_avail).limit(1)
            )
            tool_id, tool_owned_qty, tool_avail_qty = result.one()

        # qty to decrease by for available has to keep it greater than or equal to zero
        qty = tool_avail_qty

        response = test_client.put(
            f"/tools/{tool_id}/available/decrement/get?value={qty}",
        )
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert all(
            col in response_data
            for col in ("tool_id", "postTotalOwned", "postTotalAvail")
        )
        assert response_data["postTotalOwned"] == tool_owned_qty
        assert response_data["postTotalAvail"] == 0

    @given(st.integers(min_value=1, max_value=10))
    async def test_pre_atomic_update_incr(
        self, test_engine: AsyncEngine, test_client: TestClient, qty: int
    ):
        """Test that update a tool's owned quantity and then get the new value."""
        # obtain a tool_id
        async with test_engine.connect() as conn:
            result = await conn.execute(
                select(Tools.tool_id, Tools.total_owned, Tools.total_avail).limit(1)
            )
            tool_id, tool_owned_qty, tool_avail_qty = result.one()

        response = test_client.put(
            f"/tools/{tool_id}/owned/get/increment?value={qty}",
        )
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert all(
            col in response_data
            for col in ("tool_id", "preTotalOwned", "preTotalAvail")
        )
        assert response_data["preTotalOwned"] == tool_owned_qty
        assert response_data["preTotalAvail"] == tool_avail_qty

        # check that DB has updated value
        async with test_engine.connect() as conn:
            result = await conn.execute(
                select(Tools.total_owned, Tools.total_avail).where(
                    Tools.tool_id == tool_id
                )
            )
            new_owned_qty, new_avail_qty = result.one()

        assert new_owned_qty == tool_owned_qty + qty
        assert new_avail_qty == tool_avail_qty

    @given(st.integers(min_value=1))
    def test_pre_atomic_update_bad_id(
        self,
        test_client: TestClient,
        qty: int,
    ):
        """Test that we get a 404 if we try to update a tool_id route with invalid data.

        This same behavior should happen no matter which atomic operation we try.
        """
        # fake a tool_id
        tool_id = -1
        for field, op, post_get in product(
            ("owned", "available"), ("increment", "decrement"), (True, False)
        ):
            # qty would also break check constraints on the table
            # but that can't happen if the tool doesn't exist
            if post_get:
                response = test_client.put(
                    f"/tools/{tool_id}/{field}/{op}/get?value={qty}",
                )
            else:
                response = test_client.put(
                    f"/tools/{tool_id}/{field}/get/{op}?value={qty}",
                )
            assert response.status_code == status.HTTP_404_NOT_FOUND
