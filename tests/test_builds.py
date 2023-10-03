# Standard Library
from collections import namedtuple
import random
from typing import Any

# External Party
from fastapi import status
from fastapi.testclient import TestClient
import hypothesis
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
import pydantic
import pytest
import pytest_asyncio
from sqlalchemy import exc as sa_exc
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession

# Local Modules
from inven_api.database.models import BuildProducts
from inven_api.database.models import Builds
from inven_api.database.models import BuildTools
from inven_api.database.models import Products
from inven_api.database.models import Tools
from inven_api.dependencies import AtomicUpdateOperations
from inven_api.routes import builds
from inven_api.routes import products
from inven_api.routes.build_products import BuildProductCreate
from inven_api.routes.build_products import BuildProductFullAll
from inven_api.routes.build_products import BuildProductFullSingle
from inven_api.routes.build_products import BuildProductUpdate
from inven_api.routes.build_products import ProductBuildLinkOut
from inven_api.routes.build_tools import BuildToolCreate
from inven_api.routes.build_tools import BuildToolFullAll
from inven_api.routes.build_tools import BuildToolFullSingle
from inven_api.routes.build_tools import BuildToolUpdate
from inven_api.routes.build_tools import ToolBuildLinkOut
from inven_api.routes.http_models import BuildRelationBase

from .setup_deps import ASCII_ST
from .setup_deps import SQLITE_MAX_INT
from .setup_deps import db_sessions
from .setup_deps import event_loop
from .setup_deps import product_type_strategy
from .setup_deps import request_headers
from .setup_deps import setup_db
from .setup_deps import sqlite_schema_file
from .setup_deps import test_client
from .setup_deps import test_engine


@pytest.fixture(scope="session")
def joined_build_prod(single_build_product: dict) -> dict:
    """What a build product looks like after joining Products."""
    return {
        "product": {
            "name": "nail",
            "vendor_sku": "nail-123",
            "product_type": "part",
            "product_id": single_build_product["product_id"],
            # this needs to be moved out of the buildproduct object to here
            "quantity_required": single_build_product["quantity_required"],
        },
        "build_id": single_build_product["build_id"],
    }


@st.composite
def build_sub_product(draw) -> dict[str, Any]:
    """Create a Product to be linked with a Build."""
    return {
        "name": draw(ASCII_ST),
        "vendor_sku": draw(ASCII_ST),
        "product_type": draw(product_type_strategy()),
        "product_id": draw(st.integers(min_value=1)),
        "quantity_required": draw(st.integers(min_value=1)),
    }


@st.composite
def build_sub_tool(draw) -> dict[str, Any]:
    """Create a Product to be linked with a Build."""
    return {
        "tool_id": draw(st.integers(min_value=1)),
        "name": draw(ASCII_ST),
        "vendor": draw(ASCII_ST),
        "quantity_required": draw(st.integers(min_value=1)),
    }


@st.composite
def build_product_out(draw: st.DrawFn):
    """Create a BuildProduct."""
    return {
        "build_id": draw(st.integers(min_value=1)),
        "product": draw(build_sub_product()),
    }


@st.composite
def build_tool_out(draw: st.DrawFn):
    """Create a BuildTool response data."""
    return {
        "build_id": draw(st.integers(min_value=1)),
        "tool": draw(build_sub_tool()),
    }


@st.composite
def build_product_in(draw: st.DrawFn):
    """Create a BuildProduct.

    Uses BuildRelationBase alias name instead of attribute name.
    """
    return {
        "product_id": draw(st.integers(min_value=1)),
        "quantity_required": draw(st.integers(min_value=1)),
    }


@st.composite
def build_tool_in(draw: st.DrawFn):
    """Create a BuildProduct.

    Uses BuildRelationBase alias name instead of attribute name.
    """
    return {
        "tool_id": draw(st.integers(min_value=1)),
        "quantity_required": draw(st.integers(min_value=1)),
    }


@st.composite
def build_product_all_out(draw: st.DrawFn, size: int = 3):
    """Create a BuildProduct with multiple products."""
    return {
        "build_id": draw(st.integers(min_value=1)),
        "products": draw(st.lists(build_sub_product(), min_size=size)),
    }


@st.composite
def build_tool_all_out(draw: st.DrawFn, size: int = 3):
    """Create a BuildTool with multiple tools."""
    return {
        "build_id": draw(st.integers(min_value=1)),
        "tools": draw(st.lists(build_sub_tool(), min_size=size)),
    }


@st.composite
def inven_build(draw: st.DrawFn, text_st: st.SearchStrategy = ASCII_ST):
    """Create a Build."""
    return {
        "name": draw(text_st),
        "sku": draw(text_st),
        "build_id": draw(st.integers(min_value=2, max_value=SQLITE_MAX_INT)),
    }


@st.composite
def unique_builds_data(draw: st.DrawFn):
    """Create a list of Builds with unique ids and skus."""
    seen_skus = set()
    output_builds = []
    n = draw(st.integers(min_value=1))
    id_offset = draw(st.integers(min_value=10, max_value=1_000))
    for build_id in range(n):
        build_name, build_sku = (
            draw(ASCII_ST),
            draw(ASCII_ST.filter(lambda x: x not in seen_skus)),
        )
        seen_skus.add(build_sku)
        output_builds.append(
            {"build_id": build_id + id_offset, "name": build_name, "sku": build_sku}
        )
    return output_builds


@pytest.fixture(scope="session")
def single_build():
    """Create a Build with hardcoded defaults."""
    return {
        "name": "example building",
        "sku": "EX-BUILD",
        "build_id": 1,
    }


@pytest.fixture(scope="session")
def single_product():
    """Create a Build with hardcoded defaults."""
    return {
        "product_id": 1,
        "name": "example material",
        "product_type": "material",
        "vendor": "ryan",
        "vendor_sku": "ryan-mat",
        "quantity": 10,
    }


