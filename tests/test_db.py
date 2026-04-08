from unittest.mock import MagicMock, patch

import pytest

from cogamer.db import CogamerDB
from cogamer.models import CogamerState, Message


@pytest.fixture
def db():
    with patch("cogamer.db.boto3") as mock_boto:
        mock_table = MagicMock()
        mock_boto.resource.return_value.Table.return_value = mock_table
        cdb = CogamerDB(table_name="cogamer-test")
        cdb._table = mock_table
        yield cdb, mock_table


def test_put_cogent(db):
    cdb, mock_table = db
    state = CogamerState(name="alpha", codebase="https://github.com/org/repo", owner="test-user")
    cdb.put_cogamer(state)
    mock_table.put_item.assert_called_once()
    item = mock_table.put_item.call_args[1]["Item"]
    assert item["pk"] == "COGAMER#alpha"
    assert item["sk"] == "META"


def test_get_cogent(db):
    cdb, mock_table = db
    mock_table.get_item.return_value = {
        "Item": {
            "pk": "COGAMER#alpha",
            "sk": "META",
            "name": "alpha",
            "codebase": "https://github.com/org/repo",
            "owner": "test-user",
            "status": "ready",
            "config": {},
            "mcp_servers": {},
            "ecs_task_arn": "arn:aws:ecs:us-east-1:123:task/abc",
            "created_at": "2026-03-31T00:00:00Z",
        }
    }
    state = cdb.get_cogamer("alpha")
    assert state is not None
    assert state.name == "alpha"


def test_get_cogent_not_found(db):
    cdb, mock_table = db
    mock_table.get_item.return_value = {}
    assert cdb.get_cogamer("nope") is None


def test_list_cogents(db):
    cdb, mock_table = db
    mock_table.query.return_value = {
        "Items": [
            {
                "pk": "COGAMER#alpha",
                "sk": "META",
                "name": "alpha",
                "codebase": "https://github.com/org/repo",
                "owner": "test-user",
                "status": "ready",
                "config": {},
                "mcp_servers": {},
                "created_at": "2026-03-31T00:00:00Z",
            },
        ]
    }
    result = cdb.list_cogamers()
    assert len(result) == 1


def test_put_message(db):
    cdb, mock_table = db
    msg = Message(channel_id="ch-abc", sender="cli", body="hello")
    cdb.put_message("alpha", msg)
    mock_table.put_item.assert_called_once()
    item = mock_table.put_item.call_args[1]["Item"]
    assert item["pk"] == "COGAMER#alpha"
    assert item["sk"].startswith("MSG#ch-abc#")


def test_get_messages(db):
    cdb, mock_table = db
    mock_table.query.return_value = {
        "Items": [
            {
                "pk": "COGAMER#alpha",
                "sk": "MSG#ch-abc#2026-03-31T00:00:00Z",
                "channel_id": "ch-abc",
                "sender": "cli",
                "body": "hello",
                "timestamp": "2026-03-31T00:00:00Z",
            },
        ]
    }
    msgs = cdb.get_messages("alpha", "ch-abc")
    assert len(msgs) == 1
    assert msgs[0].body == "hello"


def test_delete_cogent(db):
    cdb, mock_table = db
    mock_table.query.return_value = {
        "Items": [
            {"pk": "COGAMER#alpha", "sk": "META"},
        ]
    }
    cdb.delete_cogamer("alpha")
    mock_table.delete_item.assert_called()
