# External Party
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
import pytest

# Local Modules
from inven_api.routes import tools


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