@pytest.fixture(scope="session")
def single_tool():
    """Create a Build with hardcoded defaults."""
    return {
        "tool_id": 1,
        "name": "example tool",
        "vendor": "ryan hardware",
        "total_owned": 10,
        "total_avail": 10,
    }


@pytest.fixture(scope="session")
def single_build_product(single_build: dict, single_product: dict) -> dict:
    """Defines what a BuildProduct looks like."""
    return {
        "product_id": single_product["product_id"],
        "build_id": single_build["build_id"],
        "quantity_required": 2,
    }


@pytest.fixture(scope="session")
def single_build_tool(single_tool: dict, single_build: dict) -> dict:
    """Defines what a BuildTool looks like."""
    return {
        "tool_id": single_tool["tool_id"],
        "build_id": single_build["build_id"],
        "quantity_required": 2,
    }


NamedProductResult = namedtuple(
    "NamedProductResult",
    ("product_id", "name", "vendor_sku", "product_type", "quantity_required"),
)

NamedToolResult = namedtuple(
    "NamedToolResult",
    ("tool_id", "name", "vendor", "quantity_required"),
)


class TestBuildProductResponseUnit:
    """Collection of tests around the behavior of the response model.

    In this case the response model is BuildProductFullSingle and BUildProductFullAll.
    """

    def test_build_product_full_single_init(self, joined_build_prod: dict):
        """Test the BuildProductFullSingle model."""
        build_product = BuildProductFullSingle(**joined_build_prod)
        assert (
            build_product.product.product_id
            == joined_build_prod["product"]["product_id"]
        )
        assert build_product.build_id == joined_build_prod["build_id"]
        assert not hasattr(build_product, "quantity_required")
        assert (
            build_product.product.quantity_required
            == joined_build_prod["product"]["quantity_required"]
        )
        # this exclude_none=True is important to use
        # otherwise the following will fail
        # FastAPI decorator routes have option of response_model_exclude_none=True
        nested_product = build_product.product.model_dump(exclude_none=True)
        assert "vendor" not in nested_product
        assert "quantity" not in nested_product

    def test_build_product_full_single_model(self, joined_build_prod: dict):
        build_product = BuildProductFullSingle.model_validate(joined_build_prod)
        assert not hasattr(build_product, "quantity_required")
        assert not hasattr(build_product.product, "vendor")
        assert not hasattr(build_product.product, "quantity")

    @given(build_product_out())
    def test_build_product_full_single_json(self, build_product_data: dict):
        build_product = BuildProductFullSingle.model_validate(build_product_data)
        # use exclude None to match the endpoints
        build_product_resp_json = build_product.model_dump(exclude_none=True)
        assert all(key in build_product_resp_json for key in ("product", "build_id"))
        assert "quantity_required" not in build_product_resp_json
        assert "vendor" not in build_product_resp_json["product"]
        assert "quantity" not in build_product_resp_json["product"]

    @given(build_product_all_out())
    def test_build_product_full_all_init(self, build_products_data: dict):
        bps = BuildProductFullAll(**build_products_data)
        assert bps.build_id == build_products_data["build_id"]
        assert isinstance(bps.products, list)
        assert len(bps.products) == len(build_products_data["products"])
        assert all(
            not hasattr(product, key)
            for key in ("vendor", "quantity")
            for product in bps.products
        )


