# External Party
import pytest

# Local Modules
from inven_api.database.models import Builds
from inven_api.dependencies import AtomicUpdateOperations
from inven_api.routes import builds
from inven_api.routes.builds import BuildProductFullSingle

from .setup_deps import db_sessions
from .setup_deps import event_loop
from .setup_deps import request_headers
from .setup_deps import setup_db
from .setup_deps import sqlite_schema_file
from .setup_deps import test_client
from .setup_deps import test_engine


@pytest.fixture(scope="session")
def single_build_product() -> dict:
    """Defines what a BuildProduct looks like."""
    return {
        "product_id": 1,
        "build_id": 1,
        "quantity_required": 2,
    }


@pytest.fixture(scope="session")
def joined_build_prod(single_build_product: dict) -> dict:
    """What a build product looks like after joining Products."""
    return {
        "product": {
            "name": "nail",
            "vendor_sku": "nail-123",
            "product_type": "part",
            "product_id": single_build_product["product_id"],
        },
        **single_build_product,
    }


class TestBuildProductResponseUnit:
    """Collection of tests around the behavior of the response model.

    In this case the response model is BuildProductFullSingle and BUildProductFullAll.
    """

    def test_build_product_full_single_init(self, joined_build_prod: dict) -> None:
        """Test the BuildProductFullSingle model."""
        build_product = BuildProductFullSingle(**joined_build_prod)
        assert build_product.product.product_id == joined_build_prod["product_id"]
        assert build_product.build_id == joined_build_prod["build_id"]
        assert build_product.quantity_required == joined_build_prod["quantity_required"]
        # this exclude_none=True is important to use
        # otherwise the following will fail
        # FastAPI decorator routes have option of response_model_exclude_none=True
        nested_product = build_product.product.model_dump(exclude_none=True)
        assert "vendor" not in nested_product
        assert "quantity" not in nested_product
