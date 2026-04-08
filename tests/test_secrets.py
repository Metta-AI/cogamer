import json
from unittest.mock import MagicMock, patch

import pytest

from cogamer.secrets import CogamerSecrets


@pytest.fixture
def secrets():
    with patch("cogamer.secrets.boto3") as mock_boto:
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        cs = CogamerSecrets()
        cs._client = mock_client
        yield cs, mock_client


def test_set_secrets(secrets):
    cs, mock_client = secrets
    cs.set_secrets("alpha", {"API_KEY": "abc123", "DB_PASS": "secret"})
    mock_client.put_secret_value.assert_called_once()


def test_get_secrets(secrets):
    cs, mock_client = secrets
    mock_client.get_secret_value.return_value = {"SecretString": json.dumps({"API_KEY": "abc123"})}
    result = cs.get_secrets("alpha")
    assert result == {"API_KEY": "abc123"}


def test_get_secrets_not_found(secrets):
    cs, mock_client = secrets
    mock_client.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})
    mock_client.get_secret_value.side_effect = mock_client.exceptions.ResourceNotFoundException()
    result = cs.get_secrets("alpha")
    assert result == {}


def test_list_secret_keys(secrets):
    cs, mock_client = secrets
    mock_client.get_secret_value.return_value = {"SecretString": json.dumps({"API_KEY": "abc123", "DB_PASS": "secret"})}
    keys = cs.list_secret_keys("alpha")
    assert sorted(keys) == ["API_KEY", "DB_PASS"]
