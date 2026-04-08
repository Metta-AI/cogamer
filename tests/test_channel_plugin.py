from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("cogamer.channel.plugin", reason="channel.plugin not yet ported")

from cogamer.channel.plugin import CogamerChannelPlugin  # noqa: E402


@pytest.fixture
def plugin():
    with patch("cogamer.channel.plugin.httpx") as mock_httpx:
        p = CogamerChannelPlugin(cogamer_name="alpha", api_url="http://localhost:8000")
        yield p, mock_httpx


def test_reply(plugin):
    p, mock_httpx = plugin
    mock_httpx.post.return_value = MagicMock(status_code=200)
    p.reply("ch-abc", "done fixing it")
    mock_httpx.post.assert_called_once()
    call_json = mock_httpx.post.call_args[1]["json"]
    assert call_json["channel_id"] == "ch-abc"
    assert call_json["message"] == "done fixing it"


def test_send(plugin):
    p, mock_httpx = plugin
    mock_httpx.post.return_value = MagicMock(status_code=200, json=lambda: {"channel_id": "ch-xyz"})
    channel_id = p.send("beta", "hello beta")
    assert channel_id == "ch-xyz"


def test_poll_messages(plugin):
    p, mock_httpx = plugin
    mock_httpx.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"messages": [{"channel_id": "ch-abc", "sender": "cli", "body": "fix it", "timestamp": "t1"}]},
    )
    msgs = p.poll_messages()
    assert len(msgs) == 1
    assert msgs[0]["body"] == "fix it"
