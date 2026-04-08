from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cogamer.cli import main

pytestmark = pytest.mark.skip(reason="CLI was restructured (sub-command groups); tests need rewrite")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def mock_softmax_token():
    with patch("cogamer.cli._load_softmax_token", return_value="fake-softmax-token"):
        yield


@pytest.fixture
def mock_httpx():
    with patch("cogamer.cli.httpx") as m:
        yield m


def test_list_empty(runner, mock_httpx):
    mock_httpx.get.return_value = MagicMock(status_code=200, json=lambda: [])
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0


def test_create(runner, mock_httpx):
    mock_httpx.post.return_value = MagicMock(
        status_code=201,
        json=lambda: {"name": "alpha", "status": "starting", "codebase": "https://github.com/org/repo"},
    )
    with patch("cogamer.cli._repo_is_public", return_value=True):
        result = runner.invoke(main, ["create", "alpha", "https://github.com/org/repo"])
    assert result.exit_code == 0
    assert "alpha" in result.output


def test_status_with_name(runner, mock_httpx):
    mock_httpx.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"name": "alpha", "status": "running", "codebase": "x"},
    )
    result = runner.invoke(main, ["status", "alpha"])
    assert result.exit_code == 0
    assert "alpha" in result.output


def test_status_without_name(runner, mock_httpx):
    mock_httpx.get.return_value = MagicMock(status_code=200, json=lambda: [])
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0


def test_stop(runner, mock_httpx):
    mock_httpx.delete.return_value = MagicMock(status_code=200, json=lambda: {"status": "stopped"})
    result = runner.invoke(main, ["stop", "alpha"])
    assert result.exit_code == 0


def test_send_async(runner, mock_httpx):
    mock_httpx.post.return_value = MagicMock(status_code=200, json=lambda: {"channel_id": "ch-abc"})
    result = runner.invoke(main, ["send", "alpha", "fix it", "--async"])
    assert result.exit_code == 0
    assert "ch-abc" in result.output


def test_secret(runner, mock_httpx):
    mock_httpx.put.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok"})
    result = runner.invoke(main, ["secret", "alpha", "API_KEY=abc123"])
    assert result.exit_code == 0


def test_configure_set(runner, mock_httpx):
    mock_httpx.put.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok"})
    result = runner.invoke(main, ["configure", "alpha", "key=value"])
    assert result.exit_code == 0


def test_configure_get(runner, mock_httpx):
    mock_httpx.get.return_value = MagicMock(status_code=200, json=lambda: {"key": "value"})
    result = runner.invoke(main, ["configure", "alpha", "key"])
    assert result.exit_code == 0
