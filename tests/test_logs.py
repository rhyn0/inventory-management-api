# External Party
from fastapi import status
from fastapi.testclient import TestClient
import pytest

from .setup_deps import test_client


@pytest.fixture()
def current_version() -> str:
    """Current version of the project."""
    # Local Modules
    from inven_api import __version__

    return __version__


def test_hello_logs(
    caplog: pytest.LogCaptureFixture, test_client: TestClient, current_version: str
):
    """Test that the hello route logs a message."""
    response = test_client.get("/")
    assert response.status_code == status.HTTP_200_OK
    assert current_version in response.json()["message"]
    logs = caplog.get_records("call")
    assert len(logs) > 0
    log_message = caplog.get_records("call")[0].message
    assert current_version in log_message
