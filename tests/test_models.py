from cogamer.models import Channel, CogamerCreateRequest, CogamerState, Message


def test_create_request():
    req = CogamerCreateRequest(name="alpha")
    assert req.name == "alpha"


def test_cogent_state_requires_owner():
    state = CogamerState(
        name="beta",
        codebase="https://github.com/org/repo",
        owner="user-abc123",
    )
    assert state.owner == "user-abc123"


def test_cogent_state_from_dynamo():
    state = CogamerState(
        name="alpha",
        codebase="https://github.com/org/repo",
        owner="test-user",
        status="ready",
        ecs_task_arn="arn:aws:ecs:us-east-1:123:task/abc",
        created_at="2026-03-31T00:00:00Z",
    )
    assert state.status == "ready"


def test_message_creation():
    msg = Message(channel_id="ch-123", sender="cli", body="fix the bug")
    assert msg.sender == "cli"


def test_channel_creation():
    ch = Channel(channel_id="ch-123", cogamer_name="alpha")
    assert ch.cogamer_name == "alpha"
    assert ch.messages == []