class TestBuildModelsUnit:
    """Collection of tests regarding the pydantic Build model used."""

    class TestBuildFullResponse:
        """Test the BuildFull as a response model.

        This model doesn't have any aliases so no special settings need to be set.
        But it is commonly used against SQLalchemy models, so we need to test that.
        """

        def verify_build_attributes(self, build: builds.BuildFull, data: dict):
            assert build.build_id == data["build_id"]
            assert build.name == data["name"]
            assert build.sku == data["sku"]
            assert not hasattr(build, "build_products")
            assert not hasattr(build, "build_tools")

        @given(inven_build())
        def test_build_full_init(self, build_data: dict):
            build = builds.BuildFull(**build_data)
            self.verify_build_attributes(build, build_data)

        @given(inven_build())
        def test_build_full_model(self, build_data: dict):
            build = builds.BuildFull.model_validate(build_data)
            self.verify_build_attributes(build, build_data)

        @given(inven_build())
        def test_build_full_from_orm(self, build_data: dict):
            build = Builds(**build_data)
            # if this fails, then we need to change config to add from_attributes
            build_full = builds.BuildFull.model_validate(build)
            self.verify_build_attributes(build_full, build_data)

        @given(inven_build())
        def test_build_full_missing_attr(self, build_data: dict):
            # there are no optional fields on this model
            tobe_removed = random.choice(list(build_data.keys()))
            build_data.pop(tobe_removed)
            with pytest.raises(pydantic.ValidationError):
                builds.BuildFull.model_validate(build_data)

    class TestBuildUpdateRequest:
        """Test the BuildUpdate model that is responsible for request data.

        Only fields corresponding to updateable attributes of a Build should be present.
        """

        REQUIRED_KEYS = ("name",)

        def verify_build_update_attributes(
            self, build: builds.BuildUpdateBase, data: dict
        ):
            # uses Base model because other subclasses could exist later
            for key in self.REQUIRED_KEYS:
                assert getattr(build, key) == data[key]

        @given(inven_build())
        def test_build_update_init(self, build_data: dict):
            build = builds.BuildUpdateIn(**build_data)
            self.verify_build_update_attributes(build, build_data)

        @given(inven_build())
        def test_build_update_model(self, build_data: dict):
            build = builds.BuildUpdateIn.model_validate(build_data)
            self.verify_build_update_attributes(build, build_data)

        @given(inven_build())
        def test_build_update_missing_attr(self, build_data: dict):
            # there are no optional fields on this model
            for key in self.REQUIRED_KEYS:
                build_data.pop(key)
            with pytest.raises(pydantic.ValidationError):
                builds.BuildUpdateIn.model_validate(build_data)

    class TestBuildCreateRequest:
        """Tests the BuildCreate model that is responsible for request data.

        Usage is for POST requests to create a new Build.
        """

        REQUIRED_KEYS = ("name", "sku")

        def verify_build_create_attributes(self, build: builds.BuildCreate, data: dict):
            # uses Base model because other subclasses could exist later
            for key in self.REQUIRED_KEYS:
                assert getattr(build, key) == data[key]

        @given(inven_build())
        def test_build_create_init(self, build_data: dict):
            build = builds.BuildCreate(**build_data)
            self.verify_build_create_attributes(build, build_data)

        @given(inven_build())
        def test_build_create_model(self, build_data: dict):
            build = builds.BuildCreate.model_validate(build_data)
            self.verify_build_create_attributes(build, build_data)

        @given(inven_build())
        def test_build_create_missing_attr(self, build_data: dict):
            # there are no optional fields on this model
            for key in self.REQUIRED_KEYS:
                build_data.pop(key)
            with pytest.raises(pydantic.ValidationError):
                builds.BuildCreate.model_validate(build_data)

    class TestBuildProductsRequest:
        """Tests the BuildProducts model that is responsible for request data.

        Usage is for POST requests to create a new Build.
        """

        @given(build_product_in())
        def test_build_products_init(self, data: dict):
            # this one is by keyword init, has to use the attribute name
            build = BuildProductCreate(**data)
            assert all(
                getattr(build, key) == data[key]
                for key in ("product_id", "quantity_required")
            )

        @given(build_product_in())
        def test_build_products_model(self, data: dict):
            build = BuildProductCreate.model_validate(data)
            assert build.product_id == data["product_id"]
            assert build.quantity_required == data["quantity_required"]

        @given(build_product_in())
        def test_build_products_missing_attr(self, data: dict):
            # there are no optional fields on this model
            popped_key = random.choice(list(data.keys()))
            data.pop(popped_key)
            with pytest.raises(pydantic.ValidationError):
                BuildProductCreate.model_validate(data)

        @given(build_product_in())
        def test_build_product_update_init(self, data: dict):
            # this one is by keyword init, has to use the attribute name
            build = BuildProductUpdate(**data)
            # only quantity field can be updated
            assert not hasattr(build, "product_id")
            assert build.quantity_required == data["quantity_required"]

        @given(build_product_in())
        def test_build_product_update_model(self, data: dict):
            build = BuildProductUpdate.model_validate(data)
            # only quantity field can be updated
            assert not hasattr(build, "product_id")
            assert build.quantity_required == data["quantity_required"]

        @given(st.integers(max_value=0))
        def test_build_product_update_bad_qty(self, quantity: int):
            with pytest.raises(pydantic.ValidationError):
                BuildProductUpdate.model_validate({"quantity": quantity})

        def test_build_product_update_empty(self):
            with pytest.raises(pydantic.ValidationError):
                BuildProductUpdate.model_validate({})

    class TestBuildToolsRequest:
        """Collection of tests for the BuildTools model request data model."""

        @given(build_tool_in())
        def test_build_tools_init(self, data: dict):
            # this one is by keyword init, has to use the attribute name
            build = BuildToolCreate(**data)
            assert all(
                getattr(build, key) == data[key]
                for key in ("tool_id", "quantity_required")
            )

        @given(build_tool_in())
        def test_build_tools_model(self, data: dict):
            build = BuildToolCreate.model_validate(data)
            assert build.tool_id == data["tool_id"]
            assert build.quantity_required == data["quantity_required"]

        @given(build_tool_in())
        def test_build_tools_missing_attr(self, data: dict):
            # there are no optional fields on this model
            popped_key = random.choice(list(data.keys()))
            data.pop(popped_key)
            with pytest.raises(pydantic.ValidationError):
                BuildToolCreate.model_validate(data)

        @given(build_tool_in())
        def test_build_tool_update_init(self, data: dict):
            # this one is by keyword init, has to use the attribute name
            build = BuildToolUpdate(**data)
            # only quantity field can be updated
            assert not hasattr(build, "tool_id")
            assert build.quantity_required == data["quantity_required"]

        @given(build_tool_in())
        def test_build_tool_update_model(self, data: dict):
            build = BuildToolUpdate.model_validate(data)
            # only quantity field can be updated
            assert not hasattr(build, "tool_id")
            assert build.quantity_required == data["quantity_required"]

        @given(st.integers(max_value=0))
        def test_build_tool_update_bad_qty(self, quantity: int):
            with pytest.raises(pydantic.ValidationError):
                BuildToolUpdate.model_validate({"quantity": quantity})

        def test_build_tool_update_empty(self):
            with pytest.raises(pydantic.ValidationError):
                BuildToolUpdate.model_validate({})

    class TestBuildRelationsSubItemResponse:
        """Tests for the nested data model response for a BuildRelation endpoint."""

        @given(build_sub_product())
        def test_build_sub_product_init(self, data: dict):
            # there are no aliases on this model
            build = ProductBuildLinkOut(**data)
            assert all(getattr(build, key) == data[key] for key in data)

        @given(build_sub_product())
        def test_build_sub_product_validate(self, data: dict):
            build = ProductBuildLinkOut.model_validate(data)
            assert all(getattr(build, key) == data[key] for key in data)

        @given(build_sub_product())
        def test_build_sub_product_missing_attr(self, data: dict):
            # there are no optional fields on this model
            popped_key = random.choice(list(data.keys()))
            data.pop(popped_key)
            with pytest.raises(pydantic.ValidationError):
                ProductBuildLinkOut.model_validate(data)

        @given(build_sub_product(), st.integers(max_value=0))
        def test_build_sub_product_bad_qty(self, data: dict, bad_qty: int):
            data["quantity_required"] = bad_qty
            with pytest.raises(pydantic.ValidationError) as excinfo:
                ProductBuildLinkOut.model_validate(data)
            assert excinfo.value.errors()[0]["loc"] == ("quantity_required",)

        @given(build_sub_product(), ASCII_ST)
        def test_build_sub_product_bad_product(self, data: dict, bad_product: str):
            # monkey writing shakespeare
            if bad_product in products.ProductTypes:
                return
            data["product_type"] = bad_product
            with pytest.raises(pydantic.ValidationError) as excinfo:
                ProductBuildLinkOut.model_validate(data)
            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("product_type",)

        @given(build_sub_tool())
        def test_build_sub_tool_init(self, data: dict):
            # there are no aliases on this model
            build = ToolBuildLinkOut(**data)
            assert all(getattr(build, key) == data[key] for key in data)

        @given(build_sub_tool())
        def test_build_sub_tool_validate(self, data: dict):
            build = ToolBuildLinkOut.model_validate(data)
            assert all(getattr(build, key) == data[key] for key in data)

        @given(build_sub_tool())
        def test_build_sub_tool_missing_attr(self, data: dict):
            # there are no optional fields on this model
            popped_key = random.choice(list(data.keys()))
            data.pop(popped_key)
            with pytest.raises(pydantic.ValidationError):
                ToolBuildLinkOut.model_validate(data)

        @given(build_sub_tool(), st.integers(max_value=0))
        def test_build_sub_tool_bad_qty(self, data: dict, bad_qty: int):
            data["quantity_required"] = bad_qty
            with pytest.raises(pydantic.ValidationError) as excinfo:
                ToolBuildLinkOut.model_validate(data)
            assert excinfo.value.errors()[0]["loc"] == ("quantity_required",)

    class TestBuildRelationResponse:
        """Tests for the whole response data model from a Build relation endpoint."""

        @given(build_product_out())
        def test_build_product_init(self, data: dict):
            build_product = BuildProductFullSingle(**data)
            assert build_product.build_id == data["build_id"]
            assert not hasattr(build_product, "quantity_required")
            assert not hasattr(build_product, "product_id")
            assert hasattr(build_product.product, "quantity_required")
            assert hasattr(build_product.product, "product_id")
            assert all(
                getattr(build_product.product, key) == data["product"][key]
                for key in data["product"]
            )

        @given(build_product_out())
        def test_build_product_model(self, data: dict):
            build_product = BuildProductFullSingle.model_validate(data)
            assert build_product.build_id == data["build_id"]
            assert not hasattr(build_product, "quantity_required")
            assert not hasattr(build_product, "product_id")
            assert hasattr(build_product.product, "quantity_required")
            assert hasattr(build_product.product, "product_id")
            assert all(
                getattr(build_product.product, key) == data["product"][key]
                for key in data["product"]
            )

        @given(build_sub_product(), st.integers(min_value=1), ASCII_ST)
        def test_build_product_model_orm(
            self, data: dict, build_id: int, new_vendor: str
        ):
            # create an SQLAlchemy named tuple (Result) to simulate a query
            # quantity must be renamed to instantiate the Products

            quantity_reqd = data.pop("quantity_required")
            # this product quantity is about the inventory state, not about the build
            data["quantity"] = 0
            product = Products(**data, vendor=new_vendor)
            tuple_result = NamedProductResult(
                product.product_id,
                product.name,
                product.vendor_sku,
                product.product_type,
                quantity_reqd,
            )
            build_product_data = {
                "build_id": build_id,
                "product": tuple_result,
            }

            build_product = BuildProductFullSingle.model_validate(build_product_data)
            assert build_product.build_id == build_id
            assert not hasattr(build_product, "quantity_required")
            assert not hasattr(build_product, "product_id")
            assert not hasattr(build_product.product, "vendor")
            assert hasattr(build_product.product, "product_id")
            assert hasattr(build_product.product, "product_type")
            assert all(
                getattr(build_product.product, key) == data[key]
                for key in data
                # have to skip quantity key since it is renamed as 'quantity_required'
                if key != "quantity"
            )

        @given(build_product_out())
        def test_build_product_missing_attr(self, data: dict):
            # there are no optional fields at the top level of this model
            popped_key = random.choice(list(data))
            data.pop(popped_key)
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildProductFullSingle.model_validate(data)

            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == (popped_key,)

        @given(build_product_out(), st.integers(max_value=0))
        def test_build_product_bad_build_id(self, data: dict, bad_id: int):
            data["build_id"] = bad_id
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildProductFullSingle.model_validate(data)

            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("build_id",)

        @given(build_product_all_out())
        def test_build_product_all_init(self, data: dict):
            build_prod_all = BuildProductFullAll(**data)
            assert build_prod_all.build_id == data["build_id"]
            assert not hasattr(build_prod_all, "quantity_required")
            assert not hasattr(build_prod_all, "product_id")
            assert all(
                hasattr(sub_prod, "quantity_required")
                for sub_prod in build_prod_all.products
            )
            assert all(
                hasattr(sub_prod, "product_id") for sub_prod in build_prod_all.products
            )

        @given(build_product_all_out())
        def test_build_product_all_model(self, data: dict):
            build_product = BuildProductFullAll.model_validate(data)
            assert build_product.build_id == data["build_id"]
            assert not hasattr(build_product, "quantity_required")
            assert not hasattr(build_product, "product_id")
            assert all(
                hasattr(sub_prod, "quantity_required")
                for sub_prod in build_product.products
            )
            assert all(
                hasattr(sub_prod, "product_id") for sub_prod in build_product.products
            )
            assert all(
                getattr(build_product.products[idx], key) == data["products"][idx][key]
                for key in data["products"][0]
                for idx in range(len(data["products"]))
            )

        @given(build_product_all_out())
        def test_build_product_all_missing_attr_top(self, data: dict):
            # there are no optional fields at the top level of this model
            popped_key = random.choice(list(data))
            data.pop(popped_key)
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildProductFullAll.model_validate(data)

            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == (popped_key,)

        @given(build_product_all_out())
        def test_build_product_all_missing_attr_products(self, data: dict):
            # pop a single key from a single product
            popped_key = random.choice(list(data["products"][0]))
            data["products"][0].pop(popped_key)
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildProductFullAll.model_validate(data)

            assert excinfo.value.error_count() == 1
            # in repr form this "loc" is joined with "."
            # but in the actual error it is a tuple
            assert excinfo.value.errors()[0]["loc"] == ("products", 0, popped_key)

        @given(build_product_all_out(), st.integers(max_value=0))
        def test_build_product_all_bad_build_id(self, data: dict, bad_id: int):
            data["build_id"] = bad_id
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildProductFullAll.model_validate(data)

            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("build_id",)

        # #########################
        # Begin BuildTool Section #
        # #########################
        @given(build_tool_out())
        def test_build_tool_init(self, data: dict):
            build_product = BuildToolFullSingle(**data)
            assert build_product.build_id == data["build_id"]
            assert not hasattr(build_product, "quantity_required")
            assert not hasattr(build_product, "tool_id")
            assert hasattr(build_product.tool, "quantity_required")
            assert hasattr(build_product.tool, "tool_id")
            assert all(
                getattr(build_product.tool, key) == data["tool"][key]
                for key in data["tool"]
            )

        @given(build_tool_out())
        def test_build_tool_model(self, data: dict):
            build_product = BuildToolFullSingle.model_validate(data)
            assert build_product.build_id == data["build_id"]
            assert not hasattr(build_product, "quantity_required")
            assert not hasattr(build_product, "tool_id")
            assert hasattr(build_product.tool, "quantity_required")
            assert hasattr(build_product.tool, "tool_id")
            assert all(
                getattr(build_product.tool, key) == data["tool"][key]
                for key in data["tool"]
            )

        @given(build_sub_tool(), st.integers(min_value=1), ASCII_ST)
        def test_build_tool_model_orm(self, data: dict, build_id: int, new_vendor: str):
            # create an SQLAlchemy model and validate it against the pydantic model
            # quantity must be renamed again
            qty_required = data.pop("quantity_required")
            # this tool quantity is about the inventory state, not about the build
            tool = Tools(**data, total_owned=1, total_avail=0)
            tuple_tool = NamedToolResult(
                tool.tool_id, tool.name, tool.vendor, qty_required
            )
            build_tool_data = {"build_id": build_id, "tool": tuple_tool}

            build_tool = BuildToolFullSingle.model_validate(build_tool_data)
            assert build_tool.build_id == build_id
            assert not hasattr(build_tool, "quantity_required")
            assert not hasattr(build_tool, "tool_id")
            assert hasattr(build_tool.tool, "vendor")
            assert hasattr(build_tool.tool, "tool_id")
            assert all(
                getattr(build_tool.tool, key) == data[key]
                for key in data
                # have to skip quantity key since it is renamed as 'quantity_required'
                if key != "quantity"
            )

        @given(build_tool_out())
        def test_build_tool_missing_attr(self, data: dict):
            # there are no optional fields at the top level of this model
            popped_key = random.choice(list(data))
            data.pop(popped_key)
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildToolFullSingle.model_validate(data)

            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == (popped_key,)

        @given(build_tool_out(), st.integers(max_value=0))
        def test_build_tool_bad_build_id(self, data: dict, bad_id: int):
            data["build_id"] = bad_id
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildToolFullSingle.model_validate(data)

            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("build_id",)

        @given(build_tool_all_out())
        def test_build_tool_all_init(self, data: dict):
            build_prod_all = BuildToolFullAll(**data)
            assert build_prod_all.build_id == data["build_id"]
            assert not hasattr(build_prod_all, "quantity_required")
            assert not hasattr(build_prod_all, "tool_id")
            assert all(
                hasattr(sub_tool, "quantity_required")
                for sub_tool in build_prod_all.tools
            )
            assert all(
                hasattr(sub_prod, "tool_id") for sub_prod in build_prod_all.tools
            )

        @given(build_tool_all_out())
        def test_build_tool_all_model(self, data: dict):
            build_product = BuildToolFullAll.model_validate(data)
            assert build_product.build_id == data["build_id"]
            assert not hasattr(build_product, "quantity_required")
            assert not hasattr(build_product, "tool_id")
            assert all(
                hasattr(sub_tool, "quantity_required")
                for sub_tool in build_product.tools
            )
            assert all(hasattr(sub_tool, "tool_id") for sub_tool in build_product.tools)
            assert all(
                getattr(build_product.tools[idx], key) == data["tools"][idx][key]
                for key in data["tools"][0]
                for idx in range(len(data["tools"]))
            )

        @given(build_tool_all_out())
        def test_build_tool_all_missing_attr_top(self, data: dict):
            # there are no optional fields at the top level of this model
            popped_key = random.choice(list(data))
            data.pop(popped_key)
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildToolFullAll.model_validate(data)

            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == (popped_key,)

        @given(build_tool_all_out())
        def test_build_tool_all_missing_attr_tools(self, data: dict):
            # pop a single key from a single tool
            popped_key = random.choice(list(data["tools"][0]))
            data["tools"][0].pop(popped_key)
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildToolFullAll.model_validate(data)

            assert excinfo.value.error_count() == 1
            # in repr form this "loc" is joined with "."
            # but in the actual error it is a tuple
            assert excinfo.value.errors()[0]["loc"] == ("tools", 0, popped_key)

        @given(build_tool_all_out(), st.integers(max_value=0))
        def test_build_tool_all_bad_build_id(self, data: dict, bad_id: int):
            data["build_id"] = bad_id
            with pytest.raises(pydantic.ValidationError) as excinfo:
                BuildToolFullAll.model_validate(data)

            assert excinfo.value.error_count() == 1
            assert excinfo.value.errors()[0]["loc"] == ("build_id",)


