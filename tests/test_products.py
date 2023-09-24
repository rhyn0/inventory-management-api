# Standard Library
from contextlib import asynccontextmanager
from string import ascii_letters

# External Party
from fastapi import status
from fastapi.testclient import TestClient
from hypothesis import example
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy import exc as sa_exc
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession

# Local Modules
from inven_api.database.models import Products
from inven_api.routes import products

from .setup_deps import db_sessions
from .setup_deps import event_loop
from .setup_deps import setup_db
from .setup_deps import sqlite_schema_file
from .setup_deps import test_client
from .setup_deps import test_engine


@staticmethod
def attrs_present(product_model: products.ProductBase) -> bool:
    """Return whether a given Pydantic Product instance has all attributes."""
    return all(
        getattr(product_model, attr) is not None
        for attr in products.ProductBase.__fields__
    )


@st.composite
def product_type_strategy(draw):
    """Strategy to randomly draw a ProductType."""
    return draw(st.sampled_from(products.ProductTypes))


@st.composite
def invalid_product_type_strategy(draw):
    """Strategy to draw a string that is not a ProductType value."""
    return draw(
        st.text(alphabet=ascii_letters).filter(
            lambda x: x not in products.ProductTypes._value2member_map_
        )
    )


class TestProductRequestBodyUnit:
    """Collection of tests corresponding to validation of Request bodies to models.

    Tries to show a peak of the interaction between FastAPI + Pydantic.
    """

    @pytest.fixture(scope="class")
    def example_product_dict(self, product_data: dict) -> dict:
        # wrap this for a slightly better name in this class
        return product_data

    @pytest.fixture(scope="class")
    def example_product_full_dict(self, example_product_dict: dict) -> dict:
        return {
            **example_product_dict,
            "product_id": 1,
        }

    class TestProductCreate:
        """Test how a POST request is received and parsed."""

        def test_valid_product_instantiate(self, example_product_dict: dict):
            """Test that valid product is accepted.

            This creates it through __init__ and __new__
            """
            # objects are default truthy
            assert products.ProductCreate(**example_product_dict)

        def test_valid_product_req_validate(self, example_product_dict: dict):
            """Test that valid product is accepted when validating the data."""
            # Pydantic has this .model_validate to create an instance given a dict
            model = products.ProductCreate.model_validate(example_product_dict)
            assert attrs_present(model)

        # Hypothesis given integers uses closed range on both sides
        @given(st.integers(max_value=-1))
        def test_invalid_quantity(self, example_product_dict: dict, bad_quantity: int):
            """Test that invalid quantity is rejected."""
            bad_product_dict = {**example_product_dict, "quantity": bad_quantity}
            assert bad_product_dict["quantity"] < 0
            with pytest.raises(ValidationError) as excinfo:
                products.ProductCreate(**bad_product_dict)
            # make sure that error was created due to quantity
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("quantity",)

        @given(invalid_product_type_strategy())
        def test_invalid_product_type(
            self, example_product_dict: dict, bad_product_type: str
        ):
            """Test that invalid product_type is rejected."""
            bad_product_dict = {
                **example_product_dict,
                "product_type": bad_product_type,
            }
            with pytest.raises(ValidationError) as excinfo:
                products.ProductCreate(**bad_product_dict)
            # only this one field is erroring
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("product_type",)

    class TestProductUpdate:
        """Collection of tests around creation of a ProductUpdate from request body."""

        def test_valid_product_instantiate(self, example_product_dict: dict):
            """Test that valid product is accepted.

            This creates it through __init__ and __new__
            """
            # objects are default truthy
            obj = products.ProductUpdate(**example_product_dict)
            assert hasattr(obj, "quantity")
            # only thing to validly update set is quantity
            assert all(
                not hasattr(obj, attr)
                for attr in products.ProductBase.__fields__
                if attr != "quantity"
            )

        def test_valid_product_validate(self, example_product_dict: dict):
            """Test that valid product is accepted.

            This creates it through __init__ and __new__
            """
            obj = products.ProductUpdate.model_validate(example_product_dict)
            assert hasattr(obj, "quantity")
            # only thing to validly update set is quantity
            assert all(
                not hasattr(obj, attr)
                for attr in products.ProductBase.__fields__
                if attr != "quantity"
            )

        @given(st.integers(max_value=-1))
        def test_invalid_quantity(self, bad_qty: int):
            """Test that invalid quantity is rejected."""
            with pytest.raises(ValidationError) as excinfo:
                products.ProductUpdate(quantity=bad_qty)
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("quantity",)
            # test that error is due to negative quantity
            assert excinfo.value.errors()[0]["type"] == "greater_than_equal"

    class TestProductFullResponse:
        """Collection of tests for the response object ProductFull."""

        def test_valid_product_instantiate_fail(self, example_product_dict: dict):
            """Test that valid product is accepted."""
            # objects are default truthy
            with pytest.raises(ValidationError) as excinfo:
                products.ProductFull(**example_product_dict)
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("product_id",)
            assert excinfo.value.errors()[0]["type"] == "missing"

        @given(st.integers())
        def test_valid_product_instantiate(
            self, example_product_dict: dict, prod_id: int
        ):
            obj = products.ProductFull(**example_product_dict, product_id=prod_id)
            assert hasattr(obj, "product_id")
            assert attrs_present(obj)

        def test_valid_product_validate(self, example_product_full_dict: dict):
            """Test that valid product is accepted.

            This creates it through __init__ and __new__
            """
            obj = products.ProductFull.model_validate(example_product_full_dict)
            assert hasattr(obj, "product_id")
            assert attrs_present(obj)

        @given(st.integers(max_value=-1))
        def test_invalid_quantity(
            self,
            example_product_full_dict: dict,
            bad_qty: int,
        ):
            """Test that invalid quantity is rejected."""
            with pytest.raises(ValidationError) as excinfo:
                products.ProductFull.model_validate(
                    {**example_product_full_dict, "quantity": bad_qty}
                )
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("quantity",)
            # test that error is due to negative quantity
            assert excinfo.value.errors()[0]["type"] == "greater_than_equal"

    class TestProductPreUpdateResponse:
        """Collection of tests for the response object ProductPreUpdate."""

        def test_valid_product_instantiate_fail(self, example_product_dict: dict):
            """Test that valid product is accepted."""
            with pytest.raises(ValidationError) as excinfo:
                products.ProductPreUpdate(**example_product_dict)
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("product_id",)
            assert excinfo.value.errors()[0]["type"] == "missing"

        @given(st.integers())
        def test_valid_product_instantiate(
            self, example_product_dict: dict, prod_id: int
        ):
            obj = products.ProductPreUpdate(**example_product_dict, product_id=prod_id)
            assert hasattr(obj, "product_id")
            assert hasattr(obj, "vendor_sku")
            assert hasattr(obj, "quantity")
            assert not hasattr(obj, "name")

        def test_valid_product_validate(self, example_product_full_dict: dict):
            """Test that valid product is accepted.

            This creates it through __init__ and __new__
            """
            obj = products.ProductPreUpdate.model_validate(example_product_full_dict)
            assert hasattr(obj, "product_id")
            assert hasattr(obj, "vendor_sku")
            assert hasattr(obj, "quantity")
            assert not hasattr(obj, "name")

        @given(st.integers(max_value=-1))
        def test_invalid_quantity(
            self,
            example_product_full_dict: dict,
            bad_qty: int,
        ):
            """Test that invalid quantity is rejected."""
            with pytest.raises(ValidationError) as excinfo:
                products.ProductPreUpdate.model_validate(
                    {**example_product_full_dict, "quantity": bad_qty}
                )
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("quantity",)
            # test that error is due to negative quantity
            assert excinfo.value.errors()[0]["type"] == "greater_than_equal"

        def test_serialized_name(self, example_product_full_dict: dict):
            """Test that serialized_name is set."""
            data = products.ProductPreUpdate.model_validate(
                example_product_full_dict
            ).model_dump(by_alias=True)
            assert data["vendor_sku"] == example_product_full_dict["vendor_sku"]
            assert data["preUpdateQuantity"] == example_product_full_dict["quantity"]

    class TestProductPostUpdateResponse:
        """Collection of tests for the response object ProductPostUpdate."""

        def test_valid_product_instantiate_fail(self, example_product_dict: dict):
            """Test that valid product is accepted."""
            with pytest.raises(ValidationError) as excinfo:
                products.ProductPostUpdate(**example_product_dict)
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("product_id",)
            assert excinfo.value.errors()[0]["type"] == "missing"

        @given(st.integers())
        def test_valid_product_instantiate(
            self, example_product_dict: dict, prod_id: int
        ):
            obj = products.ProductPostUpdate(**example_product_dict, product_id=prod_id)
            assert hasattr(obj, "product_id")
            assert hasattr(obj, "vendor_sku")
            assert hasattr(obj, "quantity")
            assert not hasattr(obj, "name")

        def test_valid_product_validate(self, example_product_full_dict: dict):
            """Test that valid product is accepted.

            This creates it through __init__ and __new__
            """
            obj = products.ProductPostUpdate.model_validate(example_product_full_dict)
            assert hasattr(obj, "product_id")
            assert hasattr(obj, "vendor_sku")
            assert hasattr(obj, "quantity")
            assert not hasattr(obj, "name")

        @given(st.integers(max_value=-1))
        def test_invalid_quantity(
            self,
            example_product_full_dict: dict,
            bad_qty: int,
        ):
            """Test that invalid quantity is rejected."""
            with pytest.raises(ValidationError) as excinfo:
                products.ProductPostUpdate.model_validate(
                    {**example_product_full_dict, "quantity": bad_qty}
                )
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("quantity",)
            # test that error is due to negative quantity
            assert excinfo.value.errors()[0]["type"] == "greater_than_equal"

        def test_serialized_name(self, example_product_full_dict: dict):
            """Test that serialized_name is set."""
            data = products.ProductPostUpdate.model_validate(
                example_product_full_dict
            ).model_dump(by_alias=True)
            assert data["vendor_sku"] == example_product_full_dict["vendor_sku"]
            assert data["postUpdateQuantity"] == example_product_full_dict["quantity"]


