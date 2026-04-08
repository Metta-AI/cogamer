from unittest.mock import MagicMock, patch

import pytest

from cogamer.auth import validate_softmax_token


@pytest.fixture(autouse=True)
def clear_cache():
    from cogamer.auth import _token_cache

    _token_cache.clear()
    yield
    _token_cache.clear()


def test_validate_token_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "valid": True,
        "user": {"id": "user-abc", "email": "alice@example.com", "name": "Alice", "isSoftmaxTeamMember": False},
    }
    with patch("cogamer.auth.httpx.get", return_value=mock_resp):
        user = validate_softmax_token("tok-good")
    assert user.id == "user-abc"
    assert user.email == "alice@example.com"
    assert user.is_team_member is False


def test_validate_token_team_member():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "valid": True,
        "user": {"id": "user-team", "email": "team@softmax.com", "name": "Team", "isSoftmaxTeamMember": True},
    }
    with patch("cogamer.auth.httpx.get", return_value=mock_resp):
        user = validate_softmax_token("tok-team")
    assert user.is_team_member is True


def test_validate_token_invalid():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"valid": False}
    with patch("cogamer.auth.httpx.get", return_value=mock_resp):
        user = validate_softmax_token("tok-bad")
    assert user is None


def test_validate_token_cached():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "valid": True,
        "user": {"id": "user-abc", "email": "a@b.com", "name": "A", "isSoftmaxTeamMember": False},
    }
    with patch("cogamer.auth.httpx.get", return_value=mock_resp) as mock_get:
        validate_softmax_token("tok-cached")
        validate_softmax_token("tok-cached")
    mock_get.assert_called_once()


def test_validate_token_http_error():
    with patch("cogamer.auth.httpx.get", side_effect=Exception("network error")):
        user = validate_softmax_token("tok-err")
    assert user is None