@pytest_asyncio.fixture()
async def _pre_insert_build_data(
    setup_db: AsyncSession, single_build: dict, request: pytest.FixtureRequest
):
    """Ensure for each fixture that Test DB is in preferred state."""
    marks = {m.name for m in request.node.iter_markers()}
    if "no_insert" in marks:
        # no data in the DB
        return await delete_build_data(setup_db)
    # at least one record in DB
    return await insert_build_data(setup_db, single_build)


async def delete_build_data(session: AsyncSession):
    """Delete all data from the DB and return."""
    async with session.begin():
        await session.execute(sa.delete(Builds))
        # auto commit


async def insert_build_data(session: AsyncSession, build: dict):
    """Insert the given Build into the DB and return."""
    async with session.begin():
        try:
            await session.execute(sa.insert(Builds).values(**build))
        except sa_exc.IntegrityError:
            # build already exists
            await session.rollback()
        else:
            await session.commit()


def is_build(build: dict):
    """Check if the given dict is a Build."""
    return all(key in build for key in ("name", "sku", "build_id"))


@pytest.mark.usefixtures("_pre_insert_build_data")
class TestBuildRoutesIntegration:
    """Collection of tests to make sure the Build HTTP routes work as expected."""

    @pytest.mark.asyncio()
    class TestAsyncCollections:
        """Certain tests requiring a DB connection will be marked as async."""

        async def test_get_builds_by_name(
            self, test_client: TestClient, test_engine: AsyncEngine
        ):
            """Test that GET /builds?name={name} returns a list of Builds."""
            # get a name that exists in the DB
            async with test_engine.connect() as conn:
                result = await conn.scalars(sa.select(Builds.name).limit(1))
                build_name = result.first()
            # names are not unique, so we could get multiple
            response = test_client.get("/builds", params={"name": build_name})
            assert response.status_code == status.HTTP_200_OK
            response_data = response.json()
            assert isinstance(response_data, list)
            assert len(response_data) >= 1
            assert all(is_build(build) for build in response_data)
            assert all(build["name"] == build_name for build in response_data)

        async def test_get_builds_by_sku(
            self, test_client: TestClient, test_engine: AsyncEngine
        ):
            """Test that GET /builds?name={name} returns a list of Builds."""
            # get a name that exists in the DB
            async with test_engine.connect() as conn:
                result = await conn.scalars(sa.select(Builds.sku).limit(1))
                build_sku = result.first()
            # names are not unique, so we could get multiple
            response = test_client.get(f"/builds?sku={build_sku}")
            assert response.status_code == status.HTTP_200_OK
            response_data = response.json()
            assert isinstance(response_data, list)
            assert len(response_data) >= 1
            assert all(is_build(build) for build in response_data)
            assert all(build["sku"] == build_sku for build in response_data)

        @given(unique_builds_data())
        @settings(max_examples=10)
        async def test_get_builds_pagination(
            self,
            test_client: TestClient,
            test_engine: AsyncEngine,
            to_add_builds: list[dict],
        ):
            # add all the builds to the DB
            async with test_engine.begin() as con:
                await con.execute(sa.insert(Builds).values(to_add_builds))
                # auto commit
            # now get builds one by one and make sure we get the same data
            seen_builds = set()
            for i in range(len(to_add_builds)):
                response = test_client.get(f"/builds?page={i}&page_size=1")
                assert response.status_code == status.HTTP_200_OK
                response_data = response.json()
                assert isinstance(response_data, list)
                assert len(response_data) == 1
                assert response_data[0]["build_id"] not in seen_builds
                seen_builds.add(response_data[0]["build_id"])

            # greater than equal since might be preexisting builds
            assert len(seen_builds) >= len(to_add_builds)

            # clean out data added
            async with test_engine.begin() as con:
                await con.execute(
                    sa.delete(Builds).where(
                        Builds.build_id.in_([b["build_id"] for b in to_add_builds])
                    )
                )
                # auto commit

        @given(inven_build(text_st=ASCII_ST.filter(lambda x: len(x) > 1)))
        async def test_post_new_build(
            self, test_client: TestClient, test_engine: AsyncEngine, data: dict
        ):
            """Test that POST /builds returns 201 if Build is created."""
            response = test_client.post("/builds", json=data)
            assert response.status_code == status.HTTP_201_CREATED
            response_data = response.json()
            assert response_data["name"] == data["name"]
            assert response_data["sku"] == data["sku"]
            assert response_data["build_id"] is not None
            assert response_data["build_id"] >= 1

            # remove this build from the DB
            async with test_engine.begin() as conn:
                await conn.execute(
                    sa.delete(Builds).where(
                        Builds.build_id == response_data["build_id"]
                    )
                )

        @given(inven_build())
        async def test_delete_build(
            self, test_client: TestClient, test_engine: AsyncEngine, data: dict
        ):
            """Insert a new build and then delete it through HTTP request."""
            async with test_engine.begin() as conn:
                await conn.execute(sa.insert(Builds).values(**data))

            # delete via client request
            response = test_client.delete(f"/builds/{data['build_id']}")
            assert response.status_code == status.HTTP_200_OK
            response_data = response.json()
            assert isinstance(response_data, dict)
            assert is_build(response_data)

    @pytest.mark.no_insert()
    @pytest.mark.usefixtures("setup_db")
    def test_get_no_builds(self, test_client: TestClient):
        """Test that GET /builds returns an empty list."""
        response = test_client.get("/builds")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_get_all_tools(self, test_client: TestClient):
        """Test that GET /builds returns a list of all builds."""
        response = test_client.get("/builds")
        assert response.status_code == status.HTTP_200_OK
        # possible that DB has more than one build
        response_data = response.json()
        assert isinstance(response_data, list)
        assert len(response_data) >= 1
        assert all(is_build(build) for build in response_data)

    def test_get_specific_build(self, test_client: TestClient):
        """Test that GET /builds/{build_id} returns a single Build."""
        response = test_client.get("/builds/1")
        assert response.status_code == status.HTTP_200_OK
        assert is_build(response.json())

    def test_post_existing_build(self, test_client: TestClient, single_build: dict):
        """Test that POST /builds returns 409 if Build already exists."""
        response = test_client.post("/builds", json=single_build)
        assert response.status_code == status.HTTP_409_CONFLICT
        response_data = response.json()
        assert response_data["detail"] == f"SKU {single_build['sku']} already exists"

    def test_delete_nonexistent_build(self, test_client: TestClient):
        """Test that DELETE /builds/{build_id} returns 404 if Build doesn't exist."""
        response = test_client.delete("/builds/-1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response_data = response.json()
        assert response_data["detail"] == "Build not found"

    @given(ASCII_ST)
    def test_update_name(self, test_client: TestClient, new_name: str):
        """Test that PUT /builds/{build_id} updates the name."""
        response = test_client.put("/builds/1", json={"name": new_name})
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["name"] == new_name

    @given(ASCII_ST)
    def test_update_sku(self, test_client: TestClient, new_sku: str):
        """Test that PUT /builds/{build_id} fails to update the sku."""
        response = test_client.put("/builds/1", json={"sku": new_sku})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        response_data = response.json()
        assert response_data["detail"][0]["type"] == "missing"
        assert response_data["detail"][0]["loc"] == ["body", "name"]

    @given(st.integers(min_value=1, max_value=SQLITE_MAX_INT))
    def test_update_build_id(self, test_client: TestClient, new_id: int):
        """Test that PUT /builds/{build_id} fails to update the build_id."""
        response = test_client.put("/builds/1", json={"build_id": new_id})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        response_data = response.json()
        assert response_data["detail"][0]["type"] == "missing"
        assert response_data["detail"][0]["loc"] == ["body", "name"]


@pytest_asyncio.fixture()
async def _pre_insert_build_relation_data(
    setup_db: AsyncSession,
    single_build: dict,
    single_product: dict,
    single_tool: dict,
    single_build_product: dict,
    single_build_tool: dict,
    request: pytest.FixtureRequest,
):
    """Ensure for each fixture that Test DB is in preferred state."""
    marks = {m.name for m in request.node.iter_markers()}
    if "no_insert" not in marks:
        # at least one record in DB
        await insert_build_relation_data(
            setup_db,
            [
                Builds(**single_build),
                Products(**single_product),
                Tools(**single_tool),
                BuildTools(**single_build_tool),
                BuildProducts(**single_build_product),
            ],
        )
        yield
        await delete_build_relation_data(setup_db)
    else:
        # no data in the DB
        await delete_build_relation_data(setup_db)
        yield


async def delete_build_relation_data(session: AsyncSession):
    """Delete the relation data from the DB and return."""
    async with session.begin():
        await session.execute(sa.delete(BuildProducts))
        await session.execute(sa.delete(BuildTools))
        await session.execute(sa.delete(Products))
        await session.execute(sa.delete(Tools))
        await session.execute(sa.delete(Builds))


async def insert_build_relation_data(session: AsyncSession, items: list):
    """Insert the given Build into the DB and return."""
    async with session.begin():
        for item in items:
            async with session.begin_nested():
                try:
                    await session.merge(item)
                except sa_exc.IntegrityError:
                    # build already exists
                    await session.rollback()
        await session.commit()


@pytest.mark.usefixtures("_pre_insert_build_relation_data")
class TestBuildRelationRoutesIntegration:
    """Collection of tests for API routes regarding Build relations."""

    @pytest.mark.asyncio()
    class TestAsyncs:
        """Collection of methods that need Async DB connection."""

        @pytest.mark.no_insert()
        @pytest.mark.usefixtures("setup_db")
        async def test_get_no_build_products(
            self, test_client: TestClient, test_engine: AsyncEngine, single_build: dict
        ):
            """Test that GET returns a list with no items when no build parts exist."""
            async with test_engine.begin() as conn:
                await conn.execute(sa.insert(Builds).values(**single_build))
                # auto commit

            response = test_client.get(f"/builds/{single_build['build_id']}/products")
            assert response.status_code == status.HTTP_200_OK
            response_data = response.json()
            assert isinstance(response_data, dict)
            assert response_data["build_id"] == single_build["build_id"]
            assert response_data["products"] == []

        async def test_create_build_product(
            self,
            test_client: TestClient,
            test_engine: AsyncEngine,
            single_build_product: dict,
            request: pytest.FixtureRequest,
        ):
            """Test that POST works for creating a BuildProduct."""
            async with test_engine.begin() as conn:
                # first delete the existing BuildProduct
                delete_result = await conn.execute(
                    sa.delete(BuildProducts)
                    .where(
                        BuildProducts.build_id == single_build_product["build_id"],
                        BuildProducts.product_id == single_build_product["product_id"],
                    )
                    .returning(BuildProducts.build_id, BuildProducts.product_id)
                )
            assert len(delete_result.all()) == 1

            response = test_client.post(
                f"/builds/{single_build_product['build_id']}/products",
                json=single_build_product,
            )
            assert response.status_code == status.HTTP_201_CREATED
            response_data = response.json()
            assert isinstance(response_data, dict)
            assert response_data["build_id"] == single_build_product["build_id"]
            assert isinstance(response_data["product"], dict)
            assert (
                response_data["product"]["product_id"]
                == single_build_product["product_id"]
            )
            assert (
                response_data["product"]["quantity_required"]
                == single_build_product["quantity_required"]
            )

        @given(st.integers(min_value=1, max_value=100_000))
        async def test_update_build_product_quantity(
            self,
            test_client: TestClient,
            test_engine: AsyncEngine,
            single_build_product: dict,
            qty: int,
        ):
            """Test that PUT works for updating a BuildProduct quantity required.

            Check the database before and after to make sure the quantity is updated.
            """
            database_statement = sa.select(BuildProducts.quantity_required).where(
                BuildProducts.build_id == single_build_product["build_id"],
                BuildProducts.product_id == single_build_product["product_id"],
            )
            async with test_engine.connect() as conn:
                prev_result = await conn.execute(database_statement)
                prev_qty = prev_result.scalar_one()

            response = test_client.put(
                f"/builds/{single_build_product['build_id']}/products/{single_build_product['product_id']}",
                json={"quantity_required": qty},
            )
            assert response.status_code == status.HTTP_200_OK
            response_data = response.json()
            assert isinstance(response_data, dict)
            assert response_data["build_id"] == single_build_product["build_id"]
            assert (
                response_data["product"]["product_id"]
                == single_build_product["product_id"]
            )
            if prev_qty != qty:
                # funky condition when the generated qty == prev_qty
                assert prev_qty != response_data["product"]["quantity_required"]
            assert qty == response_data["product"]["quantity_required"]

            # check database to make sure the new qty is there
            async with test_engine.connect() as conn:
                after_result = await conn.execute(database_statement)
            assert after_result.scalar_one() == qty

    @pytest.mark.no_insert()
    @pytest.mark.usefixtures("setup_db")
    def test_get_error_build_prodcuts(self, test_client: TestClient):
        """Test that GET returns error if build_id doesn't exist."""
        response = test_client.get("/builds/1/products")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["detail"] == "Build not found"

    def test_get_build_products_all(self, test_client: TestClient):
        response = test_client.get("/builds/1/products")
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["build_id"] == 1
        assert isinstance(response_data["products"], list)
        assert len(response_data["products"]) >= 1
        assert all(
            isinstance(product, dict)
            and all(
                key in product
                for key in (
                    "product_id",
                    "name",
                    "vendor_sku",
                    "product_type",
                    "quantity_required",
                )
            )
            for product in response_data["products"]
        )

    def test_get_build_products_by_id(self, test_client: TestClient):
        """Test that we get the correct BuildProduct by ID.

        Default _pre_insert function puts in build_id 1 and product_id 1.
        """
        response = test_client.get("/builds/1/products/1")
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["build_id"] == 1
        assert isinstance(response_data["product"], dict)
        assert all(
            key in response_data["product"]
            for key in (
                "product_id",
                "name",
                "vendor_sku",
                "product_type",
                "quantity_required",
            )
        )

    def test_get_build_products_by_id_producterror(self, test_client: TestClient):
        """Test that we get an error for requesting a nonexistent BuildProduct.

        Default _pre_insert function puts in build_id 1 and product_id 1.
        """
        response = test_client.get("/builds/1/products/-1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response_data = response.json()
        assert response_data["detail"] == "Build Product pair not found"

    def test_get_build_products_by_id_builderror(self, test_client: TestClient):
        """Test that we get an error for requesting a nonexistent BuildProduct.

        Default _pre_insert function puts in build_id 1 and product_id 1.
        """
        response = test_client.get("/builds/-1/products/1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response_data = response.json()
        assert response_data["detail"] == "Build Product pair not found"

    def test_delete_build_products(self, test_client: TestClient, single_product: dict):
        """Test that we can delete a BuildProduct.

        Default _pre_insert function puts in build_id 1 and product_id 1.
        """
        response = test_client.get("/builds/1/products/1")
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["build_id"] == 1
        assert isinstance(response_data["product"], dict)
        assert all(
            response_data["product"][key] == single_product[key]
            for key in response_data["product"]
            if key != "quantity_required"
        )

    def test_delete_build_products_bad_prod(self, test_client: TestClient):
        """Test that we get an error when deleting a nonexistent BuildProduct.

        Default _pre_insert function puts in build_id 1 and product_id 1.
        """
        response = test_client.get("/builds/1/products/-1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["detail"] == "Build Product pair not found"

    def test_delete_build_products_bad_build(self, test_client: TestClient):
        """Test that we get an error when deleting a nonexistent BuildProduct.

        Default _pre_insert function puts in build_id 1 and product_id 1.
        """
        response = test_client.get("/builds/-1/products/1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["detail"] == "Build Product pair not found"

    @given(st.integers(min_value=-SQLITE_MAX_INT, max_value=0))
    def test_post_build_products_bad_build(
        self, test_client: TestClient, single_build_product: dict, bad_id: int
    ):
        """Test that we get an error when deleting a nonexistent BuildProduct.

        Default _pre_insert function puts in build_id 1 and product_id 1.
        """
        response = test_client.post(
            f"/builds/{bad_id}/products/", json=single_build_product
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["detail"] == "Build not found"

    @given(st.integers(min_value=-SQLITE_MAX_INT, max_value=0))
    def test_post_build_products_bad_product(
        self, test_client: TestClient, single_build_product: dict, bad_id: int
    ):
        """Test that we get an error when deleting a nonexistent BuildProduct.

        Default _pre_insert function puts in build_id 1 and product_id 1.
        """
        build_product_new = {**single_build_product, "product_id": bad_id}
        response = test_client.post(
            f"/builds/{single_build_product['build_id']}/products/",
            json=build_product_new,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        response_data = response.json()
        assert isinstance(response_data, dict)
        assert response_data["detail"] == "Product not found"
