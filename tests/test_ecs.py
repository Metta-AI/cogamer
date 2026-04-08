from unittest.mock import MagicMock, patch

import pytest

from cogamer.ecs import CogamerECS


@pytest.fixture
def ecs():
    with patch("cogamer.ecs.boto3") as mock_boto:
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        ce = CogamerECS(
            cluster="cogamer",
            task_definition="cogamer-task",
            subnets=["subnet-abc"],
            security_groups=["sg-abc"],
        )
        ce._client = mock_client
        yield ce, mock_client


def test_run_task(ecs):
    ce, mock_client = ecs
    mock_client.run_task.return_value = {"tasks": [{"taskArn": "arn:aws:ecs:us-east-1:123:task/cogamer/abc123"}]}
    arn = ce.run_task(
        "alpha",
        env={
            "COGAMER_NAME": "alpha",
            "COGAMER_CODEBASE": "https://github.com/org/repo",
        },
    )
    assert arn == "arn:aws:ecs:us-east-1:123:task/cogamer/abc123"
    mock_client.run_task.assert_called_once()


def test_stop_task(ecs):
    ce, mock_client = ecs
    ce.stop_task("arn:aws:ecs:us-east-1:123:task/cogamer/abc123")
    mock_client.stop_task.assert_called_once()


def test_describe_task(ecs):
    ce, mock_client = ecs
    mock_client.describe_tasks.return_value = {
        "tasks": [
            {
                "taskArn": "arn:aws:ecs:us-east-1:123:task/cogamer/abc123",
                "lastStatus": "RUNNING",
                "containers": [{"networkInterfaces": [{"privateIpv4Address": "10.0.1.5"}]}],
            }
        ]
    }
    info = ce.describe_task("arn:aws:ecs:us-east-1:123:task/cogamer/abc123")
    assert info["status"] == "RUNNING"
    assert info["ip"] == "10.0.1.5"