@pytest.fixture(scope="session")
def product_data() -> dict:
    """Example product data in dict form."""
    return {
        "name": "nails",
        "product_type": "part",
        "vendor": "nailco",
        "vendor_sku": "nailco-123",
        "quantity": 100,
    }


@pytest_asyncio.fixture()
async def _pre_insert_product_data(
    setup_db: AsyncSession, product_data: dict, request: pytest.FixtureRequest
):
    """Fixture to insert tool data into the database."""
    marks = [m.name for m in request.node.iter_markers()]
    if "no_insert" in marks:
        return await remove_product_data(setup_db)
    return await insert_product_data(setup_db, product_data)


async def remove_product_data(session: AsyncSession):
    """Remove all product data from the database."""
    async with session.begin():
        await session.execute(delete(Products))


async def insert_product_data(session: AsyncSession, data: dict):
    """Insert product data into the database."""
    async with session.begin():
        try:
            await session.execute(
                text(
                    """INSERT INTO inventory.products
            (name, vendor, product_type, vendor_sku, quantity)
            VALUES (:name, :vendor, :product_type, :vendor_sku, :quantity)"""
                ),
                [data],
            )
        except sa_exc.IntegrityError:
            # item has already been inserted
            await session.rollback()


@pytest.mark.asyncio()
@pytest.mark.usefixtures("_pre_insert_product_data")
class TestProductRoutesIntegration:
    """Collection of tests that use fastapi.TestClient to make example requests."""

    @staticmethod
    def keys_present(data: dict) -> bool:
        return all(key in data for key in products.ProductFull.__fields__)

    @pytest.mark.no_insert()
    @pytest.mark.usefixtures("setup_db")
    def test_get_no_products(self, test_client: TestClient):
        """Test that no products exist.

        There are no products, because there is mark to not insert data.
        """
        response = test_client.get("/products")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_get_products(self, test_client: TestClient, product_data: dict):
        """Test that a product exists."""
        response = test_client.get("/products")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert all(product_data[key] == response.json()[0][key] for key in product_data)

    def test_get_products_by_query_name(
        self, test_client: TestClient, product_data: dict
    ):
        """Test that a product exists."""
        name = product_data["name"]
        response = test_client.get(f"/products?name={name}")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert all(product_data[key] == response.json()[0][key] for key in product_data)

    @given(
        st.text(min_size=1, alphabet=ascii_letters),
        st.integers(min_value=1, max_value=10),
    )
    async def test_get_mult_products_by_query_name(
        self,
        test_client: TestClient,
        test_engine: AsyncEngine,
        product_data: dict,
        new_name: str,
        new_products_inserted: int,
    ):
        async with test_engine.connect() as conn:
            for i in range(new_products_inserted):
                await insert_product_data(
                    conn,  # type: ignore
                    {
                        **product_data,
                        "name": new_name,
                        # unique constraint on vendor_sku
                        "vendor_sku": f"{product_data['vendor_sku']} {i}",
                    },
                )

        # don't forget pagination requirements
        response = test_client.get(
            f"/products?name={new_name}&page_size={new_products_inserted}"
        )
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert len(response_data) == new_products_inserted
        assert all(new_name == product["name"] for product in response_data)
        assert all(
            product_data["vendor"] in product["vendor"] for product in response_data
        )
        async with test_engine.begin() as conn:
            result = await conn.scalars(
                delete(Products).where(Products.name == new_name).returning(Products)
            )
        # auto commit
        assert len(result.all()) == new_products_inserted

    @given(
        st.text(min_size=1, alphabet=ascii_letters),
        st.integers(min_value=2, max_value=10),
    )
    async def test_get_products_by_query_name_paging(
        self,
        test_client: TestClient,
        test_engine: AsyncEngine,
        product_data: dict,
        new_name: str,
        new_products_inserted: int,
    ):
        async with test_engine.connect() as conn:
            for i in range(new_products_inserted):
                await insert_product_data(
                    conn,  # type: ignore
                    {
                        **product_data,
                        "name": new_name,
                        # unique constraint on vendor_sku
                        "vendor_sku": f"{product_data['vendor_sku']} {i}",
                    },
                )

        # test that setting page size and page works
        for page in range(new_products_inserted):
            response = test_client.get(
                f"/products?name={new_name}&page_size=1&page={page}"
            )
            assert response.status_code == status.HTTP_200_OK
            response_data = response.json()
            assert len(response_data) == 1
            assert all(new_name == product["name"] for product in response_data)
            assert all(
                product_data["vendor"] in product["vendor"] for product in response_data
            )
        async with test_engine.begin() as conn:
            result = await conn.scalars(
                delete(Products).where(Products.name == new_name).returning(Products)
            )
        # auto commit
        assert len(result.all()) == new_products_inserted

    async def test_get_product_by_id(
        self, test_client: TestClient, test_engine: AsyncEngine
    ):
        # obtain a product_id
        async with test_engine.connect() as conn:
            result = await conn.execute(select(Products.product_id).limit(1))
            product_id = result.scalar_one()
        response = test_client.get(f"/products/{product_id}")
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["product_id"] == product_id
        assert self.keys_present(response_data)

    def test_get_product_by_id_fail(self, test_client: TestClient):
        response = test_client.get("/products/-1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "Product not found"}

    @pytest.mark.no_insert()
    @pytest.mark.usefixtures("setup_db")
    def test_create_new_product(self, test_client: TestClient, product_data: dict):
        response = test_client.post("/products", json=product_data)
        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        assert isinstance(response_data, dict)
        # this skips the new product_id and modified_at keys in response
        assert all(product_data[key] == response_data[key] for key in product_data)
        assert "product_id" in response_data

    @given(st.integers(max_value=-1), st.text(alphabet=ascii_letters))
    def test_create_bad_product_qty(
        self, test_client: TestClient, product_data: dict, bad_qty: int, new_sku: str
    ):
        # use new sku here to avoid unique constraint on 'vendor_sku'
        bad_product_data = {**product_data, "quantity": bad_qty, "vendor_sku": new_sku}
        response = test_client.post("/products", json=bad_product_data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        response_data = response.json()
        assert isinstance(response_data, dict)
        # adds 'body' location since coming from FastAPI
        assert response_data["detail"][0]["loc"] == ["body", "quantity"]
        assert response_data["detail"][0]["type"] == "greater_than_equal"

    def test_create_bad_product_sku(self, test_client: TestClient, product_data: dict):
        response = test_client.post("/products", json=product_data)
        assert response.status_code == status.HTTP_409_CONFLICT
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["detail"] == "Vendor SKU already exists"

    async def test_delete_product(
        self, test_client: TestClient, test_engine: AsyncEngine
    ):
        # obtain a product_id
        async with test_engine.connect() as conn:
            result = await conn.execute(select(Products.product_id).limit(1))
            product_id = result.scalar_one()
        response = test_client.delete(f"/products/{product_id}")
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["product_id"] == product_id
        assert self.keys_present(response_data)

    def test_delete_product_not_found(self, test_client: TestClient):
        response = test_client.delete("/products/-1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response_data = response.json()
        assert response_data == {"detail": "Product not found"}
